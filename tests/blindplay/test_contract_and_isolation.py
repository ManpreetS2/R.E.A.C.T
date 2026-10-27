"""Browser-free checks of the player boundary, the import isolation and the upstream integrity."""

from __future__ import annotations

import ast
import json
import math
import re
import shutil
from pathlib import Path

import pytest

from rewardbench.blindplay import contract, upstream

PACKAGE = Path(contract.__file__).resolve().parent
REPO = PACKAGE.parents[2]


# ---------------------------------------------------------------- action contract
@pytest.mark.parametrize("request_", [
    {"tool": "act", "keys": ["ArrowUp"], "frames": 0},
    {"tool": "act", "keys": ["ArrowUp"], "frames": 121},
    {"tool": "act", "keys": ["ArrowUp"], "frames": 10.0},
    {"tool": "act", "keys": ["ArrowUp"], "frames": True},
    {"tool": "act", "keys": ["ArrowUp"], "frames": "10"},
    {"tool": "act", "keys": "ArrowUp", "frames": 10},
    {"tool": "act", "keys": ["KeyQ"], "frames": 10},
    {"tool": "act", "keys": ["arrowup"], "frames": 10},
    {"tool": "act", "keys": ["ArrowUp", "ArrowUp"], "frames": 10},
    {"tool": "act", "keys": [], "frames": 10, "controller": {"descent_low": 0.1}},
    {"tool": "act", "keys": [], "frames": 10, "javascript": "lander.vel.y = 0"},
    {"tool": "act", "keys": [], "frames": 10, "state": True},
    {"tool": "act", "keys": [{"key": "ArrowUp"}], "frames": 10},
    {"tool": "act"},
    {"tool": "observe", "debug": True},
    {"tool": "state"},
    {"tool": "eval", "code": "gameState"},
    {"tool": "reset"},
    {"tool": None},
    {},
    [],
    "act ArrowUp 10",
    None,
])
def test_requests_outside_the_contract_are_rejected(request_):
    with pytest.raises(contract.ActionRejected):
        contract.parse_request(request_)


def test_valid_requests():
    assert contract.parse_request({"tool": "observe"}) == ("observe", None)
    assert contract.parse_request({"tool": "brief", "id": 3}) == ("brief", None)
    tool, act = contract.parse_request({"tool": "act", "keys": ["Space", "ArrowLeft"], "frames": 120})
    assert tool == "act" and act == contract.Act(keys=("Space", "ArrowLeft"), frames=120)
    assert contract.parse_request({"tool": "act", "keys": [], "frames": 1})[1].keys == ()


def test_brief_is_only_the_objective_and_neutral_tools():
    b = contract.brief(episode_frame_budget=8000, max_episodes=20)
    assert set(b) == contract.BRIEF_FIELDS
    assert b["objective"] == "Land the rocket."
    assert [t["name"] for t in b["tools"]] == ["observe", "act"]
    assert b["keyset"]["keys"] == sorted(b["keyset"]["keys"]) == list(contract.ALLOWED_KEYS)
    words = set(re.findall(r"[a-z]+", json.dumps(b).lower()))
    hints = {"thrust", "rotate", "rotation", "turn", "tilt", "gravity", "fuel", "velocity", "speed", "accelerate",
             "brake", "engine", "steer", "pad", "angle", "upright", "slow", "gentle", "descend", "descent", "crash",
             "score", "reward", "hover", "boost", "abort", "restart", "left", "right", "down", "lift"}
    assert not words & hints, f"brief must not hint at controls or strategy: {sorted(words & hints)}"


def test_observation_and_error_fields_are_exact():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 10
    obs = contract.observation(seq=1, episode=1, episode_frame=0, episode_frame_budget=8000, max_episodes=20,
                               frames_advanced=0, episode_ended=False, session_over=False,
                               image=contract.image_payload(png, 1280, 720))
    assert set(obs) == contract.OBSERVATION_FIELDS and set(obs["image"]) == contract.IMAGE_FIELDS
    assert set(contract.error("x")) == contract.ERROR_FIELDS
    with pytest.raises(ValueError):
        contract.image_payload(b"GIF89a", 1, 1)


# ---------------------------------------------------------------- import isolation
def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(("." * node.level) + (node.module or ""))
    return names


@pytest.mark.parametrize("module", ["contract.py", "player_client.py"])
def test_player_side_modules_use_only_the_standard_library(module):
    allowed = {"__future__", "base64", "hashlib", "json", "subprocess", "dataclasses", "typing"}
    assert _imports(PACKAGE / module) <= allowed


def test_blindplay_never_imports_the_guidance_controller_simulator_or_providers():
    forbidden = ("rewardbench.environments", "rewardbench.autopilot", "rewardbench.study", "rewardbench.providers",
                 "rewardbench.core", "rewardbench.prompts", "rewardbench.operate", "rewardbench.heldout",
                 "rewardbench.run", "rewardbench.storage", "gymnasium", "openai", "anthropic", "requests", "httpx")
    for path in PACKAGE.glob("*.py"):
        for name in _imports(path):
            assert not name.startswith(forbidden), f"{path.name} imports {name}"
            if name.startswith("rewardbench"):
                assert name.startswith("rewardbench.blindplay"), f"{path.name} imports {name}"


def test_blindplay_does_not_reference_the_custom_simulator_files():
    for path in list(PACKAGE.glob("*.py")) + list(PACKAGE.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        for needle in ("apollolander/experiment", "physics.js", "render.js", "guidance", "initial_controller"):
            assert needle not in text, f"{path.name} mentions {needle}"


# ---------------------------------------------------------------- upstream integrity
def test_vendored_upstream_matches_pinned_hashes():
    files = upstream.load_upstream()
    assert set(files) == set(upstream.UPSTREAM_SHA256)
    assert upstream.UPSTREAM_COMMIT == (upstream.UPSTREAM_DIR / "UPSTREAM_COMMIT.txt").read_text().strip()


def test_tampered_upstream_refuses_to_load(tmp_path):
    copy = tmp_path / "upstream"
    shutil.copytree(upstream.UPSTREAM_DIR, copy)
    game = copy / "game.js"
    game.write_bytes(game.read_bytes().replace(b"gravity", b"gravitx", 1) + b"\n// tampered\n")
    with pytest.raises(upstream.UpstreamIntegrityError):
        upstream.load_upstream(copy)
    (copy / "game.js").unlink()
    with pytest.raises(upstream.UpstreamIntegrityError):
        upstream.load_upstream(copy)


# ---------------------------------------------------------------- virtual clock arithmetic
def test_virtual_clock_bias_gives_exact_frame_counts():
    """game.js computes floor((now - start) / (1000/60)); plain frame*1000/60 drops frames (DEVLOG)."""
    mpf = 1000 / 60
    biased = lambda n: n * mpf + n * 1e-6  # noqa: E731 - mirrors clock.js now()
    plain = lambda n: n * mpf  # noqa: E731
    bad_plain = 0
    for n0 in range(0, 20001, 97):
        for m in range(1, 9001, 7):
            assert math.floor((biased(n0 + m) - biased(n0)) / mpf) == m
            bad_plain += math.floor((plain(n0 + m) - plain(n0)) / mpf) != m
    assert bad_plain > 0, "the failure the bias fixes should still be observable with the plain clock"
    clock = (PACKAGE / "clock.js").read_text(encoding="utf-8")
    assert "frame * MPF + frame * BIAS" in clock and "BIAS = 1e-6" in clock
