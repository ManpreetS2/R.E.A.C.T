/*
 * Opt-in bridge around the vendored upstream ApolloLander runtime.
 *
 * Upstream files under ../upstream/ are not modified. This script wraps the
 * existing globals (lander, landscape, render, checkCollisions, ...) so an
 * external controller can drive the REAL game update/render path one step at
 * a time, with optional seeded Math.random for reproducible zone layout.
 *
 * Start modes (experimental bridge only; upstream physics unchanged):
 * - fixed (default): original upstream-style spawn at pad midpoint − 160,
 *   y=150, vx=0.415, vy=0, rotation=−90, fuel=1000. Episode seed does not
 *   change the physical start.
 * - research: apply an explicit start override from the versioned Python
 *   schedule ``apollolander.starts.v1`` (or an equivalent documented map).
 *   Research mode refuses to silently fall back to the fixed start.
 *
 * This bridge is NOT the published custom Node research simulator.
 *
 * Deviations from casual play (documented):
 * - Physics advances only when step() is called (no Date.now catch-up).
 * - scheduleRestart is disabled so the episode does not auto-reset.
 * - Math.random may be replaced with a seeded LCG during reset.
 * - Landing-zone multipliers can be forced to 1 for controlled trials.
 * - Sounds are muted when samples are unavailable.
 * - Research mode overrides only the initial lander state; terrain, pad,
 *   collisions, scoring, and rendering remain upstream.
 */
