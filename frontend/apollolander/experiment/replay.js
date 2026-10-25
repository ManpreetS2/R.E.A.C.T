"use strict";

// Deterministic visual replay of a rewardbench.apollolander.flight_record.v1 manifest.
// A record stores the start state and one {rotation, thrust} action per step, not
// per-step states. States are regenerated with the same physics.js the Python
// adapter drives, then compared with the outcome stored in the record.

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

// Returns frames[0..n]: frame 0 is the start, frame k the state after k recorded actions.
function replayRecord(createSimulation, record) {
  checkRecord(record);
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
  for (const action of record.trace) {
    sim.step(action);
    frames.push(snapshot(action));
    if (sim.getResult().done) break;
  }
  const comparison = compareTerminal(record.terminal, sim.getResult());
  if (frames.length - 1 !== record.trace_length && !comparison.matched) {
    comparison.mismatches.push(`replayed ${frames.length - 1} steps; record has ${record.trace_length}`);
  }
  return { frames, map: sim.mapInfo(), comparison };
}

const replayApi = { replayRecord, compareTerminal, checkRecord, RECORD_SCHEMA };
if (typeof module !== "undefined" && module.exports) module.exports = replayApi;
if (typeof window !== "undefined") window.ApolloReplay = replayApi;
