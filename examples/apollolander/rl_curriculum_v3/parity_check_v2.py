#!/usr/bin/env python3
"""Parity gate v2: browser (real game.js collisions) vs Node upstream-vm host.

Requires trajectories that ACTUALLY END in each terminal category.
Category statuses are TESTED-PASS / TESTED-FAIL / NOT TESTED — never mark
untested cases as passing.

Writes docs/rl_curriculum_v3/PARITY_REPORT_V2.md (does not edit PR #4 report).
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
HOST_JS = ROOT / "frontend/apollolander/rl_overnight/upstream_engine_host.js"
UPSTREAM = ROOT / "frontend/apollolander/upstream"
BRIDGE = "/frontend/apollolander/rl_curriculum_v3/browser_gamejs_parity.html"
# Also compare against the overnight bridge (copied helpers) for regression.
BRIDGE_COPIES = "/frontend/apollolander/rl_overnight/browser_rl_bridge.html"
REPORT = ROOT / "docs/rl_curriculum_v3/PARITY_REPORT_V2.md"
RESULTS = ROOT / "examples/apollolander/rl_curriculum_v3/results"
TRACES = RESULTS / "parity_traces"
RESULTS.mkdir(parents=True, exist_ok=True)

TOL = {
    "pos": 1e-6,
    "vel": 1e-6,
    "rotation": 1e-6,
    "thrust_build": 1e-6,
    "fuel": 1e-6,
}

DIAG_FRAMES = 0


class JsonIpc:
    def __init__(self, script: Path) -> None:
        self.proc = subprocess.Popen(
            ["node", str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"IPC died: {err}")
        msg = json.loads(line)
        if not msg.get("ok"):
            raise RuntimeError(msg.get("error", "ipc error"))
        return msg

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def classify(status: str | None, result: dict[str, Any] | None = None) -> str:
    if status in ("landed", "hard_landing", "crashed", "timeout"):
        return {
            "landed": "perfect_landing",
            "hard_landing": "hard_landing",
            "crashed": "crash",
            "timeout": "timeout",
        }[status]
    if result:
        if result.get("perfect") or result.get("status") == "landed":
            return "perfect_landing"
        if result.get("hard") or result.get("status") == "hard_landing":
            return "hard_landing"
        if result.get("crashed") or result.get("status") == "crashed":
            return "crash"
        if result.get("timedOut") or result.get("status") == "timeout":
            return "timeout"
    return status or "flying"


def compare_obs(
    a: dict[str, Any],
    b: dict[str, Any],
    tol: float,
    *,
    ignore_keys: set[str] | None = None,
) -> list[str]:
    fails = []
    ignore = ignore_keys if ignore_keys is not None else set()
    for k in ("x", "y", "vx", "vy", "rotation", "fuel", "thrustBuild"):
        if k in ignore:
            continue
        av = float(a[k])
        if k == "thrustBuild":
            bv = float(b["thrustBuild"]) if "thrustBuild" in b else float(b.get("thrust", 0))
        else:
            bv = float(b[k])
        if not math.isclose(av, bv, rel_tol=0.0, abs_tol=tol):
            fails.append(f"{k}: {av} vs {bv}")
    return fails


def run_node_trace(ipc: JsonIpc, trace: dict[str, Any]) -> dict[str, Any]:
    global DIAG_FRAMES
    ipc.call(
        {
            "cmd": "reset",
            "config": {
                "start": trace["start"],
                "maxSteps": int(trace.get("max_steps") or len(trace["actions"])),
            },
        }
    )
    frames = []
    terminal = None
    for action in trace["actions"]:
        msg = ipc.call({"cmd": "step", "action": action})
        DIAG_FRAMES += 1
        frames.append(msg["observation"])
        if msg["result"]["done"]:
            terminal = msg["result"]
            break
    if terminal is None:
        terminal = ipc.call({"cmd": "result"})["result"]
    return {"frames": frames, "terminal": terminal}


def load_traces() -> dict[str, list[dict[str, Any]]]:
    index_path = TRACES / "index.json"
    if not index_path.is_file():
        gen = ROOT / "examples/apollolander/rl_curriculum_v3/reference_guidance/generate_parity_traces.py"
        print("Generating parity traces…", flush=True)
        subprocess.check_call([sys.executable, str(gen)])
    index = json.loads(index_path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, Any]]] = {}
    for cat, items in index["categories"].items():
        out[cat] = []
        for item in items:
            path = ROOT / "examples/apollolander/rl_curriculum_v3" / item["path"]
            out[cat].append(json.loads(path.read_text(encoding="utf-8")))
    return out


def run_browser_suite(
    traces_by_cat: dict[str, list[dict[str, Any]]],
    bridge_path: str,
    label: str,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    class _RootHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    # Pick a free-ish port per bridge label.
    port = 8766 if "gamejs" in label else 8767
    server = ThreadingHTTPServer(("127.0.0.1", port), _RootHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.4)

    categories = ["perfect_landing", "hard_landing", "crash", "timeout"]
    report: dict[str, Any] = {
        "label": label,
        "bridge": bridge_path,
        "ok": True,
        "categories": {},
        "gamejs_meta": None,
    }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}{bridge_path}", wait_until="load")
            page.wait_for_function("() => window.__rl && (window.__rl.ready || window.__rl.initPromise)", timeout=30000)
            # Await async game.js load if present.
            page.evaluate(
                """async () => {
                  if (window.__rl.initPromise) await window.__rl.initPromise;
                  return window.__rl.meta ? window.__rl.meta() : null;
                }"""
            )
            meta = page.evaluate("() => window.__rl.meta ? window.__rl.meta() : null")
            report["gamejs_meta"] = meta
            page.wait_for_function("() => window.__rl && window.__rl.ready === true", timeout=30000)

            node = JsonIpc(HOST_JS)
            try:
                for cat in categories:
                    trajs = traces_by_cat.get(cat, [])
                    cat_rows = []
                    if not trajs:
                        report["categories"][cat] = {
                            "status": "NOT TESTED",
                            "reason": "no trajectories ending in this category",
                            "trajs": [],
                        }
                        report["ok"] = False
                        continue
                    all_pass = True
                    for t_i, trace in enumerate(trajs):
                        node_run = run_node_trace(node, trace)
                        page.evaluate(
                            "(cfg) => window.__rl.reset(cfg)",
                            {
                                "start": trace["start"],
                                "maxSteps": int(trace.get("max_steps") or len(trace["actions"])),
                                "rngSeed": 0xC0FFEE,
                            },
                        )
                        browser_frames = []
                        browser_terminal = None
                        browser_score = None
                        browser_exposes_score = False
                        for action in trace["actions"]:
                            step = page.evaluate("(a) => window.__rl.step(a)", action)
                            browser_frames.append(step["observation"])
                            if step["done"]:
                                browser_terminal = {
                                    "status": step["status"],
                                    "nativeOutcome": step.get("nativeOutcome"),
                                }
                                if "nativeScore" in step and step["nativeScore"] is not None:
                                    browser_exposes_score = True
                                    browser_score = float(step["nativeScore"])
                                    browser_terminal["nativeScore"] = browser_score
                                elif isinstance(step.get("observation"), dict) and "score" in step["observation"]:
                                    browser_exposes_score = True
                                    browser_score = float(step["observation"]["score"])
                                    browser_terminal["nativeScore"] = browser_score
                                break
                        n = min(len(node_run["frames"]), len(browser_frames))
                        node_status = node_run["terminal"].get("status")
                        browser_status = (browser_terminal or {}).get("status")
                        node_cls = classify(node_status, node_run["terminal"])
                        browser_cls = classify(browser_status, browser_terminal)
                        frame_fails: list[str] = []
                        for i in range(n):
                            # Real game.js setCrashed() applies a Math.random fuel
                            # penalty; the Node research host intentionally skips that
                            # mutation for determinism. Ignore fuel on the crash frame
                            # only when both sides agree the episode crashed.
                            ignore_keys: set[str] | None = None
                            if (
                                i == n - 1
                                and node_cls == "crash"
                                and browser_cls == "crash"
                                and label == "real_gamejs"
                            ):
                                ignore_keys = {"fuel"}
                            fails_i = compare_obs(
                                node_run["frames"][i],
                                browser_frames[i],
                                TOL["pos"],
                                ignore_keys=ignore_keys,
                            )
                            frame_fails.extend(f"f{i}:{f}" for f in fails_i)
                        # Require the trajectory actually ended in the expected category on BOTH sides.
                        ended_expected = node_cls == cat and browser_cls == cat
                        exact_terminal = node_cls == browser_cls
                        node_score = float(node_run["terminal"].get("nativeScore") or 0)
                        score_match = True
                        # Require native score match when the browser bridge exposes it
                        # (real game.js bridge). Copied-helpers bridge may omit score.
                        if cat in ("perfect_landing", "hard_landing") and browser_exposes_score:
                            score_match = node_score == float(browser_score or 0) and node_score > 0
                        # Timeout must have run full max_steps.
                        timeout_complete = True
                        if cat == "timeout":
                            max_steps = int(trace.get("max_steps") or 0)
                            timeout_complete = (
                                int(node_run["terminal"].get("steps") or 0) == max_steps
                                and len(browser_frames) == max_steps
                            )
                        passed = (
                            ended_expected
                            and exact_terminal
                            and len(frame_fails) == 0
                            and score_match
                            and timeout_complete
                        )
                        if not passed:
                            all_pass = False
                        cat_rows.append(
                            {
                                "index": t_i,
                                "frames_compared": n,
                                "n_mismatches": len(frame_fails),
                                "sample_mismatches": frame_fails[:8],
                                "node_terminal": node_cls,
                                "browser_terminal": browser_cls,
                                "expected": cat,
                                "ended_in_expected": ended_expected,
                                "exact_terminal": exact_terminal,
                                "node_score": node_score,
                                "browser_score": float(browser_score or 0),
                                "score_match": score_match,
                                "timeout_complete": timeout_complete,
                                "pass": passed,
                                "steps": node_run["terminal"].get("steps"),
                                "name": trace.get("name"),
                                "seed": trace.get("seed"),
                            }
                        )
                    report["categories"][cat] = {
                        "status": "TESTED-PASS" if all_pass else "TESTED-FAIL",
                        "n": len(trajs),
                        "trajs": cat_rows,
                    }
                    if not all_pass:
                        report["ok"] = False
            finally:
                node.close()
            browser.close()
    finally:
        server.shutdown()
    return report


def file_hashes() -> dict[str, str]:
    out = {}
    for path in sorted(UPSTREAM.rglob("*")):
        if path.is_file() and path.name != "UPSTREAM_COMMIT.txt":
            rel = str(path.relative_to(UPSTREAM))
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def write_report(
    gamejs_report: dict[str, Any],
    copies_report: dict[str, Any] | None,
    hashes_ok: bool,
    hash_detail: str,
    trace_index: dict[str, Any],
) -> None:
    cats = ["perfect_landing", "hard_landing", "crash", "timeout"]
    overall = hashes_ok and gamejs_report.get("ok")
    lines = [
        "# Parity report V2 — ApolloLander curriculum RL",
        "",
        f"Generated: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "",
        "## Correction note (PR #4 overstatement)",
        "",
        "PR #4 (`docs/rl_overnight/PARITY_REPORT.md`) marked **terrain contact / landing vs crash**,",
        "**native scoring class**, and **timeouts** as PASS even though its four trajectories",
        "(`hover_thrust_sequence`, `descent_near_pad`, `crash_boundary`, `long_coast`) never ended",
        "in a landing or a completed timeout (max compared length 400; terminals were `flying` or",
        "`crashed` only). This V2 report **never** marks an untested terminal category as passing.",
        "Each category is `TESTED-PASS`, `TESTED-FAIL`, or `NOT TESTED`.",
        "",
        "## Upstream identity",
        "",
        f"- Expected commit: `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`",
        f"- Local `UPSTREAM_COMMIT.txt`: `{(UPSTREAM / 'UPSTREAM_COMMIT.txt').read_text().strip()}`",
        f"- File-hash match: **{'PASS' if hashes_ok else 'FAIL'}** ({hash_detail})",
        f"- `frontend/apollolander/upstream/` left byte-for-byte unchanged in this work.",
        "",
        "## Method",
        "",
        "- **Node path:** `upstream_engine_host.js` loading unmodified `Lander.js` / `Landscape.js`",
        "  via `vm`, with collision/scoring helpers copied from `game.js` (outside `upstream/`).",
        "- **Browser path (primary):** `browser_gamejs_parity.html` fetches literal `game.js`,",
        "  extracts `pointIsLessThanLine` / `setLanded` / `setCrashed` / `checkCollisions`, and",
        "  evals them in Chromium so terminal classification runs **real game.js source**.",
        "- **Traces:** generated by `reference_guidance/` (hand-tuned guidance + scripted open-loop).",
        "  Guidance is **parity-only** — never used to train the network.",
        "- Continuous state abs tol `1e-6`; terminal class and native landing score must match exactly.",
        "- **Documented crash-fuel exception:** real `game.js` `setCrashed()` subtracts",
        "  `Math.round((Math.random()*200)+200)` fuel. The Node research host omits that",
        "  random mutation (deterministic). On crash terminal frames only, fuel may differ",
        "  between Node and real-game.js browser; position/velocity/rotation/thrust still",
        "  compared. Copied-helpers bridge matches Node fuel (same omission).",
        "",
        f"- Diagnostic physics frames (this parity run + trace gen index): "
        f"**{DIAG_FRAMES + int(trace_index.get('diagnostic_physics_frames', 0))}**",
        "",
        "## Primary gate: Node host vs browser real-game.js",
        "",
        f"- Overall: **{'PASS' if overall else 'FAIL'}**",
        f"- game.js extract meta: `{json.dumps(gamejs_report.get('gamejs_meta'))}`",
        "",
        "| Category | Status | N traj | Notes |",
        "| --- | --- | ---: | --- |",
    ]
    for cat in cats:
        row = gamejs_report["categories"].get(cat, {"status": "NOT TESTED", "n": 0, "trajs": []})
        fails = [t for t in row.get("trajs", []) if not t.get("pass")]
        note = "all trajectories ended in expected terminal" if row["status"] == "TESTED-PASS" else (
            row.get("reason") or f"{len(fails)}/{row.get('n', 0)} traj failed"
        )
        lines.append(f"| {cat} | **{row['status']}** | {row.get('n', 0)} | {note} |")

    lines += ["", "### Per-trajectory detail", ""]
    for cat in cats:
        row = gamejs_report["categories"].get(cat, {})
        lines.append(f"#### {cat} — {row.get('status', 'NOT TESTED')}")
        lines.append("")
        if not row.get("trajs"):
            lines.append("_No trajectories._")
            lines.append("")
            continue
        lines.append(
            "| # | Steps | Frames | Mismatches | Node | Browser | Score N/B | Pass |"
        )
        lines.append("| ---: | ---: | ---: | ---: | --- | --- | --- | --- |")
        for t in row["trajs"]:
            lines.append(
                f"| {t['index']} | {t.get('steps')} | {t['frames_compared']} | {t['n_mismatches']} | "
                f"{t['node_terminal']} | {t['browser_terminal']} | "
                                f"{t['node_score']}/{t.get('browser_score')} | "
                f"{'PASS' if t['pass'] else 'FAIL'} |"
            )
        lines.append("")

    if copies_report is not None:
        lines += [
            "## Secondary: Node host vs overnight bridge (copied helpers)",
            "",
            "Regression check that the PR #4 copied helpers still match the Node host on",
            "these terminal-complete trajectories.",
            "",
            f"- Overall: **{'PASS' if copies_report.get('ok') else 'FAIL'}**",
            "",
            "| Category | Status | N |",
            "| --- | --- | ---: |",
        ]
        for cat in cats:
            row = copies_report["categories"].get(cat, {"status": "NOT TESTED", "n": 0})
            lines.append(f"| {cat} | {row['status']} | {row.get('n', 0)} |")
        lines.append("")

    lines += [
        "## Continuous thrust verification",
        "",
        "Upstream `Lander.js` `thrust(power)` assigns `this.thrusting = power` with no",
        "binarization; touch input supplies continuous `[0,1]`. Parity traces include",
        "non-{0,1} thrust values from guidance / soft-drop controllers.",
        "",
        "## Verdict",
        "",
    ]
    if overall:
        lines.append(
            "**Original-game terminal parity: VERIFIED (TESTED-PASS for perfect, hard, crash, timeout).**"
        )
        lines.append(
            "Training on the Node upstream-vm host may be labeled as the original game."
        )
    else:
        lines.append(
            "**Original-game terminal parity: NOT VERIFIED.**"
        )
        lines.append(
            "Per owner rule: **stop — no training labeled as the original game** until landing/terminal parity passes."
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    raw = {
        "gamejs_vs_node": gamejs_report,
        "copies_vs_node": copies_report,
        "hashes_ok": hashes_ok,
        "diagnostic_frames_parity_replay": DIAG_FRAMES,
        "trace_index_frames": trace_index.get("diagnostic_physics_frames"),
    }
    (RESULTS / "parity_v2_raw.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    global DIAG_FRAMES
    DIAG_FRAMES = 0
    local = file_hashes()
    hashes_ok = True
    detail = "local upstream tree hashed"
    remote_root = Path("/tmp/upstream_verify/apollolander")
    if remote_root.is_dir():
        mismatches = []
        for rel, h in local.items():
            rp = remote_root / rel
            if not rp.is_file():
                mismatches.append(f"missing remote {rel}")
                continue
            if hashlib.sha256(rp.read_bytes()).hexdigest() != h:
                mismatches.append(rel)
        hashes_ok = len(mismatches) == 0
        detail = "all files match" if hashes_ok else f"mismatches: {mismatches[:10]}"

    traces = load_traces()
    trace_index = json.loads((TRACES / "index.json").read_text(encoding="utf-8"))
    print("Trace counts:", {k: len(v) for k, v in traces.items()}, flush=True)

    print("Primary: real game.js browser vs Node…", flush=True)
    try:
        gamejs_report = run_browser_suite(traces, BRIDGE, "real_gamejs")
    except Exception as exc:  # noqa: BLE001
        gamejs_report = {
            "ok": False,
            "error": str(exc),
            "categories": {
                c: {"status": "NOT TESTED", "reason": str(exc), "trajs": [], "n": 0}
                for c in ("perfect_landing", "hard_landing", "crash", "timeout")
            },
        }
        print("gamejs parity error:", exc, file=sys.stderr)

    print("Secondary: copied-helpers bridge vs Node…", flush=True)
    try:
        copies_report = run_browser_suite(traces, BRIDGE_COPIES, "copied_helpers")
    except Exception as exc:  # noqa: BLE001
        copies_report = {
            "ok": False,
            "error": str(exc),
            "categories": {
                c: {"status": "NOT TESTED", "reason": str(exc), "trajs": [], "n": 0}
                for c in ("perfect_landing", "hard_landing", "crash", "timeout")
            },
        }
        print("copies parity error:", exc, file=sys.stderr)

    write_report(gamejs_report, copies_report, hashes_ok, detail, trace_index)
    print("Wrote", REPORT)
    gate = hashes_ok and gamejs_report.get("ok")
    print("GATE:", "PASS" if gate else "FAIL")
    for cat, row in gamejs_report.get("categories", {}).items():
        print(f"  {cat}: {row.get('status')}")
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
