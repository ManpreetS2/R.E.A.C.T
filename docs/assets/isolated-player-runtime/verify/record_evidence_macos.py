"""Record the Mission 014 macOS (Seatbelt) isolation evidence (scripted, NON-AI; no model, no API call).

    python docs/assets/isolated-player-runtime/verify/record_evidence_macos.py <repo> <new empty out dir>

1. probe        the security stand-in attacks the sandbox with every path an attacker could guess on this Mac
2. scripted-*   idle / key-sweep / seeded-random, isolated, each compared byte for byte with the SAME script run
                unsandboxed on this Mac (Mission 013 path), and their physics outcomes with the Windows Mission 013
                evidence (screenshot bytes differ between OSes; outcomes and frame counts must not)
3. gateway      agent loop with a scripted gateway (NOT A MODEL): screenshots reach the gateway as PNG bytes
4. no-gateway   agent loop with the default disabled gateway: no model is reachable
Then every referee session is replayed in a fresh browser. Prints a JSON summary (hashes, no raw data).
"""

import hashlib
import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

repo, out = (Path(a).resolve() for a in sys.argv[1:3])
sys.path.insert(0, str(repo / "src"))
from rewardbench.blindplay import host as host_mod, isolation, replay, runtime_image, scripted  # noqa: E402

if out.exists() and any(out.iterdir()):
    raise SystemExit(f"{out} is not empty")
if isolation.supported() is not None or sys.platform != "darwin":
    raise SystemExit(f"macOS Seatbelt isolation unavailable: {isolation.supported()}")
home = Path.home()
M013 = json.loads((repo / "docs/assets/blind-visual-foundation/evidence-verified-2026-10-27.json").read_text())
M013_OUTCOMES = {Path(s["directory"]).name: [[e["outcome"], e["frames"]] for e in s["episodes"]] for s in M013["sessions"]}
summary = {"note": "scripted NON-AI stand-ins only; no model, no API call", "platform": isolation.describe()}


def results(d):
    return [r for r in (json.loads(x)["line"] for x in (d / "player_stderr.jsonl").read_text().splitlines())
            if isinstance(r, dict)]


# 1. probe -----------------------------------------------------------------------------------
probe = out / "probe"
scratch = Path(tempfile.mkdtemp(prefix="react-", dir="/tmp"))
listener, unix_listener = socket.socket(), socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind(("127.0.0.1", 0))
unix_listener.bind(str(scratch / "host.sock"))
hits, stop = [], threading.Event()
for sock in (listener, unix_listener):
    sock.listen(5)
    sock.settimeout(0.2)

    def accept(sock=sock):
        while not stop.is_set():
            try:
                hits.append(sock.accept()[1])
            except OSError:
                continue
    threading.Thread(target=accept, daemon=True).start()

main_checkout = home / "Projects/R.E.A.C.T"
candidates_read = [repo / p for p in ("PROJECT.md", "AGENTS.md", "src/rewardbench/blindplay/referee.py",
                                      "src/rewardbench/blindplay/host.py", "src/rewardbench/blindplay/seatbelt.py",
                                      "frontend/apollolander/upstream/game.js",
                                      "frontend/apollolander/experiment/physics.js", ".git", "pyproject.toml")] + [
    main_checkout / ".git/config", main_checkout / "experiments/apollo_gymnasium/env/apollo_env.py",
    main_checkout / "experiments/apollo_gymnasium/outputs/abcd_preflight/ABCD_REWARD_AUDIT.json",
    home / ".gitconfig", home / ".git-credentials", home / ".zshrc", home / ".zsh_history", home / ".config/gh/hosts.yml",
    home / ".claude.json", home / ".ssh/known_hosts", home / "Library/Keychains/login.keychain-db",
    Path("/etc/hosts"), Path("/etc/passwd")]
targets = {
    "read": [str(p) for p in candidates_read if p.is_file()]
            + [str(probe / "referee/referee.jsonl"), str(probe / "referee/referee_stderr.log"),
               str(probe / "host_transcript.jsonl")],
    "read_missing": [str(home / "react-no-such-file.txt"), str(repo / "no-such-file.txt")],
    "list": [str(p) for p in (repo, repo / "src", main_checkout, main_checkout / "experiments", home, home / ".ssh",
                              home / ".claude", home / "Library/Caches/ms-playwright", runtime_image.default_root(),
                              Path("/tmp"), Path("/Users"), Path("/Applications"), scratch) if p.is_dir()] + [str(probe)],
    "write": [str(repo / "pwned.txt"), str(probe / "pwned.txt"), str(runtime_image.default_root() / "pwned.txt"),
              str(scratch / "pwned.txt"), str(home / "pwned.txt")],
    "system_read": ["/"],
    "pids": [os.getpid(), 1],
    "tcp": [["127.0.0.1", listener.getsockname()[1]]],
    "unix": [str(scratch / "host.sock")],
    "persist_write": [str(scratch / "react_marker.txt")],
    "read_after_play": [str(probe / "referee/screenshots/000001.png"), str(probe / "referee/session.json"),
                        str(probe / "referee/episodes.jsonl"), str(probe / "player_stderr.jsonl")],
}
m = host_mod.Host(host_mod.HostConfig(out=probe, mode="probe", max_episodes=1, episode_frame_budget=2000,
                                      player_label="isolation probe stand-in (NOT AI)", probe_targets=targets)).run()
