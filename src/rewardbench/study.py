"""Launch package for the first real-model study (offline tooling only).

Everything here is deterministic and offline: it writes the three matched study
configs, computes worst-case spend from the pricing catalog, runs the offline
preflight, and rehearses the whole study with the scripted mock model. It never
opens a provider socket, reads a credential, or evaluates the reserved final
cohort. Paid execution stays in ``rewardbench.operate`` behind its existing
authorization flags.

    python -m rewardbench.study write-configs [--check]
    python -m rewardbench.study budget
    python -m rewardbench.study preflight
    python -m rewardbench.study rehearse --out runs/first-llm-study-rehearsal
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping

import yaml

from rewardbench.config import load_config
from rewardbench.contracts import (
    CONTRACT_VERSION,
    ConfigError,
    FeedbackCondition,
    ModelRequest,
    PriorAttempt,
    RewardFeedback,
    Split,
)
from rewardbench.prompts import PROMPT_TEMPLATE_ID, render_messages
from rewardbench.providers.pricing import load_catalog, quote_call

STUDY_ID = "first_llm_study.v1"
# The prompt template is part of the experiment's identity: it is recorded in the hashed config metadata and
# tagged into names and output paths, so a prompt change can never reuse an older experiment's database.
PROMPT_TAG = "p" + PROMPT_TEMPLATE_ID.rsplit(".v", 1)[-1]
CONDITIONS = ("no_feedback", "reward_only", "numerical_reward")
RESERVED_FINAL_SEEDS = tuple(range(2_000_000, 2_000_016))  # apollolander.final_eval.v1
ENGINEERING_HELDOUT_SEEDS = tuple(range(1_000_000, 1_000_008))  # already exposed; rehearsal only
EPISODES_PER_REVISION = 8
DEVELOPMENT_SEEDS = tuple(range(8))
HISTORY_WINDOW = 4
MAX_EPISODE_STEPS = 8000
MASTER_SEED_BASE = 20261101
ERROR_ALLOWANCE_CHARS = 400  # a validation error string per history entry, worst case

# provider, model, settings. Only the first is configured and tested; the rest are for cost comparison.
PROPOSED = ("openai", "gpt-5.4-mini")
SETTINGS: dict[str, dict[str, Any]] = {
    "openai": {"max_output_tokens": 800, "reasoning_effort": "none", "json_mode": True},
    "google": {"max_output_tokens": 800, "max_reasoning_tokens": 32},
    "anthropic": {"max_output_tokens": 800},
    "xai": {"max_output_tokens": 800},
}
TIERS: dict[str, dict[str, int]] = {
    "pilot": {"revisions": 4, "replicates": 1},
    "study": {"revisions": 6, "replicates": 5},
}
# Keys the ApolloLander adapter attaches to every episode's metrics (checked against real episodes in tests).
METRIC_KEYS = (
    "fuel_remaining", "fuel_used", "in_landing_zone", "physics_seconds", "research_mode",
    "seed_affects_physics", "start_fuel", "start_rotation", "start_vx", "start_vy", "start_x",
    "start_y", "vertical_speed", "zone_width", "zone_x1", "zone_x2", "zone_y",
)
ALLOWED_ARM_DIFFERENCES = frozenset({"feedback_condition", "experiment_name", "database_path", "notes"})
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "configs" / "study"


def experiment_name(tier: str, condition: str, replicate: int, provider: str, model: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", model.lower())
    return f"llmstudy-{tier}-{provider}-{slug}-{condition.replace('_', '')}-{PROMPT_TAG}-r{replicate}"


def study_config(
    tier: str,
    condition: str,
    *,
    replicate: int = 1,
    provider: str = PROPOSED[0],
    model: str = PROPOSED[1],
    budget: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The one place the matched design is defined. Only ``condition`` varies across arms."""

    if condition not in CONDITIONS:
        raise ConfigError(f"unknown condition {condition!r}")
    spec = TIERS[tier]
    name = experiment_name(tier, condition, replicate, provider, model)
    config: dict[str, Any] = {
        "experiment_name": name,
        "environment_id": "apollolander",
        "provider": provider,
        "model_id": model,
        "feedback_condition": condition,
        "split": "development",
        "seed": MASTER_SEED_BASE + replicate - 1,
        "num_revisions": spec["revisions"],
        "episodes_per_revision": EPISODES_PER_REVISION,
        "history_window": HISTORY_WINDOW,
        "max_episode_steps": MAX_EPISODE_STEPS,
        "max_model_retries": 0,
        "checkpoint_every": 1,
        "on_invalid_policy": "skip",
        "on_model_failure": "abort",
        "on_episode_failure": "skip",
        "database_path": f"runs/first-llm-study/{tier}-{PROMPT_TAG}/{name}.sqlite",
        "budget": dict(budget) if budget else {},
        "development_seeds": list(DEVELOPMENT_SEEDS),
        # The pilot may only ever touch the already-exposed engineering seeds; the reserved cohort belongs
        # to the study tier alone.
        "held_out_seeds": list(RESERVED_FINAL_SEEDS if tier == "study" else ENGINEERING_HELDOUT_SEEDS),
        "model_settings": dict(SETTINGS[provider]),
        "metadata": {
            "study": STUDY_ID,
            "prompt_template": PROMPT_TEMPLATE_ID,
            "tier": tier,
            "replicate": replicate,
            "approval_required": True,
            "final_eval_cohort": "apollolander.final_eval.v1" if tier == "study" else "none (engineering seeds only)",
            "environment_version": "apollolander.env.v1",
            "task": "apollolander",
            "record_flights": True,
            "adapter_kwargs": {
                "research_mode": True,
                "max_steps": MAX_EPISODE_STEPS,
                "locked_camera": True,
                "start_schedule_version": "apollolander.starts.v1",
                "vary_fuel": False,
            },
        },
        "notes": (
            f"{STUDY_ID} {tier} arm {condition}, replicate {replicate}. Matched to its sibling arms in every "
            "field except feedback_condition and names. " +
            ("held_out_seeds is the reserved final cohort, listed as integers only: never run "
             "rewardbench.heldout on this config before the owner approves final evaluation "
             "(docs/FIRST_LLM_STUDY_PROTOCOL.md)." if tier == "study" else
             "held_out_seeds are the already-exposed engineering seeds; the reserved final cohort is "
             "not referenced by this tier.")
        ),
    }
    return config


