"""Authentic-footage checks: replay-verified rendering, labels, determinism, refusals (real Chromium)."""

from __future__ import annotations

import json
import os

import pytest

from rewardbench.blindplay import footage, session as session_mod


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

ACTS = [(["ArrowUp"], 20), ([], 30), (["ArrowRight", "Space"], 25)]


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    out = tmp_path_factory.mktemp("rec") / "session"
    with session_mod.Session(out, max_episodes=1, episode_frame_budget=75,
                             player_label="scripted:pytest-fixture (NOT AI)", player_is_ai=False) as s:
        s.handle({"tool": "observe"})
        for keys, frames in ACTS:
            s.handle({"tool": "act", "keys": keys, "frames": frames})
    return out


def _copy(src, dst):
    import shutil
    shutil.copytree(src, dst)
    return dst


def test_render_labels_frames_and_sidecar(recorded, tmp_path):
    before = (recorded / "session.json").read_bytes()
    result = footage.render(recorded, tmp_path / "out", every=5)
    side = json.loads((tmp_path / "out" / "footage.json").read_text(encoding="utf-8"))
    out = tmp_path / "out"
    if (out / "footage.mp4").exists():
        assert (out / "footage.mp4").stat().st_size > 0
        assert side["output_sha256"] == footage._sha256_file(out / "footage.mp4")
        assert "ffmpeg" in side["tool_versions"] and side["tool_versions"]["imageio"]
    else:   # the 'environments' extra (imageio-ffmpeg) is not installed: numbered PNGs + manifest, as documented
        assert (out / "frames_manifest.json").is_file()
    assert side["label"]["banner"] == "REPLAY OF RECORDED SESSION"
    assert side["label"]["player_is_ai"] is False and "NON-AI" in side["label"]["player_kind"]
    assert "scripted:pytest-fixture (NOT AI)" in side["label"]["player_label"]
    assert side["input_session_json_sha256"].startswith(side["label"]["session_sha256_prefix"])
    assert side["label"]["outcomes"] == {"1": "frame_budget_exhausted"}
    assert "recorded outcome: frame_budget_exhausted" in side["label"]["label_text_line2_example"]
    assert side["replay_receipt"]["reproduced"] is True and side["every"] == 5
    assert side["capture_check"]["capture_pass_mismatches"] == []
    assert side["frame_count"] > side["acts"] == len(ACTS)
    assert side["game_frame_count"] >= 15 and result["frame_count"] == side["frame_count"]
    assert (recorded / "session.json").read_bytes() == before
    assert not (recorded / "replays").exists()          # input directory untouched
    assert not (tmp_path / "out" / "_work").exists()


def test_two_renders_have_identical_frames(recorded, tmp_path):
    a = footage.render(recorded, tmp_path / "a", every=10)
    b = footage.render(recorded, tmp_path / "b", every=10)
    assert a["frame_hashes"] == b["frame_hashes"] and a["frames_sha256"] == b["frames_sha256"]


def test_episode_filter(recorded, tmp_path):
    full = footage.render(recorded, tmp_path / "full", every=10)
    one = footage.render(recorded, tmp_path / "one", every=10, episode=1)
    assert one["frame_count"] == full["frame_count"]
    with pytest.raises(footage.FootageRefused):
        footage.render(recorded, tmp_path / "none", every=10, episode=9)
    assert not (tmp_path / "none").exists()


def test_refuses_tampered_screenshot(recorded, tmp_path):
    bad = _copy(recorded, tmp_path / "tampered")
    shot = sorted((bad / "screenshots").glob("*.png"))[-1]
    data = bytearray(shot.read_bytes())
    data[-20] ^= 0xFF
    shot.write_bytes(bytes(data))
    with pytest.raises(footage.FootageRefused, match="did not reproduce"):
        footage.render(bad, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_refuses_tampered_referee_record(recorded, tmp_path):
    bad = _copy(recorded, tmp_path / "tampered2")
    ep = bad / "episodes.jsonl"
    ep.write_text(ep.read_text(encoding="utf-8").replace("frame_budget_exhausted", "landed_perfect"), encoding="utf-8")
    with pytest.raises(footage.FootageRefused):
        footage.render(bad, tmp_path / "out")


def test_refuses_to_overwrite(recorded, tmp_path):
    out = tmp_path / "exists"
    out.mkdir()
    (out / "keep.txt").write_text("precious")
    with pytest.raises(FileExistsError):
        footage.render(recorded, out)
    assert (out / "keep.txt").read_text() == "precious"
    assert footage.main([str(recorded), "--out", str(out)]) == 2


def test_cli(recorded, tmp_path):
    assert footage.main([str(recorded), "--out", str(tmp_path / "cli"), "--every", "25"]) == 0
    assert (tmp_path / "cli" / "footage.json").is_file()
