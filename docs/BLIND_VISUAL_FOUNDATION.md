# Blind visual gameplay foundation (Mission 013)

**Status (2026-10-27): built and verified offline with scripted, non-AI inputs only. No model has played.
No paid API call, no model-driven gameplay, no reserved evaluation.** This is the environment
PROJECT.md section 20 asks for: a future AI receives only screenshots of the authentic original
ApolloLander and may only press keyboard keys for a bounded number of frames, starting from the single
instruction "Land the rocket."

Original ApolloLander game © 2017 Seb Lee-Delisle, MIT License,
https://github.com/sebleedelisle/apollolander . Vendored unchanged at `frontend/apollolander/upstream`
(commit `0da09dc`); third-party notices in `frontend/apollolander/THIRD_PARTY.md`. R.E.A.C.T. is
independent and not affiliated with or endorsed by Seb Lee-Delisle.

## Architecture

```
 future model + tool runner (UNPRIVILEGED)          referee process (PRIVILEGED)
 ┌───────────────────────────────┐   stdin/stdout   ┌──────────────────────────────────────────┐
 │ sees: "Land the rocket.",     │  JSON lines      │ serve.py -> Session.handle (session.py)   │
 │ tools observe/act, keyset,    │ ───────────────> │   validate (contract.py), budgets, record │
 │ PNG screenshots, counters     │ <─────────────── │ referee.py: headless Chromium             │
 │ player_client.py (stdlib)     │                  │   serves ONLY SHA-256-pinned upstream     │
 └───────────────────────────────┘                  │   files; clock.js virtual time/RNG/timers │
                                                    │   reads gameState for terminal receipts   │
                                                    └──────────────────────────────────────────┘
```

| Module | Side | Role |
| --- | --- | --- |
| `contract.py` | boundary | The complete player contract: objective, two tool descriptions, keyset `keyset.v1`, request validation, exact response fields. Standard library only. |
| `player_client.py` | player | Spawns or attaches to the referee pipes; `brief()`, `observe()`, `act(keys, frames)`. Standard library only, imports nothing from `rewardbench`. |
| `serve.py` | referee | One session over stdin/stdout. stdout carries only protocol lines. |
| `session.py` | referee | Budgets, automatic episode reset, chronological records. Player responses are built only from `contract` + screenshots. |
| `referee.py` | referee | Playwright/Chromium driver: request router, clock injection, key events, tick stepping, private state for receipts. |
| `clock.js` | page | Injected before any upstream script: virtual `Date`/`performance.now`, seeded `Math.random`, frame-stepped `requestAnimationFrame`, virtual `setTimeout`/`setInterval`. Upstream code is not edited. |
| `upstream.py` | referee | SHA-256 of all 17 upstream files at `0da09dc`; refuses to start on any difference. |
| `scripted.py` | test player | Non-AI input scripts (`idle`, `key-sweep`, `seeded-random`) driven through the real pipe. |
| `replay.py` | referee | Re-runs a session's exact requests in a fresh browser and compares everything. |

## The player contract (`react.blindplay.player.v1`)

