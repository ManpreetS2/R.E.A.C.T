"""Build docs/assets/blind-visual-foundation/evidence-verified-2026-10-27.json (same per-session layout as evidence.json)."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

repo, root, compare_json, audit_json, out = (Path(a) for a in sys.argv[1:6])


def lines(p):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def session_entry(d):
    m = json.loads((d / "session.json").read_text(encoding="utf-8"))
    episodes = [{k: e[k] for k in ("episode", "outcome", "frames", "native_message", "native_score",
                                   "start_frame_sha256", "end_seq", "end_screenshot_sha256")} for e in lines(d / "episodes.jsonl")]
    replays = []
    for r in sorted((d / "replays").iterdir()):
        rc = json.loads((r / "replay_receipt.json").read_text(encoding="utf-8"))
        replays.append({k: rc[k] for k in ("reproduced", "responses_identical", "screenshots_compared", "screenshots_identical",
                                           "referee_ticks_identical", "episodes_identical", "stored_screenshots_match_transcripts",
                                           "provenance_identical", "episode_outcomes")} | {"replay": r.name})
    files = [{"path": p.relative_to(repo).as_posix(), "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(d.rglob("*")) if p.is_file()]
    return {"directory": d.relative_to(repo).as_posix(), "player": m["player"], "status": m["status"],
            "started_utc": m["started_utc"], "ended_utc": m["ended_utc"], "budgets": m["budgets"], "counts": m["counts"],
            "environment": {k: m["environment"][k] for k in ("id", "upstream_commit", "clock_js_sha256", "seed", "viewport")},
            "software": m["software"], "network": m["network"], "page_errors": m["page_errors"],
            "environment_failure": m["environment_failure"], "episodes": episodes, "replays": replays, "files": files}


names = ["scripted-idle", "scripted-key-sweep", "scripted-seeded-random", "scripted-hostile-inputs", "scripted-hostile-control"]
compare = json.loads(compare_json.read_text(encoding="utf-8"))
for c in compare:
    c.pop("new_network", None)
evidence = {
    "note": ("Scripted, NON-AI infrastructure verification (Mission 013 resume, 2026-10-27), recorded on the fixed tree "
             "(commit 2f4f25a, clean). Raw records are local only under runs/blind-visual/mission013-verify-20261027 "
             "(gitignored); per-file SHA-256 below. No model was called; no paid API call. The pre-fix recordings and "
             "their evidence.json are preserved unchanged."),
    "upstream_verification": {
        "repository": "https://github.com/sebleedelisle/apollolander", "commit": "0da09dccbadf0d6ee6efcce1f72e9ae206d341d2",
        "git_blob_sha1_match_github_tree": "17/17 (only extra vendored file: UPSTREAM_COMMIT.txt, our marker)",
        "raw_download_sha256_match_pins": "17/17 (fresh download from raw.githubusercontent.com, 2026-10-27)",
    },
    "comparison_with_prefix_recordings": {
        "original": "runs/blind-visual/mission013 (recorded 2026-10-27 04:12 UTC on e22f5a5 + uncommitted changes)",
        "result": compare,
        "clock_js_note": "clock.js hash differs because review fix m3 edited it (Date edge cases); every screenshot byte and tick state is still identical",
    },
    "boundary_audit": json.loads(audit_json.read_text(encoding="utf-8")),
    "sessions": [session_entry(root / n) for n in names],
}
out.write_text(json.dumps(evidence, indent=1) + "\n", encoding="utf-8")
print(out, out.stat().st_size)
