"""The model gateway, with a mocked provider and a fake game. Runs on every platform, needs no browser or sandbox.

Nothing here contacts a provider: the only transport that exists is a local function. Isolated end-to-end runs against
the real game are in test_gateway_isolated.py.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import json
import re
import socket
import struct
import threading
import time
import zlib
from decimal import Decimal
from pathlib import Path

import pytest

from rewardbench.blindplay import contract, host as host_mod, isolation, model_gateway as mg, model_providers as mp, runtime_image, spend_ledger as sl

PACKAGE = Path(contract.__file__).resolve().parent
PRICING = mg.ModelPricing("1", "2", source="test")


def png(tag: int = 0, width: int = 1280, height: int = 720) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (mg.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(tag.to_bytes(4, "big"))) + chunk(b"IEND", b""))


class FakeGame:
    """Stands in for the referee: contract-shaped observations with unique valid PNGs. No game state exists here."""

    def __init__(self, version=contract.V2, frames_to_end=None, max_episodes=10):
        self.version, self.seq, self.episode, self.frame = version, 0, 1, 0
        self.frames_to_end, self.max_episodes = frames_to_end, max_episodes
        self.received: list[dict] = []
        self.episodes_finished = 0

    def observation(self, frames=0, ended=False, over=False):
        self.seq += 1
        data = png(self.seq)
        return contract.observation(seq=self.seq, episode=self.episode, episode_frame=self.frame, episode_frame_budget=8000,
                                    max_episodes=self.max_episodes, frames_advanced=frames, episode_ended=ended, session_over=over,
                                    image=contract.image_payload(data, 1280, 720), version=self.version)

    def call(self, request):
        self.received.append(request)
        if request["tool"] == "brief":
            return contract.brief(episode_frame_budget=8000, max_episodes=self.max_episodes, version=self.version)
        if request["tool"] == "observe":
            return self.observation()
        self.frame += request["frames"]
        ended = self.frames_to_end is not None and self.frame >= self.frames_to_end
        over = False
        if ended:
            self.frame, self.episode = 0, self.episode + 1
            self.episodes_finished += 1
            over = self.episodes_finished >= self.max_episodes
        return self.observation(request["frames"], ended, over)


def act(call_id="c1", keys=(), frames=10):
    return {"id": call_id, "name": "act", "arguments": {"keys": list(keys), "frames": frames}}


def make(tmp_path, script=(), *, default=None, sink=None, session_cap="1", cumulative_cap="1", sleep=None, **limits):
    limits.setdefault("provider_timeout_seconds", 5.0)
    config = mg.GatewayConfig(provider_id="offline-mock", model_id="mock-vision-0", pricing=limits.pop("pricing", PRICING),
                              session_cap_usd=session_cap, cumulative_cap_usd=cumulative_cap, **limits)
    provider = mp.MockVisionProvider(list(script), default=default)
    ledger = sl.SpendLedger(tmp_path / "ledger.jsonl", mode=sl.MODE_OFFLINE_MOCK)
    records = [] if sink is None else sink
    gateway = mg.VisionGateway(config, mp.MockAdapter(), mp.OfflineTransport(provider), ledger, session_id="test",
                               sink=records.append, sleep=sleep or (lambda s: None))
    return gateway, provider, ledger, records


def opened(gateway, game=None):
    game = game or FakeGame()
    gateway.authorize_game("observe", None)
    gateway.record_game(game.observation())
    return game


def play(gateway, game, reply):
    """Execute a reply's tool calls the way the player would."""
    for call in reply["tool_calls"]:
        request = {"tool": call["name"], **call["arguments"]}
        tool, parsed = contract.parse_request(request, contract.V2)
        gateway.authorize_game(tool, parsed)
        response = game.call(request)
        gateway.record_game(response)
        if response.get("episode_ended") or response.get("session_over"):
            break


# ---------------------------------------------------------------- no way to spend, by construction
GATEWAY_MODULES = ["model_gateway.py", "model_providers.py", "spend_ledger.py", "offline_demo.py"]
NETWORK_MODULES = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "httpx2", "aiohttp", "asyncio", "ftplib",
                   "smtplib", "websockets", "subprocess", "anthropic", "openai", "google", "boto3", "ctypes", "multiprocessing"}


def test_live_calls_are_disabled():
    assert mg.LIVE_CALLS_PERMITTED is False


