"use strict";

const assert = require("assert");
const { createSimulation } = require("./physics");

function run(actions, config) {
  const sim = createSimulation();
  sim.reset(config);
  const rewards = [];
  for (const action of actions) {
    rewards.push(sim.step(action).reward);
    if (sim.getResult().done) break;
  }
  return { observation: sim.observe(), result: sim.getResult(), rewards, map: sim.mapInfo() };
}

const idle = { thrust: 0, rotation: -90 };
const first = run(Array.from({ length: 30 }, () => idle));
const second = run(Array.from({ length: 30 }, () => idle));
assert.deepStrictEqual(first.observation, second.observation);
assert.deepStrictEqual(first.rewards, second.rewards);
assert.strictEqual(first.map.zone.x1 < first.map.zone.x2, true);
assert.ok(first.map.zone.width >= 12);

const randomGuard = createSimulation();
Math.random = () => {
  throw new Error("Math.random leaked into the experiment");
};
randomGuard.reset();
randomGuard.step(idle);
assert.strictEqual(randomGuard.getResult().status, "flying");

let rejected = false;
try {
  randomGuard.step({ thrust: 0, rotation: 0, code: "alert(1)" });
} catch (error) {
  rejected = /forbidden/.test(error.message);
}
assert.strictEqual(rejected, true);

const alternate = run([idle], { start: { x: 10, y: 80, vx: 0, vy: 0, rotation: 0, fuel: 500, scale: 0.25 } });
assert.strictEqual(alternate.observation.x !== first.observation.x || alternate.observation.fuel === 500, true);
assert.strictEqual(alternate.observation.fuel, 500);
assert.ok(alternate.observation.vy > 0);

const replaySim = createSimulation();
const trace = [idle, { thrust: 0.4, rotation: -80 }, { thrust: 0.4, rotation: -70 }];
const replayed = replaySim.replay(trace);
assert.strictEqual(replayed.frames.length, 3);
assert.strictEqual(replayed.frames[2].observation.rotation !== -90, true);

console.log(JSON.stringify({
  zone: first.map.zone,
  afterIdle: first.observation,
  reward: first.result.reward,
}));
