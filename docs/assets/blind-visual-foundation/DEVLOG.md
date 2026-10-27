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
