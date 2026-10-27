"""Compare a re-recorded scripted session with the original Mission 013 recording (read-only on both)."""
import hashlib
import json
import sys
from pathlib import Path

TIMING = {"received_utc", "seconds", "utc"}
# fields added by the review fixes (serve now records raw input lines); absent from pre-fix records
NEW_FIELDS = {"raw_line_sha256", "raw_line_base64", "raw_line_bytes"}


def lines(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def strip(r, drop):
    if isinstance(r, dict):
        return {k: strip(v, drop) for k, v in r.items() if k not in drop}
    if isinstance(r, list):
        return [strip(v, drop) for v in r]
    return r


def compare(old: Path, new: Path):
    to, tn = lines(old / "player_transcript.jsonl"), lines(new / "player_transcript.jsonl")
    req_same = [strip(e["request"], set()) for e in to] == [strip(e["request"], set()) for e in tn]
    resp_same = strip([e["response"] for e in to], TIMING) == strip([e["response"] for e in tn], TIMING)
    shots_o = sorted((old / "screenshots").iterdir())
    shots_n = sorted((new / "screenshots").iterdir())
    bytes_same = [a.name for a in shots_o] == [b.name for b in shots_n] and all(
        a.read_bytes() == b.read_bytes() for a, b in zip(shots_o, shots_n))
    ref_same = strip(lines(old / "referee.jsonl"), TIMING) == strip(lines(new / "referee.jsonl"), TIMING)
    epi_o, epi_n = strip(lines(old / "episodes.jsonl"), TIMING), strip(lines(new / "episodes.jsonl"), TIMING)
    starts = {hashlib.sha256(p.read_bytes()).hexdigest() for d in (old, new) for p in (d / "referee_frames").iterdir()}
    mo, mn = (json.loads((d / "session.json").read_text(encoding="utf-8")) for d in (old, new))
    return {
        "session": new.name, "requests": [len(to), len(tn)], "screenshots": [len(shots_o), len(shots_n)],
        "requests_identical": req_same, "player_responses_identical": resp_same,
        "screenshot_bytes_identical": bytes_same, "referee_ticks_identical": ref_same,
        "episode_receipts_identical": epi_o == epi_n, "distinct_start_frames": len(starts),
        "outcomes": [[e["outcome"], e["frames"]] for e in epi_n],
        "clock_js_same": mo["environment"]["clock_js_sha256"] == mn["environment"]["clock_js_sha256"],
        "browser": [mo["software"]["browser"], mn["software"]["browser"]],
        "git": [mo["software"]["git"], mn["software"]["git"]],
        "new_network": mn["network"], "new_page_errors": mn["page_errors"], "new_status": mn["status"],
        "new_stderr_log_bytes": (new / "referee_stderr.log").stat().st_size,
    }


if __name__ == "__main__":
    old_root, new_root = Path(sys.argv[1]), Path(sys.argv[2])
    out = [compare(old_root / n, new_root / n) for n in ("scripted-idle", "scripted-key-sweep", "scripted-seeded-random")]
    print(json.dumps(out, indent=1))
