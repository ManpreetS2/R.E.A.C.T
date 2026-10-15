"use strict";

/*
 * Deterministic ApolloLander physics.
 *
 * The integrator, terrain generator, and collision tests follow
 * frontend/apollolander/upstream (Seb Lee-Delisle, MIT).
 * This file does not call Math.random or Date.now. One step() is one
 * lander update from the original game, independent of rendering FPS.
 */

const LANDSCAPE_NOISE_SEED = 12039;
const PHYSICS = {
  gravity: 0.0005,
  thrustAcceleration: 0.0015,
  topSpeed: 0.35,
  drag: 0.9997,
  rotationLerp: 0.3,
  safeVerticalSpeed: 0.15,
  perfectVerticalSpeed: 0.075,
  defaultFuel: 1000,
  defaultScale: 0.25,
  physicsHz: 60,
};

const REWARD = {
  perfectLanding: 100,
  hardLanding: 40,
  crash: -100,
  timeout: -25,
  fuelPerUnit: 0.05,
  progressScale: 0.5,
};

const SHAPES = [
  ["m", 2.6, -3.36, "l", 4.2, -2.08, "l", 4.2, 2.08, "l", 2.6, 3.36, "l", -2.6, 3.36, "l", -4.2, 2.08, "l", -4.2, -2.08, "l", -2.6, -3.36, "cp"],
  ["r", -4, 3.4, 7, 4.2],
  ["m", -4, 3.4, "l", -7, 4.7, "l", -4, 7.6, "l", -8.3, 9.4, "m", -7, 4.7, "l", -9.3, 12.6, "m", -7.6, 12.6, "l", -11, 12.6],
  ["m", 4, 3.4, "l", 7, 4.7, "l", 4, 7.6, "l", 8.3, 9.4, "m", 7, 4.7, "l", 9.3, 12.6, "m", 7.6, 12.6, "l", 11, 12.6],
  ["m", -1.2, 7.6, "l", -2.2, 10.4, "m", 2.2, 10.4, "l", 1.2, 7.6, "m", 2.2, 10.4, "l", -2.2, 10.4],
];

function loadNoise() {
  if (typeof noise !== "undefined" && noise && typeof noise.simplex2 === "function") {
    return noise;
  }
  const fs = require("fs");
  const path = require("path");
  const vm = require("vm");
  const filename = path.join(__dirname, "..", "upstream", "perlin.js");
  const sandbox = { console, Math };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(filename, "utf8"), sandbox, { filename });
  if (!sandbox.noise || typeof sandbox.noise.simplex2 !== "function") {
    throw new Error("failed to load upstream perlin.js");
  }
  return sandbox.noise;
}

function clamp(value, min, max) {
  return value < min ? min : value > max ? max : value;
}

function generateLandscape(noiseApi) {
  noiseApi.seed(LANDSCAPE_NOISE_SEED);
  const raw = [];
  for (let i = 0; i < 2000; i += 1) {
    const x = i * 8;
    let y = noiseApi.simplex2(x / 500, 100) * 256;
    y += noiseApi.simplex2(x / 200, 100) * 80;
    y += noiseApi.simplex2(x / 40, 100) * 20;
    y = Math.min(y, 150) + 200;
    if (raw.length > 1) {
      const lastY = raw[raw.length - 1].y;
      const lastY2 = raw[raw.length - 2].y;
      if (Math.abs(y - lastY2) < 3) {
        raw[raw.length - 1].x = x;
        raw[raw.length - 1].y = y;
        raw[raw.length - 2].y = y;
      } else if (Math.abs(y - lastY) < 2) {
        raw[raw.length - 1].y = y;
        raw.push({ x, y });
      } else {
        raw.push({ x, y });
      }
    } else {
      raw.push({ x, y });
    }
  }

  const landscale = 0.8;
  for (const point of raw) {
    point.x *= landscale;
    point.y *= landscale;
    point.y += 400;
  }

  const lines = [];
  for (let i = 1; i < raw.length; i += 1) {
    const p1 = { x: raw[i - 1].x, y: raw[i - 1].y };
    const p2 = { x: raw[i].x, y: raw[i].y };
    lines.push({
      p1,
      p2,
      landable: p1.y === p2.y,
      designated: false,
    });
  }

  let best = null;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (!line.landable) continue;
    const width = line.p2.x - line.p1.x;
    if (width < 12) continue;
    if (!best || width > best.width) best = { index: i, width, line };
  }
  if (!best) throw new Error("fixed map has no landing segment wide enough for the lander");
  best.line.designated = true;

  return {
    points: raw.map((point) => ({ x: point.x, y: point.y })),
    lines,
    tileWidth: raw[raw.length - 1].x,
    zoneIndex: best.index,
  };
}