* **Brief** (the only task description): objective `"Land the rocket."`; tools `observe` ("Return the current
  game screen as an image. Does not advance the game.") and `act` ("Press and hold the listed keys (none,
  one or several) for the given number of game frames, then release them, and return the game screen. The
  game is paused between calls; it runs at 60 frames per second of game time."); keyset; limits.
* **Keyset `keyset.v1`** (alphabetical KeyboardEvent codes, no meanings): ArrowDown, ArrowLeft, ArrowRight,
  ArrowUp, Enter, Escape, KeyA, KeyD, KeyS, KeyW, ShiftLeft, Space. Not every key does something; which ones
  do, and what, is for the player to discover. Upstream effects observed by the referee (never told to a
  player): ArrowLeft/Right and A/D rotate, ArrowUp/Space thrust, S is upstream "speed mode" (3 extra physics
  updates per frame).
* **act**: `{"tool": "act", "keys": [...unique allowed keys], "frames": 1..120}`. Anything else (extra fields,
  code, controllers, other tools, non-JSON) is rejected without touching the game. Keys are pressed with real
  browser keyboard events into the upstream `KeyTracker`, and always released at the end of the call.
* **Observation fields** (exact): `protocol, seq, episode, episode_frame, episode_frame_budget, max_episodes,
  frames_advanced, episode_ended, session_over, image{media_type, width, height, sha256, base64}`. The image is
  a 1280×720 PNG of the browser viewport: the canvas plus the upstream HUD (score, time, fuel, altitude, X/Y
  velocity), all of which the original game renders on screen. No other game value crosses the boundary.
  `episode_ended` says the episode is over (crash/landing/budget), not which; the outcome is only on screen.

## Episodes

Environment `apollolander-upstream-fixed-start` (PROJECT.md 20.3 A). Each episode is a fresh browser context:
the unmodified game loads, renders 2 title frames, the referee clicks (upstream `newGame()`), and 4 playing
frames render so the HUD shows real values; then the player's first screenshot. Same seed → identical start
(spawn, landing-zone multipliers, stars); every recorded episode began from the same start frame
`fbcbb40b641e…`. An episode ends at the first upstream terminal state (LANDED, CRASHED, GAMEOVER) or when the
episode frame budget (default 8,000) is used. After a terminal state the referee shows 60 more frames with no
input so the authentic outcome screen is visible, and resets on the next request. Defaults: 20 episodes,
120 frames per act, 20,000 requests. Native score and messages are recorded separately by the referee.

Deviations from the live game, recorded in every `session.json`: paused step mode instead of `Date.now`
catch-up; seeded `Math.random`; virtual timers; muted audio; one fresh game per episode (fuel 1000, score 0,
instead of fuel and score carrying over between lives); the title screen is never shown to the player (its
only text, "CLICK OR TOUCH TO PLAY", is an instruction for the referee's click; no masking was needed).

## Records (`runs/blind-visual/<session>/`, gitignored)

`session.json` (configuration, upstream hashes, clock hash, browser/Playwright/Python versions, git commit,
served and blocked requests, page errors, outcomes); `player_transcript.jsonl` (every request and exactly what
was returned, with wall-clock timestamps and durations); `screenshots/` (every PNG returned, byte for byte);
`referee.jsonl` (privileged: every tick's state per call, terminal evidence); `episodes.jsonl` (privileged
receipts); `referee_frames/` (each episode's start frame). Records are append-only, flushed per line, and a
session refuses a non-empty directory. `replay.py` writes into `<session>/replays/<utc>/`.

## Verification (Mission 013)

Commands (Windows, `.venv`):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,blindplay]"
.\.venv\Scripts\python.exe -m playwright install chromium
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m pytest tests/blindplay -q
.\.venv\Scripts\python.exe -m rewardbench.blindplay.scripted --script idle --episodes 2 --out runs/blind-visual/<id>
.\.venv\Scripts\python.exe -m rewardbench.blindplay.replay runs/blind-visual/<id>
```

| Claim | Evidence |
| --- | --- |
| Authentic upstream code and physics | 17/17 committed files byte-identical to GitHub `0da09dc`; served files hash-checked at startup; only those files are fulfilled, all others aborted and logged (tests: served list, tampered copy refused) |
| One upstream update per frame | `vy` after 120 idle ticks = start + 120 × 0.0005; tick and `counter` advance by exactly 1 (test) |
| Keys reach the real game | each of the 12 keys appears in upstream `KeyTracker.keysPressed` and is released; ArrowUp burns fuel and changes velocity; ArrowRight rotates (tests; key-sweep record) |
| Deterministic reset and replay | identical start state and screenshots across fresh browsers; different seed differs (test); all three demo sessions replayed with identical screenshots (23/23, 66/66, 44/44), tick states and outcomes |
| Independent of wall-clock speed | same inputs with 0.4 s pauses produce identical screenshots (test) |
| Bounded actions, no injection | 23 malformed/forbidden requests rejected in unit tests; in the browser, rejected requests do not advance the game; frames capped at 120 and at the episode budget (exact 250-frame cut test) |
| No leaked state | observation field set is exact; the only numbers are procedural counters (test); brief contains no control/strategy words (test); stdout carries only protocol lines (test) |
| No substituted controller | `blindplay` imports nothing outside itself and the standard library/Playwright (AST test); no reference to the custom simulator or guidance controller (test); acts accept only keys and frames |
| Authentic outcomes | terminal state from upstream `gameState`; native messages recorded (e.g. "FUEL PENALTY −326 / LUNAR MODULE DESTROYED"); terminal screenshots show the upstream outcome screen |

Scripted demonstrations (`docs/assets/blind-visual-foundation/evidence.json`, NOT AI, never look at the
screen): `idle` 2 episodes, both crashed at frame 1293; `key-sweep` 1 episode, crashed at 1293; `seeded-random`
3 episodes, crashed at 792, 970 and 960. 0 landings. These show the pipeline works; they are not gameplay
results. Chronological problems and fixes: `docs/assets/blind-visual-foundation/DEVLOG.md`.

## Independent review of the isolation boundary

A fresh-context reviewer agent (same model family, not a human) audited the boundary on 2026-10-27 with
probe scripts. Verdict: **the protocol-level boundary is sound** (no request reaches the page, runs code,
changes seed/budget, holds keys across acts or exceeds 120 frames; PNGs carry no metadata; no measurable
timing side channel; `episode_ended` reveals nothing the screen does not). Findings and status:

| Finding | Status at pause |
| --- | --- |
| M1 a malformed line (5000-digit int, 100k `[`) crashed the referee with no record | **Fixed in code** (`serve.decode_line`: 64 KB cap, strict UTF-8, no duplicate keys/NaN, recursion/int-limit caught; raw line recorded; any exception ends the session with a record). Test written, **not yet run** |
| M2 referee stderr inherited by the player process (tracebacks show paths and upstream function names) | **Fixed in code** (fd 1 and 2 redirected to `<out>/referee_stderr.log`; client uses DEVNULL). Test written, **not yet run** |
| M3 process isolation intended, not enforced; player side chooses the serve command and self-declares `is_ai` | **Open, documented** (gap 2 below): the trusted runner must own the serve command; model gets only observe/act |
| m1 served-file hashes were constants | **Fixed in code** (hash at fulfil time; Session refuses non-pinned files) |
| m2 network log blind to WebSocket/DNS | **Fixed in code** (`--host-resolver-rules=MAP * ~NOTFOUND`, `route_web_socket` blocks and logs) |
| m3 Date edge cases, unpinned timezone/locale, throwing callback aborts the run | **Fixed in code** (exact Date pass-through, UTC/en-US, per-callback isolation recorded in `page_errors`) |
| m4 replay bypassed serve decoding and did not compare provenance or stored PNGs | **Fixed in code** (re-decodes recorded raw bytes; compares upstream/clock/browser/served files; hashes PNGs on disk) |
| m6 test gaps | Tests added for all of the above, **not yet run** |

## WORK IN PROGRESS: paused 2026-10-27 at the owner's request

The review fixes above were written but the test suite was **stopped before it finished**; their tests have
not run. The 47 earlier blind-play tests and the 440 existing tests passed on the pre-fix tree. The
scripted evidence in `docs/assets/blind-visual-foundation/` was recorded on the pre-fix tree. To resume:

1. `pip install -e ".[dev,blindplay]"`, `python -m playwright install chromium`, then
   `PYTHONPATH=src python -m pytest tests/blindplay -q` and fix anything failing.
2. Re-record the three scripted sessions and replays on the fixed tree; rebuild `evidence.json`.
3. Update PROJECT.md §0 with the verified milestone and gaps; mark the draft PR ready for review (not merge).

## Against the PROJECT.md 20.10 launch gates

| Gate | Status |
| --- | --- |
| 1 genuine original-game rendering shown to the player | **Met** (screenshots of the upstream page) |
| 2 action batches advance deterministic upstream physics, not the custom simulator | **Met** |
| 3 source and hidden state inaccessible to the player | **Met at the protocol boundary; NOT yet enforced for a model runtime** (see gaps) |
| 4 key list not described as a solution | **Met** (neutral keyset, no meanings) |
| 5 complete timestamped screenshots/actions/results retained | **Met** (no continuous video file; every frame is reproducible by replay) |
| 6 terminal claims independently checked | **Met** (referee reads upstream state; the player never self-certifies) |
| 7 crash and success clips are authentic footage | **Crash: met. Success: none exists** (no landing has occurred) |
| 8 model can actually consume screenshots | **Not verified** (needs a model runtime; PNGs are valid, non-blank 1280×720) |
| 9 tests show frame caps, restart behaviour, no leakage | **Met** |
| 10 no commercial API calls required | **Met** |

## Remaining gaps (not done, not claimed)

1. **No model runtime yet.** Nothing has consumed a screenshot as a model. The tool runner that gives a model
   exactly `observe`/`act` (and no filesystem, shell, browser or repository) is the next build step; its
   isolation must be verified technically, not by instruction (PROJECT.md 20.5).
2. **Process isolation of the player is by design, not enforcement.** `player_client.py` needs no repository
   code, but anything running on this PC as the same user could read `runs/`, the upstream source or the
   referee records. A sandboxed runner (separate OS user/container, no shared filesystem) is required before
   a model plays.
3. **No continuous video.** Screenshots per call plus deterministic replay; an MP4/WebM render from replay
   is not built.
4. **One browser/OS checked for cross-run determinism.** Determinism is verified on this Windows PC with
   Chromium 156; cross-platform pixel identity is not claimed (CI runs the same tests on Linux and macOS).
5. **No preregistered blind-play protocol yet**: episodes, frame budgets, keyset (including whether upstream
   speed mode `S` stays available), turn/time limits, model, and stop rules must be fixed before the first
   model session (PROJECT.md 20.6).
6. **Fixed start only.** Varied starts and held-out evaluation for interactive play are not designed.