stop.set()
listener.close()
unix_listener.close()
leftovers = sorted(p.name for p in scratch.iterdir() if p.name != "host.sock")
(scratch / "host.sock").unlink(missing_ok=True)
scratch.rmdir()
outcomes = {}
for r in results(probe):
    if "probe" in r:
        outcomes.setdefault(r["probe"], []).append({"target": r["target"], "outcome": r["outcome"], "detail": r["detail"]})
summary["probe"] = {"status": m["status"], "counts": m["counts"], "isolation": m["isolation"],
                    "runtime_image": m["runtime_image"], "host_listener_connections": len(hits),
                    "files_left_in_writable_scratch": leftovers,
                    "pwned_files_exist": [t for t in targets["write"] if Path(t).exists()], "results": outcomes}

# 2. scripted stand-ins: isolated vs unsandboxed (same Mac) vs Windows Mission 013 outcomes -----------
summary["scripted"] = {}
for name, script, episodes in (("scripted-idle", "idle", 2), ("scripted-key-sweep", "key-sweep", 1),
                               ("scripted-seeded-random", "seeded-random", 3)):
    d, control = out / name, out / f"{name}-unsandboxed-control"
    mm = host_mod.Host(host_mod.HostConfig(out=d, mode="scripted", script=script, max_episodes=episodes,
                                           player_label=f"isolated scripted:{script} script_seed=0 (NOT AI)")).run()
    scripted.run(script, control, episodes=episodes, frame_budget=8000)
    new, old = sorted((d / "referee/screenshots").iterdir()), sorted((control / "screenshots").iterdir())
    got = [[e["outcome"], e["frames"]] for e in (json.loads(x) for x in (d / "referee/episodes.jsonl").read_text().splitlines())]
    summary["scripted"][name] = {
        "status": mm["status"], "counts": mm["counts"], "screenshots": [len(old), len(new)],
        "byte_identical_to_unsandboxed_control": [p.name for p in old] == [p.name for p in new]
        and all(a.read_bytes() == b.read_bytes() for a, b in zip(old, new)),
        "outcomes": got, "windows_mission013_outcomes": M013_OUTCOMES[name],
        "outcomes_equal_windows_mission013": got == M013_OUTCOMES[name],
    }

# 3. scripted gateway (NOT A MODEL) and 4. disabled gateway ---------------------------------------
gateway = host_mod.ScriptedGateway([(["ArrowUp"], 60), (["ArrowRight"], 30), ([], 120)])
d = out / "gateway-scripted-not-a-model"
mm = host_mod.Host(host_mod.HostConfig(out=d, mode="agent", max_episodes=1, episode_frame_budget=1000, max_model_calls=4,
                                       player_label="agent loop + scripted gateway (NOT A MODEL)"), gateway=gateway).run()
shown = [json.loads(x)["response"].get("image", {}).get("sha256") for x in (d / "referee/player_transcript.jsonl").read_text().splitlines()]
summary["gateway_scripted"] = {"status": mm["status"], "counts": mm["counts"], "player_is_ai": mm["player_is_ai"],
                               "images_received_by_gateway": len(gateway.received_images),
                               "all_received_images_are_referee_screenshots": set(gateway.received_images) <= set(filter(None, shown))}
d = out / "gateway-disabled"
mm = host_mod.Host(host_mod.HostConfig(out=d, mode="agent", max_episodes=1, max_model_calls=5,
                                       player_label="agent loop, no gateway (NOT AI)")).run()
summary["gateway_disabled"] = {"status": mm["status"], "counts": mm["counts"]}

# replays ---------------------------------------------------------------------------------------
summary["replays"] = {}
for ref in sorted(out.glob("*/referee")):
    r = replay.replay(ref)
    summary["replays"][ref.parent.name] = {k: r[k] for k in ("reproduced", "screenshots_compared", "screenshots_identical")}

summary["files"] = [{"path": p.relative_to(out).as_posix(), "bytes": p.stat().st_size,
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(out.rglob("*")) if p.is_file()]
print(json.dumps(summary, indent=1))
