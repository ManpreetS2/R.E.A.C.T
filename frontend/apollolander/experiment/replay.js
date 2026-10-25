"use strict";

// Deterministic visual replay of a rewardbench.apollolander.flight_record.v1 manifest.
// A record stores the start state and one {rotation, thrust} action per step, not
// per-step states. States are regenerated with the same physics.js the Python
// adapter drives.
//
// Two separate verdicts, both required for "matched":
//   integrity - the record is self-consistent: trace_length equals the real array
//               length and trace_hash equals the hash of the recorded actions;
//   parity    - replaying the actions reproduces the recorded terminal outcome, ends
//               on the same step the physics terminates, and leaves no unused actions.
// controller_hash is NOT checked here; python verify_flight_record is authoritative
// for it and for re-deriving the start state from the episode seed.

const RECORD_SCHEMA = "rewardbench.apollolander.flight_record.v1";
const ENVIRONMENT_VERSION = "apollolander.env.v1";
const REWARD_TOLERANCE = 1e-9;

function checkRecord(record) {
  if (!record || typeof record !== "object") throw new Error("not a flight record");
  if (record.schema !== RECORD_SCHEMA) throw new Error(`unsupported schema ${record.schema}`);
  if (record.environment_version !== ENVIRONMENT_VERSION) {
    throw new Error(`record is for ${record.environment_version}; this physics is ${ENVIRONMENT_VERSION}`);
  }
  if (!Array.isArray(record.trace)) throw new Error("record has no action trace");
  if (!record.initial_state || !record.terminal) throw new Error("record lacks initial_state or terminal");
}

function compareTerminal(recorded, result) {
  const observed = {
    status: result.status,
    reward: result.reward,
    landed: result.landed,
    crashed: result.crashed,
    in_landing_zone: result.inLandingZone,
    timed_out: result.timedOut,
    steps: result.steps,
  };
  const mismatches = [];
  for (const key of Object.keys(observed)) {
    if (key === "reward") {
      if (!(Math.abs(observed.reward - recorded.reward) <= REWARD_TOLERANCE)) {
        mismatches.push(`reward ${observed.reward} != recorded ${recorded.reward}`);
      }
    } else if (observed[key] !== recorded[key]) {
      mismatches.push(`${key} ${observed[key]} != recorded ${recorded[key]}`);
    }
  }
  return { matched: mismatches.length === 0, mismatches, observed };
}

// ---- trace_hash: sha256 of Python's json.dumps(canonicalize(trace), separators=(",", ":")) ----

function pythonFloat(value) {
  if (!Number.isFinite(value)) throw new Error("non-finite number");
  if (value !== 0 && (Math.abs(value) < 1e-4 || Math.abs(value) >= 1e16)) {
    const [mantissa, exponent] = value.toExponential().split("e");
    const sign = exponent[0] === "-" ? "-" : "+";
    return `${mantissa}e${sign}${exponent.replace(/^[+-]/, "").padStart(2, "0")}`;
  }
  const text = String(value);
  return Number.isInteger(value) && !text.includes("e") ? `${text}.0` : text;
}

// The recorder writes rotation as an int and thrust as a float; other fields are not
// produced by the physics (normalizeAction rejects them).
function canonicalTrace(trace) {
  const body = trace.map((action) => {
    if (!action || typeof action !== "object" || Array.isArray(action)) throw new Error("bad action");
    return "{" + Object.keys(action).sort().map((key) => {
      const value = action[key];
      if (typeof value !== "number") throw new Error(`action ${key} is not a number`);
      const text = key === "rotation" && Number.isInteger(value) ? String(value) : pythonFloat(value);
      return `${JSON.stringify(key)}:${text}`;
    }).join(",") + "}";
  });
  return "[" + body.join(",") + "]";
}

