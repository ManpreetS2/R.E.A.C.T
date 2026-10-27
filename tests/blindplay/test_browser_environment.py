"""Checks against the real upstream game in headless Chromium.

Skipped when Playwright or its Chromium is unavailable, unless REACT_REQUIRE_BROWSER=1 (CI sets it),
in which case a missing browser fails instead of silently passing.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from rewardbench.blindplay import contract, referee as referee_mod, replay, session as session_mod
from rewardbench.blindplay.player_client import BlindPlayClient, png_bytes

SRC = Path(contract.__file__).resolve().parents[2]


def _browser_available() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "playwright not installed"
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:  # noqa: BLE001
        return f"chromium unavailable: {str(exc).splitlines()[0]}"
    return None


_REASON = _browser_available()
if _REASON and os.environ.get("REACT_REQUIRE_BROWSER") == "1":
    raise RuntimeError(f"REACT_REQUIRE_BROWSER=1 but {_REASON}")
pytestmark = pytest.mark.skipif(_REASON is not None, reason=_REASON or "")


@pytest.fixture(scope="module")
def ref():
    with referee_mod.Referee(seed=0) as r:
        yield r


def _session(tmp_path, name="s", **kw):
    kw.setdefault("player_label", "pytest (NOT AI)")
    kw.setdefault("player_is_ai", False)
    return session_mod.Session(tmp_path / name, **kw)


# ---------------------------------------------------------------- authenticity
def test_only_pinned_upstream_files_are_served(ref):
    ref.requests.clear()
    ref.reset()
    served = {r["url"].rsplit("/", 1)[-1] for r in ref.requests if r["result"] == "served"}
    assert {"index.html", "game.js", "Lander.js", "Landscape.js", "KeyTracker.js"} <= served
    for r in ref.requests:
        assert r["result"] == "served" or "favicon" in r["url"], r
        assert "experiment" not in r["url"] and "physics.js" not in r["url"]
    assert not ref.page_errors


def test_one_upstream_physics_update_per_tick(ref):
    start = ref.reset()
    ticks = ref.run([], 120)
    # upstream Lander.update adds gravity 0.0005 to vel.y once per update; no thrust, no drag on y
    assert len(ticks) == 120
    assert ticks[-1]["vy"] == pytest.approx(start["vy"] + 120 * 0.0005, abs=1e-12)
    assert [t["tick"] for t in ticks] == list(range(start["tick"] + 1, start["tick"] + 121))
    assert [t["counter"] for t in ticks] == list(range(start["counter"] + 1, start["counter"] + 121))


def test_every_allowed_key_reaches_the_game_and_is_released(ref):
    ref.reset()
    codes = {"ArrowDown": 40, "ArrowLeft": 37, "ArrowRight": 39, "ArrowUp": 38, "Enter": 13, "Escape": 27,
             "KeyA": 65, "KeyD": 68, "KeyS": 83, "KeyW": 87, "ShiftLeft": 16, "Space": 32}
    assert set(codes) == set(contract.ALLOWED_KEYS)
    for key, code in codes.items():
        ticks = ref.run([key], 1, stop_on_terminal=False)
        assert ticks[-1]["keysDown"] == [code], key
        assert ref.snapshot()["keysDown"] == [], key


def test_keys_change_the_upstream_physics(ref):
    """Referee-only causality check: input arrives in the real game, not a substitute model."""
    ref.reset()
    idle = ref.run([], 60)[-1]
    ref.reset()
    held = ref.run(["ArrowUp"], 60)[-1]
    # the ship starts rotated -90 degrees, so this thrust is horizontal: fuel burns and vx changes, vy does not
    assert idle["fuel"] == 1000 and held["fuel"] < 1000
    assert (held["vx"], held["vy"]) != (idle["vx"], idle["vy"])
    ref.reset()
    ref.run(["ArrowRight"], 30)
    assert ref.snapshot()["rotation"] > -90


# ---------------------------------------------------------------- determinism
def test_fixed_start_is_identical_across_fresh_browsers_and_differs_by_seed():
    states, pngs = [], []
    for seed in (0, 0, 7):
        with referee_mod.Referee(seed=seed) as r:
            start = r.reset()
            pngs.append(hashlib.sha256(r.screenshot()).hexdigest())
            seq = r.run(["ArrowUp", "ArrowLeft"], 45) + r.run([], 30) + r.run(["Space"], 20)
            states.append((start, seq))
            pngs.append(hashlib.sha256(r.screenshot()).hexdigest())
    assert states[0] == states[1] and pngs[0:2] == pngs[2:4]
    assert states[2][0]["x"] != states[0][0]["x"] and pngs[4] != pngs[0]


def test_wall_clock_does_not_change_results(tmp_path):
    hashes = []
    for name, pause in (("fast", 0.0), ("slow", 0.4)):
        with _session(tmp_path, name, max_episodes=1, episode_frame_budget=400) as s:
            s.handle({"tool": "observe"})
            for keys, frames in ((["ArrowUp"], 40), ([], 60), (["ArrowRight", "Space"], 50)):
                time.sleep(pause)
                hashes.append((name, s.handle({"tool": "act", "keys": keys, "frames": frames})["image"]["sha256"]))
    fast = [h for n, h in hashes if n == "fast"]
    slow = [h for n, h in hashes if n == "slow"]
    assert fast == slow


# ---------------------------------------------------------------- session: boundary, budgets, records
def test_player_receives_only_contract_fields_and_a_real_screenshot(tmp_path):
    from PIL import Image

    with _session(tmp_path, max_episodes=1, episode_frame_budget=300) as s:
        obs = s.handle({"tool": "observe"})
        assert set(obs) == contract.OBSERVATION_FIELDS and set(obs["image"]) == contract.IMAGE_FIELDS
        assert (obs["episode"], obs["episode_frame"], obs["frames_advanced"]) == (1, 0, 0)
        img = Image.open(io.BytesIO(base64.b64decode(obs["image"]["base64"])))
        assert img.size == (1280, 720) and img.mode in ("RGB", "RGBA")
        extrema = img.convert("L").getextrema()
        assert extrema[1] - extrema[0] > 100, "screenshot should contain the rendered game, not a blank frame"
        numbers = [v for k, v in obs.items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        assert sorted(numbers) == sorted([obs["seq"], 1, 0, 300, 1, 0])
        brief = s.handle({"tool": "brief"})
        assert set(brief) == contract.BRIEF_FIELDS


def test_rejected_requests_do_not_advance_the_game(tmp_path):
    with _session(tmp_path, max_episodes=1, episode_frame_budget=500) as s:
        s.handle({"tool": "observe"})
        before = s.referee.snapshot()["tick"]
        for bad in ({"tool": "act", "keys": ["ArrowUp"], "frames": 121}, {"tool": "act", "keys": ["KeyQ"], "frames": 5},
                    {"tool": "act", "keys": [], "frames": 5, "controller": {}}, {"tool": "eval", "code": "gameState"},
                    "lander.vel.y=0"):
            r = s.handle(bad)
            assert set(r) == contract.ERROR_FIELDS
        assert s.referee.snapshot()["tick"] == before
        ok = s.handle({"tool": "act", "keys": [], "frames": 120})
        assert ok["frames_advanced"] == 120 and ok["episode_frame"] == 120


def test_idle_episode_crash_reset_and_session_end(tmp_path):
    with _session(tmp_path, max_episodes=2, episode_frame_budget=8000) as s:
        first = s.handle({"tool": "observe"})
        ended = None
        previous = first
        while ended is None:
            r = s.handle({"tool": "act", "keys": [], "frames": 120})
            if r["episode_ended"]:
                ended = r
            else:
                previous = r
        assert ended["image"]["sha256"] != previous["image"]["sha256"]
        assert ended["frames_advanced"] < 120 and not ended["session_over"]
        second = s.handle({"tool": "observe"})
        assert second["episode"] == 2 and second["episode_frame"] == 0
        assert second["image"]["sha256"] == first["image"]["sha256"], "fixed start: identical first frame"
        while not r["session_over"]:
            r = s.handle({"tool": "act", "keys": [], "frames": 120})
        assert set(s.handle({"tool": "act", "keys": [], "frames": 1})) == contract.ERROR_FIELDS
        receipts = [json.loads(line) for line in (s.out / "episodes.jsonl").read_text().splitlines()]
    assert [e["outcome"] for e in receipts] == ["crashed", "crashed"]
    assert receipts[0]["frames"] == receipts[1]["frames"]
    assert receipts[0]["start_frame_sha256"] == receipts[1]["start_frame_sha256"]
    assert "LUNAR MODULE" in receipts[0]["native_message"] or "LOSS" in receipts[0]["native_message"]


def test_frame_budget_ends_the_episode_exactly(tmp_path):
    with _session(tmp_path, max_episodes=1, episode_frame_budget=250) as s:
        s.handle({"tool": "observe"})
        a = s.handle({"tool": "act", "keys": ["ArrowUp"], "frames": 120})
        b = s.handle({"tool": "act", "keys": ["ArrowUp"], "frames": 120})
        c = s.handle({"tool": "act", "keys": ["ArrowUp"], "frames": 120})
        assert (a["episode_frame"], b["episode_frame"], c["episode_frame"]) == (120, 240, 250)
        assert c["frames_advanced"] == 10 and c["episode_ended"] and c["session_over"]
    receipt = json.loads((tmp_path / "s" / "episodes.jsonl").read_text())
    assert receipt["outcome"] == "frame_budget_exhausted" and receipt["frames"] == 250


def test_records_are_complete_and_match_what_the_player_saw(tmp_path):
    with _session(tmp_path, max_episodes=1, episode_frame_budget=200) as s:
        seen = [s.handle({"tool": "observe"})]
        seen.append(s.handle({"tool": "act", "keys": ["Space"], "frames": 100}))
        seen.append(s.handle({"tool": "act", "keys": [], "frames": 100}))
    out = tmp_path / "s"
    transcript = [json.loads(line) for line in (out / "player_transcript.jsonl").read_text().splitlines()]
    assert len(transcript) == 3
    for obs, entry in zip(seen, transcript):
        png = (out / entry["response"]["image"]["file"]).read_bytes()
        assert hashlib.sha256(png).hexdigest() == obs["image"]["sha256"] == entry["response"]["image"]["sha256"]
        assert png == base64.b64decode(obs["image"]["base64"])
    manifest = json.loads((out / "session.json").read_text())
    assert manifest["status"] == "closed" and manifest["player"] == {"label": "pytest (NOT AI)", "is_ai": False}
    assert manifest["environment"]["upstream_commit"] == "0da09dccbadf0d6ee6efcce1f72e9ae206d341d2"
    assert manifest["network"]["blocked"] == [] or all("favicon" in u for u in manifest["network"]["blocked"])
    acts = [json.loads(line) for line in (out / "referee.jsonl").read_text().splitlines() if '"act"' in line]
    assert [len(a["ticks"]) for a in acts] == [100, 100]


def test_existing_records_are_never_overwritten(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "keep.txt").write_text("x")
    with pytest.raises(FileExistsError):
        _session(tmp_path)


# ---------------------------------------------------------------- process boundary and replay
def test_stdio_server_end_to_end_and_replay(tmp_path):
    out = tmp_path / "piped"
    env = dict(os.environ, PYTHONPATH=str(SRC))
    cmd = [sys.executable, "-m", "rewardbench.blindplay.serve", "--out", str(out), "--player-label", "pytest pipe (NOT AI)",
           "--player-is-ai", "false", "--max-episodes", "1", "--episode-frame-budget", "240"]
    with BlindPlayClient(cmd, env=env) as client:
        assert client.brief()["objective"] == "Land the rocket."
        obs = client.observe()
        assert png_bytes(obs).startswith(b"\x89PNG")
        assert set(client.raw({"tool": "act", "keys": ["ArrowUp"], "frames": 999})) == contract.ERROR_FIELDS
        assert set(client.raw("not json at all")) == contract.ERROR_FIELDS
        client.act(["ArrowUp"], 120)
        last = client.act([], 120)
        assert last["session_over"] and last["episode_ended"]
    receipt = replay.replay(out)
    assert receipt["reproduced"], receipt
    assert receipt["screenshots_identical"] == receipt["screenshots_compared"] == 3


def test_server_stdout_carries_only_protocol_lines(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(SRC))
    cmd = [sys.executable, "-m", "rewardbench.blindplay.serve", "--out", str(tmp_path / "raw"), "--player-label", "pytest",
           "--player-is-ai", "false", "--max-episodes", "1", "--episode-frame-budget", "60"]
    proc = subprocess.run(cmd, input='{"tool":"brief"}\n{"tool":"observe"}\n', capture_output=True, text=True,
                          env=env, timeout=180)
    lines = proc.stdout.splitlines()
    assert proc.returncode == 0 and len(lines) == 2
    assert all(json.loads(line)["protocol"] == contract.PROTOCOL for line in lines)


# ---------------------------------------------------------------- hardening from the independent review
def _serve_cmd(out, **budgets):
    cmd = [sys.executable, "-m", "rewardbench.blindplay.serve", "--out", str(out), "--player-label", "pytest (NOT AI)",
           "--player-is-ai", "false", "--max-episodes", "1", "--episode-frame-budget", "300"]
    for k, v in budgets.items():
        cmd += [f"--{k.replace('_', '-')}", str(v)]
    return cmd


def test_malformed_lines_are_recorded_rejected_and_harmless(tmp_path):
    out = tmp_path / "hostile"
    lines = [
        b'{"tool":"observe"}',
        b"not json at all",
        b'{"tool":"act","keys":[],"frames":' + b"9" * 5000 + b"}",
        b"[" * 100000,
        b'{"tool":"observe","id":"\xff\xfe\x81"}',
        b'{"tool":"act","keys":[],"frames":5,"frames":999}',
        b'{"tool":"act","keys":[],"frames":NaN}',
        b'{"tool":"act","keys":["ArrowUp"],"frames":5,"x":"' + b"a" * 70000 + b'"}',
        b'{"tool":"observe"}',
    ]
    proc = subprocess.run(_serve_cmd(out), input=b"\n".join(lines) + b"\n", capture_output=True,
                          env=dict(os.environ, PYTHONPATH=str(SRC)), timeout=300)
    assert proc.returncode == 0
    assert proc.stderr == b"", "nothing from the referee may reach the player's stderr"
    responses = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
    assert len(responses) == len(lines)
    assert all(set(r) == contract.ERROR_FIELDS for r in responses[1:-1])
    assert responses[0]["image"]["sha256"] == responses[-1]["image"]["sha256"], "rejected lines must not advance the game"
    transcript = [json.loads(line) for line in (out / "player_transcript.jsonl").read_text().splitlines()]
    assert len(transcript) == len(lines)
    assert all("rejected_before_parsing" in e for e in transcript[1:-1])
    assert transcript[7]["raw_line_bytes"] > 65536
    assert (out / "referee_stderr.log").exists()
    assert json.loads((out / "session.json").read_text())["status"] == "closed"
    assert replay.replay(out)["reproduced"]


def test_any_environment_exception_ends_the_session_with_a_record(tmp_path, monkeypatch):
    s = _session(tmp_path, max_episodes=1, episode_frame_budget=200)
    with s:
        s.handle({"tool": "observe"})
        monkeypatch.setattr(s.referee, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        r = s.handle({"tool": "act", "keys": [], "frames": 10})
        assert set(r) == contract.ERROR_FIELDS and s.session_over
        assert set(s.handle({"tool": "observe"})) == contract.ERROR_FIELDS
    manifest = json.loads((tmp_path / "s" / "session.json").read_text())
    assert "RuntimeError: boom" in manifest["environment_failure"]
    assert len((tmp_path / "s" / "player_transcript.jsonl").read_text().splitlines()) == 3


def test_referee_with_other_files_is_refused(tmp_path):
    files = dict(referee_mod.upstream.load_upstream())
    files["game.js"] = files["game.js"] + b"\n//"
    with pytest.raises(referee_mod.RefereeError):
        _session(tmp_path, ref=referee_mod.Referee(seed=0, files=files))


def test_page_environment_is_pinned_and_sealed(ref):
    ref.reset()
    ref.requests.clear()
    facts = ref.page.evaluate("""async () => {
        const d = new Date(2020, 0, undefined);
        let fetched = 'no';
        try { await fetch('http://example.com/x'); fetched = 'yes'; } catch (e) { fetched = 'blocked'; }
        try { new WebSocket('ws://example.com/socket'); } catch (e) {}
        return { invalid: isNaN(d.getTime()), ctor: new Date().constructor === Date, tz: new Date(0).getTimezoneOffset(),
                 sameClock: Date.now() === performance.now(), fetched: fetched, lang: navigator.language };
    }""")
    ref.page.wait_for_timeout(200)
    assert facts == {"invalid": True, "ctor": True, "tz": 0, "sameClock": True, "fetched": "blocked", "lang": "en-US"}
    assert {r["result"] for r in ref.requests} <= {"blocked", "blocked_websocket"}
    assert any("example.com/x" in r["url"] for r in ref.requests)
    assert any(r["result"] == "blocked_websocket" and "example.com/socket" in r["url"] for r in ref.requests)
    assert ref.run([], 2, stop_on_terminal=False), "a blocked socket must not stall the referee"


def test_exception_in_a_game_callback_is_isolated_and_recorded(ref):
    ref.reset()
    ref.page_errors.clear()
    ref.page.evaluate("() => requestAnimationFrame(() => { throw new Error('probe-failure'); })")
    ticks = ref.run([], 3, stop_on_terminal=False)
    assert len(ticks) == 3 and ticks[-1]["tick"] == ticks[0]["tick"] + 2, "the game loop keeps running"
    assert len(ref.page_errors) == 1 and "probe-failure" in ref.page_errors[0]
