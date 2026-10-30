"""The complete workflow: real sandbox, real referee, real upstream game, real screenshots, mocked provider.

Skipped where isolation or the browser is unavailable, unless REACT_REQUIRE_ISOLATION=1 (Windows and macOS CI set it),
in which case that is a failure. Every "model" here is a fixed script. No provider is contacted and nothing is charged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from rewardbench.blindplay import (contract, host as host_mod, isolation, model_gateway as mg, model_providers as mp,
                                   offline_demo, replay, spend_ledger as sl)

SRC = Path(contract.__file__).resolve().parents[2]
PRICING = mg.ModelPricing("0.10", "0.50", source="test")


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
pytestmark = pytest.mark.skipif(_REASON is not None, reason=_REASON or "")


def _act(call_id, keys=(), frames=30):
    return {"id": call_id, "name": "act", "arguments": {"keys": list(keys), "frames": frames}}


def _session(tmp_path, script, *, default=None, mode="model", probe_targets=None, session_cap="0.05", **limits):
    episodes = limits.pop("max_episodes", 1)
    frames = limits.pop("episode_frame_budget", 1000)
    config = mg.GatewayConfig(provider_id="offline-mock", model_id="mock-vision-0", pricing=PRICING, session_cap_usd=session_cap,
                              cumulative_cap_usd="0.05", max_episodes=episodes, episode_frame_budget=frames,
                              max_wall_seconds=600.0, **limits)
    provider = mp.MockVisionProvider(list(script), default=default)
    ledger = sl.SpendLedger(tmp_path / "ledger.jsonl", mode=sl.MODE_OFFLINE_MOCK)
    gateway = mg.VisionGateway(config, mp.MockAdapter(), mp.OfflineTransport(provider), ledger, session_id="test", sleep=lambda s: None)
    host = host_mod.Host(host_mod.HostConfig(out=tmp_path / "session", mode=mode, keyset="keyset.v2", max_episodes=episodes,
                                             episode_frame_budget=frames, max_wall_seconds=600.0, max_requests=1000,
                                             probe_targets=probe_targets or {}, player_label="pytest mock provider (NOT A MODEL)"),
                         gateway=gateway)
    return host, gateway, provider, ledger


def _results(out: Path) -> list[dict]:
    lines = [json.loads(x)["line"] for x in (out / "player_stderr.jsonl").read_text(encoding="utf-8").splitlines()]
    return [r for r in lines if isinstance(r, dict)]


def _referee_requests(out: Path) -> list[dict]:
    return [json.loads(x)["request"] for x in (out / "referee/player_transcript.jsonl").read_text(encoding="utf-8").splitlines()]


def _gateway_records(out: Path) -> list[dict]:
    return [json.loads(x) for x in (out / "gateway_transcript.jsonl").read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------- normal play
def test_end_to_end_screenshots_and_actions_flow_through_the_sandbox(tmp_path):
    script = [{"text": "looking", "tool_calls": [{"id": "o1", "name": "observe", "arguments": {}}]},
              {"text": "pressing", "tool_calls": [_act("a1", ["ArrowUp"], 60)]},
              {"tool_calls": [_act("a2", ["ArrowRight", "Space"], 45), _act("a3", [], 15)]}]
    host, gateway, provider, ledger = _session(tmp_path, script, default=lambda wire: {"text": "done"},
                                               max_consecutive_invalid_replies=1)
    manifest = host.run()
    out = tmp_path / "session"
    assert manifest["status"] == "closed" and manifest["player_exit_code"] == 0 and manifest["player_is_ai"] is False
    assert manifest["gateway_session"]["contract"]["keyset"] == "keyset.v2"
    requests = _referee_requests(out)
    assert [r["tool"] for r in requests] == ["brief", "observe", "observe", "act", "act", "act"]
    assert [(r["keys"], r["frames"]) for r in requests if r["tool"] == "act"] == [(["ArrowUp"], 60), (["ArrowRight", "Space"], 45), ([], 15)]
    shown = [json.loads(x)["response"]["image"]["sha256"] for x in (out / "referee/player_transcript.jsonl").read_text(encoding="utf-8").splitlines()
             if "image" in json.loads(x)["response"]]
    assert provider.images_received[0] == shown[:1]
    assert provider.images_received[-1] == shown[-4:], "the last four genuine screenshots reached the mock provider"
    assert all(len(x) <= 4 for x in provider.images_received)
    records = _gateway_records(out)
    assert mg.verify_transcript(records)["valid"] and records[-1]["event"] == "stop"
    assert ledger.state().open_reservations == {} and ledger.state().spent == Decimal(manifest["gateway_session"]["charged_usd"])
    assert replay.replay(out / "referee")["reproduced"]


def test_nothing_privileged_is_ever_sent_to_a_model(tmp_path):
    host, _, provider, _ = _session(tmp_path, [], default=lambda wire: {"tool_calls": [_act(f"a{len(provider.requests)}", ["ArrowUp"], 120)]},
                                    max_episodes=1, episode_frame_budget=1000)
    manifest = host.run()
    assert manifest["status"] == "closed" and manifest["gateway_session"]["stop_reason"] == "session_over"
    terminal = json.loads((tmp_path / "session/referee/episodes.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert terminal["outcome"], "the referee knows the outcome; the model must not"
    for wire in provider.requests:
        stripped = json.loads(json.dumps(wire))
        for m in stripped["messages"]:
            for p in m["content"]:
                p.pop("base64", None)
        text = json.dumps(stripped)
        assert not offline_demo.PRIVILEGED_WORDS.search(text), offline_demo.PRIVILEGED_WORDS.search(text)
        assert terminal["outcome"] not in text


def test_the_speed_key_is_refused_at_every_layer_in_a_v2_session(tmp_path):
    script = [{"tool_calls": [_act("s1", ["KeyS"], 120)]}, {"tool_calls": [_act("a1", ["ArrowUp"], 10)]}]
    host, gateway, provider, _ = _session(tmp_path, script, default=lambda wire: {"text": "done"}, max_consecutive_invalid_replies=2)
    manifest = host.run()
    assert manifest["status"] == "closed" and gateway.counts["tool_calls_rejected"] == 1
    keys = [k for r in _referee_requests(tmp_path / "session") if r["tool"] == "act" for k in r["keys"]]
    assert "KeyS" not in keys and keys == ["ArrowUp"]
    assert "KeyS" not in json.dumps(provider.requests[0]["tools"])
    session = json.loads((tmp_path / "session/referee/session.json").read_text(encoding="utf-8"))
    assert session["player_contract"]["keyset"] == "keyset.v2" and "KeyS" not in session["player_contract"]["allowed_keys"]


def test_sessions_are_deterministic_for_the_same_replies(tmp_path):
    def run(name):
        script = [{"tool_calls": [_act("a", ["ArrowUp"], 40)]}, {"tool_calls": [_act("b", ["ArrowLeft"], 20)]}]
        (tmp_path / name).mkdir()
        host, _, provider, _ = _session(tmp_path / name, script, default=lambda wire: {"text": "done"}, max_consecutive_invalid_replies=1)
        host.run()
        return provider.images_received[-1]
    assert run("one") == run("two")


# ---------------------------------------------------------------- malformed replies and budget, whole system
def test_hostile_mock_replies_never_reach_the_game(tmp_path):
    script = [{"tool_calls": [{"id": "h1", "name": "read_file", "arguments": {"path": "PROJECT.md"}}]},
              {"tool_calls": [{"id": "h2", "name": "shell", "arguments": {"cmd": "whoami"}}]},
              {"tool_calls": [_act("m1", ["KeyQ"], 10)]},
              {"tool_calls": [{"id": "m2", "name": "act", "arguments": {"keys": [], "frames": 10, "javascript": "lander.fuel=1e9"}}]},
              {"tool_calls": [{"id": "../../x", "name": "act", "arguments": {"keys": [], "frames": 1}}]},
              mp.TransportResponse(200, "<html>not json</html>"),
              {"text": "no tool"}]
    host, gateway, _, _ = _session(tmp_path, script, default=lambda wire: {"text": "done"}, max_consecutive_invalid_replies=7)
    manifest = host.run()
    assert manifest["status"] == "closed" and manifest["player_exit_code"] == 0
    assert [r["tool"] for r in _referee_requests(tmp_path / "session")] == ["brief", "observe"]
    assert gateway.stop_reason == "consecutive_invalid_replies"


def test_budget_exhaustion_stops_the_whole_system_before_the_next_call(tmp_path):
    host, gateway, provider, ledger = _session(tmp_path, [], default=lambda wire: {"tool_calls": [_act(f"a{len(provider.requests)}", [], 5)]},
                                               session_cap="0.002")
    manifest = host.run()
    assert manifest["status"] == "closed" and gateway.stop_reason == "budget_exhausted_session"
    assert ledger.state().committed <= Decimal("0.002") and ledger.state().open_reservations == {}
    assert len(provider.requests) == gateway.counts["model_calls"]
    assert [r for r in _gateway_records(tmp_path / "session") if r.get("event") == "model_call"][-1]["outcome"]["kind"] == "refused_before_call"
    assert replay.replay(tmp_path / "session/referee")["reproduced"]


# ---------------------------------------------------------------- crashes and unexpected exits
def test_gateway_crash_mid_session_closes_everything_cleanly(tmp_path):
    host, gateway, provider, ledger = _session(tmp_path, [{"tool_calls": [_act("a1", [], 10)]}])
    original = gateway.adapter.build_request
    calls = []

    def crash_second_time(neutral):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("gateway bug")
        return original(neutral)

    gateway.adapter.build_request = crash_second_time
    manifest = host.run()
    assert manifest["status"] == "aborted_gateway_failure" and "gateway bug" in manifest["gateway_failure"]
    assert manifest["player_exit_code"] == 0, "the player was told the session ended and left normally"
    assert "gateway bug" not in (tmp_path / "session/host_transcript.jsonl").read_text(encoding="utf-8")
    assert replay.replay(tmp_path / "session/referee")["reproduced"]
    again = tmp_path / "next"
    again.mkdir()
    host2, _, _, _ = _session(again, [], default=lambda wire: {"text": "done"}, max_consecutive_invalid_replies=1)
    assert host2.run()["status"] == "closed"


def test_player_killed_mid_session_keeps_records_and_ledger_consistent(tmp_path):
    holder = {}

    def kill_player(wire):
        holder["host"].player.kill()
        return {"tool_calls": [_act("a2", [], 10)]}

    host, gateway, provider, ledger = _session(tmp_path, [{"tool_calls": [_act("a1", [], 10)]}, kill_player])
    holder["host"] = host
    manifest = host.run()
    assert manifest["status"] == "closed" and manifest["player_exit_code"] not in (0, None)
    state = ledger.state()
    assert state.open_reservations == {} and state.spent == Decimal(manifest["gateway_session"]["charged_usd"])
    assert mg.verify_transcript(_gateway_records(tmp_path / "session"))["valid"]
    assert replay.replay(tmp_path / "session/referee")["reproduced"]


def test_referee_killed_mid_session_aborts_with_a_record_and_no_more_model_calls(tmp_path):
    holder = {}

    def kill_referee(wire):
        holder["host"]._referee.kill()
        holder["host"]._referee.wait(30)
        return {"tool_calls": [_act("a2", [], 10)]}

    host, gateway, provider, ledger = _session(tmp_path, [{"tool_calls": [_act("a1", [], 10)]}, kill_referee])
    holder["host"] = host
    with pytest.raises((RuntimeError, OSError)):
        host.run()
    manifest = json.loads((tmp_path / "session/host_session.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "aborted_host_failure" and manifest["ended_utc"]
    assert len(provider.requests) == 2 and ledger.state().open_reservations == {}
    assert mg.verify_transcript(_gateway_records(tmp_path / "session"))["valid"]


def test_host_process_death_mid_call_leaves_a_conservative_ledger_and_a_verifiable_transcript(tmp_path):
    """The hardest exit: the host dies while the provider call is in flight. The call may have been billed."""
    code = f"""
