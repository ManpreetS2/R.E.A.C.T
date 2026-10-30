"""keyset.v2 (11 keys, no KeyS) is a new version; keyset.v1 stays frozen for replaying historical sessions."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from rewardbench.blindplay import contract, replay, serve, session as session_mod, upstream

EVIDENCE = Path(contract.__file__).resolve().parents[3] / "docs" / "assets"


def _hash(version: contract.ContractVersion) -> str:
    return hashlib.sha256(json.dumps({"p": version.protocol, "k": version.keyset, "keys": version.keys,
                                      "tools": version.tools}, sort_keys=True).encode()).hexdigest()


def test_keyset_v1_is_frozen_byte_for_byte():
    """Recorded from commit c1d4b9b before keyset.v2 existed. If this fails, a historical contract was changed."""
    assert _hash(contract.V1) == "083d655c884a6f251f8490950541fe4a4137b317cb6a2264833a6ca3cca8762a"
    assert (contract.PROTOCOL, contract.KEYSET_VERSION) == ("react.blindplay.player.v1", "keyset.v1")
    assert contract.ALLOWED_KEYS == contract.V1.keys and contract.TOOLS == contract.V1.tools
    assert "KeyS" in contract.V1.keys and len(contract.V1.keys) == 12


def test_keyset_v2_is_v1_minus_exactly_keys():
    assert set(contract.V1.keys) - set(contract.V2.keys) == {"KeyS"}
    assert set(contract.V2.keys) - set(contract.V1.keys) == set()
    assert len(contract.V2.keys) == 11 and list(contract.V2.keys) == sorted(contract.V2.keys)
    assert contract.V2.keyset == "keyset.v2" and contract.V2.protocol == "react.blindplay.player.v2"


def test_only_the_key_enumeration_differs_between_v1_and_v2():
    def without_enum(tools):
        data = json.loads(json.dumps(tools))
        del data[1]["parameters"]["properties"]["keys"]["items"]["enum"]
        return data
    assert without_enum(contract.V1.tools) == without_enum(contract.V2.tools)
    assert contract.V2.tools[1]["parameters"]["properties"]["keys"]["items"]["enum"] == list(contract.V2.keys)


def test_v2_rejects_the_speed_key_and_v1_still_accepts_it():
    request = {"tool": "act", "keys": ["KeyS"], "frames": 10}
    assert contract.parse_request(request, contract.V1)[1].keys == ("KeyS",)
    with pytest.raises(contract.ActionRejected, match="KeyS"):
        contract.parse_request(request, contract.V2)
    for key in contract.V2.keys:
        assert contract.parse_request({"tool": "act", "keys": [key], "frames": 1}, contract.V2)[1].keys == (key,)
    for bad in ("keys", "KEYS", "s", "S", "keyS"):
        with pytest.raises(contract.ActionRejected):
            contract.parse_request({"tool": "act", "keys": [bad], "frames": 1}, contract.V2)


def test_unknown_keyset_is_refused():
    with pytest.raises(ValueError, match="keyset.v9"):
        contract.version_for("keyset.v9")


def test_v2_brief_and_messages_name_v2_and_give_no_hints():
    b = contract.brief(episode_frame_budget=8000, max_episodes=10, version=contract.V2)
    assert set(b) == contract.BRIEF_FIELDS and b["protocol"] == contract.V2.protocol
    assert b["keyset"] == {"version": "keyset.v2", "keys": list(contract.V2.keys)}
    assert "KeyS" not in json.dumps(b)
    words = set(re.findall(r"[a-z]+", json.dumps(b).lower()))
    assert not words & {"thrust", "rotate", "speed", "fuel", "gravity", "score", "reward", "crash"}
    assert contract.error("x", contract.V2)["protocol"] == contract.V2.protocol


@pytest.mark.parametrize("path", sorted(EVIDENCE.glob("*/evidence*.json")), ids=lambda p: p.name)
def test_historical_evidence_records_are_untouched_and_still_name_keyset_v1(path):
    """Evidence files are committed history, and the v1 allowed list they quote must remain the current v1 list."""
    text = path.read_text(encoding="utf-8")
    if "keys not allowed" in text:
        assert str(list(contract.V1.keys)).replace("'", "\\'") in text.replace("'", "\\'")


def test_upstream_source_is_still_the_pinned_authentic_game():
    files = upstream.load_upstream()
    assert {k: hashlib.sha256(v).hexdigest() for k, v in files.items()} == upstream.UPSTREAM_SHA256
    assert b"SPEED MODE" in files["game.js"], "the upstream game keeps its speed mode; keyset.v2 only stops offering the key"


def test_serve_accepts_only_known_keysets():
    assert sorted(contract.CONTRACTS) == ["keyset.v1", "keyset.v2"]
    with pytest.raises(SystemExit):
        serve.main(["--out", "unused", "--player-label", "x", "--player-is-ai", "false", "--keyset", "keyset.v9"])


# ---------------------------------------------------------------- against the real game
def _browser() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        return str(exc).splitlines()[0]
    return None


needs_browser = pytest.mark.skipif(_browser() is not None, reason="browser unavailable")
PLAY = (([], 60), (["ArrowUp"], 45), (["ArrowLeft", "Space"], 30), (["Enter", "Escape", "ShiftLeft"], 20), ([], 120))


def _session(path: Path, keyset: str):
    return session_mod.Session(path, max_episodes=1, episode_frame_budget=1000, player_label="pytest (NOT AI)",
                               player_is_ai=False, keyset=keyset)


@needs_browser
def test_same_inputs_give_identical_screens_under_v1_and_v2(tmp_path):
    """Removing the key from the offer changes nothing about the game for the other 11."""
    hashes = {}
    for keyset in ("keyset.v1", "keyset.v2"):
        with _session(tmp_path / keyset, keyset) as s:
            hashes[keyset] = [s.handle({"tool": "observe"})["image"]["sha256"]] + [
                s.handle({"tool": "act", "keys": k, "frames": f})["image"]["sha256"] for k, f in PLAY]
    assert hashes["keyset.v1"] == hashes["keyset.v2"]


@needs_browser
def test_v2_session_refuses_the_speed_key_records_it_and_replays(tmp_path):
    out = tmp_path / "v2"
    with _session(out, "keyset.v2") as s:
        first = s.handle({"tool": "observe"})
        refused = s.handle({"tool": "act", "keys": ["KeyS"], "frames": 120})
        assert set(refused) == contract.ERROR_FIELDS and "KeyS" in refused["error"]
        after = s.handle({"tool": "observe"})
        assert (after["episode_frame"], after["image"]["sha256"]) == (0, first["image"]["sha256"]), "nothing advanced"
        assert first["protocol"] == contract.V2.protocol
        s.handle({"tool": "act", "keys": ["ArrowUp"], "frames": 30})
    manifest = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert manifest["player_contract"]["keyset"] == "keyset.v2"
    assert manifest["player_contract"]["protocol"] == contract.V2.protocol
    assert "KeyS" not in manifest["player_contract"]["allowed_keys"]
    assert any("not offered" in d for d in manifest["environment"]["deviations_from_live_game"])
    assert replay.replay(out)["reproduced"]


@needs_browser
def test_v1_session_with_the_speed_key_still_replays_under_v1(tmp_path):
    """Historical compatibility: a keyset.v1 session that pressed KeyS must still reproduce exactly."""
    out = tmp_path / "v1"
    with _session(out, "keyset.v1") as s:
        s.handle({"tool": "observe"})
        response = s.handle({"tool": "act", "keys": ["KeyS"], "frames": 30})
        assert response["frames_advanced"] == 30
    manifest = json.loads((out / "session.json").read_text(encoding="utf-8"))
    assert manifest["player_contract"]["keyset"] == "keyset.v1"
    assert manifest["player_contract"]["protocol"] == "react.blindplay.player.v1"
    assert replay.replay(out)["reproduced"]
