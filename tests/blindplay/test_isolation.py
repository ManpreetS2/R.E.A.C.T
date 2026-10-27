"""OS-level isolation of the blind player (Windows AppContainer + Job Object), attacked by a NON-AI stand-in.

Skipped where isolation or the browser is unavailable, unless REACT_REQUIRE_ISOLATION=1 (Windows CI sets
it), in which case that is a failure. On other platforms the fail-closed tests still run.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from rewardbench.blindplay import contract, host as host_mod, isolation, replay, runtime_image, session as session_mod

REPO = Path(contract.__file__).resolve().parents[3]
PLAYER_SOURCE = runtime_image.PLAYER_SOURCE

# Mission 013 fixed start and the idle episode's terminal frame (evidence-verified-2026-10-27.json)
START_FRAME = "fbcbb40b641e2d3236ba38de4daffeeaa155dfdf44ada69f30d5b050e70d66f9"
IDLE_EPISODE_END = "0f31bde083218f9ed55d7c75966da6ffe9186f1b8c7d2da55928026bcd838693"


def _unavailable() -> str | None:
    reason = isolation.supported()
    if reason:
        return reason
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        return f"browser unavailable: {str(exc).splitlines()[0]}"
    return None


_REASON = _unavailable()
if _REASON and os.environ.get("REACT_REQUIRE_ISOLATION") == "1":
    raise RuntimeError(f"REACT_REQUIRE_ISOLATION=1 but {_REASON}")
needs_isolation = pytest.mark.skipif(_REASON is not None, reason=_REASON or "")


# ---------------------------------------------------------------- everywhere: fail closed, player code hygiene
@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_non_windows_refuses_instead_of_running_unisolated(tmp_path):
    assert isolation.supported() is not None
    with pytest.raises(isolation.IsolationUnavailable):
        isolation.launch(Path(sys.executable), ["-c", "pass"], cwd=tmp_path)
    with pytest.raises(isolation.IsolationUnavailable):
        runtime_image.build(tmp_path / "images")
    with pytest.raises(isolation.IsolationUnavailable):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "s", mode="scripted", player_label="pytest (NOT AI)"))
    assert not (tmp_path / "s").exists()


def test_player_runtime_uses_only_the_standard_library():
    stdlib = {"__future__", "argparse", "json", "random", "sys", "ctypes", "ctypes.wintypes", "os", "socket",
              "subprocess", "winreg", "runtime"}
    for path in PLAYER_SOURCE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            for name in names:
                assert name in stdlib or name == "probes", f"{path.name} imports {name}"


@pytest.mark.parametrize("name,value,flagged", [
    ("OPENAI_API_KEY", "x", True), ("ANTHROPIC_API_KEY", "", True), ("GH_TOKEN", "x", True),
    ("MY_SECRET", "x", True), ("ANYTHING", "sk-proj-abc", True), ("ANYTHING", "ghp_abcdef", True),
    ("ANYTHING", "github_pat_11A", True), ("ANYTHING", "AKIAIOSFODNN7", True),
    ("Path", r"C:\Windows", False), ("PNPM_HOME", r"C:\pnpm", False), ("OneDrive", r"C:\Users\x\OneDrive", False),
    ("TEMP", r"C:\Temp", False), ("ChocolateyLastPathUpdate", "1339", False),
])
def test_credential_detection(name, value, flagged):
    assert isolation.looks_like_credential(name, value) is flagged


@pytest.mark.skipif(isolation.supported() is not None, reason="Windows only")
def test_host_refuses_when_user_environment_holds_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "exposed_user_environment_secrets", lambda: ["OPENAI_API_KEY"])
    with pytest.raises(isolation.IsolationUnavailable, match="OPENAI_API_KEY"):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "s", mode="scripted", player_label="pytest (NOT AI)"))
    assert not (tmp_path / "s").exists()


# ---------------------------------------------------------------- the attack session
def _results(out: Path) -> list[dict]:
    lines = [json.loads(x)["line"] for x in (out / "player_stderr.jsonl").read_text(encoding="utf-8").splitlines()]
    return [r for r in lines if isinstance(r, dict)]


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    if _REASON:
        pytest.skip(_REASON)
    out = tmp_path_factory.mktemp("isolation") / "probe"
    home, local = Path.home(), Path(os.environ["LOCALAPPDATA"])
    image_root = runtime_image.default_root()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    listener.settimeout(0.2)
    hits, knock = [], []
    stop = threading.Event()

    def accept():
        while not stop.is_set():
            try:
                hits.append(listener.accept()[1])
            except (socket.timeout, OSError):
                continue

    def connect_into_sandbox():
        while not stop.is_set():
            f = out / "player_stderr.jsonl"
            if f.exists():
                for r in _results(out):
                    if r.get("probe") == "tcp_listen" and r.get("outcome") == "observed":
                        try:
                            socket.create_connection(("127.0.0.1", int(r["detail"])), timeout=2).close()
                            knock.append("connected")
                        except OSError as exc:
                            knock.append(type(exc).__name__)
                        return
            time.sleep(0.05)

    threads = [threading.Thread(target=accept, daemon=True), threading.Thread(target=connect_into_sandbox, daemon=True)]
    for t in threads:
        t.start()
    marker = local / "Packages" / isolation.CONTAINER_NAME.lower() / "AC" / "Temp" / "react_marker.txt"
    targets = {
        "read": [str(REPO / "PROJECT.md"), str(REPO / "src/rewardbench/blindplay/referee.py"),
                 str(REPO / "frontend/apollolander/upstream/game.js"), str(REPO / "pyproject.toml"),
                 str(out / "referee/referee.jsonl"), str(out / "referee/referee_stderr.log"),
                 str(out / "host_transcript.jsonl"), str(home / ".gitconfig"),
                 str(Path(sys.base_prefix) / "Lib" / "os.py")],
        "list": [str(REPO), str(REPO / "runs"), str(REPO / "src"), str(out), str(out / "referee"), str(home),
                 str(local / "ms-playwright"), str(image_root.parent)],
        "write": [str(REPO / "pwned.txt"), str(out / "pwned.txt"), str(image_root / "pwned.txt")],
        "system_read": [os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "win.ini")],
        "pids": [os.getpid()],
        "tcp": [["127.0.0.1", listener.getsockname()[1]]],
        "persist_write": [str(marker)],
        "read_after_play": [str(out / "referee/screenshots/000001.png"), str(out / "referee/session.json"),
                            str(out / "referee/episodes.jsonl"), str(out / "player_stderr.jsonl")],
    }
    # Attack only what exists on the host, so "not found" can never pass for "denied". (Paths inside this
    # session's own directory are created during the session and are attacked before and after they exist.)
    targets["read"] = [p for p in targets["read"] if Path(p).is_file() or Path(p).is_relative_to(out)]
    targets["list"] = [p for p in targets["list"] if Path(p).is_dir() or Path(p).is_relative_to(out)]
    assert len(targets["read"]) >= 7 and len(targets["list"]) >= 6
    config = host_mod.HostConfig(out=out, mode="probe", player_label="pytest isolation probe stand-in (NOT AI)",
                                 max_episodes=1, episode_frame_budget=2000, probe_targets=targets)
    manifest = host_mod.Host(config).run()
    stop.set()
    listener.close()
    for t in threads:
        t.join(5)
    results = _results(out)
    return {"out": out, "manifest": manifest, "results": results, "hits": hits, "knock": knock, "targets": targets,
            "marker": marker,
            "by": lambda probe: [r for r in results if r.get("probe") == probe]}


@needs_isolation
def test_probe_session_completed(probe):
    assert probe["manifest"]["status"] == "closed" and probe["manifest"]["failure"] is None
    assert any(r.get("event") == "probe_done" for r in probe["results"]), probe["results"][-5:]
    assert probe["manifest"]["player_is_ai"] is False


@needs_isolation
def test_player_token_is_an_appcontainer_at_low_integrity(probe):
    token = {r["target"]: r["detail"] for r in probe["by"]("token")}
    assert token == {"TokenIsAppContainer": "1", "IntegrityLevel": "0x1000"}


@needs_isolation
def test_repository_records_profile_and_browser_are_unreadable(probe):
    attempts = probe["by"]("read_file") + probe["by"]("list_dir") + probe["by"]("read_file_after_play")
    assert len(attempts) == sum(len(probe["targets"][k]) for k in ("read", "list", "read_after_play"))
    for r in attempts:
        assert r["outcome"] == "denied", r
        # session files attacked before the referee wrote them may not exist yet; everything else exists
        assert "PermissionError" in r["detail"] or (r["probe"] == "read_file" and Path(r["target"]).is_relative_to(probe["out"])), r
    for r in probe["by"]("read_file_after_play"):
        assert Path(r["target"]).is_file() and "PermissionError" in r["detail"], r


@needs_isolation
def test_writes_are_denied_except_the_containers_own_wiped_storage(probe):
    writes = probe["by"]("write_file")
    assert len(writes) == 3 and all(r["outcome"] == "denied" and "PermissionError" in r["detail"] for r in writes)
    own = probe["by"]("write_own_storage")
    assert [r["outcome"] for r in own] == ["allowed"]          # its own AppContainer folder ...
    assert not probe["marker"].exists(), "... which the host wipes when the session ends"
    for name in ("pwned.txt",):
        assert not (REPO / name).exists() and not (probe["out"] / name).exists()


@needs_isolation
def test_environment_is_minimal(probe):
    (env,) = probe["by"]("environment")
    assert json.loads(env["detail"]) == ["LOCALAPPDATA", "SYSTEMROOT", "TEMP", "TMP"]


@needs_isolation
def test_no_child_process_can_be_started(probe):
    spawns = probe["by"]("spawn")
    assert len(spawns) == 4 and all(r["outcome"] == "denied" for r in spawns)
    assert sum("367" in r["detail"] for r in spawns) == 3   # ERROR_CHILD_PROCESS_BLOCKED


@needs_isolation
def test_no_network_in_or_out(probe):
    for name in ("tcp_connect", "dns_lookup", "udp_dns_roundtrip", "inbound_connection"):
        rs = probe["by"](name)
        assert rs and all(r["outcome"] == "denied" for r in rs), (name, rs)
    assert probe["hits"] == [], "the host's loopback listener must receive nothing from the sandbox"
    assert probe["knock"] and probe["knock"] != ["connected"], "the host must not reach a socket inside the sandbox"


@needs_isolation
def test_no_host_process_clipboard_console_or_credential_store(probe):
    for name in ("open_process", "clipboard", "console", "credential_manager"):
        rs = probe["by"](name)
        assert rs and all(r["outcome"] == "denied" for r in rs), (name, rs)


@needs_isolation
def test_only_disk_handles_are_the_players_own(probe):
    (handles,) = probe["by"]("disk_handles")
    image = probe["manifest"]["runtime_image"]["path"].lower()
    system = os.environ.get("SYSTEMROOT", r"C:\Windows").lower()
    allowed = [image, system]
    for entry in json.loads(handles["detail"]):
        dos = entry.get("dos", "").lower().removeprefix("\\\\?\\")
        # NT form \Device\HarddiskVolumeN\<path>: compare the drive-relative part when no DOS name resolves
        nt_rest = "\\" + "\\".join(entry.get("nt", "").lower().split("\\")[3:])
        ok = any(dos.startswith(a) for a in allowed) if dos else \
            bool(entry.get("nt")) and any(nt_rest.startswith(a[2:]) for a in allowed)
        assert ok, entry


@needs_isolation
def test_documented_readable_areas_hold_no_credentials(probe):
    """AppContainers may read system files and HKCU\\Environment; the host refused credentials there."""
    assert all(r["outcome"] == "allowed" for r in probe["by"]("system_read"))
    (names,) = probe["by"]("registry_user_environment_names")
    assert not [n for n in json.loads(names["detail"]) if isolation.looks_like_credential(n, "")]


@needs_isolation
def test_hostile_protocol_lines_are_rejected_by_the_host_and_never_reach_the_referee(probe):
    rejected = probe["by"]("host_protocol")
    assert len(rejected) == 26 and all(r["outcome"] == "denied" for r in rejected)
    for r in rejected:
        assert not re.search(r"Traceback|\.py|[A-Za-z]:\\|lander|gameState|playwright", r["detail"]), r
    counts = probe["manifest"]["counts"]
    assert counts["forwarded_to_referee"] == 5 and counts["rejected_by_host"] == 26
    referee = [json.loads(x) for x in (probe["out"] / "referee/player_transcript.jsonl").read_text().splitlines()]
    assert [e["request"]["tool"] for e in referee] == ["brief", "observe", "act", "act", "act"]
    assert all("error" not in e["response"] for e in referee)


@needs_isolation
def test_game_unchanged_by_attacks_and_identical_to_the_unsandboxed_game(probe, tmp_path):
    played = [json.loads(r["detail"]) for r in probe["by"]("play")]
    with session_mod.Session(tmp_path / "control", max_episodes=1, episode_frame_budget=2000,
                             player_label="pytest control (NOT AI)", player_is_ai=False) as s:
        control = [s.handle({"tool": "observe"})] + [s.handle({"tool": "act", "keys": k, "frames": f})
                                                       for k, f in ((["ArrowUp"], 60), (["ArrowLeft", "Space"], 45), ([], 120))]
    assert [p["sha256"] for p in played] == [c["image"]["sha256"] for c in control]
    assert played[0]["sha256"] == START_FRAME


@needs_isolation
def test_player_received_only_contract_messages(probe):
    allowed = [contract.OBSERVATION_FIELDS, contract.ERROR_FIELDS, contract.BRIEF_FIELDS, host_mod.MODEL_REPLY_FIELDS]
    for line in (probe["out"] / "host_transcript.jsonl").read_text().splitlines():
        assert set(json.loads(line)["response"]) in allowed


@needs_isolation
def test_referee_session_replays_identically(probe):
    assert replay.replay(probe["out"] / "referee")["reproduced"]


@needs_isolation
def test_host_records_isolation_facts_and_owns_both_commands(probe):
    m = probe["manifest"]
    assert m["isolation"]["container_sid"].startswith("S-1-15-2-")
    assert m["referee_command"][1:4] == ["-m", "rewardbench.blindplay.serve", "--out"]
    assert m["player_command"][0].lower().startswith(m["runtime_image"]["path"].lower())
    assert m["player_command"][1:4] == ["-I", "-S", "-B"]


@needs_isolation
def test_negative_control_the_same_attack_succeeds_without_the_sandbox():
    """The denials above come from the sandbox, not from wrong paths or broken probe code."""
    import subprocess
    code = ("import socket,subprocess,sys\n"
            "open(sys.argv[1],'rb').read(5); print('read')\n"
            "subprocess.run([sys.executable,'-c','pass'],check=True); print('spawned')\n")
    target = str(REPO / "PROJECT.md")
    plain = subprocess.run([sys.executable, "-I", "-c", code, target], capture_output=True, text=True, timeout=60)
    assert plain.stdout.split() == ["read", "spawned"]
    image = runtime_image.build()
    isolation.reset_profile()
    p = isolation.launch(runtime_image.python_executable(image), ["-I", "-S", "-B", "-c", code, target], cwd=image)
    try:
        p.stdin.close()
        out, err = p.stdout.read().decode(), p.stderr.read().decode()
        p.wait(60)
    finally:
        p.close()
        isolation.reset_profile()
    assert out == "" and "PermissionError" in err


# ---------------------------------------------------------------- other isolated sessions
@needs_isolation
def test_isolated_scripted_session_reproduces_mission013(tmp_path):
    out = tmp_path / "idle"
    m = host_mod.Host(host_mod.HostConfig(out=out, mode="scripted", script="idle", max_episodes=1,
                                          player_label="pytest isolated scripted:idle (NOT AI)")).run()
    assert m["status"] == "closed" and m["counts"]["rejected_by_host"] == 0
    (receipt,) = [json.loads(x) for x in (out / "referee/episodes.jsonl").read_text().splitlines()]
    assert (receipt["outcome"], receipt["frames"]) == ("crashed", 1293)
    assert (receipt["start_frame_sha256"], receipt["end_screenshot_sha256"]) == (START_FRAME, IDLE_EPISODE_END)


@needs_isolation
def test_screenshots_reach_a_model_gateway_as_png_bytes_without_files(tmp_path):
    gateway = host_mod.ScriptedGateway([(["ArrowUp"], 60), ([], 120)])
    out = tmp_path / "agent"
    m = host_mod.Host(host_mod.HostConfig(out=out, mode="agent", max_episodes=1, episode_frame_budget=1000,
                                          max_model_calls=3, player_label="pytest scripted gateway (NOT A MODEL)"),
                      gateway=gateway).run()
    assert m["status"] == "closed" and m["counts"]["model_calls"] == 3 and m["player_is_ai"] is False
    referee = [json.loads(x) for x in (out / "referee/player_transcript.jsonl").read_text().splitlines()]
    shown = [e["response"]["image"]["sha256"] for e in referee if "image" in e["response"]]
    acts = [(e["request"]["keys"], e["request"]["frames"]) for e in referee if e["request"]["tool"] == "act"]
    assert acts == [(["ArrowUp"], 60), ([], 120)], "the gateway's tool calls were executed through the host"
    assert set(gateway.received_images) == set(shown) and len(shown) == 3
    calls = [json.loads(x) for x in (out / "gateway_transcript.jsonl").read_text().splitlines()]
    assert all(c["system"] == "Land the rocket." and c["tools"] == ["observe", "act"] for c in calls)
    parts = [p for c in calls for msg in c["messages"] for p in msg["content"]]
    assert all("base64" not in p for p in parts) and any(p["type"] == "image" for p in parts)
    assert not any("path" in p or "file" in p for p in parts)


@needs_isolation
def test_without_an_enabled_gateway_no_model_is_reached(tmp_path):
    out = tmp_path / "disabled"
    m = host_mod.Host(host_mod.HostConfig(out=out, mode="agent", max_episodes=1, max_model_calls=5,
                                          player_label="pytest agent without gateway (NOT AI)")).run()
    assert m["gateway"] == "disabled" and m["counts"]["model_calls"] == 0 and m["counts"]["model_rejected"] == 1
    assert (out / "gateway_transcript.jsonl").read_text() == ""
    referee = [json.loads(x)["request"]["tool"] for x in (out / "referee/player_transcript.jsonl").read_text().splitlines()]
    assert referee == ["brief", "observe"]


@needs_isolation
def test_existing_records_are_never_overwritten(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "keep.txt").write_text("x")
    with pytest.raises(FileExistsError):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "s", mode="scripted", player_label="pytest (NOT AI)"))


@needs_isolation
def test_altered_runtime_image_is_detected(tmp_path):
    image = runtime_image.build()
    copy = tmp_path / image.name
    shutil.copytree(image, copy)
    runtime_image.verify(copy)
    (copy / "player" / "runtime.py").write_bytes(b"print('replaced')\n")
    with pytest.raises(RuntimeError, match="changed"):
        runtime_image.verify(copy)
    shutil.copyfile(image / "player" / "runtime.py", copy / "player" / "runtime.py")
    (copy / "player" / "extra.py").write_text("x = 1\n")
    with pytest.raises(RuntimeError, match="unexpected"):
        runtime_image.verify(copy)
