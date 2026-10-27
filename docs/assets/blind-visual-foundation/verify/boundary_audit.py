"""Mission 013 boundary audit (scripted, NON-AI). Usage: boundary_audit.py <repo> <verify_root>

1. Hostile-input session through the real serve pipe: malformed/forbidden lines interleaved with valid acts.
   Checks: nothing on stderr, every rejection is a contract error with a fixed, non-revealing message,
   rejected lines never advance the game (the valid-act screenshots equal a clean session with the
   same valid acts only), and the session replays identically.
2. Audit of every player-visible response in every session under <verify_root>: exact field sets,
   no numbers beyond procedural counters, PNG bytes match hash, PNGs carry no text metadata chunks.
"""
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

repo, root = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo / "src"))
from rewardbench.blindplay import contract, replay, serve  # noqa: E402

ENV = dict(os.environ, PYTHONPATH=str(repo / "src"))
PY = sys.executable
VALID = [b'{"tool":"observe"}', b'{"tool":"act","keys":["ArrowUp"],"frames":60}',
         b'{"tool":"act","keys":["ArrowLeft","Space"],"frames":45}', b'{"tool":"act","keys":[],"frames":120}']
HOSTILE = [
    b"not json", b"[" * 100000, b'{"tool":"act","keys":[],"frames":' + b"9" * 5000 + b"}",
    b'{"tool":"observe","id":"\xff\xfe"}', b'{"tool":"act","keys":[],"frames":5,"frames":120}',
    b'{"tool":"act","keys":[],"frames":Infinity}', b'{"tool":"act","keys":["ArrowUp"],"frames":121}',
    b'{"tool":"act","keys":["ArrowUp"],"frames":0}', b'{"tool":"act","keys":["KeyQ"],"frames":5}',
    b'{"tool":"act","keys":["ArrowUp","ArrowUp"],"frames":5}', b'{"tool":"act","keys":[],"frames":5,"javascript":"lander.fuel=1e9"}',
    b'{"tool":"eval","code":"gameState"}', b'{"tool":"state"}', b'{"tool":"reset"}', b'{"tool":"observe","debug":true}',
    b'{"tool":"act","keys":[],"frames":5,"seed":7}', b'{"tool":"act","keys":[],"frames":5,"episode_frame_budget":999999}',
    b'"__import__(\'os\').system(\'whoami\')"', b'{"tool":"act","keys":["ArrowUp"],"frames":5,"x":"' + b"a" * 70000 + b'"}',
    b'{"tool":"act","keys":[{"key":"ArrowUp"}],"frames":5}', b"null", b"{}",
]


def serve_cmd(out):
    return [PY, "-m", "rewardbench.blindplay.serve", "--out", str(out), "--player-label",
            "scripted:boundary-audit (NOT AI)", "--player-is-ai", "false", "--max-episodes", "1",
            "--episode-frame-budget", "2000"]


def run(out, lines):
    p = subprocess.run(serve_cmd(out), input=b"\n".join(lines) + b"\n", capture_output=True, env=ENV, timeout=600)
    return p, [json.loads(x) for x in p.stdout.decode("utf-8").splitlines()]


hostile_lines = []
for i, v in enumerate(VALID):
    hostile_lines.append(v)
    hostile_lines += HOSTILE[i::len(VALID)]          # spread every hostile line between the valid ones
hostile_lines += HOSTILE                               # and all of them again at the end
hostile_lines.append(b'{"tool":"observe"}')
p_h, r_h = run(root / "scripted-hostile-inputs", hostile_lines)
p_c, r_c = run(root / "scripted-hostile-control", VALID + [b'{"tool":"observe"}'])

valid_idx = [i for i, l in enumerate(hostile_lines) if l in VALID or l == b'{"tool":"observe"}']
errors = [r for i, r in enumerate(r_h) if i not in valid_idx]
messages = sorted({e["error"] for e in errors})
leak_words = ("Traceback", "File \"", ".py", ".js", "\\", "/", "lander", "gameState", "Error:", "playwright", "chromium")
hostile = {
    "lines_sent": len(hostile_lines), "hostile_lines": len(hostile_lines) - len(valid_idx), "responses": len(r_h),
    "returncodes": [p_h.returncode, p_c.returncode], "player_stderr_bytes": [len(p_h.stderr), len(p_c.stderr)],
    "all_rejections_are_contract_errors": all(set(e) == contract.ERROR_FIELDS for e in errors),
    "distinct_rejection_messages": messages,
    "rejection_messages_reveal_nothing": not any(w in m for m in messages for w in leak_words),
    "valid_responses_identical_to_clean_control": [
        {k: v for k, v in r_h[i].items() if k != "seq"} == {k: v for k, v in r_c[j].items() if k != "seq"}
        for j, i in enumerate(valid_idx)],
    "referee_act_records": sum(1 for l in (root / "scripted-hostile-inputs" / "referee.jsonl").read_text().splitlines() if '"event": "act"' in l),
    "status": json.loads((root / "scripted-hostile-inputs" / "session.json").read_text())["status"],
}
hostile["replay_reproduced"] = replay.replay(root / "scripted-hostile-inputs")["reproduced"]
hostile["control_replay_reproduced"] = replay.replay(root / "scripted-hostile-control")["reproduced"]


def png_chunks(data):
    pos, kinds = 8, []
    while pos < len(data):
        n, = struct.unpack(">I", data[pos:pos + 4])
        kinds.append(data[pos + 4:pos + 8].decode("ascii"))
        pos += 12 + n
    return kinds


import hashlib  # noqa: E402

audit = {"sessions": 0, "responses": 0, "images": 0, "violations": []}
counters = {"seq", "episode", "episode_frame", "episode_frame_budget", "max_episodes", "frames_advanced"}
chunk_types = set()
for t in sorted(root.glob("**/player_transcript.jsonl")):
    d = t.parent
    audit["sessions"] += 1
    for e in (json.loads(x) for x in t.read_text(encoding="utf-8").splitlines()):
        r = e["response"]
        audit["responses"] += 1
        keys = set(r)
        if "image" in r:
            ok = keys == contract.OBSERVATION_FIELDS and set(r["image"]) == (contract.IMAGE_FIELDS - {"base64"}) | {"file"}
            nums = {k for k, v in r.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            ok &= nums <= counters
            png = (d / r["image"]["file"]).read_bytes()
            ok &= hashlib.sha256(png).hexdigest() == r["image"]["sha256"]
            ok &= (r["image"]["width"], r["image"]["height"]) == (1280, 720)
            chunk_types |= set(png_chunks(png))
            audit["images"] += 1
        else:
            ok = keys in (contract.ERROR_FIELDS, contract.BRIEF_FIELDS)
        if not ok:
            audit["violations"].append([str(d.relative_to(root)), e["request_index"]])
audit["png_chunk_types"] = sorted(chunk_types)
audit["png_text_metadata_chunks"] = sorted(chunk_types & {"tEXt", "zTXt", "iTXt", "eXIf", "tIME"})
print(json.dumps({"hostile_input_session": hostile, "player_visible_audit": audit}, indent=1))
