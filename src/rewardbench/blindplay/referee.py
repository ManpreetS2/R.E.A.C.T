"""Privileged referee: runs the authentic upstream game in a browser and steps it frame by frame.

PRIVILEGED. This module may read hidden game state (to detect landings/crashes and to keep receipts).
Nothing it reads is returned to a player; ``session.Session`` builds player messages only from
``contract`` and screenshots.

* The page is served only from the SHA-256-pinned upstream files (``upstream.load_upstream``) through
  a request router; every other request is aborted and logged.
* ``clock.js`` is injected before any upstream script. Upstream code is not edited.
* One referee tick = one ``requestAnimationFrame`` callback of the upstream ``loop()``: one upstream
  ``lander.update()`` (four while the upstream "speed mode" key is held), then the upstream render.
* Keys are pressed with real browser keyboard events, which the upstream ``KeyTracker`` receives.
* Each episode is a fresh browser context, loaded and started identically (same seed): a fixed start.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rewardbench.blindplay import contract, upstream

CLOCK_JS = Path(__file__).with_name("clock.js")
ORIGIN = "http://apollolander.upstream"
VIEWPORT = {"width": 1280, "height": 720}
PRE_START_TICKS = 2       # title/attract frames rendered before the referee starts the game
START_TICKS = 4           # playing frames before the first screenshot: upstream refreshes its HUD only when
                          # counter % 4 == 0, so fewer would show the stale "FUEL 0000 / ALT 000" text
SETTLE_TICKS = 60         # frames shown after a terminal event (no input) so the outcome is visible
BROWSER_ARGS = ["--mute-audio", "--disable-gpu", "--force-color-profile=srgb", "--font-render-hinting=none",
                "--disable-lcd-text", "--disable-renderer-backgrounding", "--disable-background-timer-throttling",
                # no name resolves: nothing can leave the machine even if a request escaped the router
                "--host-resolver-rules=MAP * ~NOTFOUND"]

# upstream game.js states
WAITING, PLAYING, LANDED, CRASHED, GAMEOVER = 0, 1, 2, 3, 4
TERMINAL_STATES = {LANDED, CRASHED, GAMEOVER}

# KeyboardEvent.code (player-facing) -> Playwright key name
PLAYWRIGHT_KEYS = {k: k for k in contract.ALLOWED_KEYS}
PLAYWRIGHT_KEYS.update({"KeyA": "a", "KeyD": "d", "KeyS": "s", "KeyW": "w", "Space": " ", "ShiftLeft": "Shift"})

_SNAPSHOT_JS = """
() => ({
  tick: window.__reactClock.frame(), counter: counter, gameState: gameState,
  x: lander.pos.x, y: lander.pos.y, vx: lander.vel.x, vy: lander.vel.y, rotation: lander.rotation,
  fuel: lander.fuel, altitude: lander.altitude, thrusting: +lander.thrusting, active: !!lander.active,
  score: score, multiplier: (typeof multiplier === 'undefined') ? null : multiplier,
  keysDown: Object.keys(KeyTracker.keysPressed).filter(function (k) { return KeyTracker.keysPressed[k]; }).map(Number)
})
"""

_RUN_JS = """
(args) => {
  const snap = %s;
  const out = [];
  for (let i = 0; i < args.n; i++) {
    window.__reactClock.tick();
    const s = snap();
    out.push(s);
    if (args.stop && s.gameState !== %d) break;
  }
  return out;
}
""" % (_SNAPSHOT_JS.strip(), PLAYING)


class RefereeError(RuntimeError):
    """The environment could not be run as specified. Nothing is substituted."""


# Playwright's sync API allows one driver per thread; referees share it (each has its own browser).
_driver: Any = None
_driver_users = 0


def _acquire_driver() -> Any:
    global _driver, _driver_users
    if _driver is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depends on the optional extra
            raise RefereeError("playwright is required: pip install -e .[blindplay] && playwright install chromium") from exc
        _driver = sync_playwright().start()
    _driver_users += 1
    return _driver


def _release_driver() -> None:
    global _driver, _driver_users
    _driver_users -= 1
    if _driver_users <= 0 and _driver is not None:
        _driver.stop()
        _driver, _driver_users = None, 0


def classify(final: dict[str, Any], previous_score: int) -> str:
    """Terminal classification from the upstream game's own state and scoring."""
    state = final["gameState"]
    if state == LANDED:
        points = final["score"] - previous_score
        return "landed_perfect" if final["multiplier"] and points == 50 * final["multiplier"] else "landed_hard"
    if state == CRASHED:
        return "crashed"
    if state == GAMEOVER:
        return "crashed_out_of_fuel_game_over"
    raise ValueError(f"not terminal: {state}")


