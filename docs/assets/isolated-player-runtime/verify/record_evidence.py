"""Record the Mission 014 isolation evidence (scripted, NON-AI; no model, no API call).

    python docs/assets/isolated-player-runtime/verify/record_evidence.py <repo> <new empty out dir> <mission013 verify dir>

1. probe        the security stand-in attacks the sandbox with every path an attacker could guess
2. scripted-*   idle / key-sweep / seeded-random, isolated; compared byte for byte with Mission 013
3. gateway      agent loop with a scripted gateway (NOT A MODEL): screenshots reach the gateway as PNG bytes
4. no-gateway   agent loop with the default disabled gateway: no model is reachable
Then every referee session is replayed in a fresh browser. Prints a JSON summary.
"""

import hashlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

repo, out, m13 = (Path(a).resolve() for a in sys.argv[1:4])
sys.path.insert(0, str(repo / "src"))
from rewardbench.blindplay import host as host_mod, isolation, replay  # noqa: E402

if out.exists() and any(out.iterdir()):
    raise SystemExit(f"{out} is not empty")
home, local = Path.home(), Path(os.environ["LOCALAPPDATA"])
summary = {"preflight_user_environment_credentials": isolation.exposed_user_environment_secrets()}


def results(d):
    return [r for r in (json.loads(x)["line"] for x in (d / "player_stderr.jsonl").read_text(encoding="utf-8").splitlines())
            if isinstance(r, dict)]


# 1. probe -----------------------------------------------------------------------------------
probe = out / "probe"
listener = socket.socket()
listener.bind(("127.0.0.1", 0))
listener.listen(5)
listener.settimeout(0.2)
hits, knock, stop = [], [], threading.Event()


def accept():
    while not stop.is_set():
        try:
            hits.append(listener.accept()[1])
        except OSError:
            continue


def connect_into_sandbox():
    while not stop.is_set():
        if (probe / "player_stderr.jsonl").exists():
            for r in results(probe):
                if r.get("probe") == "tcp_listen" and r.get("outcome") == "observed":
                    try:
                        socket.create_connection(("127.0.0.1", int(r["detail"])), timeout=2).close()
                        knock.append("connected")
                    except OSError as exc:
                        knock.append(type(exc).__name__)
                    return
        time.sleep(0.05)


for fn in (accept, connect_into_sandbox):
    threading.Thread(target=fn, daemon=True).start()
marker = local / "Packages" / isolation.CONTAINER_NAME.lower() / "AC" / "Temp" / "react_marker.txt"
targets = {
    "read": [str(repo / p) for p in ("PROJECT.md", "AGENTS.md", "src/rewardbench/blindplay/referee.py",
                                     "src/rewardbench/blindplay/host.py", "frontend/apollolander/upstream/game.js",
                                     "frontend/apollolander/experiment/physics.js", ".git/config",
                                     "runs/apollolander_offline_numerical.sqlite")]
            + [str(m13 / "scripted-idle/referee.jsonl"), str(m13 / "scripted-idle/screenshots/000001.png"),
               str(probe / "referee/referee.jsonl"), str(probe / "referee/referee_stderr.log"),
               str(probe / "host_transcript.jsonl"), str(home / ".gitconfig"), str(home / ".git-credentials"),
               str(local.parent / "Roaming/GitHub CLI/hosts.yml"), str(Path(sys.base_prefix) / "Lib/os.py")],
    "list": [str(repo), str(repo / "runs"), str(repo / "runs/first-llm-study"), str(repo / "runs/blind-visual"),
             str(repo / "src"), str(probe), str(home), str(home / ".ssh"), str(home / ".claude"),
             str(home / "R.E.A.C.T-backups"), str(local / "ms-playwright"), str(local / "REACT-blindplay")],
    "write": [str(repo / "pwned.txt"), str(probe / "pwned.txt"), str(local / "REACT-blindplay/runtime-images/pwned.txt"),
              r"C:\Users\Public\pwned.txt", r"C:\ProgramData\pwned.txt"],
    "system_read": [os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "win.ini"), r"C:\Program Files"],
    "pids": [os.getpid()],
    "tcp": [["127.0.0.1", listener.getsockname()[1]]],
    "persist_write": [str(marker)],
    "read_after_play": [str(probe / "referee/screenshots/000001.png"), str(probe / "referee/session.json"),
                        str(probe / "referee/episodes.jsonl"), str(probe / "player_stderr.jsonl")],
}
m = host_mod.Host(host_mod.HostConfig(out=probe, mode="probe", max_episodes=1, episode_frame_budget=2000,
                                      player_label="isolation probe stand-in (NOT AI)", probe_targets=targets)).run()
stop.set()
listener.close()
rs = results(probe)
outcomes = {}
for r in rs:
    if "probe" in r:
        outcomes.setdefault(r["probe"], []).append({"target": r["target"], "outcome": r["outcome"], "detail": r["detail"]})
summary["probe"] = {"status": m["status"], "counts": m["counts"], "isolation": m["isolation"],
                    "runtime_image": m["runtime_image"], "host_listener_connections": len(hits),
                    "host_connect_into_sandbox": knock, "own_storage_marker_exists_after_session": marker.exists(),
                    "results": outcomes}

# 2. scripted stand-ins vs Mission 013 ----------------------------------------------------------
summary["scripted"] = {}
for name, script, episodes in (("scripted-idle", "idle", 2), ("scripted-key-sweep", "key-sweep", 1),
                               ("scripted-seeded-random", "seeded-random", 3)):
    d = out / name
    mm = host_mod.Host(host_mod.HostConfig(out=d, mode="scripted", script=script, max_episodes=episodes,
                                           player_label=f"isolated scripted:{script} script_seed=0 (NOT AI)")).run()
    new = sorted((d / "referee/screenshots").iterdir())
    old = sorted((m13 / name / "screenshots").iterdir())
    summary["scripted"][name] = {
        "status": mm["status"], "counts": mm["counts"],
        "screenshots": [len(old), len(new)],
        "byte_identical_to_mission013": [p.name for p in old] == [p.name for p in new]
        and all(a.read_bytes() == b.read_bytes() for a, b in zip(old, new)),
        "outcomes": [[e["outcome"], e["frames"]] for e in (json.loads(x) for x in (d / "referee/episodes.jsonl").read_text().splitlines())],
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
