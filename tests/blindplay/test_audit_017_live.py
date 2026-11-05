"""Mission 017 audit of the live gate, transport, gateway and ledger. Adversarial tests; no request leaves this machine.

Reuses the loopback mock server and helpers of test_live_transport.py (loaded by path, because tests are not a package).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from rewardbench.blindplay import (live_transport as lt, model_gateway as mg, model_providers as mp, spend_ledger as sl)

_spec = importlib.util.spec_from_file_location("_audit_017_helpers", Path(__file__).with_name("test_live_transport.py"))
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)
# fixtures must live in this module's namespace for pytest to find them
loopback_only, api, owner, live_flag = H.loopback_only, H.api, H.owner, H.live_flag
message, tool_use, Game, gate, build, play, api_error = H.message, H.tool_use, H.Game, H.gate, H.build, H.play, H.api_error
authorization, NOW = H.authorization, H.NOW


# ------------------------------------------------------------ (1) credential file access control
@pytest.mark.parametrize("sddl", [
    "",                                        # nothing parsed at all
    "garbage",
    "D:NO_ACCESS_CONTROL",                     # NULL DACL: everyone has full access
    "O:BAG:SYD:NO_ACCESS_CONTROL",
    "key.txt\nD:NO_ACCESS_CONTROL\n",
    "O:BAG:SY",                                # no DACL present: also means no access control
])
def test_null_or_missing_dacl_is_not_private(sddl):
    assert lt._sddl_is_private(sddl) is False


@pytest.mark.parametrize("sddl", [
    "D:PAI(A;;FR;;;AN)",                       # anonymous logon
    "D:PAI(A;;FR;;;BG)",                       # builtin guests
    "D:PAI(A;;FR;;;S-1-5-7)",
    "D:PAI(A;;FR;;;S-1-5-32-546)",             # guests, numeric
    "D:PAI(A;;FR;;;DU)",                       # domain users
    "D:PAI(A;;FR;;;S-1-5-21-1-2-3-513)",       # domain/local users group by RID
    "D:PAI(A;;FR;;;S-1-5-21-1-2-3-514)",       # domain guests
    "D:PAI(A;;FR;;;S-1-5-21-1-2-3-515)",
    "D:PAI(A;;FR;;;S-1-15-3-1024-1-2-3-4-5-6-7-8)",   # capability SIDs (app capabilities)
    "D:PAI(A;;FR;;;s-1-1-0)",                  # lower case numeric
    "D:PAI(A;;FR;;;RC)",                       # restricted code
    "D:PAI(A;;FR;;;PU)",                       # power users
    "D:PAI(A;;FR;;;LG)",                       # local guest
    "D:PAI(A;;FR;;;S-1-5-32-545)",
])
def test_more_broad_trustees_are_not_private(sddl):
    assert lt._sddl_is_private(sddl) is False


@pytest.mark.parametrize("sddl", [
    "D:PAI(OA;;FR;00000000-0000-0000-0000-000000000000;;WD)",     # object ACE
    "D:PAI(XA;;FR;;;WD;(@User.Title==\"x\"))",                     # conditional ACE
    "D:PAI(A;;FR;;;WD;(@User.Title==\"x\"))",
    "D:PAI(A;OICIID;FR;;;WD)",                                     # inherited
    "D:PAI(D;;FR;;;S-1-5-21-1-2-3-1001)(A;;FR;;;WD)",              # deny for someone else first, allow Everyone after
    "D:AI(A;;FR;;;WD)S:AI(ML;;NW;;;LW)",                           # trailing SACL section
    "D:PAI(A;;FR;;;WD)(A;;FA;;;SY)S:(AU;SA;FA;;;WD)",
])
def test_broad_allow_in_any_ace_shape_is_not_private(sddl):
    assert lt._sddl_is_private(sddl) is False


@pytest.mark.parametrize("sddl", [
    "D:PAI(A;;FA;;;SY)(A;;FA;;;BA)(A;;FA;;;S-1-5-21-1-2-3-1001)",
    "D:P",                                                         # empty DACL: nobody has access
    "D:PAI(D;;FR;;;WD)(A;;FA;;;SY)S:(AU;SA;FA;;;WD)",              # a SACL audit entry naming Everyone grants nothing
    "D:\\keys\\x.key\nD:PAI(A;;FA;;;SY)",                           # path text that contains a drive-like "D:"
])
def test_private_shapes_stay_private(sddl):
    assert lt._sddl_is_private(sddl) is True


@pytest.mark.skipif(lt.sys.platform != "win32", reason="Windows ACLs")
def test_a_real_file_with_a_null_dacl_is_refused(tmp_path):
    """Set a real NULL DACL (everyone has access) with the Win32 API and ask the real check."""
    import ctypes
    f = tmp_path / "null.key"
    f.write_text("x")
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    SE_FILE_OBJECT, DACL_SECURITY_INFORMATION = 1, 4
    advapi.SetNamedSecurityInfoW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p,
                                             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    code = advapi.SetNamedSecurityInfoW(str(f), SE_FILE_OBJECT, DACL_SECURITY_INFORMATION | 0x80000000, None, None, None, None)
    if code != 0:
        pytest.skip(f"could not install a NULL DACL ({code})")
    assert lt._windows_acl_is_private(f) is False


# ------------------------------------------------------------ (2) authorization integrity
def test_prices_verified_in_the_future_are_refused(owner, live_flag):
    settings = authorization(pricing_verified_utc=(NOW + timedelta(days=30)).isoformat())
    owner["authorization"].write_text(json.dumps(settings), encoding="utf-8")
    with pytest.raises(lt.LiveGateRefused, match="future|checked"):
        gate(owner)


def test_a_failing_git_status_is_not_a_clean_checkout(monkeypatch):
    def run(cmd, **kwargs):
        if cmd[:2] == ["git", "rev-parse"]:
            return subprocess.CompletedProcess(cmd, 0, "a" * 40 + "\n", "")
        return subprocess.CompletedProcess(cmd, 128, "", "fatal: detected dubious ownership")
    monkeypatch.setattr(lt.subprocess, "run", run)
    assert lt.git_state()["dirty"] is not False


# ------------------------------------------------------------ (3)/(10) model mismatch, refusals: covered elsewhere
def test_model_mismatch_still_charges_and_executes_nothing(owner, api, live_flag):
    server = api([(200, {}, message([tool_use()], model="claude-opus-5-5", usage={"input_tokens": 9000, "output_tokens": 70}))])
    session, gateway, game, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert gateway.stop_reason == "model_mismatch"
    assert session.ledger.state().spent > Decimal("0.106019") and session.ledger.state().open_reservations == {}
    with pytest.raises(mg.GatewayRejected):
        gateway.authorize_game("act", None)


# ------------------------------------------------------------ (4) accounting
def test_documented_pilot_prices_and_overheads_are_inside_the_reservation():
    config = lt.build_config(lt.PILOT_CANDIDATE)
    p = config.pricing
    assert (p.input_per_mtok, p.output_per_mtok) == (Decimal("0.1"), Decimal("0.5"))
    assert (p.over_threshold_input_per_mtok, p.over_threshold_output_per_mtok) == (Decimal("0.5"), Decimal("2.5"))
    assert config.image_tokens_upper_bound >= 1196 + 0     # documented tokens per 1280x720 image
    gateway_estimate = 256 + 4 * config.image_tokens_upper_bound
    assert gateway_estimate >= 286 + 4 * 1196              # tool overhead plus four images, with no text at all


@pytest.mark.parametrize("usage", [{"input_tokens": 0, "output_tokens": 0}, {"input_tokens": 0, "output_tokens": 5}])
def test_a_reply_claiming_zero_input_tokens_cannot_be_free(owner, api, live_flag, usage):
    """A request carrying a screenshot always has input tokens; a zero count is untrustworthy and must not lower the charge."""
    server = api([(200, {}, message([tool_use()], usage=usage))])
    session, gateway, _, records = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    (call,) = [r for r in records if r["event"] == "model_call"]
    assert Decimal(call["outcome"]["charged_usd"]) == Decimal(call["worst_case_usd"])


def test_price_above_the_threshold_is_charged_at_the_higher_rate_for_the_whole_call(owner, api, live_flag):
    server = api([(200, {}, message([tool_use()], usage={"input_tokens": 100001, "output_tokens": 1000}))])
    session, gateway, _, records = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    (call,) = [r for r in records if r["event"] == "model_call"]
    assert Decimal(call["outcome"]["charged_usd"]) == Decimal("0.0525005")
    assert gateway.stop_reason == "context_limit_exceeded_by_provider_count"


# ------------------------------------------------------------ (5) ledger opening balance
def test_a_ledger_with_spending_but_no_opening_balance_record_is_refused(owner, live_flag):
    """Spent money of its own must not be mistaken for the historical balance."""
    ledger = sl.SpendLedger(owner["ledger"], mode=sl.MODE_LIVE)
    rid = ledger.reserve(session="old", call=1, worst_case="0.2", session_cap="1", cumulative_cap="1")
    ledger.settle(rid, charged="0.2", basis="test")
    with pytest.raises(lt.LiveGateRefused, match="opening balance"):
        gate(owner)


def test_cumulative_spend_is_shared_by_sessions_of_different_providers(tmp_path):
    ledger = sl.SpendLedger(tmp_path / "l.jsonl", mode=sl.MODE_LIVE)
    ledger.record_opening_balance("0.106019", "earlier")
    ledger.reserve(session="anthropic-1", call=1, worst_case="0.4", session_cap="0.5", cumulative_cap="1")
    ledger.reserve(session="other-provider-1", call=1, worst_case="0.4", session_cap="0.5", cumulative_cap="1")
    with pytest.raises(sl.BudgetExceeded) as err:
        ledger.reserve(session="third", call=1, worst_case="0.2", session_cap="0.5", cumulative_cap="1")
    assert err.value.scope == "cumulative"


# ------------------------------------------------------------ (6)/(7) failed requests and odd statuses
@pytest.mark.parametrize("status", [501, 505, 520, 522, 524, 599])
def test_unlisted_5xx_statuses_stay_charged_at_worst_case(owner, api, live_flag, status):
    server = api([(status, {}, b"gateway trouble"), (200, {}, message([tool_use()]))])
    session, gateway, _, records = build(owner, server)
    try:
        gateway.turn()
    except mg.GatewayStopped:
        pass
    first = [r for r in records if r["event"] == "model_call"][0]
    assert first["outcome"]["charged_usd"] == first["worst_case_usd"] != "0"


@pytest.mark.parametrize("status", [201, 202, 203, 204, 205, 206])
def test_a_success_status_that_is_not_200_stays_charged_at_worst_case(owner, api, live_flag, status):
    server = api([(status, {}, b"" if status in (204, 205) else b"{}"), (200, {}, message([tool_use()]))])
    session, gateway, _, records = build(owner, server)
    try:
        gateway.turn()
    except mg.GatewayStopped:
        pass
    first = [r for r in records if r["event"] == "model_call"][0]
    assert first["outcome"]["charged_usd"] == first["worst_case_usd"] != "0"


@pytest.mark.parametrize("status", [301, 303, 307, 308])
def test_a_redirect_is_not_followed_and_not_billed_as_a_reply(owner, api, live_flag, status):
    server = api([(status, {"location": "https://elsewhere.example/steal"}, b""), (200, {}, message([tool_use()]))])
    _, gateway, _, _ = build(owner, server)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert len(server.requests) == 1 and gateway.stop_reason.startswith("provider_")


def test_connection_reset_after_the_request_was_sent_is_charged_at_worst_case(owner, live_flag):
    import socket
    import threading
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    seen = []

    def serve():
        for _ in range(3):
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            seen.append(conn.recv(65536))
            conn.close()      # closed after receiving the whole request: the provider may well have processed it

    threading.Thread(target=serve, daemon=True).start()
    import http.client
    session = gate(owner, connection=lambda timeout: http.client.HTTPConnection("127.0.0.1", port, timeout=timeout))
    records = []
    gateway = mg.VisionGateway(session.config, session.adapter, session.transport, session.ledger, session_id="s",
                               sink=records.append, sleep=lambda s: None)
    gateway.record_game(Game().observation())
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    listener.close()
    calls = [r for r in records if r["event"] == "model_call"]
    assert calls and all(c["outcome"]["charged_usd"] == c["worst_case_usd"] for c in calls)
    assert session.ledger.state().spent > Decimal("0.106019")


# ------------------------------------------------------------ (8) tool calls and history
@pytest.mark.parametrize("stop", [["tool_use"], {"a": 1}, 7, None])
def test_an_unusable_stop_reason_is_a_malformed_reply_not_a_crash(owner, api, live_flag, stop):
    server = api([(200, {}, message([tool_use()], stop=stop)), (200, {}, message([tool_use("b")]))])
    session, gateway, _, records = build(owner, server)
    reply = gateway.turn()          # must not raise a TypeError out of the gateway
    first = [r for r in records if r["event"] == "model_call"][0]
    assert first["outcome"]["charged_usd"] != "0" and session.ledger.state().open_reservations == {}
    assert isinstance(reply, dict)


@pytest.mark.parametrize("block", [None, 5, "text", [], {"type": ["x"]}, {"type": "text", "text": 5}, {"type": "tool_use", "id": 5}])
def test_odd_content_blocks_never_crash_the_gateway(owner, api, live_flag, block):
    server = api([(200, {}, message([block])), (200, {}, message([tool_use("b")]))])
    session, gateway, _, records = build(owner, server)
    try:
        gateway.turn()
    except mg.GatewayStopped:
        pass
    assert session.ledger.state().open_reservations == {}


# ------------------------------------------------------------ (9) screenshot integrity
def test_a_replayed_screenshot_sequence_number_after_the_window_moved_is_refused(owner, api, live_flag):
    session, gateway, game, _ = build(owner, api())      # seq 1 recorded as the opening screenshot
    for _ in range(6):                                    # seq 2..7: seq 1 and 2 scroll out of the four-image window
        gateway._batch = [mg._BatchEntry(call={"id": "z", "name": "observe", "arguments": {}}, executable=True)]
        gateway.record_game(game.observation())
    assert 1 not in gateway._images
    replay = game.observation()
    replay["seq"] = 1                                     # reuse of a number that scrolled out of the window
    gateway._batch = [mg._BatchEntry(call={"id": "z", "name": "observe", "arguments": {}}, executable=True)]
    with pytest.raises(mg.GatewayStopped):
        gateway.record_game(replay)
    assert gateway.stop_reason == "contract_violation"


# ------------------------------------------------------------ (11) crash consistency
def test_reservation_is_durable_in_the_file_before_the_http_request_goes_out(owner, api, live_flag):
    seen = {}
    server = api()
    session = gate(owner, connection=server.connection)
    real_send = session.transport.send

    def spying_send(wire, timeout):
        seen["ledger"] = Path(owner["ledger"]).read_text().splitlines()
        seen["state"] = sl.SpendLedger(owner["ledger"], mode=sl.MODE_LIVE).state()
        return real_send(wire, timeout)

    session.transport.send = spying_send
    gateway = mg.VisionGateway(session.config, session.adapter, session.transport, session.ledger, session_id="s", sleep=lambda s: None)
    gateway.record_game(Game().observation())
    gateway.turn()
    assert json.loads(seen["ledger"][-1])["event"] == "reserve"
    assert len(seen["state"].open_reservations) == 1 and seen["state"].committed > Decimal("0.106019")


def test_a_crash_during_the_http_exchange_leaves_the_reservation_counted(owner, live_flag):
    session = gate(owner, connection=lambda timeout: (_ for _ in ()).throw(KeyboardInterrupt()))
    gateway = mg.VisionGateway(session.config, session.adapter, session.transport, session.ledger, session_id="s", sleep=lambda s: None)
    gateway.record_game(Game().observation())
    with pytest.raises(BaseException):
        gateway.turn()
    reopened = sl.SpendLedger(owner["ledger"], mode=sl.MODE_LIVE).state()
    assert len(reopened.open_reservations) == 1 and reopened.committed > Decimal("0.106019")


# ------------------------------------------------------------ (12) privileged data and key leakage
def test_the_key_is_not_in_any_exception_or_record_when_the_connection_fails_loudly(owner, live_flag):
    class Boom(Exception):
        pass

    def factory(timeout):
        raise Boom(f"cannot reach with {H.FAKE_KEY}")
    session = gate(owner, connection=factory)
    records = []
    gateway = mg.VisionGateway(session.config, session.adapter, session.transport, session.ledger, session_id="s",
                               sink=records.append, sleep=lambda s: None)
    gateway.record_game(Game().observation())
    with pytest.raises(mg.GatewayStopped) as err:
        gateway.turn()
    assert H.FAKE_KEY not in json.dumps(records) + str(err.value) + json.dumps(gateway.manifest())


def test_referee_fields_beyond_the_contract_never_reach_the_model(owner, api, live_flag):
    server = api()
    session, gateway, game, _ = build(owner, server)
    obs = game.observation()
    obs["physics"] = {"vy": 3.0}
    with pytest.raises(mg.GatewayStopped):
        gateway.record_game(obs)
    assert gateway.stop_reason == "contract_violation"
    assert "physics" not in json.dumps(gateway._messages)


# ------------------------------------------------------------ (13) referee's game-request limit
def test_the_referees_request_budget_error_ends_the_session_with_no_further_model_call(tmp_path):
    from rewardbench.blindplay import contract
    spec = importlib.util.spec_from_file_location("_audit_017_gw", Path(__file__).with_name("test_model_gateway.py"))
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    gateway, provider, ledger, records = G.make(tmp_path, [], default={"tool_calls": [G.act("c1")]})
    game = G.opened(gateway)
    reply = gateway.turn()
    call = reply["tool_calls"][0]
    tool, act = contract.parse_request({"tool": call["name"], **call["arguments"]}, contract.V2)
    gateway.authorize_game(tool, act)
    # what session.py returns once its max_requests is passed
    with pytest.raises(mg.GatewayStopped):
        gateway.record_game(contract.error("request budget exhausted", version=contract.V2)
                            if hasattr(contract, "error") else {"protocol": contract.V2.protocol, "error": "request budget exhausted"})
    assert gateway.stop_reason == "game_request_limit"
    calls_before = len(provider.requests)
    with pytest.raises(mg.GatewayStopped):
        gateway.turn()
    assert len(provider.requests) == calls_before
