"use strict";

// node replay.test.js [record.flight.json ...]
// With no arguments, replays the tracked evidence flight. With --json, prints the
// outcome of each record for cross-checking against the Python verifier.
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const { createSimulation } = require("./physics");
const crypto = require("crypto");
const { replayRecord, checkRecord, sha256Hex, traceHash } = require("./replay");

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

  // ---- record integrity regressions: any one of these must produce a mismatch ----
  const replayOf = (mutate) => {
    const copy = JSON.parse(JSON.stringify(record));
    mutate(copy);
    return replayRecord(createSimulation, copy).comparison;
  };
  const reseal = (r) => { r.trace_length = r.trace.length; r.trace_hash = traceHash(r.trace); };
  const expectMismatch = (name, comparison, pattern) => {
    assert.ok(!comparison.matched, `${name}: must not match`);
    assert.ok(comparison.mismatches.some((m) => pattern.test(m)), `${name}: got ${comparison.mismatches}`);
    console.log(`ok mismatch: ${name}`);
  };
  assert.ok(replayOf(() => {}).matched, "unmodified record matches");
  // Old bug: terminal outcome agrees but trace_length lies.
  expectMismatch("altered trace_length", replayOf((r) => { r.trace_length += 1; }), /trace_length/);
  expectMismatch("trace_length zero", replayOf((r) => { r.trace_length = 0; }), /trace_length/);
  expectMismatch("trailing actions, metadata stale",
    replayOf((r) => { r.trace.push({ rotation: 0, thrust: 1.0 }, { rotation: 0, thrust: 1.0 }); }),
    /trace_length/);
  expectMismatch("trailing actions, metadata resealed",
    replayOf((r) => { r.trace.push({ rotation: 0, thrust: 1.0 }, { rotation: 0, thrust: 1.0 }); reseal(r); }),
    /trailing action/);
  expectMismatch("trailing actions, terminal.steps also resealed",
    replayOf((r) => { r.trace.push({ rotation: 0, thrust: 1.0 }); reseal(r); r.terminal.steps = r.trace.length; }),
    /trailing action|steps/);
  expectMismatch("truncated trace, metadata stale", replayOf((r) => { r.trace.length -= 10; }), /trace_length/);
  expectMismatch("truncated trace, metadata resealed",
    replayOf((r) => { r.trace.length -= 10; reseal(r); }), /truncated trace/);
  expectMismatch("terminal reward changed", replayOf((r) => { r.terminal.reward += 1; }), /reward/);
  expectMismatch("terminal status changed", replayOf((r) => { r.terminal.status = "landed"; }), /status/);
  expectMismatch("terminal steps changed", replayOf((r) => { r.terminal.steps -= 1; }), /steps/);
  expectMismatch("terminal crashed flag changed", replayOf((r) => { r.terminal.crashed = true; }), /crashed/);
  expectMismatch("terminal fuel_remaining changed", replayOf((r) => { r.terminal.fuel_remaining = 1.0; }), /fuel_remaining/);
  expectMismatch("terminal fuel_used changed", replayOf((r) => { r.terminal.fuel_used += 5; }), /fuel_used/);
  expectMismatch("wrong trace_hash", replayOf((r) => { r.trace_hash = "sha256:" + "0".repeat(64); }), /trace_hash/);
  expectMismatch("changed action, hash stale", replayOf((r) => { r.trace[5].thrust = 0.5; }), /trace_hash/);
  expectMismatch("action rejected by physics",
    replayOf((r) => { r.trace[3] = { rotation: 7, thrust: 0.0 }; reseal(r); }), /rejected by physics/);
  const noHash = replayOf((r) => { delete r.trace_hash; });
  expectMismatch("missing trace_hash", noHash, /trace_hash/);

  // hashing primitives against independent references
  for (const text of ["", "abc", "a".repeat(55), "a".repeat(56), "a".repeat(64), "x".repeat(1000)]) {
    assert.strictEqual(sha256Hex(text), crypto.createHash("sha256").update(text).digest("hex"));
  }
  const { canonicalTrace } = require("./replay");
  assert.strictEqual(canonicalTrace([{ thrust: 0, rotation: -90 }, { thrust: 1, rotation: 0 }, { thrust: 1e-5, rotation: 10 },
    { thrust: 0.15, rotation: 10 }, { thrust: 1.5e-7, rotation: 10 }]),
    '[{"rotation":-90,"thrust":0.0},{"rotation":0,"thrust":1.0},{"rotation":10,"thrust":1e-05},' +
    '{"rotation":10,"thrust":0.15},{"rotation":10,"thrust":1.5e-07}]');
  console.log("ok hash primitives");

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
  const tampered2 = JSON.parse(JSON.stringify(record));
  tampered2.trace_length += 1;
  assert.ok(!win.ApolloReplay.replayRecord(() => win.ApolloPhysics.createSimulation({ lockedCamera: true }), tampered2)
    .comparison.matched, "page-scope trace_length mismatch detected");
  console.log("ok shared-global page scope");
}