function sha256Hex(text) {
  const bytes = [];
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i);
    if (code > 127) throw new Error("non-ASCII payload");
    bytes.push(code);
  }
  const K = new Uint32Array(64);
  for (let i = 0, candidate = 2; i < 64; candidate += 1) {
    let prime = true;
    for (let d = 2; d * d <= candidate; d += 1) if (candidate % d === 0) { prime = false; break; }
    if (prime) { K[i] = Math.floor((candidate ** (1 / 3) % 1) * 2 ** 32); i += 1; }
  }
  const H = new Uint32Array(8);
  for (let i = 0, candidate = 2; i < 8; candidate += 1) {
    let prime = true;
    for (let d = 2; d * d <= candidate; d += 1) if (candidate % d === 0) { prime = false; break; }
    if (prime) { H[i] = Math.floor((candidate ** 0.5 % 1) * 2 ** 32); i += 1; }
  }
  const bitLength = bytes.length * 8;
  bytes.push(0x80);
  while (bytes.length % 64 !== 56) bytes.push(0);
  const high = Math.floor(bitLength / 2 ** 32);
  for (const word of [high, bitLength >>> 0]) {
    bytes.push((word >>> 24) & 255, (word >>> 16) & 255, (word >>> 8) & 255, word & 255);
  }
  const rotr = (x, n) => (x >>> n) | (x << (32 - n));
  const W = new Uint32Array(64);
  for (let offset = 0; offset < bytes.length; offset += 64) {
    for (let i = 0; i < 16; i += 1) {
      const j = offset + i * 4;
      W[i] = (bytes[j] << 24) | (bytes[j + 1] << 16) | (bytes[j + 2] << 8) | bytes[j + 3];
    }
    for (let i = 16; i < 64; i += 1) {
      const s0 = rotr(W[i - 15], 7) ^ rotr(W[i - 15], 18) ^ (W[i - 15] >>> 3);
      const s1 = rotr(W[i - 2], 17) ^ rotr(W[i - 2], 19) ^ (W[i - 2] >>> 10);
      W[i] = (W[i - 16] + s0 + W[i - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let i = 0; i < 64; i += 1) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K[i] + W[i]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
  }
  return Array.from(H, (word) => word.toString(16).padStart(8, "0")).join("");
}

function traceHash(trace) {
  return "sha256:" + sha256Hex(canonicalTrace(trace));
}

function checkIntegrity(record) {
  const problems = [];
  const actual = record.trace.length;
  if (record.trace_length !== actual) {
    problems.push(`trace_length ${record.trace_length} != actual ${actual} recorded actions`);
  }
  if (record.terminal.steps !== actual) {
    problems.push(`terminal.steps ${record.terminal.steps} != actual ${actual} recorded actions`);
  }
  try {
    const expected = traceHash(record.trace);
    if (record.trace_hash !== expected) problems.push(`trace_hash does not match the recorded actions`);
  } catch (error) {
    problems.push(`trace_hash could not be recomputed: ${error.message}`);
  }
  return { ok: problems.length === 0, problems };
}

// Returns frames[0..n]: frame 0 is the start, frame k the state after k recorded actions.
function replayRecord(createSimulation, record) {
  checkRecord(record);
  const integrity = checkIntegrity(record);
  const sim = createSimulation();
  const config = {
    start: record.initial_state,
    maxSteps: record.max_steps || record.terminal.steps,
    lockedCamera: true,
    bonuses: false,
  };
  sim.reset(config);
  const snapshot = (action) => ({
    action,
    observation: sim.observe(),
    result: sim.getResult(),
    geometry: sim.frameGeometry(),
  });
  const frames = [snapshot(null)];
  const parity = [];
  let applied = 0;
  for (const action of record.trace) {
    if (sim.getResult().done) break;
    try {
      sim.step(action);
    } catch (error) {
      parity.push(`action ${applied} rejected by physics: ${error.message}`);
      break;
    }
    applied += 1;
    frames.push(snapshot(action));
  }
  const final = sim.getResult();
  if (applied < record.trace.length && final.done) {
    parity.push(`${record.trace.length - applied} trailing action(s) after the simulation ended at step ${applied}`);
  }
  if (!final.done && parity.length === 0) {
    parity.push(`trace ended at step ${applied} but the simulation had not terminated (truncated trace)`);
  }
  const comparison = compareTerminal(record.terminal, final);
  parity.push(...comparison.mismatches);
  const mismatches = [...integrity.problems, ...parity];
  return {
    frames,
    map: sim.mapInfo(),
    integrity,
    comparison: { matched: mismatches.length === 0, mismatches, observed: comparison.observed,
                  terminalMatched: comparison.matched, parityOk: parity.length === 0 },
  };
}

const replayApi = { replayRecord, compareTerminal, checkRecord, checkIntegrity, traceHash, sha256Hex,
  canonicalTrace, RECORD_SCHEMA };
if (typeof module !== "undefined" && module.exports) module.exports = replayApi;
if (typeof window !== "undefined") window.ApolloReplay = replayApi;
