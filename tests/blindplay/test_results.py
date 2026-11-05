"""results.py against real isolated scripted sessions (AppContainer sandbox + Chromium). tmp_path only."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rewardbench.blindplay import host as host_mod, isolation, results


def _run(out: Path, *, script="seeded-random", script_seed=1, keyset="keyset.v2", episodes=2, budget=60) -> None:
    rc = host_mod.main(["--out", str(out), "--script", script, "--script-seed", str(script_seed), "--keyset", keyset,
                        "--episodes", str(episodes), "--episode-frame-budget", str(budget)])
    assert rc == 0


@pytest.fixture(scope="module")
def good(tmp_path_factory) -> Path:
    reason = isolation.supported()
    if reason:
        pytest.skip(reason)   # the isolated host needs Windows (AppContainer) or macOS (Seatbelt)
    out = tmp_path_factory.mktemp("results") / "session"
    _run(out)
    return out


@pytest.fixture()
def copy(good, tmp_path) -> Path:
    dest = tmp_path / "copy"
    shutil.copytree(good, dest)
    return dest


def _episodes(session: Path) -> list[dict]:
    text = (session / "referee" / "episodes.jsonl").read_text(encoding="utf-8")
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def _image_hashes(session: Path) -> list[str]:
    text = (session / "referee" / "player_transcript.jsonl").read_text(encoding="utf-8")
    records = [json.loads(x) for x in text.splitlines() if x.strip()]
    return [r["response"]["image"]["sha256"] for r in records if "image" in r["response"]]


def test_summary_matches_trusted_records_and_replays(good):
    s = results.summarize(good, run_replay=True)
    raw = _episodes(good)
    assert [r["outcome"] for r in s["episodes"]] == [e["outcome"] for e in raw]
    assert [r["episode"] for r in s["episodes"]] == [e["episode"] for e in raw] == [1, 2]
    assert [r["frames"] for r in s["episodes"]] == [e["frames"] for e in raw]
    assert all(r["timed_out"] for r in s["episodes"])   # a 60-frame budget cannot land the rocket: timeouts are reported
    assert s["integrity"]["ok"], s["integrity"]
    assert s["integrity"]["replay_receipt"]["reproduced"] is True
    assert s["completeness"]["flag"] == "complete" and s["completeness"]["finished_episodes"] == 2
    assert s["header"]["keyset"] == "keyset.v2"
    assert not (good / "referee" / "replays").exists()   # replay ran on a copy; the evidence directory is untouched


def test_header_comes_from_the_manifest_not_a_flag(good, copy):
    assert results.summarize(good)["header"]["label"] == "scripted NON-AI baseline"
    assert "SCRIPTED NON-AI BASELINE" in results.render_text(results.summarize(good))
    p = copy / "host_session.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["player_is_ai"] = True
    p.write_text(json.dumps(d), encoding="utf-8")
    s = results.summarize(copy)
    assert s["header"]["player_is_ai"] == "unavailable" and not s["integrity"]["ok"]   # manifests disagree: never guessed


def test_cost_for_scripted_is_zero_and_gateway_chain_empty(good):
    s = results.summarize(good)
    assert s["cost"]["charged_usd"] == "0" and s["cost"]["model_calls"] == 0
    assert s["integrity"]["gateway_chain"]["records"] == 0


def test_flipped_screenshot_byte_is_detected(copy):
    shot = sorted((copy / "referee" / "screenshots").glob("*.png"))[0]
    data = bytearray(shot.read_bytes())
    data[len(data) // 2] ^= 0xFF
    shot.write_bytes(bytes(data))
    s = results.summarize(copy)
    assert not s["integrity"]["ok"]
    assert s["integrity"]["screenshots_mismatched"] == [f"screenshots/{shot.name}"]


def test_deleted_screenshot_is_detected(copy):
    shot = sorted((copy / "referee" / "screenshots").glob("*.png"))[0]
    shot.unlink()
    s = results.summarize(copy)
    assert not s["integrity"]["ok"] and s["integrity"]["screenshots_missing"] == [f"screenshots/{shot.name}"]


def test_truncated_episodes_is_incomplete_and_replay_disagrees(copy):
    p = copy / "referee" / "episodes.jsonl"
    p.write_text(p.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    s = results.summarize(copy, run_replay=True)
    assert s["completeness"]["flag"] == "INCOMPLETE" and s["completeness"]["finished_episodes"] == 1
    assert any("1 of 2" in r for r in s["completeness"]["reasons"])
    assert not s["integrity"]["ok"] and s["integrity"]["replay_receipt"]["reproduced"] is False


def test_garbled_jsonl_counts_parse_errors(copy):
    p = copy / "referee" / "episodes.jsonl"
    p.write_text(p.read_text(encoding="utf-8") + '{"episode": 3, "outc\n', encoding="utf-8")
    s = results.summarize(copy)
    assert s["integrity"]["parse_errors"]["episodes"] == 1 and not s["integrity"]["ok"]


def test_deleted_files_are_unavailable_not_invented(copy):
    (copy / "referee" / "episodes.jsonl").unlink()
    s = results.summarize(copy)
    assert s["episodes"] == [] and s["completeness"]["incomplete"] and not s["integrity"]["ok"]
    assert "referee/episodes.jsonl missing" in s["completeness"]["reasons"]
    (copy / "host_session.json").unlink()
    s = results.summarize(copy)
    assert s["completeness"]["host_status"] == "unavailable" and s["cost"]["available"] is False


def test_hand_built_aborted_session_is_flagged(tmp_path):
    ref = tmp_path / "referee"
    ref.mkdir()
    (tmp_path / "host_session.json").write_text(json.dumps({
        "status": "aborted_host_failure", "failure": "RuntimeError: boom", "player_is_ai": True, "player_exit_code": -9,
        "watchdog_fired": True, "gateway_session": {"stop_reason": "budget_exhausted"}, "config": {}}), encoding="utf-8")
    (ref / "session.json").write_text(json.dumps({"status": "aborted", "budgets": {"max_episodes": 10},
                                                  "player": {"is_ai": True, "label": "x"}}), encoding="utf-8")
    (ref / "episodes.jsonl").write_text(json.dumps({"episode": 1, "outcome": "crashed", "utc": "t"}) + "\n", encoding="utf-8")
    s = results.summarize(tmp_path)
    c = s["completeness"]
    assert c["flag"] == "INCOMPLETE" and c["stop_reason"] == "budget_exhausted"
    assert s["header"]["label"] == "AI session"
    assert s["episodes"][0]["outcome"] == "crashed" and s["episodes"][0]["frames"] == "unavailable"
    assert not s["integrity"]["ok"]
    assert "INCOMPLETE" in results.render_text(s)


def test_cli_writes_json_and_exit_code(good, copy, tmp_path):
    out = tmp_path / "s.json"
    assert results.main(["summarize", str(good), "--json", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["header"]["label"] == "scripted NON-AI baseline"
    (copy / "referee" / "episodes.jsonl").unlink()
    assert results.main(["summarize", str(copy)]) == 1


def test_same_keyset_seed_script_is_deterministic(good, tmp_path):
    other = tmp_path / "again"
    _run(other)
    a, b = results.summarize(good), results.summarize(other)

    def strip(s):
        return [{k: v for k, v in r.items() if k != "utc"} for r in s["episodes"]]

    assert strip(a) == strip(b)
    assert _image_hashes(good) == _image_hashes(other) and _image_hashes(good)
    assert [e["end_screenshot_sha256"] for e in _episodes(good)] == [e["end_screenshot_sha256"] for e in _episodes(other)]
