# Mission 013 development log (chronological, 2026-10-27)

Every problem met while building the blind-visual foundation, in the order it happened, including our
own mistakes. Nothing here involved a model or a paid API call. The setup agent did not play or
optimise the game; all gameplay inputs were the scripted, non-AI sequences in `scripted.py`.

1. **Vendored upstream did not byte-match GitHub (resolved, not a content change).** Fetching the 17 files
   of `sebleedelisle/apollolander@0da09dc` and comparing with the Windows working copy: 2 identical (the
   fonts), 15 different. Cause: `core.autocrlf=true` checks the text files out with CRLF. The committed
   git blobs are byte-identical to upstream (17/17), and no upstream text file contains a carriage
   return, so the referee normalises CRLF to LF and verifies against SHA-256 pinned from the GitHub
   download (`upstream.py`). Any other difference refuses to start (tested by tampering a copy).
2. **Playwright browser revision mismatch.** A Chromium build (1234) was cached on this PC, but the
   installed Python Playwright 1.64.1 requires build 1248. Downloaded the matching headless shell
   (Chrome 156.0.8078.4). The version is pinned in the `blindplay` extra and recorded in every session.
3. **A naive virtual clock would silently drop or duplicate upstream physics updates.** `game.js` decides
   how many updates to run from `floor((Date.now() - start) / (1000/60))`. Checked offline in Node over
   about 26 million (start, elapsed) frame pairs: `frame * 1000/60` gave 8,827,544 wrong frame counts;
   integer-millisecond rounding gave 11,986,594; a large realistic epoch with a bias still gave 152,426.
   Only a zero epoch plus a 1e-6 ms per-frame bias gave 0. `clock.js` uses that; a unit test re-checks it
   and asserts the failure is still observable with the plain clock. Confirmed in the browser: after
   120 idle ticks vertical speed equals start + 120 × 0.0005 (upstream gravity), i.e. exactly one
   upstream update per tick.
4. **First prototype screenshot showed `FUEL 0000 / ALT 000`.** Upstream refreshes the HUD only when
   `counter % 4 == 0`; after one playing frame the HUD still showed its initial text, which would tell a
   player the tank is empty. `START_TICKS` raised from 1 to 4 (the first refresh). Same for every episode.
5. **Own tooling mistakes (no effect on results).** A POSIX `/c/...` path passed to Windows Python; a
   stray `python -` in a shell command waited on stdin (Mission 012 docs step; stopped and rerun).
6. **Test written with a wrong physical assumption.** `test_keys_change_the_upstream_physics` expected
   ArrowUp to reduce vertical speed. The authentic start is rotated -90 degrees, so thrust is
   horizontal: fuel fell (1000 to 988.8 over 60 frames) and `vx` changed, `vy` did not. The test now
   asserts fuel burn and a changed velocity vector. The environment was right; the test was wrong.
7. **Playwright sync API allows one driver per thread.** Tests creating a second referee while a
   module-scoped one was open failed ("Sync API inside the asyncio loop"). Referees now share one
   reference-counted driver; each still has its own browser and each episode its own context.
8. **Hint filter false positives.** The no-hints test matched `turn` inside "return" and `down` in
   "hold down the listed keys". Switched to whole-word matching and reworded the tool text to "Press and
   hold" so not even a generic directional word appears.
9. **Checked anomaly: identical crash frame.** `scripted-idle` and `scripted-key-sweep` both crashed on
   episode frame 1293. Referee data shows different trajectories (key-sweep rotated to -30 degrees,
   burned fuel, crashed at x 3720.6 / y 587.5 with altitude 5.17 on a sloped segment; idle at
   x 3739.4 / y 570.2, rotation -90). A coincidence of two real trajectories, not a frozen game.

Outcome of the scripted demonstrations (all reported, none selected): 6 episodes, 6 crashes, 0 landings,
0 timeouts. Each session replayed in a fresh browser with identical screenshots, tick states and outcomes.

## Paused, then resumed (2026-10-27, same PC)

The session was paused at the owner's request after the independent-review fixes were written but before
their tests had finished (checkpoint `4e20dfa`). Resumed later the same day.

10. **The paused test run had not merely been stopped: it hung.** `pytest tests/blindplay` ran for more than
    10 minutes without output. A `faulthandler` stack dump showed it blocked in `Referee._websocket` ->
    `WebSocketRoute.close()`. Calling `close()` inside a Playwright *sync-API* `route_web_socket` handler
    waits forever, so the review fix m2 (block and log WebSockets) would have frozen the referee the
    moment any page opened a socket. Fix: record the attempt and do not connect; a routed socket that never
    calls `connect_to_server()` is mocked by Playwright, so nothing reaches a server (and
    `--host-resolver-rules` resolves no host anyway). The seal test now also asserts the socket attempt is
    logged and the referee keeps ticking. After the fix: `tests/blindplay` 52 passed in 20 s; full suite
    492 passed (440 + 52), 0 failed, 0 skipped; Node physics/replay checks pass. Commit `2f4f25a`.
    All other review fixes (M1 malformed input, M2 stderr, m1, m3, m4) passed their tests unchanged.
11. **Upstream re-verified against GitHub.** The 17 vendored git blob SHA-1s equal the GitHub tree of
    `0da09dc` (17/17; the only extra file is our `UPSTREAM_COMMIT.txt`), and a fresh download of all 17 raw
    files matches the SHA-256 pins in `upstream.py` (17/17).
12. **Re-recorded on the fixed, clean tree** into a new directory, `runs/blind-visual/mission013-verify-20261027`
    (the originals were hashed first, 305 files, and re-checked afterwards: unchanged; so were the 419 Mission
    010/012 run files). Same scripts, seeds and budgets as before. The new recordings equal the pre-fix ones
    **byte for byte**: 133/133 screenshots, every referee tick state, all 6 episode receipts, one start frame.
    `clock.js`'s hash differs (review fix m3 edited it) without changing a single output byte. Each session
    then replayed in a fresh Chromium: 23/23, 66/66, 44/44 identical, provenance identical.
13. **Hostile-input session through the real pipe**: 44 malformed/forbidden lines (oversized ints, 100k
    brackets, invalid UTF-8, duplicate keys, Infinity, >64 KB, `eval`/`state`/`reset` tools, injected
    `javascript`/`seed`/`episode_frame_budget` fields) interleaved with 5 valid requests. 0 bytes reached the
    player's stderr; every rejection is a fixed contract message naming no file, path or game variable; the
    5 valid responses are identical to a clean control session that received only those 5 lines (rejected
    lines advance nothing); both sessions replay identically. A sweep of all 380 player-visible responses
    (286 PNGs) across the 10 recorded sessions found 0 field violations and no PNG metadata chunks
    (only IHDR/IDAT/IEND). Scripts: `verify/`; evidence: `evidence-verified-2026-10-27.json`.
14. **Own mistake (no effect on results):** the first run of `build_evidence.py` mixed a relative session
    root with an absolute repository root and failed in `Path.relative_to`; rerun with absolute paths.
15. **CI.** The run before the pause was not merely cancelled: it ran 6 h 0 m to GitHub's job limit, the same
    WebSocket hang as entry 10. After the fix, commit `9ba7c98` passed on Windows, macOS and Ubuntu (Actions
    runs 40547788929 push and 40547794521 PR): 320 core/provider/analysis + 52 blind-play + 120 environment
    tests per OS, plus the Node physics/replay checks. The job now has a 45-minute timeout.