# ---------------------------------------------------------------- worst-case budget

def _long(value: float) -> float:
    return float(f"{value:.16g}")


def _worst_attempt(index: int, condition: FeedbackCondition, episodes: int) -> PriorAttempt:
    """A history entry at its practical maximum size: 17-digit floats, full metrics, long error."""

    from rewardbench.environments.apollolander import demonstration_guidance_controller

    controller = demonstration_guidance_controller()
    params = {k: _long(v + 0.123456789012345) if isinstance(v, float) else v
              for k, v in controller.get("parameters", {}).items()}
    controller = {**controller, "parameters": params}
    feedback = None
    if condition is not FeedbackCondition.NO_FEEDBACK:
        feedback = tuple(
            RewardFeedback(
                revision_index=index,
                episode_index=episode,
                total_reward=_long(-123.45678901234567),
                success=False,
                crashed=False,
                steps=MAX_EPISODE_STEPS,
                metrics={key: _long(1234.5678901234567) for key in METRIC_KEYS},
            )
            for episode in range(episodes)
        )
    return PriorAttempt(
        revision_index=index,
        parameters=controller,
        valid=True,
        validation_error="x" * ERROR_ALLOWANCE_CHARS,
        feedback=feedback,
    )


def worst_case_calls(config: Mapping[str, Any], spec, catalog) -> list[dict[str, Any]]:
    """Per-call worst-case quote for every revision of one experiment (retries = 0)."""

    condition = FeedbackCondition(config["feedback_condition"])
    window = int(config["history_window"])
    calls = []
    for revision in range(int(config["num_revisions"])):
        history = tuple(_worst_attempt(i, condition, int(config["episodes_per_revision"]))
                        for i in range(max(0, revision - window), revision))
        request = ModelRequest(
            contract_version=CONTRACT_VERSION,
            experiment_id="budget",
            session_id="budget",
            revision_index=revision,
            feedback_condition=condition,
            split=Split.DEVELOPMENT,
            environment=spec,
            history=history,
            model_settings=config["model_settings"],
        )
        system_text, user_text = render_messages(request)
        quote = quote_call(
            catalog, config["provider"], config["model_id"],
            system_text=system_text, user_text=user_text,
            settings=config["model_settings"], attempts=int(config["max_model_retries"]) + 1,
        )
        if not quote.available:
            raise ConfigError(f"cannot bound {config['provider']}:{config['model_id']}: {quote.note}")
        calls.append({"revision": revision, "usd": quote.usd,
                      "tokens": quote.prompt_tokens + quote.completion_tokens + quote.reasoning_tokens,
                      "prompt_tokens": quote.prompt_tokens, "completion_tokens": quote.completion_tokens})
    return calls