import os, sys
from pathlib import Path
from rewardbench.blindplay import host, model_gateway as mg, model_providers as mp, spend_ledger as sl
base = Path(sys.argv[1])
def die(wire):
    os._exit(42)
script = [{{"tool_calls": [{{"id": "a1", "name": "act", "arguments": {{"keys": [], "frames": 10}}}}]}}, die]
cfg = mg.GatewayConfig(provider_id="offline-mock", model_id="mock-vision-0", pricing=mg.ModelPricing("0.10", "0.50", source="test"),
                       session_cap_usd="0.05", cumulative_cap_usd="0.05", max_episodes=1, episode_frame_budget=1000, max_wall_seconds=300.0)
gw = mg.VisionGateway(cfg, mp.MockAdapter(), mp.OfflineTransport(mp.MockVisionProvider(script)),
                      sl.SpendLedger(base / "ledger.jsonl", mode=sl.MODE_OFFLINE_MOCK), session_id="crash")
host.Host(host.HostConfig(out=base / "session", mode="model", keyset="keyset.v2", max_episodes=1, episode_frame_budget=1000,
                          max_wall_seconds=300.0, max_requests=1000, player_label="pytest (NOT A MODEL)"), gateway=gw).run()
"""
    env = dict(os.environ, PYTHONPATH=str(SRC))
    done = subprocess.run([sys.executable, "-c", code, str(tmp_path)], capture_output=True, text=True, timeout=300, env=env)
    assert done.returncode == 42, done.stderr[-2000:]
    ledger = sl.SpendLedger(tmp_path / "ledger.jsonl", mode=sl.MODE_OFFLINE_MOCK)   # no stale lock
    state = ledger.state()
    assert len(state.open_reservations) == 1, "the in-flight call stays charged at worst case"
    (open_reservation,) = state.open_reservations.values()
    assert state.reserved == Decimal(open_reservation["worst_case_usd"]) > 0 and state.spent > 0
    records = _gateway_records(tmp_path / "session")
    assert mg.verify_transcript(records)["valid"]
    audit = offline_demo.audit_session(tmp_path / "session", tmp_path / "ledger.jsonl")
    assert audit["ledger_open_reservations"] == [open_reservation["reservation"]] and audit["transcript"]["valid"]
    manifest = json.loads((tmp_path / "session/host_session.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "running" and manifest["ended_utc"] is None, "visibly unfinished, never reported as complete"


# ---------------------------------------------------------------- the sandbox still holds with a gateway attached
@pytest.fixture(scope="module")
def attack(tmp_path_factory):
    if _REASON:
        pytest.skip(_REASON)
    base = tmp_path_factory.mktemp("gateway-attack")
    out = base / "session"
    fake_key = base / "provider_key.txt"
    fake_key.write_text("sk-ant-api03-FAKE-CREDENTIAL-FILE\n", encoding="utf-8")
    home = Path.home()
    targets = {"read": [str(fake_key), str(base / "ledger.jsonl"), str(Path(mg.__file__)), str(Path(mp.__file__)), str(Path(sl.__file__))],
               "list": [str(base), str(out), str(home)],
               "write": [str(base / "ledger.jsonl"), str(base / "pwned.txt"), str(out / "pwned.txt")],
               "read_after_play": [str(out / "gateway_transcript.jsonl"), str(out / "host_session.json"), str(base / "ledger.jsonl"), str(fake_key)]}
    ledger = sl.SpendLedger(base / "ledger.jsonl", mode=sl.MODE_OFFLINE_MOCK)
    config = mg.GatewayConfig(provider_id="offline-mock", model_id="mock-vision-0", pricing=PRICING, session_cap_usd="0.05", cumulative_cap_usd="0.05",
                              max_episodes=1, episode_frame_budget=1000, max_wall_seconds=600.0)
    provider = mp.MockVisionProvider([{"tool_calls": [_act("real", ["ArrowUp"], 20)]}], default=lambda wire: {"text": "done"})
    gateway = mg.VisionGateway(config, mp.MockAdapter(), mp.OfflineTransport(provider), ledger, session_id="attack", sleep=lambda s: None)
    host = host_mod.Host(host_mod.HostConfig(out=out, mode="gateway-probe", keyset="keyset.v2", max_episodes=1, episode_frame_budget=1000,
                                             max_wall_seconds=600.0, max_requests=1000, probe_targets=targets,
                                             player_label="pytest gateway attack stand-in (NOT AI)"),
                         gateway=gateway)
    manifest = host.run()
    results = _results(out)
    return {"out": out, "base": base, "manifest": manifest, "results": results, "provider": provider, "ledger": ledger, "gateway": gateway, "by": lambda name: [r for r in results if r.get("probe") == name]}


def test_attack_session_finished(attack):
    assert attack["manifest"]["status"] == "closed" and attack["manifest"]["player_exit_code"] == 0
    assert any(r.get("event") == "gateway_probe_done" for r in attack["results"]), attack["results"][-5:]


def test_sandbox_cannot_read_write_or_list_gateway_files_credentials_or_ledger(attack):
    for name in ("read_file", "list_dir", "write_file", "read_file_after_play"):
        rs = attack["by"](name)
        assert rs, name
        for r in rs:
            assert r["outcome"] == "denied", r
    for r in attack["by"]("read_file_after_play"):
        assert "PermissionError" in r["detail"], r
    assert not (attack["base"] / "pwned.txt").exists() and not (attack["out"] / "pwned.txt").exists()
    assert "FAKE-CREDENTIAL" not in json.dumps(attack["results"])


def test_sandbox_still_has_no_network_with_a_gateway_attached(attack):
    for name in ("tcp_connect", "dns_lookup", "udp_dns_roundtrip"):
        rs = attack["by"](name)
        assert rs and all(r["outcome"] == "denied" for r in rs), (name, rs)


def test_sandbox_environment_has_no_credentials(attack):
    (env,) = attack["by"]("environment")
    names = json.loads(env["detail"])
    assert names == (["LOCALAPPDATA", "SYSTEMROOT", "TEMP", "TMP"] if sys.platform == "win32" else [])


def test_every_protocol_attack_on_the_gateway_was_denied(attack):
    results = attack["by"]("gateway_attack")
    names = {r["target"] for r in results}
    assert names == {"act_before_the_opening_observe", "model_before_the_opening_observe", "smuggled_history", "choose_model",
                     "raise_output_limit", "forged_system_prompt", "act_the_model_never_asked_for", "repeat_observe", "speed_key",
                     "different_frames_than_the_model", "different_keys_than_the_model", "next_turn_before_executing", "replay_the_same_call"}
    assert all(r["outcome"] == "denied" for r in results), [r for r in results if r["outcome"] != "denied"]


def test_attacks_never_reached_the_referee_or_the_provider(attack):
    requests = _referee_requests(attack["out"])
    assert [r["tool"] for r in requests] == ["brief", "observe", "act"]
    assert (requests[2]["keys"], requests[2]["frames"]) == (["ArrowUp"], 20), "only the mock's own call was executed"
    assert len(attack["provider"].requests) == 1, "smuggled model requests made no call and cost nothing"
    assert "pad is at" not in json.dumps(attack["provider"].requests[0])
    (executed,) = attack["by"]("executed_model_call")
    assert executed["outcome"] == "allowed"


def test_attack_session_replays_and_its_records_verify(attack):
    assert replay.replay(attack["out"] / "referee")["reproduced"]
    assert mg.verify_transcript(_gateway_records(attack["out"]))["valid"]


def test_referee_environment_excludes_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-MUST-NOT-LEAK")
    monkeypatch.setenv("REACT_HARMLESS", "yes")
    captured = {}
    real = subprocess.Popen

    def spy(*args, **kwargs):
        captured["env"] = kwargs.get("env")
        return real(*args, **kwargs)

    host, _, _, _ = _session(tmp_path, [], default=lambda wire: {"text": "done"}, max_consecutive_invalid_replies=1)
    monkeypatch.setattr(subprocess, "Popen", spy)
    referee = host._start_referee()
    monkeypatch.setattr(subprocess, "Popen", real)
    referee.stdin.close()
    referee.wait(120)
    host._files["host_transcript.jsonl"].close()
    assert "ANTHROPIC_API_KEY" not in captured["env"] and captured["env"]["REACT_HARMLESS"] == "yes"


# ---------------------------------------------------------------- the demonstration
def test_offline_demo_runs_and_its_report_is_honest(tmp_path):
    report = offline_demo.run_demo(tmp_path / "demo", max_episodes=1, episode_frame_budget=800)
    assert report["paid_api_calls"] == 0 and report["player_is_ai"] is False and "not a model" in report["disclaimer"]
    assert report["keyset"] == "keyset.v2" and "KeyS" not in report["allowed_keys"]
    assert report["host_status"] == "closed" and report["replay"]["reproduced"]
    audit = report["audit"]
    assert audit["transcript"]["valid"] and audit["ledger_matches_transcript"] and audit["ledger_open_reservations"] == []
    assert audit["max_images_in_a_call"] <= 4 and audit["privileged_words_sent"] == []
    counts = report["gateway"]["counts"]
    assert counts["tool_calls_rejected"] >= 5 and counts["provider_errors"] == 2 and counts["invalid_replies"] >= 1
    assert (tmp_path / "demo" / "demo_report.json").is_file()
    with pytest.raises(FileExistsError):
        offline_demo.run_demo(tmp_path / "demo")
