"""The complete live path with only the far end replaced: real sandbox, real referee, real game, real screenshots, real HTTP, and a
mock API on the loopback interface. **No request can leave this machine, and the key is fake.**

Skipped where isolation or the browser is unavailable, unless REACT_REQUIRE_ISOLATION=1 (Windows and macOS CI set it).
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import socket
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from rewardbench.blindplay import isolation, live_session, live_transport as lt, model_gateway as mg, replay

FAKE_KEY = "sk-ant-api03-FAKEFAKEFAKEFAKEFAKEFAKE-not-a-real-key"
COMMIT = "c" * 40


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


class MockApi:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append({"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                status, payload = outer.replies.pop(0) if outer.replies else (401, {"type": "error", "error": {"type": "authentication_error", "message": "end of script"}})
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("request-id", f"req_{len(outer.requests)}")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def connection(self, timeout):
        return http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=timeout)


def reply(call_id, keys, frames, text=""):
    content = ([{"type": "text", "text": text}] if text else []) + [{"type": "tool_use", "id": call_id, "name": "act", "input": {"keys": keys, "frames": frames}}]
    return 200, {"type": "message", "id": "msg", "role": "assistant", "model": "claude-haiku-5-5", "content": content, "stop_reason": "tool_use",
                 "usage": {"input_tokens": 1500, "output_tokens": 60}}


def test_complete_live_path_with_a_mock_api(tmp_path, monkeypatch):
    real_create = socket.create_connection

    def loopback_only(address, *args, **kwargs):
        assert address[0] == "127.0.0.1", f"tried to reach {address}"
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", loopback_only)
    monkeypatch.setattr(mg, "LIVE_CALLS_PERMITTED", True)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    now = datetime.now(timezone.utc)
    settings = dict(lt.PILOT_CANDIDATE, max_model_calls=6)
    auth = {"schema": lt.AUTHORIZATION_SCHEMA, "approved_by": "pytest", "approved_utc": (now - timedelta(minutes=1)).isoformat(),
            "expires_utc": (now + timedelta(hours=1)).isoformat(), "pricing_verified_utc": now.isoformat(), "git_commit": COMMIT,
            "config_sha256": lt.build_config(settings).sha256(), **settings}
    (tmp_path / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    credential = tmp_path / "anthropic.key"
    credential.write_text(FAKE_KEY, encoding="utf-8")
    credential.chmod(0o600)
    api = MockApi([reply("a", ["ArrowUp"], 60, "Trying the first key."), reply("b", ["ArrowLeft", "Space"], 45),
                   reply("s", ["KeyS"], 120), reply("c", [], 120), reply("d", [], 120), reply("e", [], 120)])
    session = lt.open_gate(authorization_path=tmp_path / "auth.json", credential_path=credential, ledger_path=tmp_path / "ledger.jsonl",
                           connection_factory=api.connection, state=lambda: {"commit": COMMIT, "dirty": False})
    report = live_session.run_session(session, out=tmp_path / "session", ledger_path=tmp_path / "ledger.jsonl",
                                      player_label="pytest mock API (NOT A MODEL)")
    out = tmp_path / "session"
    assert report["host_status"] == "closed" and report["gateway"]["stop_reason"] == "model_call_limit"
    assert report["audit"]["transcript"]["valid"] and report["audit"]["ledger_open_reservations"] == []
    assert report["audit"]["max_images_in_a_call"] <= 4 and report["audit"]["privileged_words_sent"] == []
    referee = [json.loads(x) for x in (out / "referee/player_transcript.jsonl").read_text(encoding="utf-8").splitlines()]
    acts = [(e["request"]["keys"], e["request"]["frames"]) for e in referee if e["request"]["tool"] == "act"]
    assert acts == [(["ArrowUp"], 60), (["ArrowLeft", "Space"], 45), ([], 120), ([], 120), ([], 120)], "the speed key never reached the game"
    assert len(api.requests) == 6
    assert all(r["headers"]["authorization"] == f"Bearer {FAKE_KEY}" for r in api.requests)
    last = api.requests[-1]["body"]
    assert last["thinking"] == {"type": "disabled"} and last["output_config"] == {"effort": "low"}
    shown = [e["response"]["image"]["sha256"] for e in referee if "image" in e["response"]]
    import hashlib
    sent = []
    for message in last["messages"]:
        for block in message["content"]:
            inner = block["content"] if block["type"] == "tool_result" else [block]
            sent += [hashlib.sha256(base64.b64decode(b["source"]["data"])).hexdigest() for b in inner if b["type"] == "image"]
    # the sixth reply's action ran after the last request went out, so that request carries the four screenshots before it
    assert sent == shown[-5:-1], "the most recent four real screenshots reached the HTTP request, byte for byte"
    for path in out.rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".log"):
            assert FAKE_KEY not in path.read_text(encoding="utf-8", errors="replace"), path
    assert FAKE_KEY not in (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    state = session.ledger.state()
    assert state.spent == Decimal("0.106019") + 6 * (Decimal("0.00015") + Decimal("0.00003"))
    assert replay.replay(out / "referee")["reproduced"]
    assert json.loads((out / "referee/session.json").read_text(encoding="utf-8"))["player"]["is_ai"] is True


def test_sandbox_cannot_read_the_credential_authorization_or_live_ledger(tmp_path):
    """The real flag is off here on purpose: a stand-in attacks the owner's files through the existing gateway-probe mode, offline."""
    from rewardbench.blindplay import host as host_mod, model_providers as mp, spend_ledger as sl

    secret = tmp_path / "anthropic.key"
    secret.write_text(FAKE_KEY, encoding="utf-8")
    (tmp_path / "auth.json").write_text("{}", encoding="utf-8")
    targets = {"read": [str(secret), str(tmp_path / "auth.json"), str(Path(lt.__file__))], "list": [str(tmp_path)]}
    config = mg.GatewayConfig(provider_id="offline-mock", model_id="mock-vision-0", pricing=mg.ModelPricing("0.10", "0.50", source="test"),
                              session_cap_usd="0.05", cumulative_cap_usd="0.05", max_episodes=1, episode_frame_budget=1000, max_wall_seconds=300.0)
    provider = mp.MockVisionProvider([{"tool_calls": [{"id": "real", "name": "act", "arguments": {"keys": ["ArrowUp"], "frames": 20}}]}],
                                     default=lambda wire: {"text": "done"})
    gateway = mg.VisionGateway(config, mp.MockAdapter(), mp.OfflineTransport(provider), sl.SpendLedger(tmp_path / "mock.jsonl", mode=sl.MODE_OFFLINE_MOCK),
                               session_id="attack", sleep=lambda s: None)
    out = tmp_path / "session"
    manifest = host_mod.Host(host_mod.HostConfig(out=out, mode="gateway-probe", keyset="keyset.v2", max_episodes=1, episode_frame_budget=1000,
                                                 max_wall_seconds=300.0, max_requests=1000, probe_targets=targets,
                                                 player_label="pytest stand-in (NOT AI)"), gateway=gateway).run()
    assert manifest["status"] == "closed"
    lines = [json.loads(x)["line"] for x in (out / "player_stderr.jsonl").read_text(encoding="utf-8").splitlines()]
    reads = [r for r in lines if isinstance(r, dict) and r.get("probe") in ("read_file", "list_dir")]
    assert len(reads) == 4 and all(r["outcome"] == "denied" and "PermissionError" in r["detail"] for r in reads), reads
    assert FAKE_KEY not in (out / "player_stderr.jsonl").read_text(encoding="utf-8")
