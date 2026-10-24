"""Load RewardBench SQLite logs and JSONL exports.

SQLite tables follow schema version 1 in ``docs/INTERFACES.md``. Missing
validation metadata is treated as preliminary. Nothing in this loader calls
a model provider.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from rewardbench.analysis.schema import (
    PRELIMINARY,
    AnalysisError,
    AttemptObservation,
    EpisodeObservation,
    ErrorObservation,
    LogBundle,
    SchemaError,
    ValidationIssue,
)
from rewardbench.analysis.validate import validate_bundle

EPISODE_COLUMNS = frozenset(
    {
        "experiment_id",
        "session_id",
        "revision_index",
        "episode_index",
        "seed",
        "total_reward",
        "success",
        "crashed",
        "steps",
        "elapsed_seconds",
        "error",
    }
)
ATTEMPT_COLUMNS = frozenset(
    {
        "experiment_id",
        "session_id",
        "revision_index",
        "call_index",
        "selected",
        "valid",
        "validation_error",
        "prompt_tokens",
        "completion_tokens",
        "reasoning_tokens",
        "total_tokens",
        "latency_seconds",
        "estimated_cost_usd",
        "error",
    }
)
EXPERIMENT_COLUMNS = frozenset(
    {
        "experiment_id",
        "environment_id",
        "provider",
        "model_id",
        "feedback_condition",
        "split",
        "seed",
        "config_json",
        "status",
    }
)


def load_logs(path: str | Path) -> LogBundle:
    """Load and validate a SQLite database or a JSONL export."""

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"experiment log not found: {source}")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    suffix = source.suffix.lower()
    if suffix in {".sqlite", ".sqlite3", ".db"}:
        bundle = _load_sqlite(source, digest)
    elif suffix == ".jsonl":
        bundle = _load_jsonl(source, digest)
    else:
        raise SchemaError(
            f"unsupported log suffix {suffix!r}; expected .sqlite, .sqlite3, .db, or .jsonl"
        )
    return validate_bundle(bundle)


def _load_sqlite(path: Path, digest: str) -> LogBundle:
    uri = path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise SchemaError(f"could not open sqlite log: {exc}") from exc
    try:
        connection.row_factory = sqlite3.Row
        tables = _table_names(connection)
        required = {"experiments", "sessions", "attempts", "episodes"}
        missing = sorted(required - tables)
        if missing:
            raise SchemaError("sqlite log is missing tables: " + ", ".join(missing))
        _require_columns(connection, "experiments", EXPERIMENT_COLUMNS)
        _require_columns(connection, "attempts", ATTEMPT_COLUMNS)
        _require_columns(connection, "episodes", EPISODE_COLUMNS)
        schema_version = _schema_version(connection)
        warnings: list[str] = []
        if schema_version not in (None, 1):
            warnings.append(
                f"schema_version is {schema_version}; the loader was written for version 1"
            )
        experiments = {
            row["experiment_id"]: _experiment_context(row)
            for row in connection.execute("SELECT * FROM experiments")
        }
        episodes = []
        for row in connection.execute("SELECT * FROM episodes"):
            context = _context_for(experiments, row["experiment_id"])
            episodes.append(_episode_from_row(row, context))
        attempts = []
        for row in connection.execute("SELECT * FROM attempts"):
            context = _context_for(experiments, row["experiment_id"])
            attempts.append(_attempt_from_row(row, context))
        errors = []
        if "errors" in tables:
            for row in connection.execute("SELECT * FROM errors"):
                errors.append(
                    ErrorObservation(
                        experiment_id=str(row["experiment_id"]),
                        session_id=str(row["session_id"]),
                        phase=str(row["phase"]),
                        message=str(row["message"]),
                        revision_index=_optional_int(row["revision_index"]),
                        episode_index=_optional_int(row["episode_index"]),
                    )
                )
        else:
            warnings.append("errors table is absent")
        return LogBundle(
            episodes=episodes,
            attempts=attempts,
            errors=errors,
            issues=[],
            source=path,
            sha256=digest,
            schema_version=schema_version,
            source_format="sqlite",
            load_warnings=warnings,
        )
    except SchemaError:
        raise
    except sqlite3.Error as exc:
        raise SchemaError(f"could not read sqlite log: {exc}") from exc
    finally:
        connection.close()


def _load_jsonl(path: Path, digest: str) -> LogBundle:
    episodes: list[EpisodeObservation] = []
    attempts: list[AttemptObservation] = []
    errors: list[ErrorObservation] = []
    issues: list[ValidationIssue] = []
    with path.open("r", encoding="utf-8", newline="\n") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SchemaError(f"jsonl line {line_number} is not valid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise SchemaError(f"jsonl line {line_number} must be an object")
            record_type = payload.get("record_type")
            try:
                if record_type == "episode":
                    episodes.append(_episode_from_mapping(payload))
                elif record_type == "attempt":
                    attempts.append(_attempt_from_mapping(payload))
                elif record_type == "error":
                    errors.append(
                        ErrorObservation(
                            experiment_id=str(payload["experiment_id"]),
                            session_id=str(payload["session_id"]),
                            phase=str(payload["phase"]),
                            message=str(payload["message"]),
                            revision_index=_optional_int(payload.get("revision_index")),
                            episode_index=_optional_int(payload.get("episode_index")),
                        )
                    )
                else:
                    issues.append(
                        ValidationIssue(
                            "warning",
                            "skipped_record",
                            f"line {line_number} has unsupported record_type {record_type!r}",
                        )
                    )
            except (KeyError, TypeError, ValueError) as exc:
                raise SchemaError(f"jsonl line {line_number} does not match the export schema: {exc}") from exc
    return LogBundle(
        episodes=episodes,
        attempts=attempts,
        errors=errors,
        issues=issues,
        source=path,
        sha256=digest,
        schema_version=1,
        source_format="jsonl",
        load_warnings=[],
    )


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(row["name"]) for row in rows}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _require_columns(connection: sqlite3.Connection, table: str, required: frozenset[str]) -> None:
    present = _columns(connection, table)
    missing = sorted(required - present)
    if missing:
        raise SchemaError(f"table {table} is missing columns: " + ", ".join(missing))


def _schema_version(connection: sqlite3.Connection) -> int | None:
    tables = _table_names(connection)
    if "schema_meta" not in tables:
        return None
    row = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row["value"])
    except (TypeError, ValueError) as exc:
        raise SchemaError("schema_meta.schema_version is not an integer") from exc


def _experiment_context(row: sqlite3.Row) -> dict[str, object]:
    config = _parse_config(row["config_json"])
    metadata = config.get("metadata") if isinstance(config.get("metadata"), dict) else {}
    status = metadata.get("validation_status", PRELIMINARY)
    if status not in {PRELIMINARY, "independently_validated"}:
        status = PRELIMINARY
    return {
        "environment_config": _environment_config(config),
        "environment_id": str(row["environment_id"]),
        "provider": str(row["provider"]),
        "model_id": str(row["model_id"]),
        "feedback_condition": str(row["feedback_condition"]),
        "split": str(row["split"]),
        "experiment_seed": int(row["seed"]),
        "experiment_status": str(row["status"]),
        "validation_status": str(status),
        "synthetic": bool(metadata.get("synthetic", False)),
        "development_seeds": _seed_list(config.get("development_seeds")),
        "held_out_seeds": _seed_list(config.get("held_out_seeds")),
    }


def _environment_config(config: dict[str, object]) -> str:
    """Recorded simulator settings only; replica seeds and experiment ids are excluded.

    Missing settings remain unrecorded rather than guessing the installed adapter's
    defaults/version. Retain additional adapter physics options conservatively.
    """
    metadata = config.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    adapter = metadata.get("adapter_kwargs", {})
    adapter = adapter if isinstance(adapter, dict) else {}
    runtime_keys = {"record_dir", "record_video", "locked_camera", "experiment_id", "split", "origin"}
    settings = {key: value for key, value in adapter.items() if key not in runtime_keys}
    for key in ("research_mode", "start_schedule_version", "vary_fuel", "environment_version"):
        if key in metadata:
            settings[key] = metadata[key]
        if key in config:
            settings[key] = config[key]
    if "max_episode_steps" in config:
        settings["max_episode_steps"] = config["max_episode_steps"]
    # Missing legacy provenance stays unknown; it must not pool with matched v2.
    settings["seed_schedule_version"] = config.get("seed_schedule_version", "unrecorded")
    return json.dumps(settings, sort_keys=True, separators=(",", ":"))


def _parse_config(raw: object) -> dict[str, object]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _seed_list(value: object) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    seeds: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            continue
        seeds.append(item)
    return tuple(seeds)


def _context_for(experiments: dict[str, dict[str, object]], experiment_id: object) -> dict[str, object]:
    key = str(experiment_id)
    if key not in experiments:
        raise SchemaError(f"row references unknown experiment_id {key}")
    return experiments[key]


def _episode_from_row(row: sqlite3.Row, context: dict[str, object]) -> EpisodeObservation:
    return EpisodeObservation(
        experiment_id=str(row["experiment_id"]),
        session_id=str(row["session_id"]),
        environment_id=str(context["environment_id"]),
        provider=str(context["provider"]),
        model_id=str(context["model_id"]),
        feedback_condition=str(context["feedback_condition"]),
        split=str(context["split"]),
        experiment_seed=int(context["experiment_seed"]),
        experiment_status=str(context["experiment_status"]),
        revision_index=int(row["revision_index"]),
        episode_index=int(row["episode_index"]),
        episode_seed=int(row["seed"]),
        total_reward=_optional_float(row["total_reward"]),
        success=_optional_bool(row["success"]),
        crashed=_optional_bool(row["crashed"]),
        steps=int(row["steps"]),
        elapsed_seconds=float(row["elapsed_seconds"]),
        error=_optional_str(row["error"]),
        validation_status=str(context["validation_status"]),
        synthetic=bool(context["synthetic"]),
        environment_config=str(context["environment_config"]),
        development_seeds=tuple(context["development_seeds"]),  # type: ignore[arg-type]
        held_out_seeds=tuple(context["held_out_seeds"]),  # type: ignore[arg-type]
    )


def _attempt_from_row(row: sqlite3.Row, context: dict[str, object]) -> AttemptObservation:
    return AttemptObservation(
        experiment_id=str(row["experiment_id"]),
        session_id=str(row["session_id"]),
        environment_id=str(context["environment_id"]),
        provider=str(context["provider"]),
        model_id=str(context["model_id"]),
        feedback_condition=str(context["feedback_condition"]),
        split=str(context["split"]),
        experiment_status=str(context["experiment_status"]),
        revision_index=int(row["revision_index"]),
        call_index=int(row["call_index"]),
        selected=bool(_required_bool(row["selected"])),
        valid=bool(_required_bool(row["valid"])),
        validation_error=_optional_str(row["validation_error"]),
        prompt_tokens=int(row["prompt_tokens"]),
        completion_tokens=int(row["completion_tokens"]),
        reasoning_tokens=int(row["reasoning_tokens"]),
        total_tokens=int(row["total_tokens"]),
        latency_seconds=float(row["latency_seconds"]),
        estimated_cost_usd=float(row["estimated_cost_usd"]),
        error=_optional_str(row["error"]),
        validation_status=str(context["validation_status"]),
        synthetic=bool(context["synthetic"]),
        environment_config=str(context["environment_config"]),
        usage=_parse_config(row["usage_json"]) if "usage_json" in row.keys() else {},
    )


def _episode_from_mapping(payload: dict[str, object]) -> EpisodeObservation:
    return EpisodeObservation(
        experiment_id=str(payload["experiment_id"]),
        session_id=str(payload["session_id"]),
        environment_id=str(payload["environment_id"]),
        provider=str(payload["provider"]),
        model_id=str(payload["model_id"]),
        feedback_condition=str(payload["feedback_condition"]),
        split=str(payload["split"]),
        experiment_seed=int(payload["experiment_seed"]),  # type: ignore[arg-type]
        experiment_status=str(payload.get("experiment_status", "completed")),
        revision_index=int(payload["revision_index"]),  # type: ignore[arg-type]
        episode_index=int(payload["episode_index"]),  # type: ignore[arg-type]
        episode_seed=int(payload["episode_seed"]),  # type: ignore[arg-type]
        total_reward=_optional_float(payload.get("total_reward")),
        success=_optional_bool(payload.get("success")),
        crashed=_optional_bool(payload.get("crashed")),
        steps=int(payload["steps"]),  # type: ignore[arg-type]
        elapsed_seconds=float(payload["elapsed_seconds"]),  # type: ignore[call-overload]
        error=_optional_str(payload.get("error")),
        validation_status=str(payload.get("validation_status", PRELIMINARY)),
        synthetic=bool(payload.get("synthetic", False)),
        environment_config=str(payload.get("environment_config", "{}")),
        development_seeds=_seed_list(payload.get("development_seeds")),
        held_out_seeds=_seed_list(payload.get("held_out_seeds")),
    )


def _attempt_from_mapping(payload: dict[str, object]) -> AttemptObservation:
    return AttemptObservation(
        experiment_id=str(payload["experiment_id"]),
        session_id=str(payload["session_id"]),
        environment_id=str(payload["environment_id"]),
        provider=str(payload["provider"]),
        model_id=str(payload["model_id"]),
        feedback_condition=str(payload["feedback_condition"]),
        split=str(payload["split"]),
        experiment_status=str(payload.get("experiment_status", "completed")),
        revision_index=int(payload["revision_index"]),  # type: ignore[arg-type]
        call_index=int(payload["call_index"]),  # type: ignore[arg-type]
        selected=bool(_required_bool(payload["selected"])),
        valid=bool(_required_bool(payload["valid"])),
        validation_error=_optional_str(payload.get("validation_error")),
        prompt_tokens=int(payload["prompt_tokens"]),  # type: ignore[arg-type]
        completion_tokens=int(payload["completion_tokens"]),  # type: ignore[arg-type]
        reasoning_tokens=int(payload["reasoning_tokens"]),  # type: ignore[arg-type]
        total_tokens=int(payload["total_tokens"]),  # type: ignore[arg-type]
        latency_seconds=float(payload["latency_seconds"]),  # type: ignore[call-overload]
        estimated_cost_usd=float(payload["estimated_cost_usd"]),  # type: ignore[call-overload]
        error=_optional_str(payload.get("error")),
        validation_status=str(payload.get("validation_status", PRELIMINARY)),
        synthetic=bool(payload.get("synthetic", False)),
        environment_config=str(payload.get("environment_config", "{}")),
        usage=dict(payload.get("usage") or {}),
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalysisError(f"expected a real number or null, got {value!r}")
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnalysisError(f"expected an integer or null, got {value!r}")
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_bool(value: object) -> bool | None:
    if value is None:
        return None
    return _required_bool(value)


def _required_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"0", "1", "true", "false"}:
        return value.strip().lower() in {"1", "true"}
    raise AnalysisError(f"expected a boolean, got {value!r}")
