"use strict";

// node replay.test.js [record.flight.json ...]
// With no arguments, replays the tracked evidence flight. With --json, prints the
// outcome of each record for cross-checking against the Python verifier.
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const { createSimulation } = require("./physics");
const { replayRecord, checkRecord } = require("./replay");

const args = process.argv.slice(2);
const asJson = args.includes("--json");
const files = args.filter((a) => a !== "--json");
if (files.length === 0) {
  files.push(path.join(__dirname, "..", "..", "..", "docs", "assets", "v1-evidence", "flights",
    "offline_mock_development_episode.flight.json"));
}

const outcomes = files.map((file) => {
  const record = JSON.parse(fs.readFileSync(file, "utf8"));
  const { frames, comparison } = replayRecord(createSimulation, record);
  const last = frames[frames.length - 1];
  return {
    file, matched: comparison.matched, mismatches: comparison.mismatches,
    steps: frames.length - 1, reward: last.result.reward, status: last.result.status,
  };
});

if (asJson) {
  console.log(JSON.stringify(outcomes));
} else {
  for (const o of outcomes) {
    assert.ok(o.matched, `${o.file}: ${o.mismatches.join("; ")}`);
    console.log(`ok ${path.basename(o.file)} steps=${o.steps} status=${o.status} reward=${o.reward}`);
  }
  // A tampered action trace must be reported, never silently accepted.
  const record = JSON.parse(fs.readFileSync(files[0], "utf8"));
  const tampered = JSON.parse(JSON.stringify(record));
  tampered.trace[0] = { rotation: 90, thrust: 1.0 };
  assert.ok(!replayRecord(createSimulation, tampered).comparison.matched, "tampered trace must not match");
  assert.throws(() => checkRecord({ schema: "other" }), /unsupported schema/);
  console.log("ok tamper and schema checks");

  // Browsers share one global scope across <script> tags; Node modules hide clashes
  // such as two top-level `const api` declarations. Load the page scripts the same way.
  const vm = require("vm");
  const page = fs.readFileSync(path.join(__dirname, "replay.html"), "utf8");
  const sources = [...page.matchAll(/<script src="([^"]+)"><\/script>/g)].map((m) => m[1]);
  assert.deepStrictEqual(sources.map((s) => path.basename(s)),
    ["perlin.js", "physics.js", "render.js", "replay.js"]);
  const context = vm.createContext({ console, Math, window: {} });
  for (const source of sources) {
    const file = path.join(__dirname, source);
    vm.runInContext(fs.readFileSync(file, "utf8"), context, { filename: file });
  }
  const win = context.window;
  assert.ok(win.ApolloPhysics && win.ApolloRender && win.ApolloReplay, "page globals defined");
  const viaPage = win.ApolloReplay.replayRecord(
    () => win.ApolloPhysics.createSimulation({ lockedCamera: true }), record);
  assert.ok(viaPage.comparison.matched, "page-scope replay matches record");
  console.log("ok shared-global page scope");
}