def _spec(config: Mapping[str, Any]):
    from rewardbench.run.factory import build_environment

    env = build_environment(config_from_dict(config))
    try:
        return env.describe()
    finally:
        close = getattr(env, "close", None)
        if callable(close):
            close()


def config_from_dict(data: Mapping[str, Any]):
    from rewardbench.config.loader import config_from_mapping

    prepared = copy.deepcopy(dict(data))
    if not prepared.get("budget"):
        prepared["budget"] = {"max_cost_usd": 1.0, "max_tokens": 1_000_000, "max_wall_seconds": 3600,
                              "max_revisions": prepared["num_revisions"], "max_episodes": 1000,
                              "max_model_calls": prepared["num_revisions"]}
    return config_from_mapping(prepared)


def ceilings(tier: str, provider: str = PROPOSED[0], model: str = PROPOSED[1]) -> dict[str, Any]:
    """Per-experiment budget block: the worst-case sum for this tier, rounded up to the cent."""

    catalog = load_catalog()
    config = study_config(tier, "numerical_reward", provider=provider, model=model)  # largest prompts
    calls = worst_case_calls(config, _spec(config), catalog)
    revisions = TIERS[tier]["revisions"]
    return {
        "max_cost_usd": math.ceil(sum(c["usd"] for c in calls) * 100) / 100,
        "max_tokens": int(math.ceil(sum(c["tokens"] for c in calls) / 1000) * 1000),
        "max_wall_seconds": 3600,
        "max_revisions": revisions,
        "max_episodes": revisions * EPISODES_PER_REVISION,
        "max_model_calls": revisions,
    }


def build_study_config(tier: str, condition: str, *, replicate: int = 1, provider: str = PROPOSED[0],
                       model: str = PROPOSED[1]) -> dict[str, Any]:
    return study_config(tier, condition, replicate=replicate, provider=provider, model=model,
                        budget=ceilings(tier, provider, model))


HEADER = (
    "# {study}: matched arm for the first real-model study. NOT AUTHORIZED TO RUN.\n"
    "# Live execution needs the owner's approval of provider, model and a total USD ceiling, an\n"
    "# exported API key, and the explicit flags in docs/FIRST_LLM_STUDY_LAUNCH.md.\n"
    "# Generated by `python -m rewardbench.study write-configs`; do not hand-edit (a test enforces it).\n"
    "# budget.* is the computed worst-case ceiling for this tier at the catalog price (not an approval).\n"
)


def render_yaml(config: Mapping[str, Any]) -> str:
    return HEADER.format(study=STUDY_ID) + yaml.safe_dump(dict(config), sort_keys=False, width=100)


def config_path(tier: str, condition: str, replicate: int = 1, base: Path = CONFIG_DIR) -> Path:
    suffix = "" if replicate == 1 else f"_r{replicate}"
    return base / f"{tier}_{condition}{suffix}.yaml"


def write_configs(tier: str, base: Path, *, replicates: int | None = None, check: bool = False) -> list[Path]:
    count = replicates or TIERS[tier]["replicates"]
    written, stale = [], []
    for replicate in range(1, count + 1):
        for condition in CONDITIONS:
            path = config_path(tier, condition, replicate, base)
            text = render_yaml(build_study_config(tier, condition, replicate=replicate))
            if check:
                if not path.exists() or path.read_text(encoding="utf-8") != text:
                    stale.append(path)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            written.append(path)
    if stale:
        raise ConfigError("study configs are out of date: " + ", ".join(str(p) for p in stale))
    return written


def arm_differences(a: Mapping[str, Any], b: Mapping[str, Any]) -> set[str]:
    keys = set(a) | set(b)
    return {k for k in keys if a.get(k) != b.get(k)}


def check_matched(configs: Mapping[str, Mapping[str, Any]]) -> None:
    """Raise unless every arm differs from the others only in the allowed fields."""

    items = list(configs.items())
    for (_, first), (name, other) in zip(items, items[1:]):
        extra = arm_differences(first, other) - ALLOWED_ARM_DIFFERENCES
        if extra:
            raise ConfigError(f"arm {name} differs from its sibling in {sorted(extra)}")


# ---------------------------------------------------------------- budget report

