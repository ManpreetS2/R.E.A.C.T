"use strict";

const readline = require("readline");
const { createSimulation } = require("./physics");

const sim = createSimulation();
const rl = readline.createInterface({ input: process.stdin, terminal: false });

function reply(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

rl.on("line", (line) => {
  if (!line.trim()) return;
  try {
    const message = JSON.parse(line);
    if (message.cmd === "reset") {
      reply({ ok: true, observation: sim.reset(message.config || {}), map: publicMap(sim.mapInfo()) });
    } else if (message.cmd === "observe") {
      reply({ ok: true, observation: sim.observe() });
    } else if (message.cmd === "step") {
      const stepped = sim.step(message.action || {});
      reply({ ok: true, step: stepped, observation: sim.observe(), result: sim.getResult() });
    } else if (message.cmd === "result") {
      reply({ ok: true, result: sim.getResult(), observation: sim.observe() });
    } else if (message.cmd === "geometry") {
      reply({ ok: true, map: publicMap(sim.mapInfo()), frame: sim.frameGeometry(), observation: sim.observe(), result: sim.getResult() });
    } else if (message.cmd === "replay") {
      reply({ ok: true, replay: sim.replay(message.trace || [], message.config) });
    } else {
      reply({ ok: false, error: `unknown command ${message.cmd}` });
    }
  } catch (error) {
    reply({ ok: false, error: error.message });
  }
});

function publicMap(info) {
  return {
    tileWidth: info.tileWidth,
    zone: info.zone,
    points: info.points,
    physicsHz: info.physics.physicsHz,
    reward: info.reward,
  };
}