function rotateVector(x, y, degrees) {
  const radians = degrees * Math.PI / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  return { x: x * cos - y * sin, y: x * sin + y * cos };
}

function pointBelowLine(point, line) {
  const span = line.p2.x - line.p1.x;
  if (span === 0) return false;
  const dist = (point.x - line.p1.x) / span;
  const yHit = line.p1.y + (line.p2.y - line.p1.y) * dist;
  return dist > 0 && dist < 1 && yHit <= point.y;
}

function createSimulation(options) {
  const noiseApi = loadNoise();
  const map = generateLandscape(noiseApi);
  const zone = map.lines[map.zoneIndex];
  let config = null;
  let state = null;

  function standardStart() {
    const mid = (zone.p1.x + zone.p2.x) / 2;
    return {
      x: mid - 160,
      y: 150,
      vx: 0.415,
      vy: 0,
      rotation: -90,
      fuel: PHYSICS.defaultFuel,
      scale: PHYSICS.defaultScale,
    };
  }

  function reset(nextConfig) {
    config = normalizeConfig(nextConfig || {}, standardStart());
    const start = config.start;
    state = {
      x: start.x,
      y: start.y,
      vx: start.vx,
      vy: start.vy,
      rotation: start.rotation,
      targetRotation: start.rotation,
      fuel: start.fuel,
      fuelUsed: 0,
      scale: start.scale,
      thrust: 0,
      thrustBuild: 0,
      active: true,
      step: 0,
      status: "flying",
      landed: false,
      crashed: false,
      inLandingZone: false,
      timedOut: false,
      perfect: false,
      hard: false,
      altitude: 0,
      totalReward: 0,
      lastPotential: null,
      terminalReward: 0,
      verified: null,
      done: false,
    };
    state.altitude = altitudeAt(state.x, state.y, state.scale);
    state.lastPotential = potential(state);
    return observe();
  }

  function normalizeConfig(raw, fallbackStart) {
    const start = Object.assign({}, fallbackStart, raw.start || {});
    const required = ["x", "y", "vx", "vy", "rotation", "fuel", "scale"];
    for (const key of required) {
      if (typeof start[key] !== "number" || !Number.isFinite(start[key])) {
        throw new Error(`start.${key} must be a finite number`);
      }
    }
    if (raw.bonuses) throw new Error("landing-zone bonuses are disabled for controlled trials");
    return {
      start,
      maxSteps: raw.maxSteps || 3600,
      lockedCamera: raw.lockedCamera !== false,
      bonuses: false,
    };
  }

  function wrapX(x) {
    let wrapped = x % map.tileWidth;
    if (wrapped < 0) wrapped += map.tileWidth;
    return wrapped;
  }

  function altitudeAt(x, y, scale) {
    const wrapped = wrapX(x);
    for (let i = 0; i < map.lines.length; i += 1) {
      const line = map.lines[i];
      if (wrapped < line.p1.x || wrapped > line.p2.x) continue;
      const span = line.p2.x - line.p1.x;
      const dist = span === 0 ? 0 : (wrapped - line.p1.x) / span;
      const ground = line.p1.y + (line.p2.y - line.p1.y) * dist;
      return ground - (y + 13 * scale);
    }
    return 0;
  }

  function potential(ship) {
    const mid = (zone.p1.x + zone.p2.x) / 2;
    const dx = (ship.x - mid) / 100;
    const dy = (ship.y - zone.p1.y) / 100;
    return -Math.hypot(dx, dy) - Math.abs(ship.rotation) / 90;
  }

  function observe() {
    const mid = (zone.p1.x + zone.p2.x) / 2;
    return {
      x: state.x,
      y: state.y,
      vx: state.vx,
      vy: state.vy,
      rotation: state.rotation,
      fuel: state.fuel,
      altitude: state.altitude,
      thrust: state.thrustBuild,
      zoneLeft: zone.p1.x,
      zoneRight: zone.p2.x,
      zoneY: zone.p1.y,
      dx: mid - state.x,
      dy: zone.p1.y - state.y,
      step: state.step,
      status: state.status,
    };
  }

  function step(action) {
    if (state.done) {
      return { reward: 0, breakdown: emptyBreakdown(), done: true, status: state.status };
    }
    const command = normalizeAction(action);
    state.step += 1;
    state.targetRotation = command.rotation;
    state.thrust = state.fuel > 0 ? command.thrust : 0;

    state.rotation += (state.targetRotation - state.rotation) * PHYSICS.rotationLerp;
    if (Math.abs(state.rotation - state.targetRotation) < 0.1) state.rotation = state.targetRotation;

    let fuelUsed = 0;
    if (state.active) {
      state.thrustBuild += (state.thrust - state.thrustBuild) * 0.2;
      if (state.thrustBuild > 0) {
        const thrust = rotateVector(0, -PHYSICS.thrustAcceleration * state.thrustBuild, state.rotation);
        state.vx += thrust.x;
        state.vy += thrust.y;
        fuelUsed = 0.2 * state.thrustBuild;
        state.fuel -= fuelUsed;
        state.fuelUsed += fuelUsed;
        if (state.fuel < 0) state.fuel = 0;
      }
      state.x += state.vx;
      state.y += state.vy;
      state.vx *= PHYSICS.drag;
      state.vy += PHYSICS.gravity;
      // The original assignment writes velY and does not clamp vel.y. Preserved.
      if (state.fuel <= 0) state.thrust = 0;
    }

    state.altitude = altitudeAt(state.x, state.y, state.scale);
    const contact = collide();
    const nextPotential = potential(state);
    const shaping = (nextPotential - state.lastPotential) * REWARD.progressScale;
    state.lastPotential = nextPotential;
    const fuelPenalty = fuelUsed * REWARD.fuelPerUnit;
    let terminal = 0;
    if (contact && state.status === "flying") {
      terminal = applyContact(contact);
    } else if (state.step >= config.maxSteps && state.status === "flying") {
      state.status = "timeout";
      state.timedOut = true;
      state.done = true;
      state.active = false;
      terminal = REWARD.timeout;
    }
    if (state.status !== "flying") state.done = true;
    const reward = shaping - fuelPenalty + terminal;
    state.totalReward += reward;
    state.terminalReward += terminal;
    return {
      reward,
      breakdown: { shaping, fuelPenalty, terminal },
      done: state.done,
      status: state.status,
      applied: command,
    };
  }

  function applyContact(contact) {
    state.verified = contact;
    state.active = false;
    state.thrust = 0;
    state.thrustBuild = 0;
    if (contact.kind === "landed") {
      state.inLandingZone = contact.designated;
      state.perfect = contact.perfect;
      state.hard = !contact.perfect;
      if (contact.designated && contact.perfect) {
        state.status = "landed";
        state.landed = true;
        return REWARD.perfectLanding;
      }
      if (contact.designated) {
        state.status = "hard_landing";
        state.landed = true;
        return REWARD.hardLanding;
      }
      state.status = "landed_outside_zone";
      state.landed = false;
      return 0;
    }
    state.status = "crashed";
    state.crashed = true;
    state.landed = false;
    return REWARD.crash;
  }

  function collide() {
    const halfWidth = 10 * state.scale;
    let right = (state.x + halfWidth) % map.tileWidth;
    let left = (state.x - halfWidth) % map.tileWidth;
    while (right < 0) {
      right += map.tileWidth;
      left += map.tileWidth;
    }
    const bottom = state.y + 13 * state.scale;
    for (let i = 0; i < map.lines.length; i += 1) {
      const line = map.lines[i];
      if (right < line.p1.x || left > line.p2.x) continue;
      if (line.landable) {
        if (bottom >= line.p1.y) {
          const inside = left > line.p1.x && right < line.p2.x;
          const upright = state.rotation === 0;
          const slow = state.vy < PHYSICS.safeVerticalSpeed;
          if (inside && upright && slow) {
            return {
              kind: "landed",
              designated: line.designated,
              perfect: state.vy < PHYSICS.perfectVerticalSpeed,
              lineIndex: i,
              rotation: state.rotation,
              vy: state.vy,
              left,
              right,
              bottom,
              segmentY: line.p1.y,
            };
          }
          return {
            kind: "crashed",
            reason: inside ? "attitude_or_speed" : "not_fully_on_segment",
            lineIndex: i,
            rotation: state.rotation,
            vy: state.vy,
            left,
            right,
            bottom,
          };
        }
      } else if (bottom > line.p2.y || bottom > line.p1.y) {
        const bottomLeft = { x: left, y: bottom };
        const bottomRight = { x: right, y: bottom };
        if (pointBelowLine(bottomLeft, line) || pointBelowLine(bottomRight, line)) {
          return {
            kind: "crashed",
            reason: "slope_contact",
            lineIndex: i,
            rotation: state.rotation,
            vy: state.vy,
            left,
            right,
            bottom,
          };
        }
      }
    }
    return null;
  }

  function getResult() {
    return {
      status: state.status,
      landed: state.landed,
      crashed: state.crashed,
      inLandingZone: state.inLandingZone,
      timedOut: state.timedOut,
      perfect: state.perfect,
      hard: state.hard,
      steps: state.step,
      reward: state.totalReward,
      fuelUsed: state.fuelUsed,
      fuelRemaining: state.fuel,
      verified: state.verified,
      done: state.done,
    };
  }

  function replay(trace, replayConfig) {
    reset(replayConfig || config);
    const frames = [];
    for (const action of trace || []) {
      const stepped = step(action);
      frames.push({ observation: observe(), step: stepped, result: getResult(), geometry: frameGeometry() });
      if (state.done) break;
    }
    return { frames, result: getResult() };
  }

  function camera() {
    const start = config.start;
    const marginX = 50;
    const marginY = 40;
    let left = Math.min(start.x, zone.p1.x) - marginX;
    let right = Math.max(start.x, zone.p2.x) + marginX;
    let top = start.y - 90;
    let bottom = zone.p1.y + marginY;
    if (!config.lockedCamera) {
      left = state.x - 120;
      right = state.x + 120;
      top = state.y - 80;
      bottom = state.y + 80;
    }
    const worldWidth = Math.max(20, right - left);
    const worldHeight = Math.max(20, bottom - top);
    const aspect = 1920 / 1080;
    let width = worldWidth;
    let height = worldHeight;
    if (width / height > aspect) height = width / aspect;
    else width = height * aspect;
    const cx = (left + right) / 2;
    const cy = (top + bottom) / 2;
    return { left: cx - width / 2, top: cy - height / 2, width, height, screenWidth: 1920, screenHeight: 1080 };
  }

  function frameGeometry() {
    return {
      camera: camera(),
      lander: landerPolylines(),
      thrust: state.thrustBuild > 0.0001 && state.active ? thrustPolyline() : null,
      zone: { x1: zone.p1.x, x2: zone.p2.x, y: zone.p1.y },
    };
  }

  function visualScale() {
    const view = camera();
    const pixelsPerUnit = view.screenHeight / view.height;
    const physicsHeight = 16 * state.scale;
    const pixels = physicsHeight * pixelsPerUnit;
    const minimumPixels = 48;
    if (pixels >= minimumPixels) return state.scale;
    return state.scale * (minimumPixels / pixels);
  }

  function landerPolylines() {
    const scale = visualScale();
    const polygons = [];
    for (const shape of SHAPES) {
      let current = [];
      const flush = () => {
        if (current.length > 1) polygons.push(current);
        current = [];
      };
      for (let i = 0; i < shape.length; ) {
        const command = shape[i];
        i += 1;
        if (command === "cp") {
          if (current.length) current.push(current[0]);
          flush();
        } else if (command === "m") {
          flush();
          current.push(worldPoint(shape[i], shape[i + 1], scale));
          i += 2;
        } else if (command === "l") {
          current.push(worldPoint(shape[i], shape[i + 1], scale));
          i += 2;
        } else if (command === "r") {
          const x = shape[i];
          const y = shape[i + 1];
          const w = shape[i + 2];
          const h = shape[i + 3];
          i += 4;
          polygons.push([
            worldPoint(x, y, scale),
            worldPoint(x + w, y, scale),
            worldPoint(x + w, y + h, scale),
            worldPoint(x, y + h, scale),
            worldPoint(x, y, scale),
          ]);
        }
      }
      flush();
    }
    return polygons;
  }

  function thrustPolyline() {
    const length = 10.4 + Math.min(state.thrustBuild, 1) * 15;
    const scale = visualScale();
    return [worldPoint(0, 7.6, scale), worldPoint(0, length, scale)];
  }

  function worldPoint(localX, localY, scale) {
    const used = scale === undefined ? state.scale : scale;
    const scaledX = localX * used;
    const scaledY = localY * used;
    const rotated = rotateVector(scaledX, scaledY, state.rotation);
    return { x: state.x + rotated.x, y: state.y + rotated.y };
  }

  function mapInfo() {
    return {
      tileWidth: map.tileWidth,
      zone: { x1: zone.p1.x, x2: zone.p2.x, y: zone.p1.y, index: map.zoneIndex, width: zone.p2.x - zone.p1.x },
      points: map.points,
      physics: PHYSICS,
      reward: REWARD,
    };
  }

  reset(options || {});
  return { reset, observe, step, getResult, replay, frameGeometry, mapInfo, standardStart };
}

