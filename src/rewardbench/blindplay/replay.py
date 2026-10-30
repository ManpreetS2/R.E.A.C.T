"""Reproducibility check: re-run a recorded session's exact requests in a fresh referee.

The replay is a new session recorded under ``<session>/replays/<utc>/`` (the original record is
never modified). The receipt compares, request by request, everything returned to the player
(screenshot SHA-256, counters, errors), every referee tick state, and every episode outcome.

    python -m rewardbench.blindplay.replay runs/blind-visual/<id>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rewardbench.blindplay import serve, session as session_mod

_TIMING = {"received_utc", "seconds", "utc"}


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _strip(record: Any) -> Any:
    if isinstance(record, dict):
        return {k: _strip(v) for k, v in record.items() if k not in _TIMING}
    if isinstance(record, list):
        return [_strip(v) for v in record]
    return record


def replay(original: Path, *, label: str | None = None) -> dict[str, Any]:
    original = Path(original)
    manifest = json.loads((original / "session.json").read_text(encoding="utf-8"))
    transcript = _lines(original / "player_transcript.jsonl")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = original / "replays" / stamp
    budgets = manifest["budgets"]
    with session_mod.Session(out, seed=manifest["environment"]["seed"],
                             episode_frame_budget=budgets["episode_frame_budget"],
                             max_episodes=budgets["max_episodes"], max_requests=budgets["max_requests"],
                             player_label=label or f"replay of {original.name} (referee verification, not a player)",
                             player_is_ai=False, keyset=manifest["player_contract"]["keyset"]) as s:
        for entry in transcript:
            if "raw_line_base64" in entry:   # arrived over serve: re-decode the exact bytes the same way
                raw = base64.b64decode(entry["raw_line_base64"])
                request, rejection = serve.decode_line(raw)
                if entry.get("raw_line_bytes", len(raw)) > len(raw):
                    rejection = f"request longer than {serve.MAX_LINE_BYTES} bytes"
                s.handle(request, raw_line=raw, rejection=rejection)
            else:
                s.handle(entry["request"])
    replayed = _lines(out / "player_transcript.jsonl")
    a = [_strip(e["response"]) for e in transcript]
    b = [_strip(e["response"]) for e in replayed]
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    ref_a, ref_b = (_strip(_lines(d / "referee.jsonl")) for d in (original, out))
    epi_a, epi_b = (_strip(_lines(d / "episodes.jsonl")) for d in (original, out))
    images = [(x.get("image", {}).get("sha256"), y.get("image", {}).get("sha256")) for x, y in zip(a, b) if "image" in x]
    stored_ok = all(hashlib.sha256((d / e["response"]["image"]["file"]).read_bytes()).hexdigest() == e["response"]["image"]["sha256"]
                    for d, entries in ((original, transcript), (out, replayed)) for e in entries if "image" in e["response"])
    new_manifest = json.loads((out / "session.json").read_text(encoding="utf-8"))
    provenance = {k: (manifest["environment"][k] == new_manifest["environment"][k])
                  for k in ("upstream_commit", "upstream_sha256", "clock_js_sha256", "seed", "viewport")}
    provenance["browser"] = manifest["software"]["browser"] == new_manifest["software"]["browser"]
    provenance["served_files"] = manifest["network"]["served"] == new_manifest["network"]["served"]
    receipt = {
        "original": str(original), "replay": str(out), "requests": len(transcript), "replayed_requests": len(replayed),
        "responses_identical": len(a) == len(b) and first is None, "first_mismatch_index": first,
        "screenshots_compared": len(images), "screenshots_identical": sum(1 for x, y in images if x == y),
        "referee_ticks_identical": ref_a == ref_b, "episodes_identical": epi_a == epi_b,
        "stored_screenshots_match_transcripts": stored_ok, "provenance_identical": provenance,
        "episode_outcomes": [e["outcome"] for e in epi_b],
        "original_environment": {k: manifest["environment"][k] for k in ("id", "upstream_commit", "seed", "clock_js_sha256")},
        "original_browser": manifest["software"]["browser"],
    }
    receipt["reproduced"] = bool(receipt["responses_identical"] and receipt["referee_ticks_identical"]
                                 and receipt["episodes_identical"] and stored_ok and all(provenance.values()))
    (out / "replay_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.replay", description=__doc__.split("\n\n")[0])
    parser.add_argument("session", type=Path)
    args = parser.parse_args(argv)
    receipt = replay(args.session)
    print(json.dumps(receipt, indent=2))
    return 0 if receipt["reproduced"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