(function () {
  "use strict";

  var realRandom = Math.random;
  var outcome = null;
  var stepCount = 0;
  var totalReward = 0;
  var mode = "play";
  var lastStatus = "waiting";
  var recorder = null;
  var recordedChunks = [];
  var designatedLine = null;
  var physicsLoop = null;

  function installLoopWrapper() {
    if (typeof loop !== "function" || physicsLoop) return;
    physicsLoop = loop;
    loop = function () {
      if (mode === "step") {
        requestAnimationFrame(loop);
        if (typeof updateView === "function") updateView();
        if (typeof updateParticles === "function") updateParticles();
        if (typeof render === "function") render();
        return;
      }
      return physicsLoop();
    };
  }

  installLoopWrapper();

  function seedRandom(seed) {
    var state = (seed >>> 0) || 1;
    Math.random = function () {
      state = (Math.imul(1664525, state) + 1013904223) >>> 0;
      return state / 4294967296;
    };
  }

  function restoreRandom() {
    Math.random = realRandom;
  }

  function muteSounds() {
    if (typeof samples === "undefined" || !samples) return;
    Object.keys(samples).forEach(function (key) {
      var sample = samples[key];
      if (sample && typeof sample.play === "function") {
        sample.play = function () {};
      }
    });
  }

  function disableAutoRestart() {
    window.scheduleRestart = function () {};
  }

  function enterStepMode() {
    installLoopWrapper();
    mode = "step";
    disableAutoRestart();
    muteSounds();
  }

  function forceZoneMultipliers(ones) {
    if (!landscape || !landscape.lines) return null;
    var best = null;
    for (var i = 0; i < landscape.lines.length; i++) {
      var line = landscape.lines[i];
      if (!line.landable) continue;
      if (ones) line.multiplier = 1;
      var width = line.p2.x - line.p1.x;
      if (!best || width > best.width) {
        best = { line: line, width: width, index: i };
      }
    }
    designatedLine = best ? best.line : null;
    return best;
  }

  function defaultStart(pad) {
    var mid = pad ? (pad.line.p1.x + pad.line.p2.x) / 2 : 1000;
    return {
      x: mid - 160,
      y: 150,
      vx: 0.415,
      vy: 0,
      rotation: -90,
      fuel: 1000,
      scale: 0.25,
    };
  }

  function requireResearchStart(config) {
    var required = ["x", "y", "vx", "vy", "rotation"];
    for (var i = 0; i < required.length; i++) {
      var key = required[i];
      if (typeof config[key] !== "number" || !isFinite(config[key])) {
        throw new Error(
          "research start_mode requires finite numeric start." +
            key +
            " (refusing silent fixed-start fallback)"
        );
      }
    }
  }

  function setBanner(startMode) {
    var el = document.getElementById("bridge-banner");
    if (!el) return;
    if (startMode === "research") {
      el.textContent =
        "ORIGINAL UPSTREAM PHYSICS · RESEARCH STARTS (bridge overrides spawn only)";
    } else {
      el.textContent = "ORIGINAL UPSTREAM RUNTIME · FIXED START · EXPERIMENT BRIDGE";
    }
  }

  function reset(config) {
    config = config || {};
    enterStepMode();
    outcome = null;
    stepCount = 0;
    totalReward = 0;
    lastStatus = "flying";
    particles = [];
    spareParticles = [];

    var startMode = config.start_mode === "research" ? "research" : "fixed";
    var scheduleVersion =
      typeof config.start_schedule_version === "string" ? config.start_schedule_version : null;
    if (startMode === "research") requireResearchStart(config);

    if (typeof config.seed === "number") seedRandom(config.seed | 0);
    else restoreRandom();

    gameState = PLAYING;
    score = 0;
    time = 0;
    counter = 0;
    gameStartTime = Date.now();

    lander.reset();
    lander.scale = config.scale != null ? config.scale : 0.25;
    lander.fuel = config.fuel != null ? config.fuel : 1000;
    lander.active = true;

    if (typeof landscape.setZones === "function") landscape.setZones();
    var pad = forceZoneMultipliers(config.bonuses === true ? false : true);
    var start = defaultStart(pad);
    if (startMode === "research") {
      // Explicit overrides only — never leave residual fixed-start values.
      start = {
        x: config.x,
        y: config.y,
        vx: config.vx,
        vy: config.vy,
        rotation: config.rotation,
        fuel: config.fuel != null ? config.fuel : 1000,
        scale: config.scale != null ? config.scale : 0.25,
      };
    } else {
      if (config.x != null) start.x = config.x;
      if (config.y != null) start.y = config.y;
      if (config.vx != null) start.vx = config.vx;
      if (config.vy != null) start.vy = config.vy;
      if (config.rotation != null) start.rotation = config.rotation;
      if (config.fuel != null) start.fuel = config.fuel;
      if (config.scale != null) start.scale = config.scale;
    }

    lander.pos.x = start.x;
    lander.pos.y = start.y;
    lander.vel.x = start.vx;
    lander.vel.y = start.vy;
    lander.rotation = start.rotation;
    lander.setRotation(start.rotation);
    lander.fuel = start.fuel;
    lander.scale = start.scale;
    lander.thrust(0);
    setBanner(startMode);

    if (infoDisplay && infoDisplay.hideGameInfo) infoDisplay.hideGameInfo();
    if (typeof updateView === "function") updateView();
    if (typeof render === "function") render();

    return {
      observation: observe(),
      zone: pad
        ? { x1: pad.line.p1.x, x2: pad.line.p2.x, y: pad.line.p1.y, width: pad.width, index: pad.index }
        : null,
      start: start,
      start_mode: startMode,
      start_schedule_version: scheduleVersion,
      engine: "upstream-original",
      experiment_kind:
        startMode === "research"
          ? "upstream-physics-research-starts"
          : "upstream-fixed-start",
      not_custom_node_simulator: true,
    };
  }

  function observe() {
    var altitude = lander.altitude;
    var mid = designatedLine ? (designatedLine.p1.x + designatedLine.p2.x) / 2 : lander.pos.x;
    var padWidth = designatedLine ? designatedLine.p2.x - designatedLine.p1.x : 0;
    return {
      x: lander.pos.x,
      y: lander.pos.y,
      vx: lander.vel.x,
      vy: lander.vel.y,
      rotation: lander.rotation,
      fuel: lander.fuel,
      altitude: altitude,
      thrust: lander.thrustLevel || 0,
      dx: mid - lander.pos.x,
      dy: (designatedLine ? designatedLine.p1.y : lander.pos.y) - lander.pos.y,
      pad_width: padWidth,
      native_score: typeof score !== "undefined" ? score : null,
      step: stepCount,
      status: lastStatus,
      gameState: gameState,
    };
  }

  function classify() {
    if (gameState === LANDED) {
      lastStatus = lander.vel && lander.vel.y < 0.075 ? "landed" : "hard_landing";
      outcome = {
        status: lastStatus,
        landed: true,
        crashed: false,
        perfect: lastStatus === "landed",
      };
      return;
    }
    if (gameState === CRASHED || gameState === GAMEOVER) {
      lastStatus = "crashed";
      outcome = { status: "crashed", landed: false, crashed: true, perfect: false };
    }
  }

  function step(action) {
    if (outcome) {
      return { observation: observe(), result: getResult(), reward: 0 };
    }
    action = action || {};
    var thrust = typeof action.thrust === "number" ? action.thrust : 0;
    var rotation = typeof action.rotation === "number" ? action.rotation : lander.rotation;
    thrust = Math.max(0, Math.min(1, thrust));
    lander.thrust(thrust);
    lander.setRotation(rotation);

    var fuelBefore = lander.fuel;
    lander.update();
    if (lander.thrusting) makeThrustParticles();
    checkCollisions();
    updateView();
    updateParticles();
    stepCount += 1;

    classify();
    var fuelUsed = Math.max(0, fuelBefore - lander.fuel);
    var reward = -0.05 * fuelUsed;
    if (outcome) {
      if (outcome.landed && outcome.perfect) reward += 100;
      else if (outcome.landed) reward += 40;
      else if (outcome.crashed) reward += -100;
    }
    totalReward += reward;
    return {
      observation: observe(),
      result: getResult(),
      reward: reward,
      applied: { thrust: thrust, rotation: Math.round(rotation / 10) * 10 },
    };
  }

  function getResult() {
    return {
      status: lastStatus,
      landed: !!(outcome && outcome.landed),
      crashed: !!(outcome && outcome.crashed),
      perfect: !!(outcome && outcome.perfect),
      hard_landing: !!(outcome && outcome.landed && !outcome.perfect),
      steps: stepCount,
      reward: totalReward,
      fuelRemaining: lander.fuel,
      native_score: typeof score !== "undefined" ? score : null,
      done: !!outcome,
      engine: "upstream-original",
      gameState: gameState,
    };
  }

  function startRecording() {
    recordedChunks = [];
    if (!canvas || !canvas.captureStream) {
      throw new Error("canvas.captureStream is unavailable");
    }
    var stream = canvas.captureStream(60);
    var mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
      ? "video/webm;codecs=vp9"
      : "video/webm";
    recorder = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond: 8000000 });
    recorder.ondataavailable = function (event) {
      if (event.data && event.data.size > 0) recordedChunks.push(event.data);
    };
    recorder.start(200);
    return { ok: true, mime: mime };
  }

  function stopRecording() {
    return new Promise(function (resolve, reject) {
      if (!recorder) {
        reject(new Error("recording was not started"));
        return;
      }
      recorder.onstop = function () {
        var blob = new Blob(recordedChunks, { type: recorder.mimeType || "video/webm" });
        var reader = new FileReader();
        reader.onloadend = function () {
          resolve({
            mime: blob.type,
            bytesBase64: String(reader.result).split(",")[1] || "",
            size: blob.size,
          });
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      };
      recorder.stop();
    });
  }

  function snapshotPNG() {
    return canvas.toDataURL("image/png");
  }

  window.ApolloOriginal = {
    enterStepMode: enterStepMode,
    reset: reset,
    step: step,
    observe: observe,
    getResult: getResult,
    startRecording: startRecording,
    stopRecording: stopRecording,
    snapshotPNG: snapshotPNG,
    restoreRandom: restoreRandom,
    engine: "upstream-original",
  };
})();