function normalizeAction(action) {
  if (!action || typeof action !== "object" || Array.isArray(action)) {
    throw new Error("action must be an object with thrust and rotation");
  }
  const forbidden = ["code", "js", "javascript", "script", "eval", "function"];
  for (const key of Object.keys(action)) {
    if (forbidden.includes(key) || key.startsWith("_")) {
      throw new Error(`forbidden action field ${key}`);
    }
    if (key !== "thrust" && key !== "rotation") {
      throw new Error(`unknown action field ${key}`);
    }
  }
  const thrust = action.thrust;
  const rotation = action.rotation;
  if (typeof thrust !== "number" || !Number.isFinite(thrust) || thrust < 0 || thrust > 1) {
    throw new Error("thrust must be a finite number from 0 to 1");
  }
  if (typeof rotation !== "number" || !Number.isFinite(rotation) || rotation < -90 || rotation > 90) {
    throw new Error("rotation must be a finite number from -90 to 90");
  }
  if (Math.abs(rotation / 10 - Math.round(rotation / 10)) > 1e-9) {
    throw new Error("rotation must be a multiple of 10 degrees");
  }
  return { thrust, rotation: Math.round(rotation) };
}

function emptyBreakdown() {
  return { shaping: 0, fuelPenalty: 0, terminal: 0 };
}

const api = { createSimulation, normalizeAction, PHYSICS, REWARD, SHAPES, LANDSCAPE_NOISE_SEED };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof window !== "undefined") {
  window.ApolloPhysics = api;
}
