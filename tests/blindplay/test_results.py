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


# ---------------------------------------------------------------- request-limit censoring (Mission 018)
def _run_limited(out: Path, max_requests: int, episodes=2) -> None:
    rc = host_mod.main(["--out", str(out), "--script", "idle", "--keyset", "keyset.v2", "--episodes", str(episodes),
                        "--episode-frame-budget", "60", "--max-requests", str(max_requests)])
    assert rc == 0


@pytest.fixture(scope="module")
def censored(tmp_path_factory) -> Path:
    reason = isolation.supported()
    if reason:
        pytest.skip(reason)
    out = tmp_path_factory.mktemp("censored") / "session"
    _run_limited(out, 3)
    return out


def test_cli_max_requests_reaches_the_host_and_referee(censored):
    host = json.loads((censored / "host_session.json").read_text(encoding="utf-8"))
    ref = json.loads((censored / "referee" / "session.json").read_text(encoding="utf-8"))
    assert host["config"]["max_requests"] == 3 and ref["budgets"]["max_requests"] == 3


def test_request_limit_censoring_is_reported(censored):
    s = results.summarize(censored, run_replay=True)
    c = s["completeness"]
    cen = c["censoring"]
    assert cen["flag"] == "CENSORED_BY_REQUEST_LIMIT" and c["flag"] == "INCOMPLETE" and c["incomplete"]
    assert cen["max_requests"] == 3 and cen["planned_episodes"] == 2
    assert cen["finished_episodes"] < 2 and cen["finished_episodes"] == c["finished_episodes"]
    assert cen["requests_used"] == 3 and cen["requests_rejected_over_limit"] >= 1
    assert s["header"]["max_requests"] == 3
    assert s["integrity"]["ok"], s["integrity"]
    assert s["integrity"]["replay_receipt"]["reproduced"] is True
    text = results.render_text(s)
    assert "CENSORED_BY_REQUEST_LIMIT" in text and "max_requests=3" in text and "NOT a complete run" in text


def test_normal_session_is_not_flagged_as_censored(tmp_path):
    reason = isolation.supported()
    if reason:
        pytest.skip(reason)
    out = tmp_path / "s"
    _run_limited(out, 20000, episodes=1)
    s = results.summarize(out)
    assert s["completeness"]["censoring"]["flag"] == "not_censored"
    assert s["completeness"]["flag"] == "complete" and s["header"]["max_requests"] == 20000
    assert "CENSORED" not in results.render_text(s)


def test_censoring_unavailable_facts_are_marked_not_invented(tmp_path):
    ref = tmp_path / "referee"
    ref.mkdir()
    (tmp_path / "host_session.json").write_text(json.dumps({"status": "closed", "config": {}}), encoding="utf-8")
    (ref / "session.json").write_text(json.dumps({"status": "closed", "budgets": {"max_episodes": 3}}), encoding="utf-8")
    s = results.summarize(tmp_path)
    assert s["completeness"]["censoring"]["flag"] == "unavailable"
    assert s["header"]["max_requests"] == "unavailable" and s["header"]["condition"] == "unavailable"


def test_hand_built_censored_session_without_files(tmp_path):
    ref = tmp_path / "referee"
    ref.mkdir()
    (tmp_path / "host_session.json").write_text(json.dumps({"status": "closed", "config": {}}), encoding="utf-8")
    (ref / "session.json").write_text(json.dumps({
        "status": "closed", "budgets": {"max_episodes": 10, "max_requests": 1000},
        "counts": {"requests": 1001, "episodes_finished": 2}}), encoding="utf-8")
    (ref / "player_transcript.jsonl").write_text(
        json.dumps({"request_index": 1001, "request": {}, "response": {"error": "request budget exhausted"}}) + "\n", encoding="utf-8")
    cen = results.summarize(tmp_path)["completeness"]["censoring"]
    assert cen["flag"] == "CENSORED_BY_REQUEST_LIMIT" and cen["max_requests"] == 1000 and cen["requests_used"] == 1000
    assert cen["planned_episodes"] == 10


