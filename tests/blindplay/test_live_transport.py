"""The live transport and its gate, against a local mock HTTP server. **No request can leave this machine.**

An autouse fixture makes any connection to anything but the loopback interface fail the test. The API key here is fake, and the
gate is opened only by monkeypatching the flag inside a test; a test pins the real flag as False.
"""

from __future__ import annotations

import ast
import hashlib
import http.client
import io
import json
import re
import socket
import struct
import threading
import time
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rewardbench.blindplay import (contract, live_session, live_transport as lt, model_gateway as mg, model_providers as mp,
                                   spend_ledger as sl)

PACKAGE = Path(contract.__file__).resolve().parent
FAKE_KEY = "sk-ant-api03-FAKEFAKEFAKEFAKEFAKEFAKE-not-a-real-key"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
COMMIT = "a" * 40
CLEAN = lambda: {"commit": COMMIT, "dirty": False}  # noqa: E731


@pytest.fixture(autouse=True)
def loopback_only(monkeypatch):
    real_connect = socket.socket.connect
    real_create = socket.create_connection

    def connect(self, address):
        if self.family == socket.AF_INET and address[0] != "127.0.0.1":
            pytest.fail(f"a test tried to reach {address}")
        return real_connect(self, address)

    def create(address, *args, **kwargs):
        if address[0] != "127.0.0.1":
            pytest.fail(f"a test tried to reach {address}")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", create)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


def message(content, stop="tool_use", usage=None, model="claude-haiku-5-5", **extra):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content, "stop_reason": stop,
            "usage": usage or {"input_tokens": 5000, "output_tokens": 50}, **extra}


def tool_use(call_id="toolu_1", keys=("ArrowUp",), frames=30, name="act"):
    return {"type": "tool_use", "id": call_id, "name": name, "input": {"keys": list(keys), "frames": frames}}