def budget_rows(provider: str, model: str) -> dict[str, Any]:
    catalog = load_catalog()
    out: dict[str, Any] = {"model": f"{provider}:{model}", "catalog": catalog.version, "tiers": {}}
    for tier, spec_ in TIERS.items():
        per_arm = {}
        for condition in CONDITIONS:
            config = study_config(tier, condition, provider=provider, model=model)
            calls = worst_case_calls(config, _spec(config), catalog)
            per_arm[condition] = {
                "calls": len(calls),
                "usd": sum(c["usd"] for c in calls),
                "tokens": sum(c["tokens"] for c in calls),
                "max_prompt_tokens": max(c["prompt_tokens"] for c in calls),
                "completion_ceiling": calls[0]["completion_tokens"],
            }
        if tier == "pilot":
            out["first_call"] = {
                "calls": 3,
                "worst_case_usd": sum(
                    worst_case_calls(study_config("pilot", c, provider=provider, model=model),
                                     _spec(study_config("pilot", c, provider=provider, model=model)), catalog)[0]["usd"]
                    for c in CONDITIONS),
            }
        sessions = 3 * spec_["replicates"]
        total_usd = sum(v["usd"] for v in per_arm.values()) * spec_["replicates"]
        out["tiers"][tier] = {
            "revisions": spec_["revisions"], "replicates": spec_["replicates"], "sessions": sessions,
            "calls": sum(v["calls"] for v in per_arm.values()) * spec_["replicates"],
            "per_arm": per_arm, "worst_case_usd": total_usd,
            "worst_case_tokens": sum(v["tokens"] for v in per_arm.values()) * spec_["replicates"],
        }
    return out


def budget_markdown() -> str:
    lines = []
    main = budget_rows(*PROPOSED)
    lines.append(f"Proposed model `{main['model']}`, catalog `{main['catalog']}`.\n")
    lines.append("| Tier | Revisions | Replicates | Paid calls | Worst-case tokens | Worst-case USD |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    lines.append(f"| first call per arm | 1 | 1 | {main['first_call']['calls']} | - | "
                 f"${main['first_call']['worst_case_usd']:.4f} |")
    for tier, row in main["tiers"].items():
        lines.append(f"| {tier} | {row['revisions']} | {row['replicates']} | {row['calls']} | "
                     f"{row['worst_case_tokens']:,} | ${row['worst_case_usd']:.4f} |")
    lines.append("\nPer arm, per replicate (worst case):\n")
    lines.append("| Tier | Arm | Calls | Largest prompt (token ceiling) | Output ceiling/call | USD |")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
    for tier, row in main["tiers"].items():
        for condition, arm in row["per_arm"].items():
            lines.append(f"| {tier} | {condition} | {arm['calls']} | {arm['max_prompt_tokens']:,} | "
                         f"{arm['completion_ceiling']} | ${arm['usd']:.4f} |")
    lines.append("\nSame designs priced on the other catalog models (indicative only; settings for these "
                 "providers are not live-tested):\n")
    lines.append("| Model | first_call | pilot | study |")
    lines.append("| --- | ---: | ---: | ---: |")
    for provider, model in (("openai", "gpt-5.4-mini"), ("google", "gemini-3.1-flash-lite"),
                            ("anthropic", "claude-haiku-5-5"), ("xai", "grok-4.3"), ("openai", "gpt-5.4")):
        try:
            rows = budget_rows(provider, model)
        except ConfigError as exc:
            lines.append(f"| {provider}:{model} | unavailable: {exc} | | |")
            continue
        t = rows["tiers"]
        lines.append(f"| {provider}:{model} | ${rows['first_call']['worst_case_usd']:.4f} | "
                     f"${t['pilot']['worst_case_usd']:.4f} | ${t['study']['worst_case_usd']:.4f} |")
    return "\n".join(lines)


# ---------------------------------------------------------------- offline preflight

def preflight(tier: str = "pilot") -> list[dict[str, Any]]:
    """Run the real live preflight for each arm with a placeholder key. No network, no env read."""

    from rewardbench.run.factory import build_environment, prepare_config
    from rewardbench.run.live import preflight_live

    results = []
    configs = {}
    for condition in CONDITIONS:
        path = config_path(tier, condition)
        config = prepare_config(path)
        configs[condition] = yaml.safe_load(path.read_text(encoding="utf-8"))
        env = build_environment(config)
        try:
            live = preflight_live(config, env, api_key="offline-placeholder-not-a-key")
        finally:
            close = getattr(env, "close", None)
            if callable(close):
                close()
        results.append({"arm": condition, "model": f"{live.provider}:{live.model_id}",
                        "first_call_worst_case_usd": live.quote.usd, "budget_usd": live.max_cost_usd,
                        "retries": live.max_model_retries})
    check_matched(configs)
    return results