@pytest.mark.parametrize("module", GATEWAY_MODULES)
def test_gateway_modules_have_no_network_sdk_or_process_code(module):
    tree = ast.parse((PACKAGE / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
            [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        for name in names:
            assert name.split(".")[0] not in NETWORK_MODULES, f"{module} imports {name}"


@pytest.mark.parametrize("module", GATEWAY_MODULES)
def test_gateway_modules_never_read_credentials(module):
    text = (PACKAGE / module).read_text(encoding="utf-8")
    assert not re.search(r"environ|getenv|keyring|x-api-key|api_key|Authorization", text), module


def test_a_transport_that_is_not_offline_is_refused(tmp_path):
    class Live:
        is_offline = False

        def send(self, wire, timeout):   # pragma: no cover - must never run
            raise AssertionError("a live transport was called")

    config = mg.GatewayConfig(provider_id="offline-mock", model_id="m", pricing=PRICING, session_cap_usd="1", cumulative_cap_usd="1")
    ledger = sl.SpendLedger(tmp_path / "l.jsonl", mode=sl.MODE_OFFLINE_MOCK)
    with pytest.raises(mg.LiveCallsDisabled):
        mg.VisionGateway(config, mp.MockAdapter(), Live(), ledger, session_id="s")


def test_offline_transport_refuses_a_live_ledger(tmp_path):
    config = mg.GatewayConfig(provider_id="offline-mock", model_id="m", pricing=PRICING, session_cap_usd="1", cumulative_cap_usd="1")
    with pytest.raises(mg.LiveCallsDisabled):
        mg.VisionGateway(config, mp.MockAdapter(), mp.OfflineTransport(lambda w, t: None),
                         sl.SpendLedger(tmp_path / "l.jsonl", mode=sl.MODE_LIVE), session_id="s")


def test_real_format_adapter_over_offline_transport_is_recorded_as_not_a_model(tmp_path):
    config = mg.GatewayConfig(provider_id="anthropic", model_id="claude-haiku-5-5", pricing=PRICING, session_cap_usd="1", cumulative_cap_usd="1")
    gateway = mg.VisionGateway(config, mp.AnthropicMessagesAdapter(), mp.OfflineTransport(lambda w, t: None),
                               sl.SpendLedger(tmp_path / "l.jsonl", mode=sl.MODE_OFFLINE_MOCK), session_id="s")
    assert gateway.is_model is False and "NOT A MODEL" in gateway.name


def test_a_full_mock_session_opens_no_socket(tmp_path, monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("the gateway tried to use the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    gateway, _, _, _ = make(tmp_path, [{"tool_calls": [act()]}, {"tool_calls": [act("c2")]}])
    game = opened(gateway)
    play(gateway, game, gateway.turn())
    play(gateway, game, gateway.turn())
    assert gateway.counts["tool_calls_executed"] == 2


# ---------------------------------------------------------------- configuration
@pytest.mark.parametrize("kwargs", [
    {"session_cap_usd": "0"}, {"session_cap_usd": "2", "cumulative_cap_usd": "1"}, {"cumulative_cap_usd": "-1"},
    {"session_cap_usd": 0.5}, {"keyset": "keyset.v1"}, {"keyset": "keyset.v9"}, {"max_model_calls": 0}, {"max_output_tokens": True},
])
def test_bad_configuration_is_refused(kwargs):
    base = dict(provider_id="offline-mock", model_id="m", pricing=PRICING, session_cap_usd="1", cumulative_cap_usd="1")
    with pytest.raises((ValueError, TypeError)):
        mg.GatewayConfig(**{**base, **kwargs})


def test_spend_caps_have_no_defaults():
    with pytest.raises(TypeError):
        mg.GatewayConfig(provider_id="x", model_id="m", pricing=PRICING)


def test_context_limit_must_stay_below_a_price_threshold():
    """Claude Haiku 5.5 costs 5x above 100K input tokens; a session must not be able to drift over it unnoticed."""
    tier = mg.ModelPricing("0.10", "0.50", source="test", threshold_input_tokens=100000,
                           over_threshold_input_per_mtok="0.50", over_threshold_output_per_mtok="2.50")
    base = dict(provider_id="x", model_id="m", pricing=tier, session_cap_usd="1", cumulative_cap_usd="1")
    mg.GatewayConfig(**base, max_context_tokens=100000)
    with pytest.raises(ValueError, match="threshold"):
        mg.GatewayConfig(**base, max_context_tokens=100001)
    assert tier.cost(mp.Usage(100000, 1000)) == Decimal("0.0105")
    assert tier.cost(mp.Usage(100001, 1000)) == Decimal("0.0525005"), "over the threshold the whole call costs more"


def test_config_hash_is_stable_and_changes_with_any_limit():
    base = dict(provider_id="x", model_id="m", pricing=PRICING, session_cap_usd="1", cumulative_cap_usd="1")
    assert mg.GatewayConfig(**base).sha256() == mg.GatewayConfig(**base).sha256()
    assert mg.GatewayConfig(**base).sha256() != mg.GatewayConfig(**base, max_model_calls=149).sha256()


# ---------------------------------------------------------------- schemas and normal flow
def test_exact_tool_schemas_and_system_text_reach_the_provider(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": [act(keys=["ArrowUp"])]}])
    game = opened(gateway)
    reply = gateway.turn()
    wire = provider.requests[0]
    assert wire["system"] == "Land the rocket."
    assert [t["name"] for t in wire["tools"]] == ["observe", "act"]
    assert wire["tools"] == json.loads(json.dumps(contract.V2.tools))
    assert "KeyS" not in json.dumps(wire["tools"])
    assert wire["messages"][0]["content"][0] == {"type": "text", "text": "Land the rocket."}
    assert wire["messages"][0]["role"] == "user" and wire["messages"][0]["content"][1]["type"] == "image"
    assert reply == {"protocol": contract.V2.protocol, "text": "", "tool_calls": [act(keys=["ArrowUp"])]}, \
        "the player gets only what to press, not the model's words"
    play(gateway, game, reply)


def test_screenshot_bytes_reach_the_provider_intact(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": [act()]}, {"tool_calls": []}])
    game = opened(gateway)
    first = hashlib.sha256(png(1)).hexdigest()
    play(gateway, game, gateway.turn())
    gateway.turn()
    assert provider.images_received[0] == [first]
    assert provider.images_received[1] == [first, hashlib.sha256(png(2)).hexdigest()]


def test_tool_results_carry_exactly_the_contract_counters(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": [act()]}, {"tool_calls": []}])
    game = opened(gateway)
    play(gateway, game, gateway.turn())
    gateway.turn()
    tool = next(m for m in provider.requests[1]["messages"] if m["role"] == "tool")
    assert tool["tool_call_id"] == "c1" and tool["is_error"] is False
    text = json.loads(tool["content"][0]["text"])
    assert set(text) == set(mg.TOOL_RESULT_COUNTERS)
    assert tool["content"][1]["type"] == "image"


def test_history_is_append_only_and_keeps_the_full_text(tmp_path):
    script = [{"text": f"thought {i}", "tool_calls": [act(f"c{i}")]} for i in range(8)]
    gateway, provider, _, _ = make(tmp_path, script)
    game = opened(gateway)
    for _ in range(8):
        play(gateway, game, gateway.turn())
    last = provider.requests[-1]["messages"]
    texts = [p["text"] for m in last if m["role"] == "assistant" for p in m["content"]]
    assert texts == [f"thought {i}" for i in range(7)], "every earlier visible message is still there"
    for earlier, later in zip(provider.requests, provider.requests[1:]):
        assert len(later["messages"]) > len(earlier["messages"])
        for a, b in zip(earlier["messages"], later["messages"]):
            assert a["role"] == b["role"] and a.get("tool_call_id") == b.get("tool_call_id")


def test_a_conversation_starts_only_after_the_opening_screenshot(tmp_path):
    gateway, provider, _, _ = make(tmp_path)
    with pytest.raises(mg.GatewayRejected):
        gateway.turn()
    with pytest.raises(mg.GatewayRejected):
        gateway.authorize_game("act", contract.Act((), 1))
    assert provider.requests == []


# ---------------------------------------------------------------- last-four-screenshots policy
def test_only_the_last_four_screenshots_are_sent_and_older_ones_become_a_note(tmp_path):
    gateway, provider, _, _ = make(tmp_path, default=lambda wire: {"tool_calls": [act(f"c{len(provider.requests)}")]})
    game = opened(gateway)
    for _ in range(12):
        play(gateway, game, gateway.turn())
    assert [len(x) for x in provider.images_received] == [1, 2, 3, 4] + [4] * 8
    last = provider.requests[-1]
    notes = sum(p.get("text") == mg.OMITTED_IMAGE_NOTE for m in last["messages"] for p in m["content"])
    assert notes == 12 - 4 + 1 - 1   # 12 turns have shown 12 screenshots by the last call
    expected = [hashlib.sha256(png(s)).hexdigest() for s in range(9, 13)]
    assert provider.images_received[-1] == expected, "the most recent four, oldest first"


def test_a_big_batch_cannot_push_more_than_four_images_into_one_call(tmp_path):
    batch = [act(f"b{i}") for i in range(8)]
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": batch}, {"tool_calls": []}])
    game = opened(gateway)
    play(gateway, game, gateway.turn())
    gateway.turn()
    assert len(provider.images_received[-1]) == 4


def test_gateway_keeps_only_the_window_in_memory(tmp_path):
    gateway, _, _, _ = make(tmp_path, default=lambda wire: {"tool_calls": [act(f"c{time.monotonic_ns()}")]})
    game = opened(gateway)
    for _ in range(10):
        play(gateway, game, gateway.turn())
    assert len(gateway._images) == 4


def test_the_window_holds_by_itself_even_if_more_images_are_in_memory(tmp_path):
    """Three layers keep images down (memory trim, window, outbound guard); each must work on its own."""
    gateway, _, _, _ = make(tmp_path)
    game = opened(gateway)
    gateway._messages.append({"role": "user", "content": []})
    for _ in range(5):
        obs = game.observation()
        gateway._images[obs["seq"]] = obs["image"]["base64"]
        gateway._messages[-1]["content"].append({"type": "image", "media_type": "image/png", "seq": obs["seq"], "sha256": obs["image"]["sha256"]})
    request = gateway._request()
    images = [p for m in request["messages"] for p in m["content"] if p["type"] == "image"]
    assert [p["seq"] for p in images] == [3, 4, 5, 6]
    gateway._guard(request)


@pytest.mark.parametrize("window", [1, 2, 4])
def test_outbound_guard_blocks_more_images_than_the_policy_whatever_the_code_above_did(tmp_path, window):
    gateway, provider, _, records = make(tmp_path, max_images_per_call=window)
    opened(gateway)
    request = gateway._request()
    request["messages"][0]["content"] = [dict(request["messages"][0]["content"][1])] * (window + 1)
    with pytest.raises(mg.GatewayStopped):
        gateway._guard(request)
    assert gateway.stop_reason == "outbound_guard_too_many_images" and provider.requests == []


@pytest.mark.parametrize("change", [
    lambda r: r.update(system="Land the rocket. Fire the engine when low."),
    lambda r: r["tools"].append({"name": "read_file"}),
    lambda r: r.update(model="another-model"),
    lambda r: r.update(max_output_tokens=999999),
    lambda r: r["messages"][0].update(extra="x"),
    lambda r: r["messages"][0]["content"][0].update(gameState="PLAYING"),
])
def test_outbound_guard_blocks_anything_but_the_contract_request(tmp_path, change):
    gateway, _, _, _ = make(tmp_path)
    opened(gateway)
    request = gateway._request()
    request["tools"] = list(request["tools"])
    change(request)
    with pytest.raises(mg.GatewayStopped):
        gateway._guard(request)


# ---------------------------------------------------------------- tool-call validation
@pytest.mark.parametrize("call,reason", [
    ({"id": "h1", "name": "read_file", "arguments": {"path": "PROJECT.md"}}, "unknown tool"),
    ({"id": "h2", "name": "shell", "arguments": {"cmd": "whoami"}}, "unknown tool"),
    ({"id": "h3", "name": "brief", "arguments": {}}, "unknown tool"),
    ({"id": "h4", "name": "model", "arguments": {}}, "unknown tool"),
    ({"id": "h5", "name": "state", "arguments": {}}, "unknown tool"),
    ({"id": "h6", "name": None, "arguments": {}}, "unknown tool"),
    ({"id": "h7", "name": ["act"], "arguments": {}}, "unknown tool"),
    ({"id": "m1", "name": "act", "arguments": {"keys": ["KeyS"], "frames": 10}}, "keys not allowed"),
    ({"id": "m2", "name": "act", "arguments": {"keys": ["KeyQ"], "frames": 10}}, "keys not allowed"),
    ({"id": "m3", "name": "act", "arguments": {"keys": [], "frames": 0}}, "between"),
    ({"id": "m4", "name": "act", "arguments": {"keys": [], "frames": 121}}, "between"),
    ({"id": "m5", "name": "act", "arguments": {"keys": [], "frames": 1.5}}, "integer"),
    ({"id": "m6", "name": "act", "arguments": {"keys": [], "frames": True}}, "integer"),
    ({"id": "m7", "name": "act", "arguments": {"keys": "ArrowUp", "frames": 1}}, "list"),
    ({"id": "m8", "name": "act", "arguments": {"keys": ["ArrowUp", "ArrowUp"], "frames": 1}}, "repeat"),
    ({"id": "m9", "name": "act", "arguments": {"keys": []}}, "integer"),
    ({"id": "n1", "name": "act", "arguments": {"keys": [], "frames": 1, "javascript": "x"}}, "unexpected"),
    ({"id": "n2", "name": "act", "arguments": {"keys": [], "frames": 1, "tool": "observe"}}, "unexpected"),
    ({"id": "n3", "name": "act", "arguments": {"keys": [], "frames": 1, "id": "other"}}, "unexpected"),
    ({"id": "n4", "name": "observe", "arguments": {"debug": True}}, "unexpected"),
    ({"id": "n5", "name": "act", "arguments": "keys=[]"}, "invalid arguments"),
    ({"id": "n6", "name": "act", "arguments": None}, "invalid arguments"),
    ({"id": "n7", "name": "act", "arguments": {"keys": ["a" * 5000], "frames": 1}}, "invalid arguments"),
])
def test_bad_tool_calls_are_answered_with_an_error_and_never_reach_the_game(tmp_path, call, reason):
    gateway, provider, _, records = make(tmp_path, [{"tool_calls": [call]}, {"tool_calls": [act("ok")]}])
    game = opened(gateway)
    reply = gateway.turn()
    assert reply["tool_calls"] == [], "the player is given nothing to press"
    assert game.received == []
    assert gateway.counts["tool_calls_rejected"] == 1 and gateway.counts["invalid_replies"] == 1
    gateway.turn()
    answer = next(m for m in provider.requests[1]["messages"] if m["role"] == "tool")
    assert answer["tool_call_id"] == call["id"] and answer["is_error"] is True
    assert reason in json.loads(answer["content"][0]["text"])["error"]
    assert any(r["event"] == "tool_call_rejected" for r in records)


def test_too_many_tool_calls_in_a_reply_are_answered_but_not_executed(tmp_path):
    batch = [act(f"b{i}") for i in range(11)]
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": batch}, {"tool_calls": []}])
    game = opened(gateway)
    reply = gateway.turn()
    assert [c["id"] for c in reply["tool_calls"]] == [f"b{i}" for i in range(8)]
    play(gateway, game, reply)
    gateway.turn()
    answers = [m for m in provider.requests[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in answers] == [c["id"] for c in batch], "every call answered, in the model's order"
    assert [m["is_error"] for m in answers] == [False] * 8 + [True] * 3
    assert len(game.received) == 8


@pytest.mark.parametrize("bad_id", [None, "", 7, "has space", "x" * 65, "../../etc"])
def test_tool_call_ids_that_cannot_be_answered_reject_the_whole_reply(tmp_path, bad_id):
    gateway, provider, _, _ = make(tmp_path, [{"text": "sneaky", "tool_calls": [{"id": bad_id, "name": "act", "arguments": {"keys": [], "frames": 1}}]},
                                              {"tool_calls": []}])
    opened(gateway)
    assert gateway.turn()["tool_calls"] == []
    gateway.turn()
    assert "sneaky" not in json.dumps(provider.requests[1]["messages"])
    assert provider.requests[1]["messages"][-1]["content"] == [{"type": "text", "text": mg.NO_TOOL_NOTE}]


def test_reused_tool_call_ids_reject_the_reply(tmp_path):
    gateway, _, _, _ = make(tmp_path, [{"tool_calls": [act("same"), act("same")]}, {"tool_calls": [act("again")]},
                                       {"tool_calls": [act("again")]}])
    game = opened(gateway)
    assert gateway.turn()["tool_calls"] == []
    play(gateway, game, gateway.turn())
    assert gateway.turn()["tool_calls"] == [], "an id from an earlier reply cannot be used again"


def test_a_cut_off_reply_is_never_executed(tmp_path):
    gateway, _, _, records = make(tmp_path, [{"stop": "max_tokens", "tool_calls": [act()]}])
    game = opened(gateway)
    assert gateway.turn()["tool_calls"] == [] and game.received == []
    assert any("cut off" in r.get("reason", "") for r in records)


def test_no_tool_call_gets_the_disclosed_note_and_is_counted(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"text": "thinking out loud"}, {"tool_calls": []}])
    opened(gateway)
    assert gateway.turn()["tool_calls"] == []
    gateway.turn()
    assert provider.requests[1]["messages"][-1]["content"] == [{"type": "text", "text": "Use a tool to continue."}]
    assert gateway.counts["invalid_replies"] == 2


def test_ten_replies_without_a_valid_tool_call_end_the_session(tmp_path):
    gateway, provider, _, _ = make(tmp_path, default=lambda wire: {"text": "no"})
    opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        for _ in range(20):
            gateway.turn()
    assert gateway.stop_reason == "consecutive_invalid_replies" and len(provider.requests) == 10


def test_a_valid_call_resets_the_invalid_reply_count(tmp_path):
    script = ([{"text": "no"}] * 9 + [{"tool_calls": [act("v1")]}]) + [{"text": "no"}] * 9 + [{"tool_calls": [act("v2")]}]
    gateway, _, _, _ = make(tmp_path, script)
    game = opened(gateway)
    for _ in range(20):
        play(gateway, game, gateway.turn())
    assert gateway.stop_reason is None


def test_reply_text_longer_than_the_limit_is_cut_in_the_history(tmp_path):
    long_reply = {"text": "x" * 30000, "tool_calls": [act()], "usage": {"input_tokens": 100, "output_tokens": 100}}
    gateway, provider, _, _ = make(tmp_path, [long_reply, {"tool_calls": []}], max_reply_text_chars=100)
    game = opened(gateway)
    play(gateway, game, gateway.turn())
    gateway.turn()
    assistant = next(m for m in provider.requests[1]["messages"] if m["role"] == "assistant")
    assert len(assistant["content"][0]["text"]) == 100


# ---------------------------------------------------------------- the game only moves when the model asks
def test_only_the_models_next_call_may_reach_the_game(tmp_path):
    gateway, _, _, _ = make(tmp_path, [{"tool_calls": [act("c1", ["ArrowUp"], 10), act("c2", ["ArrowLeft"], 20)]}])
    opened(gateway)
    with pytest.raises(mg.GatewayRejected):
        gateway.authorize_game("observe", None)
    gateway.turn()
    for tool, parsed in [("act", contract.Act(("ArrowUp",), 11)), ("act", contract.Act(("ArrowLeft",), 20)), ("observe", None)]:
        with pytest.raises(mg.GatewayRejected):
            gateway.authorize_game(tool, parsed)
    gateway.authorize_game("act", contract.Act(("ArrowUp",), 10))
    assert gateway.counts["game_requests_refused"] == 4


def test_next_turn_is_refused_while_calls_are_waiting(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": [act()]}])
    opened(gateway)
    gateway.turn()
    with pytest.raises(mg.GatewayRejected):
        gateway.turn()
    assert len(provider.requests) == 1


def test_calls_after_an_episode_ends_are_not_executed_and_are_answered(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": [act("c1", frames=100), act("c2", ["ArrowUp"], 100)]}, {"tool_calls": []}])
    game = opened(gateway, FakeGame(frames_to_end=50))
    play(gateway, game, gateway.turn())
    with pytest.raises(mg.GatewayRejected):
        gateway.authorize_game("act", contract.Act(("ArrowUp",), 100))
    gateway.turn()
    answers = {m["tool_call_id"]: m for m in provider.requests[1]["messages"] if m["role"] == "tool"}
    assert answers["c1"]["is_error"] is False and answers["c2"]["is_error"] is True
    assert "episode ended" in answers["c2"]["content"][0]["text"]
    assert len(game.received) == 1


def test_session_over_stops_further_model_calls_for_free(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": [act(frames=10)]}])
    game = opened(gateway, FakeGame(frames_to_end=5, max_episodes=1))
    play(gateway, game, gateway.turn())
    assert gateway.stop_reason == "session_over"
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert len(provider.requests) == 1


# ---------------------------------------------------------------- screenshots
def _image(data=None, **overrides):
    return {**contract.image_payload(data or png(1), 1280, 720), **overrides}


def _crc_broken():
    data = bytearray(png(1))
    data[-1] ^= 0xFF
    return bytes(data)


@pytest.mark.parametrize("image", [
    _image(sha256="0" * 64),
    _image(base64="!!!not base64"),
    _image(base64=12345),
    _image(media_type="image/jpeg"),
    _image(width=640),
    _image(height=480),
    {"media_type": "image/png"},
    {**_image(), "path": "C:/x.png"},
    None,
    "x",
], ids=["hash", "base64", "b64type", "media", "width", "height", "missing", "extra", "none", "string"])
def test_invalid_screenshot_fields_are_refused(image):
    with pytest.raises(mg.InvalidScreenshot):
        mg.validate_screenshot(image, width=1280, height=720, max_bytes=1 << 20)


@pytest.mark.parametrize("data,why", [
    (b"GIF89a" + b"0" * 64, "not a PNG"),
    (png(1)[:-4], "truncated"),
    (png(1)[:40], "truncated"),
    (_crc_broken(), "CRC"),
    (png(1) + b"trailing", "after IEND"),
    (png(1, width=1920, height=1080), "IHDR"),
    (mg.PNG_SIGNATURE, "no IEND"),
], ids=["gif", "cut_end", "cut_mid", "crc", "trailing", "wrong_size", "signature_only"])
def test_corrupt_png_bytes_are_refused(data, why):
    image = {"media_type": "image/png", "width": 1280, "height": 720, "sha256": hashlib.sha256(data).hexdigest(),
             "base64": base64.b64encode(data).decode()}
    with pytest.raises(mg.InvalidScreenshot, match=why):
        mg.validate_screenshot(image, width=1280, height=720, max_bytes=1 << 20)


def test_oversized_screenshot_is_refused():
    with pytest.raises(mg.InvalidScreenshot, match="larger"):
        mg.validate_screenshot(_image(), width=1280, height=720, max_bytes=8)


def test_a_valid_screenshot_passes():
    assert mg.validate_screenshot(_image(), width=1280, height=720, max_bytes=1 << 20) == png(1)


def test_invalid_screenshot_stops_the_session_before_any_provider_call(tmp_path):
    gateway, provider, ledger, records = make(tmp_path, [{"tool_calls": [act()]}])
    game = FakeGame()
    bad = game.observation()
    bad["image"]["sha256"] = "0" * 64
    with pytest.raises(mg.GatewayStopped):
        gateway.record_game(bad)
    assert gateway.stop_reason == "invalid_screenshot" and provider.requests == []
    assert any(r["event"] == "invalid_screenshot" for r in records)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert ledger.state().committed == 0


# ---------------------------------------------------------------- no privileged state
@pytest.mark.parametrize("extra", [{"gameState": "PLAYING"}, {"fuel": 1000}, {"state": {"vx": 1}}, {"debug": 1}])
def test_a_game_reply_with_extra_fields_stops_the_session_and_is_not_forwarded(tmp_path, extra):
    gateway, provider, _, _ = make(tmp_path)
    with pytest.raises(mg.GatewayStopped):
        gateway.record_game({**FakeGame().observation(), **extra})
    assert gateway.stop_reason == "contract_violation" and provider.requests == []


def test_counters_of_the_wrong_type_cannot_carry_text_to_the_model(tmp_path):
    gateway, provider, _, _ = make(tmp_path)
    with pytest.raises(mg.GatewayStopped):
        gateway.record_game({**FakeGame().observation(), "episode": "the fuel is 1000"})
    assert provider.requests == []


def test_gateway_modules_import_nothing_from_the_referee_side():
    for module in ("model_gateway.py", "model_providers.py", "spend_ledger.py"):
        tree = ast.parse((PACKAGE / module).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names.update(a.name for a in node.names)
                names.add(node.module or "")
            elif isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
        assert not names & {"referee", "session", "serve", "replay", "upstream", "host", "isolation"}, module


def test_gateway_modules_have_no_attribute_path_to_a_session_directory(tmp_path):
    gateway, _, _, _ = make(tmp_path)
    assert not {"out", "referee", "session", "session_dir"} & set(vars(gateway))


# ---------------------------------------------------------------- budget
def test_budget_is_checked_before_the_call_and_refusal_makes_no_call(tmp_path):
    gateway, provider, ledger, records = make(tmp_path, default=lambda wire: {"tool_calls": [act(f"c{len(provider.requests)}")]},
                                              session_cap="0.02", cumulative_cap="0.02")
    game = opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        for _ in range(1000):
            play(gateway, game, gateway.turn())
    assert gateway.stop_reason == "budget_exhausted_session"
    calls = [r for r in records if r["event"] == "model_call"]
    assert calls[-1]["outcome"]["kind"] == "refused_before_call" and "reservation" not in calls[-1]
    assert len(provider.requests) == len(calls) - 1, "the refused call never reached the provider"
    assert ledger.state().committed <= Decimal("0.02") and ledger.state().open_reservations == {}
    count = len(provider.requests)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert len(provider.requests) == count


def test_cumulative_cap_stops_a_later_session(tmp_path):
    ledger = sl.SpendLedger(tmp_path / "ledger.jsonl", mode=sl.MODE_OFFLINE_MOCK)
    ledger.settle(ledger.reserve(session="earlier", call=1, worst_case="0.90", session_cap="1", cumulative_cap="1"),
                  charged="0.90", basis="provider_usage")
    config = mg.GatewayConfig(provider_id="offline-mock", model_id="mock-vision-0", pricing=PRICING,
                              session_cap_usd="0.50", cumulative_cap_usd="0.901")
    provider = mp.MockVisionProvider([{"tool_calls": []}])
    second = mg.VisionGateway(config, mp.MockAdapter(), mp.OfflineTransport(provider), ledger, session_id="second")
    opened(second)
    with pytest.raises(mg.GatewayStopped):
        second.turn()
    assert second.stop_reason == "budget_exhausted_cumulative" and provider.requests == []


def test_first_call_already_too_expensive_never_goes_out(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": []}], session_cap="0.000001", cumulative_cap="0.000001")
    opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert provider.requests == []


def test_worst_case_bounds_the_actual_charge_and_is_recorded(tmp_path):
    gateway, _, ledger, records = make(tmp_path, [{"tool_calls": [act()]}])
    opened(gateway)
    gateway.turn()
    (call,) = [r for r in records if r["event"] == "model_call"]
    assert Decimal(call["outcome"]["charged_usd"]) <= Decimal(call["worst_case_usd"])
    assert ledger.state().spent == Decimal(call["outcome"]["charged_usd"])


def test_token_and_cost_accounting_uses_the_providers_usage_exactly(tmp_path):
    usage = {"input_tokens": 1000, "output_tokens": 500, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 200}
    gateway, _, ledger, records = make(tmp_path, [{"tool_calls": [act()], "usage": usage}])
    opened(gateway)
    gateway.turn()
    # (1000 + 200 + 100 x 2) x $1 + 500 x $2, per million tokens
    assert ledger.state().spent == Decimal("0.0024")
    (call,) = [r for r in records if r["event"] == "model_call"]
    assert call["outcome"]["usage"] == {"input_tokens": 1000, "output_tokens": 500, "cache_write_tokens": 100, "cache_read_tokens": 200}
    assert gateway.manifest()["charged_usd"] == "0.002400000"


@pytest.mark.parametrize("usage", [None, {}, {"input_tokens": -5, "output_tokens": 1}, {"input_tokens": "9", "output_tokens": 1},
                                   {"input_tokens": 1.5, "output_tokens": 1}, {"input_tokens": True, "output_tokens": 1}, "lots"])
def test_missing_or_nonsense_usage_is_charged_at_worst_case_and_ends_the_session(tmp_path, usage):
    gateway, _, ledger, records = make(tmp_path, [{"tool_calls": [act()], "usage": usage}])
    game = opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    (call,) = [r for r in records if r["event"] == "model_call"]
    assert gateway.stop_reason == "usage_missing" and ledger.state().spent == Decimal(call["worst_case_usd"])
    assert game.received == []


def test_more_output_than_requested_is_charged_and_ends_the_session(tmp_path):
    gateway, _, ledger, _ = make(tmp_path, [{"tool_calls": [act()], "usage": {"input_tokens": 1, "output_tokens": 999999}}],
                                 max_output_tokens=100)
    opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "output_limit_violated" and ledger.state().spent >= Decimal("1.99")


def test_a_different_model_answering_ends_the_session(tmp_path):
    gateway, _, _, _ = make(tmp_path, [{"tool_calls": [act()], "model": "some-fallback-model"}])
    game = opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "model_mismatch" and game.received == []


def test_model_call_limit(tmp_path):
    gateway, provider, _, _ = make(tmp_path, default=lambda wire: {"tool_calls": [act(f"c{len(provider.requests)}")]}, max_model_calls=3)
    game = opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        for _ in range(10):
            play(gateway, game, gateway.turn())
    assert gateway.stop_reason == "model_call_limit" and len(provider.requests) == 3


def test_wall_clock_limit_is_checked_before_a_call(tmp_path):
    now = [0.0]
    config = mg.GatewayConfig(provider_id="offline-mock", model_id="mock-vision-0", pricing=PRICING, session_cap_usd="1",
                              cumulative_cap_usd="1", max_wall_seconds=10.0)
    provider = mp.MockVisionProvider([{"tool_calls": []}])
    gateway = mg.VisionGateway(config, mp.MockAdapter(), mp.OfflineTransport(provider), sl.SpendLedger(tmp_path / "l.jsonl", mode=sl.MODE_OFFLINE_MOCK),
                               session_id="s", clock=lambda: now[0])
    opened(gateway)
    now[0] = 11.0
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "wall_clock_limit" and provider.requests == []


def test_context_limit_stops_before_the_call_and_never_cuts_history_silently(tmp_path):
    gateway, provider, _, _ = make(tmp_path, default=lambda wire: {"text": "y" * 4000, "tool_calls": [act(f"c{len(provider.requests)}")]},
                                   max_context_tokens=12000)
    game = opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        for _ in range(50):
            play(gateway, game, gateway.turn())
    assert gateway.stop_reason == "context_limit"
    assert 1 < len(provider.requests) < 50


def test_request_size_limit(tmp_path):
    gateway, provider, _, _ = make(tmp_path, [{"tool_calls": []}], max_request_bytes=100)
    opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "request_size_limit" and provider.requests == []


def test_token_estimate_is_an_overestimate_of_the_mock_count(tmp_path):
    gateway, provider, _, records = make(tmp_path, default=lambda wire: {"text": "z" * 500, "tool_calls": [act(f"c{len(provider.requests)}")]})
    game = opened(gateway)
    for _ in range(10):
        play(gateway, game, gateway.turn())
    for r in (r for r in records if r["event"] == "model_call"):
        assert r["estimated_input_tokens"] >= r["outcome"]["usage"]["input_tokens"]


# ---------------------------------------------------------------- provider failures
def test_refusal_is_charged_recorded_and_ends_the_session(tmp_path):
    gateway, _, ledger, records = make(tmp_path, [{"stop": "refusal", "text": "I can't"}])
    game = opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "provider_refusal" and ledger.state().spent > 0 and game.received == []
    (call,) = [r for r in records if r["event"] == "model_call"]
    assert call["outcome"]["stop"] == "refusal"


def test_timeout_is_charged_at_worst_case_and_a_hung_provider_cannot_hang_the_session(tmp_path):
    release = threading.Event()

    def hang(wire):
        release.wait(30)
        return {"tool_calls": []}

    gateway, _, ledger, records = make(tmp_path, [hang, hang, hang], provider_timeout_seconds=0.05)
    opened(gateway)
    started = time.monotonic()
    try:
        with pytest.raises(mg.GatewayStopped):
            gateway.turn()
    finally:
        release.set()
    assert time.monotonic() - started < 10
    assert gateway.stop_reason == "consecutive_provider_errors"
    calls = [r for r in records if r["event"] == "model_call"]
    assert [c["outcome"]["kind"] for c in calls] == ["timeout"] * 3
    assert ledger.state().spent == sum(Decimal(c["worst_case_usd"]) for c in calls), "the request may have been processed"
    assert ledger.state().open_reservations == {}


def test_rate_limit_is_not_charged_honours_retry_after_and_retries(tmp_path):
    waits = []
    script = [mp.TransportResponse(429, {"error": "slow"}, {"Retry-After": "7"}), {"tool_calls": [act()]}]
    gateway, provider, ledger, records = make(tmp_path, script, sleep=waits.append)
    opened(gateway)
    assert gateway.turn()["tool_calls"] == [act()]
    assert waits == [7.0] and len(provider.requests) == 2
    calls = [r for r in records if r["event"] == "model_call"]
    assert calls[0]["outcome"]["charged_usd"] == "0" and calls[0]["outcome"]["kind"] == "rate_limited"
    assert gateway.counts["model_calls"] == 2, "attempts count against the call limit"


def test_retry_after_cannot_stall_the_session(tmp_path):
    waits = []
    script = [mp.TransportResponse(429, {}, {"retry-after": "999999"}), mp.TransportResponse(429, {}, {"retry-after": "nan"}),
              {"tool_calls": []}]
    gateway, _, _, _ = make(tmp_path, script, sleep=waits.append)
    opened(gateway)
    gateway.turn()
    assert waits[0] == 60.0 and 0 < waits[1] <= 60.0


def test_three_consecutive_errors_end_the_session_and_success_resets_the_count(tmp_path):
    err = mp.TransportResponse(529, {})
    gateway, provider, _, _ = make(tmp_path, [err, err, {"tool_calls": [act()]}, err, err, err])
    game = opened(gateway)
    play(gateway, game, gateway.turn())
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "consecutive_provider_errors" and len(provider.requests) == 6


@pytest.mark.parametrize("status", [500, 502, 503, 504, 408])
def test_server_errors_are_charged_at_worst_case_until_reconciled(tmp_path, status):
    gateway, _, ledger, records = make(tmp_path, [mp.TransportResponse(status, {}), {"tool_calls": []}])
    opened(gateway)
    gateway.turn()
    first = [r for r in records if r["event"] == "model_call"][0]
    assert first["outcome"]["charged_usd"] == first["worst_case_usd"]
    assert ledger.state().spent >= Decimal(first["worst_case_usd"])


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 413])
def test_rejected_requests_end_the_session_without_a_retry_or_charge(tmp_path, status):
    gateway, provider, ledger, _ = make(tmp_path, [mp.TransportResponse(status, {"error": "no"}), {"tool_calls": []}])
    opened(gateway)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == f"provider_rejected_{status}"
    assert len(provider.requests) == 1 and ledger.state().spent == 0 and ledger.state().open_reservations == {}


@pytest.mark.parametrize("body", [None, "<html>gateway error</html>", [], {"text": "no stop"}, {"stop": "exploded"},
                                  {"stop": "end_turn", "text": 5}, {"stop": "end_turn", "tool_calls": "act"}])
def test_malformed_replies_are_charged_and_never_interpreted(tmp_path, body):
    gateway, _, ledger, records = make(tmp_path, [mp.TransportResponse(200, body), {"tool_calls": []}])
    game = opened(gateway)
    gateway.turn()
    first = [r for r in records if r["event"] == "model_call"][0]
    assert first["outcome"]["kind"] == "malformed_reply" and game.received == []
    assert Decimal(first["outcome"]["charged_usd"]) == Decimal(first["worst_case_usd"])


def test_connection_errors_are_retried_and_charged_conservatively(tmp_path):
    gateway, _, _, records = make(tmp_path, [ConnectionResetError("boom"), {"tool_calls": []}])
    opened(gateway)
    gateway.turn()
    first = [r for r in records if r["event"] == "model_call"][0]
    assert first["outcome"]["kind"] == "transport_error" and first["outcome"]["detail"] == "ConnectionResetError"


# ---------------------------------------------------------------- safe logging and provenance
CANARY = "sk-ant-api03-CANARYCANARYCANARY"


def test_secrets_never_reach_the_transcript_or_the_player(tmp_path):
    script = [mp.TransportResponse(429, {"error": f"bad key {CANARY}"}, {"authorization": f"Bearer {CANARY}"}),
              {"text": f"my key is {CANARY}", "tool_calls": [{"id": "c1", "name": "act", "arguments": {"keys": [CANARY], "frames": 1}}]}]
    gateway, _, _, records = make(tmp_path, script)
    opened(gateway)
    reply = gateway.turn()
    assert CANARY not in json.dumps(records) and CANARY not in json.dumps(gateway.manifest())
    assert CANARY not in json.dumps(reply)


def test_redact():
    for secret in (CANARY, "ghp_abcdefghijklmnop", "AKIAIOSFODNN7EXAMPLE", "Bearer abc.def.ghi", "AIzaSyD-abcdefg", "eyJhbGciOiJIUzI1NiJ9.x"):
        assert secret not in mg.redact(f"text {secret} text")
    assert mg.redact("x" * 900, 100) == "x" * 100


def test_transcript_records_images_by_hash_never_bytes(tmp_path):
    gateway, _, _, records = make(tmp_path, [{"tool_calls": [act()]}])
    opened(gateway)
    gateway.turn()
    text = json.dumps(records)
    assert base64.b64encode(png(1)).decode() not in text and '"base64"' not in text
    assert hashlib.sha256(png(1)).hexdigest() in text


def test_transcript_hash_chain_detects_any_edit(tmp_path):
    gateway, provider, _, records = make(tmp_path, default=lambda wire: {"tool_calls": [act(f"c{len(provider.requests)}")]})
    game = opened(gateway)
    for _ in range(4):
        play(gateway, game, gateway.turn())
    check = mg.verify_transcript(records)
    assert check["valid"] and check["records"] == len(records) and check["tip_sha256"] == gateway.manifest()["transcript_tip_sha256"]
    edited = json.loads(json.dumps(records))
    edited[1]["outcome"]["charged_usd"] = "0"
    assert mg.verify_transcript(edited) == {"valid": False, "first_bad_record": 2}
    assert not mg.verify_transcript(records[1:])["valid"]


def test_manifest_gives_full_provenance(tmp_path):
    gateway, _, _, _ = make(tmp_path)
    m = gateway.manifest()
    assert m["is_model"] is False and "NOT A MODEL" in m["name"] and m["live_calls_permitted"] is False
    assert m["transport_offline"] is True and m["ledger_mode"] == "offline-mock"
    assert m["contract"] == {"protocol": contract.V2.protocol, "keyset": "keyset.v2", "tools_sha256": gateway.tools_sha256}
    assert m["config_sha256"] == gateway.config.sha256() and "MOCK" in m["disclaimer"]
    assert m["config"]["pricing"]["source"] == "test"


# ---------------------------------------------------------------- the disabled Claude adapter (never sent anywhere)
def neutral_history(tmp_path):
    captured = {}
    gateway, provider, _, _ = make(tmp_path, [{"text": "first", "tool_calls": [act("c1", ["ArrowUp"], 30),
                                                                                 {"id": "c2", "name": "read_file", "arguments": {}}]},
                                              {"tool_calls": []}, {"tool_calls": []}])
    game = opened(gateway)
    play(gateway, game, gateway.turn())
    gateway.turn()
    gateway.turn()
    captured = provider.requests[-1]
    return captured


def test_claude_wire_format_for_vision_and_tools(tmp_path):
    wire = mp.AnthropicMessagesAdapter(effort="low").build_request(neutral_history(tmp_path))
    assert wire["model"] == "mock-vision-0" and wire["system"] == "Land the rocket." and wire["tool_choice"] == {"type": "auto"}
    assert wire["output_config"] == {"effort": "low"} and wire["max_tokens"] == 2048
    assert [t["name"] for t in wire["tools"]] == ["observe", "act"] and set(wire["tools"][1]) == {"name", "description", "input_schema"}
    roles = [m["role"] for m in wire["messages"]]
    assert roles[:2] == ["user", "assistant"] and roles[0] == "user"
    assert all(a != b for a, b in zip(roles, roles[1:])), "tool results and notes merge into one user turn"
    opening = wire["messages"][0]["content"]
    assert opening[0] == {"type": "text", "text": "Land the rocket."}
    assert opening[1]["type"] == "image" and opening[1]["source"]["type"] == "base64" and opening[1]["source"]["media_type"] == "image/png"
    assistant = wire["messages"][1]["content"]
    assert assistant[0] == {"type": "text", "text": "first"}
    assert assistant[1] == {"type": "tool_use", "id": "c1", "name": "act", "input": {"keys": ["ArrowUp"], "frames": 30}}
    results = wire["messages"][2]["content"]
    assert [(b["type"], b["tool_use_id"], b["is_error"]) for b in results[:2]] == [("tool_result", "c1", False), ("tool_result", "c2", True)]
    assert results[0]["content"][1]["type"] == "image"


def test_claude_request_enables_nothing_beyond_the_two_tools(tmp_path):
    wire = mp.AnthropicMessagesAdapter().build_request(neutral_history(tmp_path))
    assert set(wire) == {"model", "max_tokens", "system", "tools", "tool_choice", "messages"}
    assert not re.search(r"fallbacks|betas|thinking|cache_control|web_search|code_execution|memory", json.dumps({k: v for k, v in wire.items() if k != "messages"}))


def test_claude_reply_parsing_discards_thinking_and_finds_tool_calls():
    body = {"type": "message", "id": "msg_1", "model": "claude-haiku-5-5", "stop_reason": "tool_use",
            "content": [{"type": "thinking", "thinking": "", "signature": "abc"}, {"type": "redacted_thinking", "data": "x"},
                        {"type": "text", "text": "Trying."}, {"type": "tool_use", "id": "toolu_1", "name": "act", "input": {"keys": [], "frames": 5}}],
            "usage": {"input_tokens": 1500, "output_tokens": 80, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}}
    reply = mp.AnthropicMessagesAdapter().parse_response(mp.TransportResponse(200, body, {"Request-Id": "req_9"}))
    assert (reply.text, reply.stop, reply.request_id, reply.model) == ("Trying.", "tool_use", "req_9", "claude-haiku-5-5")
    assert reply.tool_calls == ({"id": "toolu_1", "name": "act", "arguments": {"keys": [], "frames": 5}},)
    assert reply.discarded_blocks == ("thinking", "redacted_thinking") and reply.usage == mp.Usage(1500, 80)
    assert "signature" not in json.dumps(reply.tool_calls)


def test_claude_refusal_and_unknown_stop_reasons():
    adapter = mp.AnthropicMessagesAdapter()
    refused = adapter.parse_response(mp.TransportResponse(200, {"type": "message", "content": [], "stop_reason": "refusal",
                                                                "stop_details": {"type": "refusal", "category": "cyber"}, "usage": {"input_tokens": 1, "output_tokens": 0}}))
    assert refused.stop == "refusal" and refused.refusal_category == "cyber"
    paused = adapter.parse_response(mp.TransportResponse(200, {"type": "message", "content": [], "stop_reason": "pause_turn", "usage": {"input_tokens": 1, "output_tokens": 0}}))
    assert paused.stop == "other"


@pytest.mark.parametrize("body", [None, [], {"type": "error"}, {"type": "message"}, {"type": "message", "content": [7]}])
def test_claude_malformed_replies(body):
    with pytest.raises(mp.ProviderProtocolError):
        mp.AnthropicMessagesAdapter().parse_response(mp.TransportResponse(200, body))


def test_thinking_is_never_replayed_through_the_whole_gateway(tmp_path):
    """The reason: replacing old screenshots edits history, which invalidates replayed thinking on current models."""
    def reply(wire):
        n = sum(m["role"] == "assistant" for m in wire["messages"])
        return mp.TransportResponse(200, {"type": "message", "model": "claude-haiku-5-5", "stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
                                          "content": [{"type": "thinking", "thinking": "SECRET-REASONING", "signature": "sig"},
                                                      {"type": "tool_use", "id": f"t{n}", "name": "act", "input": {"keys": [], "frames": 5}}]})
    wires = []
    config = mg.GatewayConfig(provider_id="anthropic", model_id="claude-haiku-5-5", pricing=PRICING, session_cap_usd="1", cumulative_cap_usd="1")

    def handler(wire, timeout):
        wires.append(wire)
        return reply(wire)

    gateway = mg.VisionGateway(config, mp.AnthropicMessagesAdapter(), mp.OfflineTransport(handler),
                               sl.SpendLedger(tmp_path / "l.jsonl", mode=sl.MODE_OFFLINE_MOCK), session_id="s", sink=lambda r: None)
    game = opened(gateway)
    for _ in range(7):
        play(gateway, game, gateway.turn())
    last = json.dumps(wires[-1])
    assert "SECRET-REASONING" not in last and '"thinking"' not in last
    assert sum(b["type"] == "image" for m in wires[-1]["messages"] for b in m["content"] if isinstance(m["content"], list)
               ) + sum(sub["type"] == "image" for m in wires[-1]["messages"] for b in m["content"]
                       if b["type"] == "tool_result" for sub in b["content"]) == 4


# ---------------------------------------------------------------- the real broker and player loop, with a fake referee
@pytest.fixture
def broker(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "supported", lambda: None)
    monkeypatch.setattr(isolation, "exposed_user_environment_secrets", lambda: [])

    def build(script, *, game=None, **limits):
        gateway, provider, ledger, _ = make(tmp_path, script, **limits)
        game = game or FakeGame()
        config = host_mod.HostConfig(out=tmp_path / "session", mode="model", keyset="keyset.v2", player_label="pytest (NOT AI)",
                                     max_episodes=gateway.config.max_episodes, episode_frame_budget=gateway.config.episode_frame_budget,
                                     max_wall_seconds=gateway.config.max_wall_seconds, max_requests=gateway.config.max_game_requests)
        host = host_mod.Host(config, gateway=gateway)
        host.started = "test"
        host._referee_call = lambda request: json.dumps(game.call(request)).encode() + b"\n"
        return host, gateway, provider, ledger, game
    return build


def load_runtime():
    spec = importlib.util.spec_from_file_location("player_runtime_under_test", runtime_image.PLAYER_SOURCE / "runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def relay(host_obj):
    runtime = load_runtime()

    class Pipe(runtime.Host):
        def __init__(self):
            pass

        def raw(self, line):
            return json.loads(host_obj._handle_line(line.rstrip(b"\n"), False)[0])

    reports = []
    runtime.report = lambda **fields: reports.append(fields)
    code = runtime.run_model_session(Pipe())
    return code, reports


def test_player_loop_plays_a_session_through_the_real_broker(broker):
    game = FakeGame(frames_to_end=30, max_episodes=2)
    script = [{"text": "go", "tool_calls": [{"id": "o", "name": "observe", "arguments": {}}]},
              {"tool_calls": [act("a", ["ArrowUp"], 10)]},
              {"tool_calls": [{"id": "h", "name": "read_file", "arguments": {}}]},
              {"tool_calls": [act("b", [], 40), act("c", ["ArrowUp"], 1)]},
              {"tool_calls": [act("d", [], 40)]}]
    host, gateway, provider, ledger, game = broker(script, game=game)
    assert relay(host)[0] == 0
    assert [r["tool"] for r in game.received] == ["brief", "observe", "observe", "act", "act", "act"]
    assert gateway.stop_reason == "session_over" and host.counts["model_calls"] == 5
    assert ledger.state().open_reservations == {} and gateway.counts["tool_calls_rejected"] == 1


@pytest.mark.parametrize("line", [
    b'{"tool":"model","messages":[{"role":"user","content":[{"type":"text","text":"the pad is at x=3"}]}]}',
    b'{"tool":"model","messages":[]}', b'{"tool":"model","model":"gpt-9"}', b'{"tool":"model","max_output_tokens":99}',
    b'{"tool":"model","system":"x"}', b'{"tool":"model","tools":[]}',
])
def test_the_player_cannot_supply_any_content_for_the_model(broker, line):
    host, gateway, provider, _, game = broker([{"tool_calls": []}])
    host._handle_line(b'{"tool":"brief"}', False)
    host._handle_line(b'{"tool":"observe"}', False)
    response, decision = host._handle_line(line, False)
    assert decision == "rejected" and "error" in json.loads(response)
    assert provider.requests == []


def test_forged_actions_never_reach_the_referee(broker):
    host, _, _, _, game = broker([{"tool_calls": [act("a", ["ArrowUp"], 10)]}])
    for line in (b'{"tool":"brief"}', b'{"tool":"observe"}'):
        host._handle_line(line, False)
    before = len(game.received)
    for line in (b'{"tool":"act","keys":["ArrowUp"],"frames":120}', b'{"tool":"observe"}', b'{"tool":"act","keys":["KeyS"],"frames":1}'):
        assert host._handle_line(line, False)[1] == "rejected"
    host._handle_line(b'{"tool":"model"}', False)
    assert host._handle_line(b'{"tool":"act","keys":["ArrowUp"],"frames":11}', False)[1] == "rejected"
    assert len(game.received) == before
    assert host._handle_line(b'{"tool":"act","keys":["ArrowUp"],"frames":10}', False)[1] == "forwarded"
    assert host._handle_line(b'{"tool":"act","keys":["ArrowUp"],"frames":10}', False)[1] == "rejected"
    assert len(game.received) == before + 1


def test_stop_reasons_stay_private_the_player_gets_one_fixed_message(broker):
    host, gateway, _, _, _ = broker([mp.TransportResponse(401, {"error": f"bad key {CANARY}"})])
    code, reports = relay(host)
    assert code == 0 and gateway.stop_reason == "provider_rejected_401"
    assert reports[-1]["detail"] == mg.ENDED_MESSAGE
    assert CANARY not in json.dumps(reports)


def test_a_gateway_crash_ends_the_session_cleanly_and_the_reservation_stays_charged(broker, monkeypatch):
    host, gateway, _, ledger, _ = broker([{"tool_calls": []}])

    class Broken:
        status = property(lambda self: (_ for _ in ()).throw(RuntimeError(f"bug near {CANARY}")))

    gateway.transport.send = lambda wire, timeout: Broken()
    code, reports = relay(host)
    assert code == 0 and reports[-1]["detail"] == mg.ENDED_MESSAGE
    assert host.gateway_failure.startswith("RuntimeError") and CANARY not in host.gateway_failure
    state = ledger.state()
    assert len(state.open_reservations) == 1 and state.committed > 0
    assert CANARY not in json.dumps(host._manifest())


def test_invalid_screenshot_from_the_referee_is_not_shown_to_the_player(broker):
    class BadGame(FakeGame):
        def observation(self, *a, **k):
            obs = super().observation(*a, **k)
            obs["image"]["sha256"] = "f" * 64
            return obs
    host, gateway, provider, _, _ = broker([], game=BadGame())
    host._handle_line(b'{"tool":"brief"}', False)
    response, decision = host._handle_line(b'{"tool":"observe"}', False)
    assert decision == "gateway_stopped" and set(json.loads(response)) == contract.ERROR_FIELDS
    assert gateway.stop_reason == "invalid_screenshot" and provider.requests == []


def test_host_and_gateway_must_agree_or_nothing_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "supported", lambda: None)
    monkeypatch.setattr(isolation, "exposed_user_environment_secrets", lambda: [])
    gateway, _, _, _ = make(tmp_path, max_episodes=3)
    base = dict(mode="model", keyset="keyset.v2", player_label="x", max_wall_seconds=gateway.config.max_wall_seconds,
                episode_frame_budget=gateway.config.episode_frame_budget, max_requests=gateway.config.max_game_requests)
    with pytest.raises(ValueError, match="disagree"):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "a", max_episodes=4, **base), gateway=gateway)
    with pytest.raises(ValueError, match="disagree"):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "e", max_episodes=3, **{**base, "max_requests": 20000}), gateway=gateway)
    with pytest.raises(ValueError, match="disagree"):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "b", max_episodes=3, **{**base, "keyset": "keyset.v1"}), gateway=gateway)
    with pytest.raises(ValueError, match="does not match"):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "c", mode="scripted", player_label="x"), gateway=gateway)
    with pytest.raises(ValueError, match="does not match"):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "d", mode="model", player_label="x"))
    assert not any((tmp_path / n).exists() for n in "abcd")


def test_a_real_model_cannot_use_the_mission_014_player_owned_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "supported", lambda: None)
    monkeypatch.setattr(isolation, "exposed_user_environment_secrets", lambda: [])

    class Old:
        name, is_model = "old", True

    with pytest.raises(ValueError, match="owns the conversation"):
        host_mod.Host(host_mod.HostConfig(out=tmp_path / "s", mode="agent", player_label="x", max_model_calls=1), gateway=Old())
