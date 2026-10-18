"use strict";

/**
 * Headless host for the ORIGINAL ApolloLander upstream engine.
 *
 * Loads unmodified files from ../upstream/ via vm:
 *   perlin.js, Vector2.js, Lander.js, Landscape.js
 * plus the checkCollisions / setLanded / setCrashed logic extracted as
 * executable copies of the upstream game.js functions (same source text),
 * run outside upstream/ so upstream/ stays byte-identical.
 *
 * Wrappers, seeding, JSON-IPC, and research instrumentation live HERE only.
 *
 * Action mapping (player-available controls only):
 *   thrust  ∈ [0,1]  — lander.thrust(power); keyboard is 0/1, touch allows continuous
 *   rotation ∈ [-90,90] quantized to 10° — lander.setRotation(angle)
 * No abort, no new capabilities.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const readline = require("readline");

const UPSTREAM = path.join(__dirname, "..", "upstream");
const PHYSICS_HZ = 60;
const SAFE_VY = 0.15;
const PERFECT_VY = 0.075;

// Research reward table (training signal). Native outcome classification is
// always from upstream landing/crash rules; scores below are research labels.
const RESEARCH_REWARD = {
  perfectLanding: 100,
  hardLanding: 40,
  crash: -100,
  timeout: -25,
  fuelPerUnit: 0.05,
  progressScale: 0.5,
};

// Curriculum v3 training signal ONLY. Native landing/scoring rules unchanged.
// Designed to discourage hover: timeout == crash, large landing bonuses,
// modest potential shaping, small per-frame time cost.
const TOUCHDOWN_V1_REWARD = {
  perfectLanding: 200,
  hardLanding: 100,
  crash: -100,
  timeout: -100,
  fuelPerUnit: 0.0,
  progressScale: 0.25,
  stepCost: 0.02,
};

function loadUpstreamSandbox() {
  const clock = { now: 1_000_000 };
  const sandbox = {
    console,
    Math,
    Date: {
      now: () => clock.now,
      getTime: () => clock.now,
    },
    performance: { now: () => clock.now },
    window: {},
    document: {
      createElement: () => ({
        getContext: () => stubCanvasContext(),
        style: {},
        width: 800,
        height: 600,
        appendChild: () => {},
      }),
      body: {
        appendChild: () => {},
        addEventListener: () => {},
        style: {},
      },
      addEventListener: () => {},
    },
    requestAnimationFrame: (cb) => setTimeout(cb, 0),
    setTimeout,
    clearTimeout,
    setThrustVolume: () => {},
    samples: { beep: { play: () => {} }, explosion: { play: () => {} } },
    TO_RADIANS: Math.PI / 180,
    clamp(value, min, max) {
      return value < min ? min : value > max ? max : value;
    },
    map(value, min1, max1, min2, max2, doClamp) {
      if (doClamp) {
        if (value <= min1) return min2;
        if (value >= max1) return max2;
      }
      return ((value - min1) / (max1 - min1)) * (max2 - min2) + min2;
    },
    counter: 0,
    infoDisplay: {
      showGameInfo: () => false,
      hideGameInfo: () => {},
      updateBoxInt: () => {},
      updateBoxTime: () => {},
      arrangeBoxes: () => {},
      domElement: { style: {} },
    },
    sendLanded: () => {},
    sendCrashed: () => {},
    sendGameOver: () => {},
    sendRestart: () => {},
    scheduleRestart: () => {},
    __clock: clock,
  };

  // Minimal Date constructor so `new Date().getTime()` in Lander.rotate works
  // under our controlled clock.
  function ControlledDate(...args) {
    if (!(this instanceof ControlledDate)) {
      return new ControlledDate(...args);
    }
    this._t = args.length ? new (Function.prototype.bind.apply(global.Date, [null].concat(args)))().getTime() : clock.now;
  }
  ControlledDate.now = () => clock.now;
  ControlledDate.prototype.getTime = function getTime() {
    return this._t;
  };
  sandbox.Date = ControlledDate;

  vm.createContext(sandbox);

  const files = ["perlin.js", "libs/Vector2.js", "Lander.js", "Landscape.js"];
  for (const rel of files) {
    const filename = path.join(UPSTREAM, rel);
    const code = fs.readFileSync(filename, "utf8");
    vm.runInContext(code, sandbox, { filename });
  }

  // Inject collision + outcome helpers — same logic as upstream game.js
  // (checkCollisions, pointIsLessThanLine, setLanded, setCrashed) without
  // loading the full DOM-coupled game.js.
  vm.runInContext(
    `
    var gameState = 1; // PLAYING
    var PLAYING = 1, LANDED = 2, CRASHED = 3, GAMEOVER = 4, WAITING = 0;
    var score = 0;
    var singlePlayMode = false;
    var lander = null;
    var landscape = null;
    var lastNativeOutcome = null;

    function bindEngine(l, scape) {
      lander = l;
      landscape = scape;
    }

    function pointIsLessThanLine(point, linepoint1, linepoint2) {
      var dist = (point.x - linepoint1.x) / (linepoint2.x - linepoint1.x);
      var yhitpoint = linepoint1.y + ((linepoint2.y - linepoint1.y) * dist);
      return ((dist > 0) && (dist < 1) && (yhitpoint <= point.y));
    }

    function setLanded(line) {
      var multiplier = line.multiplier;
      lander.land();
      var points = 0;
      var perfect = false;
      if (lander.vel.y < 0.075) {
        points = 50 * multiplier;
        perfect = true;
        lander.fuel += 50;
      } else {
        points = 15 * multiplier;
        lander.makeBounce();
      }
      score += points;
      gameState = LANDED;
      lastNativeOutcome = {
        kind: "landed",
        perfect: perfect,
        hard: !perfect,
        nativePoints: points,
        multiplier: multiplier,
        designated: multiplier > 1,
        vy: lander.vel.y,
        rotation: lander.rotation,
      };
    }

    function setCrashed() {
      lander.crash();
      // Original uses Math.random for fuel penalty display; research mode
      // records crash without mutating fuel via random (deterministic).
      // We still call lander.crash() which is the native physics outcome.
      gameState = CRASHED;
      lastNativeOutcome = {
        kind: "crashed",
        perfect: false,
        hard: false,
        nativePoints: 0,
        multiplier: 1,
        designated: false,
        vy: lander.vel.y,
        rotation: lander.rotation,
      };
    }

    function checkCollisions() {
      lastNativeOutcome = null;
      var lines = landscape.lines,
        right = lander.right % landscape.tileWidth,
        left = lander.left % landscape.tileWidth;

      while (right < 0) {
        right += landscape.tileWidth;
        left += landscape.tileWidth;
      }

      for (var i = 0; i < lines.length; i++) {
        var line = lines[i];
        line.checked = false;
        if (!((right < line.p1.x) || (left > line.p2.x))) {
          lander.altitude = line.p1.y - lander.bottom;
          line.checked = true;

          if (line.landable) {
            if (lander.bottom >= line.p1.y) {
              if ((left > line.p1.x) && (right < line.p2.x)) {
                if ((lander.rotation == 0) && (lander.vel.y < 0.15)) {
                  setLanded(line);
                } else {
                  setCrashed();
                }
              } else {
                setCrashed();
              }
              return lastNativeOutcome;
            }
          } else if ((lander.bottom > line.p2.y) || (lander.bottom > line.p1.y)) {
            lander.bottomRight.x = right;
            lander.bottomLeft.x = left;
            if (pointIsLessThanLine(lander.bottomLeft, line.p1, line.p2) ||
                pointIsLessThanLine(lander.bottomRight, line.p1, line.p2)) {
              setCrashed();
              return lastNativeOutcome;
            }
          }
        }
      }
      return lastNativeOutcome;
    }

    function snapshotLander() {
      return {
        x: lander.pos.x,
        y: lander.pos.y,
        vx: lander.vel.x,
        vy: lander.vel.y,
        rotation: lander.rotation,
        targetRotation: lander.__targetRotation !== undefined ? lander.__targetRotation : lander.rotation,
        fuel: lander.fuel,
        altitude: lander.altitude,
        thrust: lander.thrusting,
        thrustBuild: lander.thrustLevel,
        active: lander.active,
        left: lander.left,
        right: lander.right,
        bottom: lander.bottom,
        top: lander.top,
        scale: lander.scale,
      };
    }
    `,
    sandbox
  );

  return sandbox;
}

function stubCanvasContext() {
  const noop = () => {};
  return new Proxy(
    {},
    {
      get: () => noop,
    }
  );
}

function createEngine() {
  const sandbox = loadUpstreamSandbox();
  // Deterministic Math.random for landscape stars / setZones during init.
  let rngState = 0xc0ffee;
  function seededRandom() {
    // xorshift32
    rngState ^= rngState << 13;
    rngState ^= rngState >>> 17;
    rngState ^= rngState << 5;
    return ((rngState >>> 0) % 1_000_000) / 1_000_000;
  }
  sandbox.Math.random = seededRandom;

  const lander = vm.runInContext("new Lander()", sandbox);
  const landscape = vm.runInContext("new Landscape()", sandbox);
  sandbox.__lander = lander;
  sandbox.__landscape = landscape;
  vm.runInContext("bindEngine(__lander, __landscape)", sandbox);

  // Expose targetRotation for observations (closure-private in Lander).
  // We track it ourselves via setRotation calls.
  let targetRotation = -90;
  let config = null;
  let stepCount = 0;
  let status = "flying";
  let done = false;
  let totalReward = 0;
  let fuelUsed = 0;
  let lastPotential = null;
  let nativeOutcome = null;
  let zone = pickPrimaryZone(landscape);

  function pickPrimaryZone(scape) {
    let best = null;
    for (let i = 0; i < scape.lines.length; i += 1) {
      const line = scape.lines[i];
      if (!line.landable) continue;
      const width = line.p2.x - line.p1.x;
      if (width < 12) continue;
      if (!best || width > best.width) {
        best = { index: i, width, line };
      }
    }
    if (!best) throw new Error("no landable zone wide enough");
    // Mark for research "designated" comparisons; multiplier>1 mimics scoring pad.
    best.line.multiplier = Math.max(best.line.multiplier, 2);
    best.line.designated = true;
    return best.line;
  }

  function potential(obs) {
    const mid = (zone.p1.x + zone.p2.x) / 2;
    const dx = (obs.x - mid) / 100;
    const dy = (obs.y - zone.p1.y) / 100;
    return -Math.hypot(dx, dy) - Math.abs(obs.rotation) / 90;
  }

  function observe() {
    const mid = (zone.p1.x + zone.p2.x) / 2;
    const snap = vm.runInContext("snapshotLander()", sandbox);
    return {
      x: snap.x,
      y: snap.y,
      vx: snap.vx,
      vy: snap.vy,
      rotation: snap.rotation,
      fuel: snap.fuel,
      altitude: snap.altitude,
      thrust: snap.thrustBuild,
      thrustBuild: snap.thrustBuild,
      zoneLeft: zone.p1.x,
      zoneRight: zone.p2.x,
      zoneY: zone.p1.y,
      dx: mid - snap.x,
      dy: zone.p1.y - snap.y,
      step: stepCount,
      status,
      targetRotation,
      active: snap.active,
      scale: snap.scale,
    };
  }

  function applyStart(start) {
    lander.reset();
    lander.scale = start.scale;
    lander.pos.reset(start.x, start.y);
    lander.vel.reset(start.vx, start.vy);
    lander.rotation = start.rotation;
    targetRotation = start.rotation;
    lander.setRotation(start.rotation);
    // Force exact rotation after setRotation's 10° snap.
    lander.rotation = start.rotation;
    lander.fuel = start.fuel;
    lander.active = true;
    lander.thrust(0);
    lander.thrustLevel = 0;
    lander.left = lander.pos.x - 10 * lander.scale;
    lander.right = lander.pos.x + 10 * lander.scale;
    lander.bottom = lander.pos.y + 13 * lander.scale;
    lander.top = lander.pos.y - 5 * lander.scale;
    lander.bottomLeft.reset(lander.left, lander.bottom);
    lander.bottomRight.reset(lander.right, lander.bottom);
  }

  function reset(nextConfig) {
    const start = Object.assign(
      {
        x: (zone.p1.x + zone.p2.x) / 2 - 160,
        y: 150,
        vx: 0.415,
        vy: 0,
        rotation: -90,
        fuel: 1000,
        scale: 0.25,
      },
      (nextConfig && nextConfig.start) || {}
    );
    config = {
      start,
      maxSteps: (nextConfig && nextConfig.maxSteps) || 8000,
      lockedCamera: nextConfig && nextConfig.lockedCamera !== false,
      bonuses: false,
      rewardMode: (nextConfig && nextConfig.rewardMode) || "research_shaped",
    };
    if (nextConfig && nextConfig.bonuses) {
      throw new Error("bonuses disabled");
    }
    // Advance controlled clock so rotation rate limits don't block.
    sandbox.__clock.now += 1000;
    vm.runInContext("gameState = PLAYING; score = 0; lastNativeOutcome = null;", sandbox);
    applyStart(start);
    stepCount = 0;
    status = "flying";
    done = false;
    totalReward = 0;
    fuelUsed = 0;
    nativeOutcome = null;
    const obs = observe();
    lastPotential = potential(obs);
    return obs;
  }

  function step(action) {
    if (done) {
      return {
        reward: 0,
        breakdown: { shaping: 0, fuelPenalty: 0, terminal: 0 },
        done: true,
        status,
        applied: action,
      };
    }
    const thrust = Math.max(0, Math.min(1, Number(action.thrust) || 0));
    let rotation = Number(action.rotation);
    if (!Number.isFinite(rotation)) rotation = targetRotation;
    rotation = Math.round(Math.max(-90, Math.min(90, rotation)) / 10) * 10;

    sandbox.__clock.now += Math.round(1000 / PHYSICS_HZ);
    lander.setRotation(rotation);
    targetRotation = rotation;
    lander.thrust(lander.fuel > 0 ? thrust : 0);

    const fuelBefore = lander.fuel;
    lander.update();
    const burned = Math.max(0, fuelBefore - lander.fuel);
    // Perfect landing bonus fuel in setLanded would increase fuel; only count burns.
    if (lander.fuel <= fuelBefore) {
      fuelUsed += burned;
    }

    stepCount += 1;
    sandbox.counter = stepCount;

    let contact = null;
    if (lander.active) {
      contact = vm.runInContext("checkCollisions()", sandbox);
    }

    const obs = observe();
    const nextPotential = potential(obs);
    const isTouchdownV1 = config.rewardMode === "touchdown_v1";
    const shapingScale = isTouchdownV1
      ? TOUCHDOWN_V1_REWARD.progressScale
      : RESEARCH_REWARD.progressScale;
    const shaping =
      config.rewardMode === "research_shaped" || isTouchdownV1
        ? (nextPotential - lastPotential) * shapingScale
        : 0;
    lastPotential = nextPotential;
    let fuelPenalty = burned * RESEARCH_REWARD.fuelPerUnit;
    if (
      config.rewardMode === "sparse_terminal_only" ||
      config.rewardMode === "timeout_eq_crash" ||
      config.rewardMode === "step_cost" ||
      isTouchdownV1
    ) {
      fuelPenalty = 0;
    }
    // Family C / touchdown_v1: per-physics-frame cost to remove hover incentive.
    let stepCost = 0;
    if (config.rewardMode === "step_cost") stepCost = 0.01;
    if (isTouchdownV1) stepCost = TOUCHDOWN_V1_REWARD.stepCost;

    const landTable = isTouchdownV1 ? TOUCHDOWN_V1_REWARD : RESEARCH_REWARD;
    let terminal = 0;
    if (contact && status === "flying") {
      nativeOutcome = contact;
      if (contact.kind === "landed") {
        const onDesignated =
          contact.designated ||
          (obs.x > zone.p1.x && obs.x < zone.p2.x);
        if (onDesignated && contact.perfect) {
          status = "landed";
          terminal = landTable.perfectLanding;
        } else if (onDesignated) {
          status = "hard_landing";
          terminal = landTable.hardLanding;
        } else {
          status = "landed_outside_zone";
          terminal = 0;
        }
        done = true;
      } else if (contact.kind === "crashed") {
        status = "crashed";
        terminal = landTable.crash;
        done = true;
      }
    } else if (stepCount >= config.maxSteps && status === "flying") {
      status = "timeout";
      // Family C / touchdown_v1: timeout_eq_crash removes the hover incentive.
      if (
        config.rewardMode === "timeout_eq_crash" ||
        config.rewardMode === "step_cost" ||
        isTouchdownV1
      ) {
        terminal = landTable.crash;
      } else {
        terminal = RESEARCH_REWARD.timeout;
      }
      done = true;
      lander.active = false;
    }

    let shaped = shaping;
    if (
      config.rewardMode === "sparse_terminal_only" ||
      config.rewardMode === "timeout_eq_crash" ||
      config.rewardMode === "no_shaping_keep_fuel" ||
      config.rewardMode === "step_cost"
    ) {
      shaped = 0;
    }

    // Equalize timeout/crash under step_cost so neither is a cheap escape.
    if (config.rewardMode === "step_cost" && status === "timeout") {
      terminal = RESEARCH_REWARD.crash;
    }

    let reward =
      config.rewardMode === "native_score_only"
        ? (contact && contact.nativePoints) ||
          (status === "timeout"
            ? RESEARCH_REWARD.timeout
            : status === "crashed"
              ? RESEARCH_REWARD.crash
              : 0)
        : shaped - fuelPenalty - stepCost + terminal;

    // Reward-causality control: physics & native outcomes unchanged; learning
    // signal is identically zero so any behavioral change is not reward-driven.
    if (config.rewardMode === "constant_zero") {
      reward = 0;
      shaped = 0;
      fuelPenalty = 0;
      terminal = 0;
    }

    totalReward += reward;
    return {
      reward,
      breakdown: { shaping: shaped, fuelPenalty, terminal, stepCost },
      done,
      status,
      applied: { thrust, rotation },
      nativeOutcome,
      contactMetrics: done
        ? {
            vy: obs.vy,
            altitude: obs.altitude,
            dx_to_pad: obs.dx,
            dy_to_pad: obs.dy,
            dist_to_pad: Math.hypot(obs.dx, obs.dy),
            rotation: obs.rotation,
            fuel: obs.fuel,
          }
        : null,
    };
  }

  function getResult() {
    const obs = observe();
    const nativeScore = vm.runInContext("score", sandbox);
    return {
      done,
      status,
      landed: status === "landed" || status === "hard_landing",
      crashed: status === "crashed",
      timedOut: status === "timeout",
      perfect: status === "landed",
      hard: status === "hard_landing",
      fuelUsed,
      steps: stepCount,
      reward: totalReward,
      nativeOutcome,
      nativeScore,
      observation: obs,
    };
  }

  function mapInfo() {
    return {
      tileWidth: landscape.tileWidth,
      zone: {
        x1: zone.p1.x,
        x2: zone.p2.x,
        y: zone.p1.y,
        width: zone.p2.x - zone.p1.x,
      },
      points: landscape.points.map((p) => ({ x: p.x, y: p.y })),
      lineCount: landscape.lines.length,
      physicsHz: PHYSICS_HZ,
      upstream: true,
      engine: "unmodified_upstream_Lander_Landscape_via_vm",
    };
  }

  function exportState() {
    return observe();
  }

  return { reset, step, observe: exportState, getResult, mapInfo };
}

// JSON-IPC
const engine = createEngine();
const rl = readline.createInterface({ input: process.stdin, terminal: false });

function reply(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

rl.on("line", (line) => {
  if (!line.trim()) return;
  try {
    const message = JSON.parse(line);
    if (message.cmd === "reset") {
      reply({ ok: true, observation: engine.reset(message.config || {}), map: engine.mapInfo() });
    } else if (message.cmd === "observe") {
      reply({ ok: true, observation: engine.observe() });
    } else if (message.cmd === "step") {
      const stepped = engine.step(message.action || {});
      reply({ ok: true, step: stepped, observation: engine.observe(), result: engine.getResult() });
    } else if (message.cmd === "result") {
      reply({ ok: true, result: engine.getResult(), observation: engine.observe() });
    } else if (message.cmd === "geometry") {
      reply({ ok: true, map: engine.mapInfo(), observation: engine.observe(), result: engine.getResult() });
    } else if (message.cmd === "meta") {
      reply({
        ok: true,
        meta: {
          engine: "upstream_vm_host",
          upstream_dir: UPSTREAM,
          upstream_commit_file: "UPSTREAM_COMMIT.txt",
          action_mapping: {
            thrust: "lander.thrust(0..1) — keyboard binary, touch continuous",
            rotation: "lander.setRotation(angle) — 10° quantization, [-90,90]",
            not_exposed: ["abort", "mouse aiming beyond setRotation/thrust"],
          },
          physics_hz: PHYSICS_HZ,
          safe_vy: SAFE_VY,
          perfect_vy: PERFECT_VY,
        },
      });
    } else {
      reply({ ok: false, error: `unknown command ${message.cmd}` });
    }
  } catch (error) {
    reply({ ok: false, error: error.stack || error.message });
  }
});