@dataclass
class Referee:
    seed: int = 0
    headless: bool = True
    files: dict[str, bytes] = field(default_factory=upstream.load_upstream)
    requests: list[dict[str, str]] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.seed, int) or not 0 <= self.seed < 2**32:
            raise RefereeError("seed must be an integer in [0, 2**32)")
        self.clock_source = CLOCK_JS.read_text(encoding="utf-8").replace("__SEED__", str(self.seed))
        self.clock_sha256 = hashlib.sha256(CLOCK_JS.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        self._pw = self._browser = self._context = self.page = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._pw = _acquire_driver()
        self._browser = self._pw.chromium.launch(headless=self.headless, args=BROWSER_ARGS)

    @property
    def browser_version(self) -> str:
        return self._browser.version if self._browser else ""

    def close(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except Exception:  # noqa: BLE001 - best effort shutdown
                pass
        if self._pw:
            _release_driver()
        self._pw = self._browser = self._context = self.page = None

    def __enter__(self) -> "Referee":
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _route(self, route: Any) -> None:
        url = route.request.url
        name = url[len(ORIGIN) + 1:].split("?")[0] if url.startswith(ORIGIN + "/") else None
        if name in self.files:
            body = self.files[name]
            self.requests.append({"url": url, "result": "served", "sha256": hashlib.sha256(body).hexdigest()})
            route.fulfill(status=200, body=body, headers={"content-type": upstream.content_type(name)})
        else:
            self.requests.append({"url": url, "result": "blocked"})
            route.abort()

    def _websocket(self, ws: Any) -> None:
        # Never calling ws.connect_to_server() keeps the socket mocked: nothing reaches any server. Do not call
        # ws.close() here: inside a sync-API route handler it waits forever and freezes the referee (Mission 013).
        self.requests.append({"url": ws.url, "result": "blocked_websocket"})

    # ------------------------------------------------------------------ episodes
    def reset(self) -> dict[str, Any]:
        """Fresh context, load the unmodified game, start it identically. Returns the private start state."""
        if self._browser is None:
            raise RefereeError("referee not started")
        if self._context is not None:
            self._context.close()
        self._context = self._browser.new_context(viewport=VIEWPORT, device_scale_factor=1, has_touch=False,
                                                  is_mobile=False, java_script_enabled=True, service_workers="block",
                                                  timezone_id="UTC", locale="en-US")
        self._context.add_init_script(script=self.clock_source)
        self._context.route("**/*", self._route)
        self._context.route_web_socket("**/*", self._websocket)
        page = self.page = self._context.new_page()
        page.on("pageerror", lambda exc: self.page_errors.append(str(exc)))
        page.goto(f"{ORIGIN}/index.html", wait_until="load")
        checks = page.evaluate("""() => ({
            clock: typeof window.__reactClock === 'object', frame: window.__reactClock.frame(),
            seeded: String(Math.random).indexOf('0x6d2b79f5') >= 0, state: gameState,
            touch: ('ontouchstart' in window), width: window.innerWidth, height: window.innerHeight })""")
        if not (checks["clock"] and checks["seeded"] and checks["frame"] == 0 and not checks["touch"]):
            raise RefereeError(f"deterministic shim not active before the game: {checks}")
        if checks["state"] != WAITING:
            raise RefereeError(f"upstream game did not reach its title state: {checks}")
        page.evaluate("() => document.fonts.load('bold 14pt HersheySimplex')")
        page.evaluate("() => document.fonts.ready.then(() => true)")
        if not page.evaluate("() => document.fonts.check('bold 14pt HersheySimplex')"):
            raise RefereeError("upstream Hershey font did not load")
        self.run([], PRE_START_TICKS, stop_on_terminal=False)
        page.mouse.click(VIEWPORT["width"] // 2, VIEWPORT["height"] // 2)   # upstream onMouseDown -> newGame()
        ticks = self.run([], START_TICKS, stop_on_terminal=False)
        if ticks[-1]["gameState"] != PLAYING:
            raise RefereeError(f"game did not start: {ticks[-1]}")
        return ticks[-1]

    def run(self, keys: tuple[str, ...] | list[str], n: int, *, stop_on_terminal: bool = True) -> list[dict[str, Any]]:
        """Hold ``keys`` for up to ``n`` ticks (stopping after a terminal tick), then release them."""
        if self.page is None:
            raise RefereeError("no episode")
        pressed: list[str] = []
        try:
            for key in keys:
                self.page.keyboard.down(PLAYWRIGHT_KEYS[key])
                pressed.append(key)
            ticks = self.page.evaluate(_RUN_JS, {"n": int(n), "stop": bool(stop_on_terminal)})
            self.page_errors.extend(self.page.evaluate("() => window.__reactClock.takeErrors()"))
            return ticks
        finally:
            for key in reversed(pressed):
                self.page.keyboard.up(PLAYWRIGHT_KEYS[key])

    def snapshot(self) -> dict[str, Any]:
        return self.page.evaluate(_SNAPSHOT_JS)

    def message(self) -> str:
        return self.page.evaluate("() => { const m = document.querySelector('.titleBox'); "
                                  "return m && m.style.visibility !== 'hidden' && m.style.display !== 'none' ? m.innerText : ''; }")

    def screenshot(self) -> bytes:
        return self.page.screenshot(type="png", full_page=False, animations="allow", caret="initial")
