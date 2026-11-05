"""Summarize a blind-play host session directory from its recorded files.

Outcomes come from the referee's ``episodes.jsonl`` (the trusted record), never from a screenshot or HUD.
Whatever is missing is reported as ``"unavailable"``; nothing is defaulted or invented. Whether the player was
an AI is read from the recorded manifest, not from any command-line flag. ``--replay`` re-runs the referee on a
COPY of the referee directory, so the evidence directory is never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from rewardbench.blindplay import model_gateway, replay as replay_mod

UNAVAILABLE = "unavailable"
TIMEOUT_OUTCOME = "frame_budget_exhausted"
CENSORED = "CENSORED_BY_REQUEST_LIMIT"
BUDGET_REJECTION = "request budget exhausted"   # session.Session.handle: later requests are refused, the session is not ended


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]] | None, int]:
    """(records, parse_error_count); records is None when the file is absent."""
    if not path.is_file():
        return None, 0
    records, errors = [], 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            errors += 1
            continue
        if isinstance(value, dict):
            records.append(value)
        else:
            errors += 1
    return records, errors


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _get(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return UNAVAILABLE
        d = d[k]
    return UNAVAILABLE if d is None else d


def _condition(root: Path) -> dict[str, Any]:
    """Baseline condition, only if a run log or per-run file RECORDED it; never inferred from names or budgets."""
    rec = _read_json(root / "baseline_condition.json")
    if rec is None:
        log = _read_json(root.parent / "baseline_run_log.json")
        for r in (log or {}).get("runs", []) if isinstance(log, dict) else []:
            if isinstance(r, dict) and r.get("subdir") == root.name and "condition" in r:
                rec = r
                break
    if rec is None or "condition" not in rec:
        return {"condition": UNAVAILABLE, "condition_role": UNAVAILABLE, "condition_max_requests": UNAVAILABLE}
    return {"condition": rec["condition"], "condition_role": rec.get("condition_role", UNAVAILABLE),
            "condition_max_requests": rec.get("max_requests", UNAVAILABLE)}


def _censoring(rsess: dict[str, Any] | None, ptrans: list[dict[str, Any]] | None, referee_log: list[dict[str, Any]] | None,
               planned: Any, finished: int) -> dict[str, Any]:
    """Did the game-request limit end the session before the planned episodes finished? Recorded facts only."""
    max_req, used_raw = _get(rsess, "budgets", "max_requests"), _get(rsess, "counts", "requests")
    rejected: Any = UNAVAILABLE if ptrans is None else sum(
        1 for e in ptrans if isinstance(e.get("response"), dict) and e["response"].get("error") == BUDGET_REJECTION)
    over = isinstance(max_req, int) and isinstance(used_raw, int) and used_raw > max_req
    at_limit = isinstance(max_req, int) and isinstance(used_raw, int) and used_raw >= max_req
    # a player that stops exactly at the limit leaves no rejection record, so used >= limit counts as reached
    hit = over or (isinstance(rejected, int) and rejected > 0) or at_limit
    out: dict[str, Any] = {"max_requests": max_req, "planned_episodes": planned, "finished_episodes": finished,
                           "requests_recorded": used_raw, "requests_rejected_over_limit": rejected,
                           "requests_used": UNAVAILABLE, "partial_episode": UNAVAILABLE}
    if isinstance(max_req, int) and isinstance(used_raw, int):
        out["requests_used"] = min(used_raw, max_req)
    elif isinstance(rejected, int) and rejected > 0 and isinstance(max_req, int):
        out["requests_used"] = max_req
    if max_req == UNAVAILABLE or (not hit and (used_raw == UNAVAILABLE and rejected == UNAVAILABLE)):
        out["flag"] = "unavailable"
    elif not hit:
        out["flag"] = "not_censored"
    elif planned == UNAVAILABLE:
        out["flag"] = "unavailable"
        out["note"] = "the request limit was reached but the planned episode count is unavailable"
    elif finished < planned:
        out["flag"] = CENSORED
        last_ep = max((r.get("episode", 0) for r in referee_log or [] if isinstance(r.get("episode"), int)), default=0)
        if last_ep > finished:
            frames = [r.get("episode_frame_after", 0) for r in referee_log or []
                      if r.get("event") == "act" and r.get("episode") == last_ep]
            out["partial_episode"] = {"episode": last_ep, "frames_played": max(frames, default=0), "recorded_as_finished": False}
        elif referee_log is not None:
            out["partial_episode"] = "none (no episode was in progress when the limit ended the session)"
    else:
        out["flag"] = "limit_reached_run_complete"
    return out


def summarize(session_dir: Path, *, run_replay: bool = False) -> dict[str, Any]:
    root = Path(session_dir)
    ref = root / "referee"
    problems: list[str] = []
    host = _read_json(root / "host_session.json")
    rsess = _read_json(ref / "session.json")
    if host is None:
        problems.append("host_session.json missing or unreadable")
    if rsess is None:
        problems.append("referee/session.json missing or unreadable")

    # ---- who played (from the recorded manifests only)
    flags = {"host": _get(host, "player_is_ai"), "referee": _get(rsess, "player", "is_ai")}
    known = {v for v in flags.values() if isinstance(v, bool)}
    if len(known) == 1:
        is_ai: Any = known.pop()
    else:
        is_ai = UNAVAILABLE
        if len(known) > 1:
            problems.append("host and referee manifests disagree on player_is_ai")
    label = {True: "AI session", False: "scripted NON-AI baseline"}.get(is_ai, "player type unavailable")
    header = {"player_is_ai": is_ai, "label": label, "player_label": _get(rsess, "player", "label"),
              "keyset": _get(rsess, "player_contract", "keyset"), "seed": _get(rsess, "environment", "seed"),
              "script": _get(host, "config", "script"), "script_seed": _get(host, "config", "script_seed"),
              "mode": _get(host, "config", "mode"), "session_dir": str(root),
              "max_requests": _get(rsess, "budgets", "max_requests"), **_condition(root)}
    cm = header["condition_max_requests"]
    header["condition_max_requests_agrees"] = (UNAVAILABLE if UNAVAILABLE in (cm, header["max_requests"])
                                               else cm == header["max_requests"])

    conflict = header["condition_max_requests_agrees"] is False
    if conflict:
        header["condition_recorded"] = header["condition"]
        header["condition"] = "CONFLICT"
        problems.append(f"condition {header['condition_recorded']!r} recorded max_requests={cm} but session recorded "
                        f"{header['max_requests']}")

    # ---- episodes (trusted referee data), chronological
    episodes, ep_errors = _read_jsonl(ref / "episodes.jsonl")
    rows = []
    for e in sorted(episodes or [], key=lambda r: (str(r.get("utc", "")), r.get("episode", 0))):
        term = e.get("terminal_tick_state")
        outcome = e.get("outcome", UNAVAILABLE)
        rows.append({"episode": e.get("episode", UNAVAILABLE), "outcome": outcome, "timed_out": outcome == TIMEOUT_OUTCOME,
                     "frames": e.get("frames", UNAVAILABLE), "native_score": e.get("native_score", UNAVAILABLE),
                     "native_message": e.get("native_message", UNAVAILABLE), "end_seq": e.get("end_seq", UNAVAILABLE),
                     "utc": e.get("utc", UNAVAILABLE),
                     "terminal_fuel": term.get("fuel", UNAVAILABLE) if isinstance(term, dict) else UNAVAILABLE,
                     "terminal_altitude": term.get("altitude", UNAVAILABLE) if isinstance(term, dict) else UNAVAILABLE})

    # ---- completeness
    planned = _get(rsess, "budgets", "max_episodes")
    host_status, ref_status = _get(host, "status"), _get(rsess, "status")
    exit_code = _get(host, "player_exit_code")
    why: list[str] = []
    if conflict:
        why.append(f"condition CONFLICT: recorded {header['condition_recorded']!r} (max_requests={cm}) vs session max_requests={header['max_requests']}")
    if episodes is None:
        why.append("referee/episodes.jsonl missing")
    if planned == UNAVAILABLE:
        why.append("planned episode count unavailable")
    elif len(rows) < planned:
        why.append(f"only {len(rows)} of {planned} planned episodes recorded")
    if host_status != "closed":
        why.append(f"host status {host_status!r} (not 'closed')")
    if ref_status != "closed":
        why.append(f"referee status {ref_status!r} (not 'closed')")
    if exit_code != 0:
        why.append(f"player exit code {exit_code!r}")
    if _get(host, "watchdog_fired") is not False:
        why.append(f"watchdog_fired={_get(host, 'watchdog_fired')!r}")
    for key in ("failure", "gateway_failure"):
        if _get(host, key) != UNAVAILABLE:
            why.append(f"{key}: {_get(host, key)}")
    stop_reason = _get(host, "gateway_session", "stop_reason")
    if stop_reason != UNAVAILABLE:
        why.append(f"gateway stop reason: {stop_reason}")
    censoring = _censoring(rsess, _read_jsonl(ref / "player_transcript.jsonl")[0], _read_jsonl(ref / "referee.jsonl")[0],
                           planned, len(rows))
    if censoring["flag"] == CENSORED:
        why.append(f"{CENSORED}: {len(rows)} of {planned} planned episodes finished; limit max_requests={censoring['max_requests']}, "
                   f"requests used {censoring['requests_used']}")
    completeness = {"planned_episodes": planned, "censoring": censoring, "finished_episodes": len(rows), "host_status": host_status,
                    "referee_status": ref_status, "player_exit_code": exit_code,
                    "watchdog_fired": _get(host, "watchdog_fired"), "stop_reason": stop_reason,
                    "incomplete": bool(why), "flag": "INCOMPLETE" if why else "complete", "reasons": why}

    # ---- integrity
    ptrans, pt_err = _read_jsonl(ref / "player_transcript.jsonl")
    htrans, ht_err = _read_jsonl(root / "host_transcript.jsonl")
    _, rj_err = _read_jsonl(ref / "referee.jsonl")
    shots_expected: dict[str, str] = {}
    transcript_hashes: list[str] = []
    for entry in ptrans or []:
        img = (entry.get("response") or {}).get("image")
        if isinstance(img, dict) and "file" in img and "sha256" in img:
            shots_expected[img["file"]] = img["sha256"]
            transcript_hashes.append(img["sha256"])
    missing, mismatched = [], []
    for rel, digest in sorted(shots_expected.items()):
        f = ref / rel
        if not f.is_file():
            missing.append(rel)
        elif _sha(f) != digest:
            mismatched.append(rel)
    shots_dir = ref / "screenshots"
    on_disk = sorted(p.relative_to(ref).as_posix() for p in shots_dir.glob("*") if p.is_file()) if shots_dir.is_dir() else []
    unreferenced = [p for p in on_disk if p not in shots_expected]
    frames_bad = []
    for e in episodes or []:
        if isinstance(e.get("episode"), int):
            f = ref / "referee_frames" / f"episode_{e['episode']:04d}_start.png"
            if f.is_file() and e.get("start_frame_sha256") != _sha(f):
                frames_bad.append(f.name)
    host_hashes = [(e.get("response") or {})["image"].get("sha256") for e in htrans or []
                   if isinstance((e.get("response") or {}).get("image"), dict)]
    host_vs_referee: Any = UNAVAILABLE if htrans is None or ptrans is None else host_hashes == transcript_hashes
    gw_records, gw_err = _read_jsonl(root / "gateway_transcript.jsonl")
    if gw_records is None:
        chain: Any = UNAVAILABLE
    elif not gw_records and gw_err == 0:
        chain = {"valid": True, "records": 0, "note": "empty gateway transcript (no model gateway activity)"}
    elif gw_err:
        chain = {"valid": False, "parse_errors": gw_err}
    else:
        chain = model_gateway.verify_transcript(gw_records)
        tip = _get(host, "gateway_session", "transcript_tip_sha256")
        if chain.get("valid") and tip != UNAVAILABLE and tip != chain.get("tip_sha256"):
            chain = {**chain, "valid": False, "note": "tip differs from host manifest"}
    receipt: Any = _replay_copy(ref) if run_replay else UNAVAILABLE
    required = (root / "host_session.json", root / "host_transcript.jsonl", ref / "session.json", ref / "episodes.jsonl",
                ref / "player_transcript.jsonl", ref / "referee.jsonl")
    checks = {
        "required_files_present": all(p.is_file() for p in required),
        "screenshots_all_present": not missing,
        "screenshots_hashes_match_transcript": not mismatched,
        "no_unreferenced_screenshots": not unreferenced,
        "episode_start_frames_match": not frames_bad,
        "no_transcript_parse_errors": (pt_err + ht_err + ep_errors + rj_err + gw_err) == 0,
        "host_and_referee_screenshot_hashes_agree": host_vs_referee is True,
        "gateway_chain_valid": chain == UNAVAILABLE or chain.get("valid") is True,
    }
    if run_replay:
        checks["replay_reproduced"] = isinstance(receipt, dict) and receipt.get("reproduced") is True
    integrity = {"ok": all(checks.values()) and not problems, "checks": checks, "problems": problems,
                 "screenshots_checked": len(shots_expected), "screenshots_missing": missing,
                 "screenshots_mismatched": mismatched, "screenshots_unreferenced": unreferenced,
                 "episode_start_frames_mismatched": frames_bad,
                 "parse_errors": {"player_transcript": pt_err, "host_transcript": ht_err, "episodes": ep_errors,
                                  "referee": rj_err, "gateway_transcript": gw_err},
                 "gateway_chain": chain, "replay_receipt": receipt}

    return {"schema": "react.blindplay.results-summary.v1", "header": header, "episodes": rows,
            "outcome_counts": _counts(rows), "completeness": completeness, "integrity": integrity,
            "cost": _cost(host, gw_records, is_ai, chain)}


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[str(r["outcome"])] = out.get(str(r["outcome"]), 0) + 1
    return out


def _cost(host: dict[str, Any] | None, records: list[dict[str, Any]] | None, is_ai: Any, chain: Any) -> dict[str, Any]:
    if host is None:
        return {"available": False, "note": UNAVAILABLE}
    if _get(host, "gateway_session") == UNAVAILABLE and is_ai is False:
        return {"available": True, "model_calls": 0, "input_tokens": 0, "output_tokens": 0, "charged_usd": "0",
                "note": "no model gateway: scripted player, nothing was billed"}
    if records is None:
        return {"available": False, "note": "gateway_transcript.jsonl " + UNAVAILABLE}
    tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    calls = 0
    for r in records:
        usage = r.get("usage")
        if isinstance(usage, dict):
            calls += 1
            for k in tokens:
                tokens[k] += int(usage.get(k, 0) or 0)
    return {"available": True, "model_calls_with_usage": calls, **tokens,
            "charged_usd": chain.get("charged_usd", UNAVAILABLE) if isinstance(chain, dict) else UNAVAILABLE,
            "gateway_manifest_charged_usd": _get(host, "gateway_session", "charged_usd")}


def _replay_copy(ref: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="blindplay-replay-") as tmp:
        copy = Path(tmp) / "referee"
        try:
            shutil.copytree(ref, copy, ignore=shutil.ignore_patterns("replays"))
            receipt = replay_mod.replay(copy)
        except Exception as exc:  # noqa: BLE001 - a tampered session may fail anywhere; that is itself the finding
            return {"reproduced": False, "error": f"{type(exc).__name__}: {str(exc)[:500]}"}
    receipt = dict(receipt)
    receipt["original"] = str(ref)
    receipt["replay"] = "(temporary copy, discarded)"
    return receipt


def render_text(summary: dict[str, Any]) -> str:
    h, c, i, k = summary["header"], summary["completeness"], summary["integrity"], summary["cost"]
    out = [f"=== {h['label'].upper()} === player_is_ai={h['player_is_ai']}", f"player_label: {h['player_label']}",
           f"keyset={h['keyset']} seed={h['seed']} script={h['script']} script_seed={h['script_seed']}",
           f"status: {c['flag']}  (planned {c['planned_episodes']}, finished {c['finished_episodes']}, host {c['host_status']}, "
           f"referee {c['referee_status']}, player exit {c['player_exit_code']}, watchdog {c['watchdog_fired']})"]
    out += [f"  reason: {r}" for r in c["reasons"]]
    out.append(f"max_requests={h['max_requests']} condition={h['condition']} (condition recorded in run log only; 'unavailable' = not recorded)")
    if h["condition_max_requests_agrees"] is False:
        out.append(f"  WARNING: run log says max_requests={h['condition_max_requests']} but the session recorded {h['max_requests']}")
    cen = c["censoring"]
    if cen["flag"] == CENSORED:
        out.append(f"*** {CENSORED}: planned {cen['planned_episodes']} episodes, finished {cen['finished_episodes']}, "
                   f"max_requests={cen['max_requests']}, requests used {cen['requests_used']} "
                   f"({cen['requests_rejected_over_limit']} rejected over the limit); partial episode: {cen['partial_episode']}. "
                   f"This is NOT a complete run; do not compare it as if all planned episodes were played. ***")
    elif cen["flag"] != "not_censored":
        out.append(f"request-limit censoring: {cen['flag']}")
    out.append("episode  outcome                      timeout  frames  score  fuel  altitude")
    for r in summary["episodes"]:
        out.append(f"{r['episode']!s:<8} {r['outcome']!s:<28} {'YES' if r['timed_out'] else 'no':<8} {r['frames']!s:<7} "
                   f"{r['native_score']!s:<6} {r['terminal_fuel']!s:<5} {r['terminal_altitude']!s}")
    out.append(f"outcome counts: {summary['outcome_counts']}")
    out.append(f"integrity: {'OK' if i['ok'] else 'FAILED'}")
    out += [f"  {name}: {'ok' if ok else 'FAILED'}" for name, ok in i["checks"].items()]
    out += [f"  problem: {p}" for p in i["problems"]]
    if i["replay_receipt"] != UNAVAILABLE:
        out.append(f"replay reproduced: {i['replay_receipt'].get('reproduced')}")
    out.append(f"cost: {json.dumps(k)}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.results", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("summarize")
    p.add_argument("session", type=Path)
    p.add_argument("--json", type=Path, default=None)
    p.add_argument("--replay", action="store_true", help="verify by re-running the referee on a copy")
    args = parser.parse_args(argv)
    summary = summarize(args.session, run_replay=args.replay)
    if args.json:
        args.json.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(render_text(summary))
    return 0 if summary["integrity"]["ok"] and not summary["completeness"]["incomplete"] else 1


if __name__ == "__main__":
    sys.exit(main())
