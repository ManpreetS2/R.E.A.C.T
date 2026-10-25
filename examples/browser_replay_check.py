"""Drive replay.html and index.html in a real Chromium and save screenshots + results.

Manual evidence tool (needs `pip install playwright` and `playwright install chromium`;
not part of CI). Run from the repo root:
    python examples/browser_replay_check.py --out docs/assets/replay-evidence
It generates flights with the real physics, mutates copies to create tampered records,
serves the repo over a local http server and checks every control in the page.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import subprocess
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

from rewardbench.environments import make_environment
from rewardbench.environments.apollolander import constant_controller, demonstration_guidance_controller
from rewardbench.environments.apollolander.flight_record import trace_hash

ROOT = Path(__file__).resolve().parents[1]
EXP = "/frontend/apollolander/experiment"
RESULTS: list[dict] = []


def check(name: str, passed: bool, detail: object = "") -> None:
    RESULTS.append({"check": name, "passed": bool(passed), "detail": detail})
    print(("PASS " if passed else "FAIL ") + name, detail if detail != "" else "")


def make_fixtures(directory: Path) -> dict[str, Path]:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=8000)
    def flight(controller, seed):
        return adapter.evaluate(controller, [seed], revision=1, max_steps=8000, split="development")["episodes"][0]["flight_record"]
    records = {"landed": flight(demonstration_guidance_controller(), 0), "crashed": flight(constant_controller(0.0, 0), 2)}
    tracked = json.loads((ROOT / "docs/assets/v1-evidence/flights/offline_mock_development_episode.flight.json").read_text())
    records["timeout"] = tracked

    def mutated(name, fn):
        copy = json.loads(json.dumps(records["crashed"]))
        fn(copy)
        records[name] = copy
    def reseal(r): r["trace_length"] = len(r["trace"]); r["trace_hash"] = trace_hash(r["trace"])
    mutated("bad_trace_length", lambda r: r.update(trace_length=r["trace_length"] + 1))
    mutated("bad_trace_hash", lambda r: r.update(trace_hash="sha256:" + "0" * 64))
    mutated("trailing_actions", lambda r: (r["trace"].extend([{"rotation": 0, "thrust": 1.0}] * 3), reseal(r)))
    mutated("truncated_trace", lambda r: (r["trace"].__delitem__(slice(-20, None)), reseal(r)))
    mutated("bad_terminal_reward", lambda r: r["terminal"].update(reward=r["terminal"]["reward"] + 0.5))
    paths = {}
    for name, record in records.items():
        paths[name] = directory / f"{name}.flight.json"
        paths[name].write_text(json.dumps(record))
    return paths


def state(page):
    return page.evaluate("window.apolloReplayState && window.apolloReplayState()")


def open_record(page, base, rel):
    page.goto(f"{base}{EXP}/replay.html?file={rel}")
    page.wait_for_function("window.apolloReplayState && window.apolloReplayState()", timeout=60000)


def canvas_stats(page):
    return page.evaluate("""() => {
      const c = document.getElementById('screen'); const d = c.getContext('2d').getImageData(0,0,1920,1080).data;
      let lit = 0, h = 2166136261;
      for (let i = 0; i < d.length; i += 4) { if (d[i] + d[i+1] + d[i+2] > 60) lit += 1; h = Math.imul(h ^ (d[i] + d[i+1]*3 + d[i+2]*7), 16777619); }
      return {lit, hash: h >>> 0}; }""")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixture_dir = ROOT / "runs" / "browser-evidence-fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixtures = make_fixtures(fixture_dir)
    rel = {name: "/" + str(path.relative_to(ROOT)) for name, path in fixtures.items()}
    landed_steps = json.loads(fixtures["landed"].read_text())["terminal"]["steps"]

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args, **kwargs):
            pass

    handler = functools.partial(Quiet, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 760})
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        # --- landed flight: matches, rendering, controls ---
        open_record(page, base, rel["landed"])
        st = state(page)
        check("landed record loads and matches", st["matched"] and st["steps"] == landed_steps, st)
        check("verdict banner says MATCHES", "REPLAY MATCHES RECORD" in page.inner_text("#verdict"))
        page.click("#play"); page.click("#play")  # ensure paused at a known place
        page.fill("#scrub", "0"); page.dispatch_event("#scrub", "input")
        s0 = canvas_stats(page)
        check("terrain+ship visible at step 0", s0["lit"] > 2000, s0)
        page.screenshot(path=str(out / "replay_landed_step0.png"))
        page.eval_on_selector("#scrub", "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'))}", str(landed_steps // 2))
        page.wait_for_timeout(200)
        st = state(page); s1 = canvas_stats(page)
        check("scrub sets step and pauses", st["index"] == landed_steps // 2 and page.inner_text("#play") == "Play", st)
        check("canvas changes when scrubbed", s1["hash"] != s0["hash"] and s1["lit"] > 2000, s1)
        page.screenshot(path=str(out / "replay_landed_mid.png"))
        page.eval_on_selector("#scrub", "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'))}", str(landed_steps))
        page.wait_for_timeout(200)
        st = state(page)
        check("final frame reports landed", st["status"] == "landed", st)
        page.screenshot(path=str(out / "replay_landed_end.png"))

        # independent check of a mid-flight state against the Python adapter's replay
        record = json.loads(fixtures["landed"].read_text())
        adapter = make_environment("ApolloLander", research_mode=True, max_steps=8000)
        mid = landed_steps // 2
        py = adapter.replay(record["trace"][:mid], seed=record["episode_seed"], max_steps=8000)["result"]
        page.eval_on_selector("#scrub", "(e,v)=>{e.value=v;e.dispatchEvent(new Event('input'))}", str(mid))
        page.wait_for_timeout(100)
        check("mid-flight reward equals Python replay", abs(state(page)["reward"] - py["reward"]) < 1e-9,
              {"browser": state(page)["reward"], "python": py["reward"]})

        # --- play / pause / speeds ---
        rates = {}
        for speed in ("0.25", "1", "4", "16"):
            page.select_option("#speed", speed)
            page.click("#restart")
            page.wait_for_timeout(1500)
            rates[speed] = state(page)["index"]
        check("playback advances at each speed", all(v > 0 for v in rates.values()), rates)
        check("speeds are ordered 0.25x<1x<4x<16x", rates["0.25"] < rates["1"] < rates["4"] < rates["16"], rates)
        ratio = rates["16"] / max(1, rates["1"])
        check("16x is about 16x of 1x", 8 < ratio < 24, round(ratio, 2))
        page.select_option("#speed", "1"); page.click("#restart"); page.wait_for_timeout(500)
        page.click("#play"); a = state(page)["index"]; page.wait_for_timeout(600); b = state(page)["index"]
        check("pause freezes playback", a == b and page.inner_text("#play") == "Play", (a, b))
        page.click("#play"); page.wait_for_timeout(600)
        check("resume continues playback", state(page)["index"] > b)

        # --- crashed + timeout records ---
        for name, expected in (("crashed", "crashed"), ("timeout", "timeout")):
            open_record(page, base, rel[name])
            page.eval_on_selector("#scrub", "(e)=>{e.value=e.max;e.dispatchEvent(new Event('input'))}")
            page.wait_for_timeout(200)
            st = state(page)
            check(f"{name} record matches and ends {expected}", st["matched"] and st["status"] == expected, st)
            page.screenshot(path=str(out / f"replay_{name}_end.png"))

        # --- mismatching records ---
        for name, pattern in (("bad_trace_length", "trace_length"), ("bad_trace_hash", "trace_hash"),
                              ("trailing_actions", "trailing action"), ("truncated_trace", "truncated trace"),
                              ("bad_terminal_reward", "reward")):
            open_record(page, base, rel[name])
            page.eval_on_selector("#scrub", "(e)=>{e.value=e.max;e.dispatchEvent(new Event('input'))}")
            page.wait_for_timeout(200)
            text = page.inner_text("#verdict"); st = state(page)
            check(f"{name}: REPLAY MISMATCH shown", st["matched"] is False and "REPLAY MISMATCH" in text and pattern in text, text[:160])
            if name in ("bad_trace_length", "trailing_actions"):
                page.screenshot(path=str(out / f"replay_mismatch_{name}.png"))

        # --- file picker ---
        page.goto(f"{base}{EXP}/replay.html")
        page.set_input_files("#file", str(fixtures["crashed"]))
        page.wait_for_function("window.apolloReplayState && window.apolloReplayState()", timeout=30000)
        check("file picker loads a record", state(page)["matched"] is True)

        # --- drag and drop ---
        page.goto(f"{base}{EXP}/replay.html")
        page.evaluate("""async (url) => {
          const text = await (await fetch(url)).text();
          const dt = new DataTransfer(); dt.items.add(new File([text], 'dropped.flight.json', {type: 'application/json'}));
          window.dispatchEvent(new DragEvent('drop', {dataTransfer: dt, bubbles: true, cancelable: true}));
        }""", rel["landed"])
        page.wait_for_function("window.apolloReplayState && window.apolloReplayState()", timeout=30000)
        check("drag and drop loads a record", state(page)["steps"] == landed_steps)

        # --- non-record file is refused with a visible message ---
        page.goto(f"{base}{EXP}/replay.html")
        bad = fixture_dir / "not_a_record.json"; bad.write_text(json.dumps({"schema": "other"}))
        page.set_input_files("#file", str(bad)); page.wait_for_timeout(500)
        check("unsupported file is refused visibly", "Cannot replay" in page.inner_text("#drop"))

        # --- original index.html still works with shared render.js ---
        page.goto(f"{base}{EXP}/index.html"); page.wait_for_timeout(800)
        s_a = canvas_stats(page)
        before = page.evaluate("window.apolloObserve()")
        page.keyboard.down(" "); page.wait_for_timeout(800); page.keyboard.up(" ")
        after = page.evaluate("window.apolloObserve()")
        check("index.html draws terrain+ship", s_a["lit"] > 2000, s_a)
        check("index.html responds to thrust input", before != after, {"y_before": before["y"], "y_after": after["y"]})
        page.screenshot(path=str(out / "index_live_page.png"))

        # pixel parity of the first frame: pre-refactor index.html vs refactored index.html
        orig = subprocess.run(["git", "show", "origin/t3/verify-offline-v1:frontend/apollolander/experiment/index.html"],
                              cwd=ROOT, capture_output=True, text=True, check=True).stdout
        orig_path = ROOT / "frontend/apollolander/experiment/_orig_index.html"
        orig_path.write_text(orig)
        freeze = "window.requestAnimationFrame = cb => { if (!window.__ran) { window.__ran = true; setTimeout(() => cb(performance.now()), 50); } return 1; };"
        try:
            hashes = {}
            for label, name in (("original", "_orig_index.html"), ("refactored", "index.html")):
                ctx = browser.new_context(viewport={"width": 1280, "height": 760})
                pg = ctx.new_page(); pg.add_init_script(freeze)
                pg.goto(f"{base}{EXP}/{name}"); pg.wait_for_timeout(1500)
                hashes[label] = canvas_stats(pg); ctx.close()
        finally:
            orig_path.unlink(missing_ok=True)
        check("first frame pixel-identical before/after render.js refactor",
              hashes["original"] == hashes["refactored"] and hashes["original"]["lit"] > 2000, hashes)
        check("no console or page errors", errors == [], errors[:5])
        browser.close()
    server.shutdown()
    (out / "browser_check_results.json").write_text(json.dumps(RESULTS, indent=2))
    failed = [r for r in RESULTS if not r["passed"]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