class MockApi:
    """A real HTTP server on loopback that answers from a script: (status, headers, body-or-bytes), or a callable."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["content-length"]))
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": json.loads(body)})
                item = outer.script.pop(0) if outer.script else (200, {}, message([{"type": "text", "text": "done"}], "end_turn"))
                if callable(item):
                    item = item()
                status, headers, payload = item
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                for key, value in {"content-type": "application/json", "request-id": "req_test", **headers}.items():
                    self.send_header(key, value)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def connection(self, timeout):
        return http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=timeout)

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def api():
    servers = []

    def build(script=()):
        server = MockApi(script)
        servers.append(server)
        return server
    yield build
    for server in servers:
        server.close()


def authorization(**overrides):
    settings = dict(lt.PILOT_CANDIDATE)
    settings.update({k: v for k, v in overrides.items() if k in settings})
    fields = {"schema": lt.AUTHORIZATION_SCHEMA, "approved_by": "pytest", "approved_utc": (NOW - timedelta(hours=1)).isoformat(),
              "expires_utc": (NOW + timedelta(days=1)).isoformat(), "pricing_verified_utc": NOW.isoformat(), "git_commit": COMMIT,
              "config_sha256": lt.build_config(settings).sha256(), **settings}
    fields.update(overrides)
    return fields


@pytest.fixture
def owner(tmp_path):
    """Files as the owner would create them, outside the repository."""
    credential = tmp_path / "anthropic.key"
    credential.write_text(FAKE_KEY + "\n", encoding="utf-8")
    credential.chmod(0o600)
    auth = tmp_path / "authorization.json"
    auth.write_text(json.dumps(authorization()), encoding="utf-8")
    return {"credential": credential, "authorization": auth, "ledger": tmp_path / "live_ledger.jsonl"}


@pytest.fixture
def live_flag(monkeypatch):
    monkeypatch.setattr(mg, "LIVE_CALLS_PERMITTED", True)


def gate(owner, connection=lambda timeout: pytest.fail("no connection expected"), **kwargs):
    kwargs.setdefault("state", CLEAN)
    kwargs.setdefault("now", lambda: NOW)
    return lt.open_gate(authorization_path=owner["authorization"], credential_path=owner["credential"], ledger_path=owner["ledger"],
                        connection_factory=connection, **kwargs)


# ---------------------------------------------------------------- closed by default
def test_the_real_flag_is_false():
    assert mg.LIVE_CALLS_PERMITTED is False


def test_closed_gate_looks_at_nothing(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(mg.LiveCallsDisabled):
        lt.open_gate(authorization_path=missing, credential_path=missing, ledger_path=missing)
    assert not missing.exists(), "not even a ledger is created"


def test_closed_gate_never_reads_the_credential(owner, monkeypatch):
    monkeypatch.setattr(lt, "read_credential", lambda path: pytest.fail("the credential was read"))
    with pytest.raises(mg.LiveCallsDisabled):
        gate(owner)
    assert not owner["ledger"].exists()


def test_transport_refuses_at_send_time_if_the_flag_is_off(owner, api, live_flag, monkeypatch):
    server = api()
    session = gate(owner, connection=server.connection)
    monkeypatch.setattr(mg, "LIVE_CALLS_PERMITTED", False)
    with pytest.raises(mg.LiveCallsDisabled):
        session.transport.send({"model": "claude-haiku-5-5"}, 1.0)
    assert server.requests == []


def test_cli_refuses_with_the_gate_closed(owner, tmp_path, capsys):
    code = live_session.main(["run", "--authorization", str(owner["authorization"]), "--credential", str(owner["credential"]),
                              "--ledger", str(owner["ledger"]), "--out", str(tmp_path / "out")])
    assert code == 3 and "disabled" in capsys.readouterr().err
    assert not (tmp_path / "out").exists() and not owner["ledger"].exists()


def test_gateway_refuses_a_live_transport_while_the_flag_is_off(owner, api, live_flag, monkeypatch):
    session = gate(owner, connection=api().connection)
    monkeypatch.setattr(mg, "LIVE_CALLS_PERMITTED", False)
    with pytest.raises(mg.LiveCallsDisabled):
        mg.VisionGateway(session.config, session.adapter, session.transport, session.ledger, session_id="s")


# ---------------------------------------------------------------- only this module may touch the network
def _imports(path):
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


@pytest.mark.parametrize("module", ["host.py", "model_gateway.py", "model_providers.py", "spend_ledger.py", "offline_demo.py", "session.py",
                                    "serve.py", "referee.py", "replay.py", "contract.py", "player_runtime/runtime.py", "player_runtime/probes.py"])
def test_nothing_else_imports_the_live_transport(module):
    assert not any("live_transport" in n or "live_session" in n for n in _imports(PACKAGE / module)), module


def test_the_sandbox_image_cannot_contain_the_live_transport():
    assert sorted(p.name for p in (PACKAGE / "player_runtime").glob("*.py")) == ["probes.py", "runtime.py"]


def test_live_transport_uses_no_sdk_and_reads_no_key_from_the_environment():
    names = _imports(PACKAGE / "live_transport.py")
    assert not {n.split(".")[0] for n in names} & {"anthropic", "openai", "requests", "httpx", "httpx2", "urllib", "aiohttp", "keyring"}
    text = (PACKAGE / "live_transport.py").read_text(encoding="utf-8")
    assert "os.getenv" not in text and "environ[" not in text and "environ.get" not in text
    assert re.findall(r"os\.environ", text) == ["os.environ"], "only passed to the check that refuses ambient credentials"


def test_host_is_pinned_to_tls_and_the_official_endpoint():
    conn = lt._https_connection(1.0)
    assert isinstance(conn, http.client.HTTPSConnection) and conn.host == "api.anthropic.com" and conn.port == 443
    assert conn._context.verify_mode.name == "CERT_REQUIRED" and conn._context.check_hostname is True
    assert (lt.MESSAGES_PATH, lt.ANTHROPIC_VERSION) == ("/v1/messages", "2023-06-01")


# ---------------------------------------------------------------- what opens the gate
@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"])
def test_a_credential_in_the_environment_is_refused_and_not_echoed(owner, live_flag, monkeypatch, name):
    monkeypatch.setenv(name, FAKE_KEY)
    with pytest.raises(lt.LiveGateRefused, match=name) as err:
        gate(owner)
    assert FAKE_KEY not in str(err.value)


@pytest.mark.parametrize("change,why", [
    ({"approved_by": "OWNER_NAME"}, "filled in"),
    ({"git_commit": "OWNER_COMMIT"}, "filled in"),
    ({"approved_by": "   "}, "filled in"),
    ({"schema": "other"}, "schema"),
    ({"extra": "field"}, "exactly"),
    ({"max_model_calls": "30"}, "wrong type"),
    ({"max_model_calls": True}, "wrong type"),
    ({"thinking": "adaptive"}, "not supported"),
    ({"provider": "openai"}, "only the anthropic"),
    ({"session_cap_usd": "5.00", "cumulative_cap_usd": "5.00", "config_sha256": "0" * 64}, "config_sha256"),
    ({"model_id": "claude-opus-5-5", "config_sha256": "0" * 64}, "config_sha256"),
    ({"expires_utc": (NOW - timedelta(minutes=1)).isoformat()}, "expired"),
    ({"expires_utc": (NOW + timedelta(days=30)).isoformat()}, "at most"),
    ({"approved_utc": (NOW + timedelta(hours=1)).isoformat()}, "future"),
    ({"approved_utc": "yesterday"}, "ISO"),
    ({"approved_utc": "2026-10-30T11:00:00"}, "time zone"),
    ({"pricing_verified_utc": (NOW - timedelta(days=8)).isoformat()}, "checked"),
    ({"git_commit": "b" * 40}, "exact authorized commit"),
    ({"session_cap_usd": "not money"}, "not valid"),
    ({"session_cap_usd": "2.00"}, "not valid"),
])
def test_authorization_problems_refuse_the_gate(owner, live_flag, change, why):
    settings = authorization()
    settings.update(change)
    if not {"config_sha256", "session_cap_usd", "provider", "model_id", "thinking"} & set(change):
        pass
    elif "config_sha256" not in change and "session_cap_usd" not in change:
        rebuilt = {k: settings[k] for k in lt.PILOT_CANDIDATE}
        settings["config_sha256"] = lt.build_config(rebuilt).sha256()
    owner["authorization"].write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(lt.LiveGateRefused, match=why):
        gate(owner)
    assert not owner["ledger"].exists()


def test_raising_a_cap_without_a_new_hash_is_refused(owner, live_flag):
    settings = authorization()
    settings["session_cap_usd"] = "0.90"
    owner["authorization"].write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(lt.LiveGateRefused, match="config_sha256"):
        gate(owner)


@pytest.mark.parametrize("bad", ["not json", "[]", "null"])
def test_unreadable_authorization(owner, live_flag, bad):
    owner["authorization"].write_text(bad, encoding="utf-8")
    with pytest.raises(lt.LiveGateRefused):
        gate(owner)


def test_missing_authorization(owner, live_flag):
    owner["authorization"].unlink()
    with pytest.raises(lt.LiveGateRefused, match="authorization file"):
        gate(owner)


@pytest.mark.parametrize("state", [{"commit": COMMIT, "dirty": True}, {"commit": COMMIT, "dirty": None}, {"commit": None, "dirty": None}])
def test_a_dirty_or_unknown_checkout_is_refused(owner, live_flag, state):
    with pytest.raises(lt.LiveGateRefused, match="clean"):
        gate(owner, state=lambda: state)


@pytest.mark.parametrize("content", ["", "not-a-key", "sk-other-abcdefghijklmnopqrstuvwxyz", "sk-ant-short",
                                     "sk-ant-api03-has spaces in it and more text", FAKE_KEY + "\n" + FAKE_KEY, "x" * 2000])
def test_bad_credentials_are_refused_without_being_echoed(owner, live_flag, content):
    owner["credential"].write_text(content, encoding="utf-8")
    with pytest.raises(lt.LiveGateRefused) as err:
        gate(owner)
    assert content.strip() == "" or content not in str(err.value)
    assert not owner["ledger"].exists(), "nothing is created until the credential is good"


def test_a_credential_inside_the_repository_is_refused(owner, live_flag, monkeypatch):
    monkeypatch.setattr(lt, "REPOSITORY", owner["credential"].parent)
    with pytest.raises(lt.LiveGateRefused, match="outside the repository"):
        gate(owner)


def test_missing_credential(owner, live_flag):
    owner["credential"].unlink()
    with pytest.raises(lt.LiveGateRefused, match="credential file"):
        gate(owner)


def test_a_credential_readable_by_others_is_refused(owner, live_flag, monkeypatch):
    if lt.sys.platform == "win32":
        monkeypatch.setattr(lt, "_windows_acl_is_private", lambda path: False)
    else:
        owner["credential"].chmod(0o644)
    with pytest.raises(lt.LiveGateRefused, match="(readable by other|private to your user)"):
        gate(owner)


def test_a_linked_credential_is_refused(owner, live_flag, tmp_path):
    link = tmp_path / "link.key"
    try:
        link.symlink_to(owner["credential"])
    except OSError:
        pytest.skip("this account may not create symbolic links")
    owner["credential"] = link
    with pytest.raises(lt.LiveGateRefused, match="regular file"):
        gate(owner)


def test_a_valid_gate_opens_and_hides_the_key(owner, live_flag):
    session = gate(owner)
    assert session.config.model_id == "claude-haiku-5-5" and session.config.max_model_calls == 30
    assert session.adapter.settings() == (("effort", "low"), ("thinking", "disabled"))
    for shown in (repr(session.transport), str(session.transport._secret), repr(session.transport._secret), f"{session.transport._secret}", repr(session)):
        assert FAKE_KEY not in shown
    with pytest.raises(TypeError):
        import pickle
        pickle.dumps(session.transport._secret)


def test_new_ledger_includes_historical_spending_and_is_live(owner, live_flag):
    session = gate(owner)
    assert session.ledger.mode == sl.MODE_LIVE and session.ledger.state().spent == Decimal("0.106019")
    gate(owner)   # reopening adds nothing
    assert session.ledger.state().spent == Decimal("0.106019")


def test_an_existing_ledger_without_the_balance_is_refused(owner, live_flag):
    sl.SpendLedger(owner["ledger"], mode=sl.MODE_LIVE)
    with pytest.raises(lt.LiveGateRefused, match="opening balance"):
        gate(owner)


def test_a_mock_ledger_cannot_become_a_live_one(owner, live_flag):
    sl.SpendLedger(owner["ledger"], mode=sl.MODE_OFFLINE_MOCK)
    with pytest.raises(sl.LedgerCorrupt):
        gate(owner)


def test_gateway_binds_the_transport_to_the_exact_configuration(owner, live_flag):
    session = gate(owner)
    other = lt.build_config({**lt.PILOT_CANDIDATE, "max_model_calls": 29})
    with pytest.raises(mg.LiveCallsDisabled, match="not authorized"):
        mg.VisionGateway(other, session.adapter, session.transport, session.ledger, session_id="s")
    mock_ledger = sl.SpendLedger(owner["ledger"].with_name("mock.jsonl"), mode=sl.MODE_OFFLINE_MOCK)
    with pytest.raises(mg.LiveCallsDisabled, match="live ledger"):
        mg.VisionGateway(session.config, session.adapter, session.transport, mock_ledger, session_id="s")
    with pytest.raises(ValueError, match="disagree"):
        mg.VisionGateway(session.config, mp.AnthropicMessagesAdapter(effort="low"), session.transport, session.ledger, session_id="s")


# ---------------------------------------------------------------- the human step
class Terminal(io.StringIO):
    def __init__(self, text, tty=True):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


def test_a_person_must_type_the_exact_sentence_at_a_terminal():
    auth = lt.LiveAuthorization(**authorization())
    sentence = "SPEND UP TO 0.50 USD ON claude-haiku-5-5"
    assert live_session.confirmation_sentence(auth) == sentence
    live_session.require_human(auth, stdin=Terminal(sentence + "\n"), stdout=io.StringIO())
    for typed in ("yes\n", sentence.lower() + "\n", "\n", ""):
        with pytest.raises(lt.LiveGateRefused, match="not confirmed"):
            live_session.require_human(auth, stdin=Terminal(typed), stdout=io.StringIO())
    with pytest.raises(lt.LiveGateRefused, match="real terminal"):
        live_session.require_human(auth, stdin=Terminal(sentence + "\n", tty=False), stdout=io.StringIO())


def test_template_approves_nothing_and_is_refused_until_filled_in(owner, live_flag, capsys):
    assert live_session.main(["template"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["approved_by"] == "OWNER_NAME" and printed["model_id"] == "claude-haiku-5-5"
    assert (printed["max_episodes"], printed["max_model_calls"], printed["session_cap_usd"], printed["cumulative_cap_usd"]) == (1, 30, "0.50", "1.00")
    assert printed["opening_balance_usd"] == "0.106019" and printed["thinking"] == "disabled" and printed["effort"] == "low"
    owner["authorization"].write_text(json.dumps(printed), encoding="utf-8")
    with pytest.raises(lt.LiveGateRefused, match="filled in"):
        gate(owner)


# ---------------------------------------------------------------- whole request/response flow
def png(tag):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (mg.PNG_SIGNATURE + chunk(b"IHDR", struct.pack(">IIBBBBB", 1280, 720, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(tag.to_bytes(4, "big"))) + chunk(b"IEND", b""))


class Game:
    def __init__(self):
        self.seq = 0
        self.frame = 0

    def observation(self, frames=0):
        self.seq += 1
        self.frame += frames
        return contract.observation(seq=self.seq, episode=1, episode_frame=self.frame, episode_frame_budget=8000, max_episodes=1,
                                    frames_advanced=frames, episode_ended=False, session_over=False,
                                    image=contract.image_payload(png(self.seq), 1280, 720), version=contract.V2)


def build(owner, server, sink=None, **kwargs):
    session = gate(owner, connection=server.connection, **kwargs)
    records = [] if sink is None else sink
    gateway = mg.VisionGateway(session.config, session.adapter, session.transport, session.ledger, session_id="s",
                               sink=records.append, sleep=lambda seconds: None)
    game = Game()
    gateway.record_game(game.observation())
    return session, gateway, game, records


def play(gateway, game, reply):
    for call in reply["tool_calls"]:
        request = {"tool": call["name"], **call["arguments"]}
        tool, act = contract.parse_request(request, contract.V2)
        gateway.authorize_game(tool, act)
        gateway.record_game(game.observation(call["arguments"].get("frames", 0)))


def test_request_on_the_wire_is_exactly_the_documented_shape(owner, api, live_flag):
    server = api([(200, {}, message([{"type": "text", "text": "Trying."}, tool_use()]))])
    _, gateway, _, _ = build(owner, server)
    reply = gateway.turn()
    assert reply["tool_calls"][0]["arguments"] == {"keys": ["ArrowUp"], "frames": 30}
    (sent,) = server.requests
    assert sent["path"] == "/v1/messages"
    headers = sent["headers"]
    assert headers["authorization"] == f"Bearer {FAKE_KEY}" and headers["anthropic-version"] == "2023-06-01"
    assert headers["content-type"] == "application/json"
    assert "x-api-key" not in headers and "anthropic-beta" not in headers and "anthropic-workspace-id" not in headers
    body = sent["body"]
    assert set(body) == {"model", "max_tokens", "system", "tools", "tool_choice", "messages", "output_config", "thinking"}
    assert body["model"] == "claude-haiku-5-5" and body["max_tokens"] == 2048 and body["system"] == "Land the rocket."
    assert body["thinking"] == {"type": "disabled"} and body["output_config"] == {"effort": "low"} and body["tool_choice"] == {"type": "auto"}
    assert FAKE_KEY not in json.dumps(body)
    assert [t["name"] for t in body["tools"]] == ["observe", "act"]
    assert body["tools"][1]["input_schema"]["properties"]["keys"]["items"]["enum"] == list(contract.V2.keys)
    assert "KeyS" not in json.dumps(body["tools"])


def test_screenshot_bytes_arrive_intact_as_documented_image_blocks(owner, api, live_flag):
    import base64
    server = api([(200, {}, message([tool_use("a")])), (200, {}, message([tool_use("b")]))])
    _, gateway, game, _ = build(owner, server)
    play(gateway, game, gateway.turn())
    gateway.turn()
    opening, assistant, results = server.requests[1]["body"]["messages"]
    block = opening["content"][1]
    assert opening["content"][0] == {"type": "text", "text": "Land the rocket."}
    assert block["type"] == "image" and block["source"]["type"] == "base64" and block["source"]["media_type"] == "image/png"
    assert base64.b64decode(block["source"]["data"]) == png(1)
    assert assistant["content"] == [{"type": "tool_use", "id": "a", "name": "act", "input": {"keys": ["ArrowUp"], "frames": 30}}]
    result = results["content"][0]
    assert (result["type"], result["tool_use_id"], result["is_error"]) == ("tool_result", "a", False)
    assert base64.b64decode(result["content"][1]["source"]["data"]) == png(2)
    assert set(json.loads(result["content"][0]["text"])) == set(mg.TOOL_RESULT_COUNTERS)


def test_every_request_follows_the_documented_conversation_rules(owner, api, live_flag):
    """Starts with user, alternates, ends with user (no prefill), tool results first in their turn, every tool_use answered, at most
    4 images, no empty text. Includes the awkward replies: no tool, whitespace only, bad tool, oversized batch."""
    script = [(200, {}, message([tool_use("a")])),
              (200, {}, message([{"type": "text", "text": "  \n"}], "end_turn")),
              (200, {}, message([{"type": "tool_use", "id": "h", "name": "read file!", "input": {}}])),
              (200, {}, message([], "end_turn")),
              (200, {}, message([tool_use(f"b{i}", frames=5) for i in range(10)])),
              (200, {}, message([{"type": "text", "text": "next"}, tool_use("c")]))]
    server = api(script)
    _, gateway, game, _ = build(owner, server)
    for _ in range(6):
        play(gateway, game, gateway.turn())
    gateway.turn()
    assert len(server.requests) == 7

    def images(messages):
        count = 0
        for m in messages:
            for block in m["content"]:
                count += block["type"] == "image"
                if block["type"] == "tool_result":
                    count += sum(sub["type"] == "image" for sub in block["content"])
        return count

    for sent in server.requests:
        messages = sent["body"]["messages"]
        roles = [m["role"] for m in messages]
        assert roles[0] == "user" and roles[-1] == "user"
        assert all(a != b for a, b in zip(roles, roles[1:])), roles
        assert images(messages) <= 4
        for i, m in enumerate(messages):
            assert m["content"], "no empty turn"
            kinds = [b["type"] for b in m["content"]]
            if "tool_result" in kinds:
                assert kinds == sorted(kinds, key=lambda k: k != "tool_result"), "tool results come first"
            for block in m["content"]:
                if block["type"] == "text":
                    assert block["text"].strip()
                if block["type"] == "tool_use":
                    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", block["name"]) and isinstance(block["input"], dict)
            if m["role"] == "assistant":
                wanted = [b["id"] for b in m["content"] if b["type"] == "tool_use"]
                if wanted:
                    answered = [b["tool_use_id"] for b in messages[i + 1]["content"] if b["type"] == "tool_result"]
                    assert answered == wanted, "every call answered, immediately, in order"


def test_usage_accounting_is_exact_and_recorded(owner, api, live_flag):
    usage = {"input_tokens": 1500, "output_tokens": 400, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
             "output_tokens_details": {"thinking_tokens": 0}}
    server = api([(200, {"request-id": "req_abc"}, message([tool_use()], usage=usage))])
    session, gateway, _, records = build(owner, server)
    gateway.turn()
    (call,) = [r for r in records if r["event"] == "model_call"]
    expected = Decimal("0.00015") + Decimal("0.0002")   # 1,500 x $0.10 + 400 x $0.50, per million tokens
    assert Decimal(call["outcome"]["charged_usd"]) == expected
    assert call["outcome"]["usage"]["input_tokens"] == 1500 and call["outcome"]["thinking_tokens"] == 0
    assert call["outcome"]["request_id"] == "req_abc" and call["outcome"]["provider_model"] == "claude-haiku-5-5"
    assert session.ledger.state().spent == Decimal("0.106019") + expected
    assert Decimal(call["worst_case_usd"]) >= expected


def test_real_screenshot_token_cost_is_inside_the_estimate():
    assert (1280 + 27) // 28 * ((720 + 27) // 28) == 1196   # documented: ceil(w/28) x ceil(h/28) visual tokens
    assert mg.GatewayConfig.image_tokens_upper_bound >= 1196


def test_pilot_worst_case_cannot_reach_the_session_cap_inside_the_call_limit():
    config = lt.build_config(lt.PILOT_CANDIDATE)
    one_call = config.pricing.cost(mp.Usage(config.max_context_tokens, config.max_output_tokens))
    assert one_call <= Decimal("0.0101")
    assert one_call * config.max_model_calls < Decimal("0.50") and config.max_context_tokens < 100000


def test_the_price_threshold_is_the_documented_one():
    config = lt.build_config(lt.PILOT_CANDIDATE)
    assert config.pricing.cost(mp.Usage(1_000_000, 0)) > 0 and config.pricing.threshold_input_tokens == 100000
    assert config.pricing.cost(mp.Usage(100000, 1_000_000)) == Decimal("0.51")
    assert config.pricing.cost(mp.Usage(100001, 1_000_000)) == Decimal("2.5500005")


# ---------------------------------------------------------------- thinking and output limits
def test_thinking_is_requested_off_and_a_returned_block_is_still_never_replayed(owner, api, live_flag):
    thinking = {"type": "thinking", "thinking": "SECRET-REASONING", "signature": "SIG"}
    usage = {"input_tokens": 100, "output_tokens": 900, "output_tokens_details": {"thinking_tokens": 850}}
    server = api([(200, {}, message([thinking, {"type": "redacted_thinking", "data": "X"}, tool_use("a")], usage=usage)),
                  (200, {}, message([tool_use("b")]))])
    _, gateway, game, records = build(owner, server)
    play(gateway, game, gateway.turn())
    gateway.turn()
    assert server.requests[0]["body"]["thinking"] == {"type": "disabled"}
    text = json.dumps(server.requests[1]["body"])
    assert "SECRET-REASONING" not in text and "SIG" not in text and '"redacted_thinking"' not in text
    first = [r for r in records if r["event"] == "model_call"][0]["outcome"]
    assert first["thinking_tokens"] == 850 and first["discarded_blocks"] == ["thinking", "redacted_thinking"]
    assert "SECRET-REASONING" not in json.dumps(records)


def test_reply_cut_off_at_the_output_limit_is_charged_and_not_executed(owner, api, live_flag):
    usage = {"input_tokens": 100, "output_tokens": 2048}
    server = api([(200, {}, message([tool_use("a")], "max_tokens", usage=usage))])
    session, gateway, _, records = build(owner, server)
    assert gateway.turn()["tool_calls"] == []
    assert session.ledger.state().spent == Decimal("0.106019") + Decimal("0.001034")
    assert any("cut off" in r.get("reason", "") for r in records)


def test_reply_spent_entirely_on_thinking_counts_as_no_valid_call(owner, api, live_flag):
    server = api([(200, {}, message([{"type": "thinking", "thinking": "", "signature": "s"}], "max_tokens", usage={"input_tokens": 10, "output_tokens": 2048}))])
    _, gateway, _, _ = build(owner, server)
    assert gateway.turn()["tool_calls"] == [] and gateway.counts["invalid_replies"] == 1


@pytest.mark.parametrize("stop", ["model_context_window_exceeded", "pause_turn", "something_new"])
def test_unexpected_stop_reasons_are_never_executed(owner, api, live_flag, stop):
    server = api([(200, {}, message([tool_use("a")], stop))])
    _, gateway, _, records = build(owner, server)
    assert gateway.turn()["tool_calls"] == []
    assert any("stopped early" in r.get("reason", "") for r in records)


def test_more_output_than_requested_ends_the_session(owner, api, live_flag):
    server = api([(200, {}, message([tool_use("a")], usage={"input_tokens": 1, "output_tokens": 2049}))])
    _, gateway, _, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "output_limit_violated"


def test_refusal_is_charged_and_ends_the_session(owner, api, live_flag):
    server = api([(200, {}, message([], "refusal", stop_details={"type": "refusal", "category": "general_harms"}))])
    session, gateway, _, records = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "provider_refusal" and session.ledger.state().spent > Decimal("0.106019")
    assert [r for r in records if r["event"] == "model_call"][0]["outcome"]["refusal_category"] == "general_harms"


def test_a_different_model_answering_ends_the_session(owner, api, live_flag):
    server = api([(200, {}, message([tool_use()], model="claude-opus-5-5"))])
    _, gateway, _, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "model_mismatch"


# ---------------------------------------------------------------- errors
def api_error(kind, text, **details):
    return {"type": "error", "error": {"type": kind, "message": text, **({"details": details} if details else {})}, "request_id": "req_e"}


@pytest.mark.parametrize("status,kind", [(401, "authentication_error"), (402, "billing_error"), (403, "permission_error"),
                                         (404, "not_found_error"), (413, "request_too_large"), (400, "invalid_request_error")])
def test_authentication_and_request_failures_stop_at_once_with_no_charge_or_retry(owner, api, live_flag, status, kind):
    server = api([(status, {}, api_error(kind, "refused")), (200, {}, message([tool_use()]))])
    session, gateway, _, records = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == f"provider_rejected_{status}" and len(server.requests) == 1
    assert session.ledger.state().spent == Decimal("0.106019") and session.ledger.state().open_reservations == {}
    assert FAKE_KEY not in json.dumps(records)


def test_an_error_body_quoting_the_key_is_redacted(owner, api, live_flag):
    server = api([(401, {}, api_error("authentication_error", f"bad key {FAKE_KEY}"))])
    _, gateway, _, records = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert FAKE_KEY not in json.dumps(records) and FAKE_KEY not in json.dumps(gateway.manifest())


def test_own_spend_limit_stops_the_session(owner, api, live_flag):
    server = api([(400, {}, api_error("invalid_request_error", "You have reached your specified API usage limits."))])
    _, gateway, _, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "provider_rejected_400" and len(server.requests) == 1


def test_tier_spend_cap_is_not_retried(owner, api, live_flag):
    body = api_error("rate_limit_error", "You have reached your API usage limits", error_code="enforced_spend_limit_reached")
    server = api([(429, {}, body), (200, {}, message([tool_use()]))])
    session, gateway, _, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "provider_spend_cap" and len(server.requests) == 1
    assert session.ledger.state().open_reservations == {}


def test_rate_limit_honours_retry_after_with_no_charge(owner, api, live_flag):
    waits = []
    server = api([(429, {"retry-after": "7"}, api_error("rate_limit_error", "slow")), (200, {}, message([tool_use()]))])
    session = gate(owner, connection=server.connection)
    gateway = mg.VisionGateway(session.config, session.adapter, session.transport, session.ledger, session_id="s", sleep=waits.append)
    gateway.record_game(Game().observation())
    assert gateway.turn()["tool_calls"]
    assert waits == [7.0] and gateway.counts["model_calls"] == 2


@pytest.mark.parametrize("status", [500, 504, 529])
def test_server_errors_stay_charged_at_worst_case(owner, api, live_flag, status):
    server = api([(status, {}, api_error("api_error", "boom")), (200, {}, message([tool_use()]))])
    session, gateway, _, records = build(owner, server)
    gateway.turn()
    first = [r for r in records if r["event"] == "model_call"][0]
    assert first["outcome"]["charged_usd"] == first["worst_case_usd"]
    assert first["outcome"]["kind"] == "server_error"


def test_a_redirect_is_never_followed(owner, api, live_flag):
    server = api([(302, {"location": "https://elsewhere.example/steal"}, b"")])
    _, gateway, _, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "provider_rejected_302" and len(server.requests) == 1


@pytest.mark.parametrize("payload", [b"<html>bad gateway</html>", b"", b"\xff\xfe", b"[]", b'{"type":"message"}'])
def test_a_malformed_200_is_charged_and_never_interpreted(owner, api, live_flag, payload):
    server = api([(200, {}, payload), (200, {}, message([tool_use()]))])
    _, gateway, game, records = build(owner, server)
    gateway.turn()
    first = [r for r in records if r["event"] == "model_call"][0]
    assert first["outcome"]["kind"] == "malformed_reply" and first["outcome"]["charged_usd"] == first["worst_case_usd"]


def test_an_oversized_response_is_treated_as_malformed(owner, api, live_flag, monkeypatch):
    monkeypatch.setattr(lt, "MAX_RESPONSE_BYTES", 1000)
    server = api([(200, {}, json.dumps(message([{"type": "text", "text": "x" * 5000}])).encode()), (200, {}, message([tool_use()]))])
    _, gateway, _, records = build(owner, server)
    gateway.turn()
    assert [r for r in records if r["event"] == "model_call"][0]["outcome"]["kind"] == "malformed_reply"


def test_a_real_socket_timeout_is_charged_and_bounded(owner, api, live_flag, monkeypatch):
    release = threading.Event()

    def hang():
        release.wait(20)
        return 200, {}, message([tool_use()])

    server = api([hang])
    session = gate(owner, connection=lambda timeout: server.connection(0.2))
    config = session.config
    gateway = mg.VisionGateway(config, session.adapter, session.transport, session.ledger, session_id="s", sleep=lambda s: None)
    gateway.record_game(Game().observation())
    started = time.monotonic()
    server.script.extend([(200, {}, message([tool_use()]))])
    reply = gateway.turn()
    release.set()
    assert time.monotonic() - started < 15 and reply["tool_calls"]
    assert gateway.counts["provider_errors"] == 1 and session.ledger.state().open_reservations == {}


def test_connection_refused_is_retried_then_stops_with_no_secret_logged(owner, live_flag):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    session = gate(owner, connection=lambda timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout))
    records = []
    gateway = mg.VisionGateway(session.config, session.adapter, session.transport, session.ledger, session_id="s",
                               sink=records.append, sleep=lambda s: None)
    gateway.record_game(Game().observation())
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "consecutive_provider_errors"
    assert FAKE_KEY not in json.dumps(records) and session.ledger.state().open_reservations == {}


# ---------------------------------------------------------------- budget
def test_budget_exhaustion_stops_before_any_http_request(owner, api, live_flag):
    settings = authorization(session_cap_usd="0.0001", cumulative_cap_usd="1.00")
    settings["config_sha256"] = lt.build_config({k: settings[k] for k in lt.PILOT_CANDIDATE}).sha256()
    owner["authorization"].write_text(json.dumps(settings), encoding="utf-8")
    server = api()
    session, gateway, _, records = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "budget_exhausted_session" and server.requests == [] and session.transport.requests_sent == 0
    assert records[-2]["outcome"]["kind"] == "refused_before_call"


def test_historical_spending_counts_toward_the_cumulative_cap(owner, api, live_flag):
    settings = authorization(session_cap_usd="0.1065", cumulative_cap_usd="0.1065")   # $0.106019 is already spent
    settings["config_sha256"] = lt.build_config({k: settings[k] for k in lt.PILOT_CANDIDATE}).sha256()
    owner["authorization"].write_text(json.dumps(settings), encoding="utf-8")
    server = api()
    _, gateway, _, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "budget_exhausted_cumulative" and server.requests == []


def test_session_runs_until_budget_and_never_overspends(owner, api, live_flag):
    settings = authorization(session_cap_usd="0.008", cumulative_cap_usd="1.00")
    settings["config_sha256"] = lt.build_config({k: settings[k] for k in lt.PILOT_CANDIDATE}).sha256()
    owner["authorization"].write_text(json.dumps(settings), encoding="utf-8")
    counter = iter(range(1000))
    server = api([lambda: (200, {}, message([tool_use(f"c{next(counter)}")], usage={"input_tokens": 6000, "output_tokens": 500})) for _ in range(40)])
    session, gateway, game, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        for _ in range(40):
            play(gateway, game, gateway.turn())
    assert gateway.stop_reason == "budget_exhausted_session"
    state = session.ledger.state()
    assert state.session_total["s"] <= Decimal("0.008") and state.open_reservations == {} and len(server.requests) > 2


def test_transport_has_its_own_call_limit_and_field_checks(owner, api, live_flag):
    server = api()
    session = gate(owner, connection=server.connection)
    base = {"model": "claude-haiku-5-5", "max_tokens": 1, "messages": []}
    for bad in ({**base, "fallbacks": "default"}, {**base, "betas": ["x"]}, {**base, "tools": [], "stream": True}, {**base, "metadata": {}}):
        with pytest.raises(mg.LiveCallsDisabled, match="unexpected"):
            session.transport.send(bad, 1.0)
    with pytest.raises(mg.LiveCallsDisabled, match="not authorized"):
        session.transport.send({**base, "model": "claude-fable-5-1"}, 1.0)
    assert server.requests == []
    session.transport.requests_sent = 30
    with pytest.raises(mg.LiveCallsDisabled, match="number of model calls"):
        session.transport.send(base, 1.0)
    assert server.requests == []


def test_the_transcript_chain_and_ledger_agree_after_a_live_shaped_session(owner, api, live_flag):
    server = api([(200, {}, message([tool_use(f"c{i}")])) for i in range(5)])
    session, gateway, game, records = build(owner, server)
    for _ in range(5):
        play(gateway, game, gateway.turn())
    check = mg.verify_transcript(records)
    assert check["valid"]
    assert session.ledger.state().spent - Decimal("0.106019") == Decimal(check["charged_usd"])
    assert hashlib.sha256(FAKE_KEY.encode()).hexdigest() not in json.dumps(records) and FAKE_KEY not in json.dumps(records)
    assert gateway.manifest()["is_model"] is True and gateway.manifest()["transport_offline"] is False