def test_condition_only_from_the_run_log(tmp_path):
    root = tmp_path / "root"
    sess = root / "matched-1000_01_idle"
    ref = sess / "referee"
    ref.mkdir(parents=True)
    (sess / "host_session.json").write_text(json.dumps({"status": "closed", "config": {}}), encoding="utf-8")
    (ref / "session.json").write_text(json.dumps({"status": "closed", "budgets": {"max_episodes": 1, "max_requests": 1000}}),
                                      encoding="utf-8")
    assert results.summarize(sess)["header"]["condition"] == "unavailable"   # nothing recorded, nothing inferred
    (root / "baseline_run_log.json").write_text(json.dumps({"runs": [
        {"name": "01_idle", "subdir": "matched-1000_01_idle", "condition": "matched-1000", "max_requests": 1000}]}), encoding="utf-8")
    h = results.summarize(sess)["header"]
    assert h["condition"] == "matched-1000" and h["condition_max_requests_agrees"] is True
    (root / "baseline_run_log.json").write_text(json.dumps({"runs": [
        {"name": "01_idle", "subdir": "matched-1000_01_idle", "condition": "matched-1000", "max_requests": 20000}]}), encoding="utf-8")
    assert results.summarize(sess)["header"]["condition_max_requests_agrees"] is False


def _hand_session(sess: Path, *, max_requests=1000, requests=None, planned=3, finished=1) -> None:
    ref = sess / "referee"
    ref.mkdir(parents=True)
    (sess / "host_session.json").write_text(json.dumps({"status": "closed", "config": {}}), encoding="utf-8")
    counts = {} if requests is None else {"requests": requests}
    (ref / "session.json").write_text(json.dumps({"status": "closed", "budgets": {"max_episodes": planned, "max_requests": max_requests},
                                                  "counts": counts}), encoding="utf-8")
    (ref / "episodes.jsonl").write_text(
        "".join(json.dumps({"episode": n + 1, "outcome": "crashed", "utc": f"t{n}"}) + "\n" for n in range(finished)), encoding="utf-8")


def test_disagreeing_condition_is_a_conflict_and_incomplete(tmp_path):
    root = tmp_path / "root"
    sess = root / "matched-1000_01_idle"
    _hand_session(sess, max_requests=20000, planned=1, finished=1)
    (sess / "baseline_condition.json").write_text(json.dumps({"condition": "matched-1000", "max_requests": 1000}), encoding="utf-8")
    s = results.summarize(sess)
    assert s["header"]["condition"] == "CONFLICT" and s["header"]["condition_recorded"] == "matched-1000"
    assert s["completeness"]["flag"] == "INCOMPLETE" and any("CONFLICT" in r for r in s["completeness"]["reasons"])
    assert not s["integrity"]["ok"] and s["integrity"]["problems"]
    p = tmp_path / "out.json"
    assert results.main(["summarize", str(sess), "--json", str(p)]) == 1


def test_stopping_exactly_at_the_limit_is_censored_but_a_full_run_is_not(tmp_path):
    a = tmp_path / "a"
    _hand_session(a, max_requests=1000, requests=1000, planned=3, finished=1)   # no rejection record at all
    cen = results.summarize(a)["completeness"]["censoring"]
    assert cen["flag"] == "CENSORED_BY_REQUEST_LIMIT" and cen["requests_used"] == 1000
    b = tmp_path / "b"
    _hand_session(b, max_requests=1000, requests=1000, planned=3, finished=3)
    assert results.summarize(b)["completeness"]["censoring"]["flag"] == "limit_reached_run_complete"
    c = tmp_path / "c"
    _hand_session(c, max_requests=1000, requests=999, planned=3, finished=1)
    assert results.summarize(c)["completeness"]["censoring"]["flag"] == "not_censored"


def test_run_log_fallback_matches_subdir_only_never_name(tmp_path):
    root = tmp_path / "root"
    m, d = root / "matched-1000_01_idle", root / "diagnostic-20000_01_idle"
    _hand_session(m, max_requests=1000, planned=1)
    _hand_session(d, max_requests=20000, planned=1)
    (root / "baseline_run_log.json").write_text(json.dumps({"runs": [
        {"name": "01_idle", "subdir": "matched-1000_01_idle", "condition": "matched-1000", "max_requests": 1000},
        {"name": "01_idle", "subdir": "diagnostic-20000_01_idle", "condition": "diagnostic-20000", "max_requests": 20000}]}),
        encoding="utf-8")
    assert results.summarize(m)["header"]["condition"] == "matched-1000"
    assert results.summarize(d)["header"]["condition"] == "diagnostic-20000"
    other = root / "01_idle"   # a directory named like the run but not a recorded subdir
    _hand_session(other, max_requests=1000, planned=1)
    assert results.summarize(other)["header"]["condition"] == "unavailable"
