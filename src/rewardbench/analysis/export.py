"""Write a canonical JSONL export from a loaded log."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from rewardbench.analysis.schema import LogBundle


def export_jsonl(bundle: LogBundle, path: str | Path) -> Path:
    """Write episodes, attempts, and errors as JSONL.

    The export is a portable copy of the loaded log. It is not a new experiment.
    """

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as handle:
        for episode in bundle.episodes:
            handle.write(_line("episode", asdict(episode)))
        for attempt in bundle.attempts:
            handle.write(_line("attempt", asdict(attempt)))
        for error in bundle.errors:
            handle.write(_line("error", asdict(error)))
    return destination


def _line(record_type: str, payload: dict[str, object]) -> str:
    body = {"record_type": record_type, **payload}
    return json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n"
