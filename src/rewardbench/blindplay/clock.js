// R.E.A.C.T. blind-play deterministic clock (injected by the referee before any upstream script).
//
// The upstream ApolloLander files are served unchanged. This shim only replaces the browser's
// sources of time and randomness so that the referee, not the wall clock, decides when the game
// advances:
//   * Date / Date.now / performance.now return virtual time: frame * (1000/60) + frame * 1e-6 ms.
//     The 1e-6 ms per frame bias makes the game's floor((now - start) / (1000/60)) equal the exact
//     frame difference (plain frame * 1000/60 drops frames through float rounding; see DEVLOG).
//   * requestAnimationFrame callbacks and setTimeout/setInterval timers run only inside tick().
//   * Math.random is a seeded mulberry32 stream (the game's spawn x, zone multipliers, crash fuel
//     penalty and particles are therefore identical for identical seeds and inputs).
// __SEED__ is substituted by the referee.
(function () {
  "use strict";
  var MPF = 1000 / 60, BIAS = 1e-6;
  var frame = 0;
  function now() { return frame * MPF + frame * BIAS; }

  var RealDate = Date;
  function VirtualDate() {
    if (!(this instanceof VirtualDate)) return new RealDate(now()).toString();
    if (arguments.length === 0) return new RealDate(now());
    // explicit arguments are passed through unchanged, exactly as the real constructor treats them
    return new (Function.prototype.bind.apply(RealDate, [null].concat([].slice.call(arguments))))();
  }
  VirtualDate.prototype = RealDate.prototype;
  Object.defineProperty(RealDate.prototype, "constructor", { value: VirtualDate, writable: true, configurable: true });
  VirtualDate.now = now;
  VirtualDate.parse = RealDate.parse;
  VirtualDate.UTC = RealDate.UTC;
  window.Date = VirtualDate;
  if (window.performance) {
    try { Object.defineProperty(window.performance, "now", { value: now, configurable: true }); } catch (err) {}
  }

  var state = (__SEED__ >>> 0) || 0x9e3779b9;
  Math.random = function () {
    state = (state + 0x6d2b79f5) >>> 0;
    var t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };

  var rafQueue = [], nextId = 1, timers = [], errors = [];
  // A browser reports an exception thrown by one callback and carries on with the next; so do we,
  // and the referee collects the reports.
  function call(kind, fn, self, args) {
    try { fn.apply(self, args); }
    catch (err) { errors.push(kind + " at frame " + frame + ": " + (err && err.stack ? err.stack : String(err))); }
  }
  window.requestAnimationFrame = function (cb) { var id = nextId++; rafQueue.push({ id: id, cb: cb }); return id; };
  window.cancelAnimationFrame = function (id) { rafQueue = rafQueue.filter(function (r) { return r.id !== id; }); };
  ["webkit", "moz", "ms", "o"].forEach(function (p) {
    window[p + "RequestAnimationFrame"] = window.requestAnimationFrame;
    window[p + "CancelAnimationFrame"] = window.cancelAnimationFrame;
  });
  function addTimer(cb, ms, args, every) {
    if (typeof cb !== "function") throw new Error("string timer callbacks are not supported");
    var id = nextId++;
    timers.push({ id: id, due: now() + Math.max(0, +ms || 0), cb: cb, args: args, every: every });
    return id;
  }
  function clearTimer(id) { timers = timers.filter(function (t) { return t.id !== id; }); }
  window.setTimeout = function (cb, ms) { return addTimer(cb, ms, [].slice.call(arguments, 2), 0); };
  window.setInterval = function (cb, ms) { return addTimer(cb, ms, [].slice.call(arguments, 2), Math.max(1, +ms || 0)); };
  window.clearTimeout = clearTimer;
  window.clearInterval = clearTimer;

  function runTimers() {
    for (var guard = 0; guard < 100000; guard++) {
      var t = now(), due = null;
      for (var i = 0; i < timers.length; i++) {
        if (timers[i].due <= t && (due === null || timers[i].due < due.due || (timers[i].due === due.due && timers[i].id < due.id))) due = timers[i];
      }
      if (due === null) return;
      if (due.every) due.due += due.every; else clearTimer(due.id);
      call("timer", due.cb, window, due.args);
    }
    throw new Error("timer storm");
  }

  function tick() {
    frame += 1;
    runTimers();
    var queue = rafQueue;
    rafQueue = [];
    for (var i = 0; i < queue.length; i++) call("requestAnimationFrame", queue[i].cb, window, [now()]);
  }

  Object.defineProperty(window, "__reactClock", {
    value: Object.freeze({ tick: tick, frame: function () { return frame; }, pending: function () { return rafQueue.length; },
                           takeErrors: function () { var e = errors; errors = []; return e; } }),
    enumerable: false, configurable: false, writable: false
  });
})();