# ---------------------------------------------------------------- rehearsal

def rehearsal_config(live_config: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the scripted-mock twin of a live study config. Design fields are untouched."""

    data = copy.deepcopy(dict(live_config))
    data["experiment_name"] = str(data["experiment_name"]).replace("llmstudy", "rehearsal", 1)
    data["provider"] = "mock"
    data["model_id"] = "scripted-feedback-responsive"
    data["model_settings"] = {"temperature": 0}
    data["held_out_seeds"] = list(ENGINEERING_HELDOUT_SEEDS)
    data["budget"] = {"max_cost_usd": 1.0, "max_tokens": 10_000_000, "max_wall_seconds": 3600,
                      "max_revisions": data["num_revisions"],
                      "max_episodes": data["num_revisions"] * data["episodes_per_revision"],
                      "max_model_calls": data["num_revisions"] * 2}
    meta = dict(data["metadata"])
    meta.update(purpose="offline_rehearsal", not_llm_learning=True, approval_required=False)
    meta.pop("final_eval_cohort", None)
    data["metadata"] = meta
    data["notes"] = ("Scripted mock rehearsal of " + str(live_config["experiment_name"]) +
                     ". Infrastructure verification only; not evidence of LLM learning. "
                     "Held-out seeds are the already-exposed engineering cohort.")
    return data


def audit_rehearsal(out: Path, tier: str) -> dict[str, Any]:
    """Independent checks over a finished rehearsal directory. Raises AssertionError on any failure."""

    from rewardbench.environments import make_environment

    spec = TIERS[tier]
    summary: dict[str, Any] = {"tier": tier, "arms": {}}
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=MAX_EPISODE_STEPS)
    all_prompts: dict[str, dict[int, str]] = {}
    for condition in CONDITIONS:
        name = experiment_name(tier, condition, 1, *PROPOSED).replace("llmstudy", "rehearsal", 1)
        database = out / f"{name}.sqlite"
        assert database.exists(), f"missing {database}"
        with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            experiment = db.execute("SELECT status, completed_revisions, feedback_condition FROM experiments").fetchone()
            assert experiment["status"] == "completed" and experiment["completed_revisions"] == spec["revisions"]
            assert experiment["feedback_condition"] == condition
            attempts = db.execute("SELECT * FROM attempts ORDER BY revision_index, call_index").fetchall()
            episodes = db.execute("SELECT revision_index, seed FROM episodes").fetchall()
            heldout = db.execute("SELECT seed, total_reward FROM heldout_episodes").fetchall()
            freezes = db.execute("SELECT source_revision_index, selection_rule FROM frozen_controllers").fetchall()
        assert len(attempts) == spec["revisions"] and all(a["valid"] for a in attempts)
        assert len(episodes) == spec["revisions"] * EPISODES_PER_REVISION
        panels = {frozenset(e["seed"] for e in episodes if e["revision_index"] == r) for r in range(spec["revisions"])}
        assert len(panels) == 1 and panels.pop() == frozenset(DEVELOPMENT_SEEDS), "development panel must repeat"
        assert {h["seed"] for h in heldout} == set(ENGINEERING_HELDOUT_SEEDS)
        assert len(freezes) == 1 and freezes[0]["selection_rule"] == "last_valid_selected"
        assert freezes[0]["source_revision_index"] == spec["revisions"] - 1
        seen = {e["seed"] for e in episodes} | {h["seed"] for h in heldout}
        assert not seen & set(RESERVED_FINAL_SEEDS), "reserved final seeds were touched"
        prompts = {}
        for file in sorted((out / "prompts" / name).glob("revision_*.txt")):
            prompts[int(file.name.split("_")[1])] = file.read_text(encoding="utf-8")
        assert len(prompts) == spec["revisions"]
        all_prompts[condition] = prompts
        leaked = [str(h["total_reward"]) for h in heldout if str(h["total_reward"]) in "".join(prompts.values())]
        assert not leaked, f"held-out reward appeared in a development prompt: {leaked}"
        assert not any(str(s) in "".join(prompts.values()) for s in ENGINEERING_HELDOUT_SEEDS + RESERVED_FINAL_SEEDS)
        flights = sorted((out / "flights").rglob("*.flight.json")) + sorted((out / "heldout-flights" / name).rglob("*.flight.json"))
        verified = 0
        for path in flights:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("experiment_id") != _experiment_id(database):
                continue
            result = adapter.verify_flight_record(record)
            assert result["matched"], (path.name, result["mismatches"])
            verified += 1
        assert verified >= spec["revisions"] * EPISODES_PER_REVISION + len(ENGINEERING_HELDOUT_SEEDS)
        summary["arms"][condition] = {
            "model_calls": len(attempts), "dev_episodes": len(episodes), "heldout_episodes": len(heldout),
            "replays_verified": verified,
            "dev_reward_by_revision": [round(_mean([r for r in _rewards(database, rev)]), 3) for rev in range(spec["revisions"])],
            "heldout_mean_reward": round(_mean([h["total_reward"] for h in heldout]), 3),
            "frozen_revision": freezes[0]["source_revision_index"],
        }
    for revision in range(1, spec["revisions"]):
        none = all_prompts["no_feedback"][revision]
        reward = all_prompts["reward_only"][revision]
        numeric = all_prompts["numerical_reward"][revision]
        assert "reward=" not in none and "success=" not in none
        assert "reward=" in reward and not any(t in reward for t in ("success=", "steps=", "metrics="))
        assert all(t in numeric for t in ("reward=", "success=", "steps=", "metrics="))
    zero = [_strip_header(all_prompts[c][0]) for c in CONDITIONS]
    assert len(set(zero)) == 1, "revision-0 prompts must be identical apart from the condition header"
    summary["isolation"] = "verified"
    return summary


def _strip_header(prompt: str) -> str:
    return "\n".join(line for line in prompt.splitlines()
                     if not line.startswith(("# provider=", "Earlier revisions")))


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else float("nan")


def _rewards(database: Path, revision: int) -> list[float]:
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
        return [r[0] for r in db.execute(
            "SELECT total_reward FROM episodes WHERE revision_index=? AND total_reward IS NOT NULL", (revision,))]


def _experiment_id(database: Path) -> str:
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
        return db.execute("SELECT experiment_id FROM experiments").fetchone()[0]


def rehearse(out: Path, tier: str) -> dict[str, Any]:
    from rewardbench import operate

    base = out / "configs"
    base.mkdir(parents=True, exist_ok=True)
    paths = []
    for condition in CONDITIONS:
        derived = rehearsal_config(build_study_config(tier, condition))
        path = base / f"{tier}_{condition}_rehearsal.yaml"
        path.write_text(yaml.safe_dump(derived, sort_keys=False), encoding="utf-8")
        paths.append(path)
    args = ["run", "--mode", "mock", "--heldout", "--out", str(out)]
    for path in paths:
        args += ["--config", str(path)]
    code = operate.main(args)
    if code != 0:
        raise RuntimeError(f"operator rehearsal exited {code}")
    summary = audit_rehearsal(out, tier)
    (out / "rehearsal_audit.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.study", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    w = sub.add_parser("write-configs", help="write (or --check) the matched study configs")
    w.add_argument("--tier", choices=tuple(TIERS), action="append")
    w.add_argument("--out", type=Path, default=CONFIG_DIR)
    w.add_argument("--replicates", type=int, default=None)
    w.add_argument("--check", action="store_true")
    sub.add_parser("budget", help="print worst-case spend tables from the pricing catalog")
    p = sub.add_parser("preflight", help="offline live preflight for every arm (no key, no network)")
    p.add_argument("--tier", choices=tuple(TIERS), default="pilot")
    r = sub.add_parser("rehearse", help="free scripted-mock rehearsal of the whole study design")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--tier", choices=tuple(TIERS), default="pilot")
    args = parser.parse_args(argv)
    try:
        if args.command == "write-configs":
            for tier in args.tier or ["pilot"]:
                for path in write_configs(tier, args.out, replicates=args.replicates, check=args.check):
                    print(("ok " if args.check else "wrote ") + str(path))
        elif args.command == "budget":
            print(budget_markdown())
        elif args.command == "preflight":
            for row in preflight(args.tier):
                print(json.dumps(row))
            print("matched arms: ok; no network or credential was used")
        else:
            print(json.dumps(rehearse(args.out.resolve(), args.tier), indent=2))
    except (ConfigError, AssertionError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
