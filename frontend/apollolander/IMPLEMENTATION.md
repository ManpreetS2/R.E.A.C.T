# ApolloLander integration

The original game is vendored, unchanged, at `frontend/apollolander/upstream`.
Upstream commit `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`. Copyright (c) 2017
Seb Lee-Delisle, MIT. Third-party libraries are listed in `THIRD_PARTY.md`.
The experiment physics does not load jsfx, audio.js, or jsfxlib.js because
those files have no license header.

## What stayed the same

`experiment/physics.js` copies the original lander update: rotation lerp 0.3,
thrust acceleration 0.0015, fuel burn 0.2 times thrust build, drag 0.9997,
gravity 0.0005, and the original `velY` assignment that does not clamp `vel.y`.
Terrain comes from the public-domain simplex noise in `perlin.js` with seed
12039. A landing requires the feet to sit inside one horizontal segment,
rotation exactly 0, and vertical speed below 0.15. Below 0.075 is a perfect
landing. One `step()` is one original update. The browser play page may call
`step()` on a 60 Hz accumulator; that clock does not change the integrator.

## What the experiment changes

Controlled trials use one landscape and one designated pad: the widest
landable segment at least 12 units wide. On this map that pad is x 6873.6 to
7052.8, y about 679.44. Multipliers are forced to 1. `bonuses: true` throws.
The standard start is x = pad midpoint minus 160, y = 150, vx = 0.415,
vy = 0, rotation = -90, fuel = 1000, scale = 0.25. Alternate starts are
explicit objects. Episode seeds name matched trials and do not move the
terrain or the ship. `Math.random` and `Date.now` are not used.

Drawing enlarges the rocket so it is at least 48 pixels tall in a 1920×1080
locked view of the arena. Collision still uses scale 0.25. The picture is
the simulated position with a larger icon, the same approach the original
game uses when the camera is zoomed out.

## Reward

| Event | Value |
| --- | --- |
| Perfect designated landing | +100 |
| Hard designated landing (vertical speed under 0.15) | +40 |
| Safe landing outside the designated pad | 0, and `landed` stays false |
| Crash | -100 |
| Timeout | -25 |
| Fuel | -0.05 per fuel unit burned that step |
| Progress | 0.5 times the change in potential |

Potential is the negative distance to the pad center, in hundreds of units,
minus absolute rotation over 90. `landed` is true only when the verifier
records a designated segment, rotation 0, and vertical speed under 0.15.

## Experiment runner

`ApolloLanderAdapter` implements contract `1.0.0`: `describe`, `validate_policy`,
and `run_episode`. `describe().environment_id` is `apollolander`. Gymnasium's
runner id stays `lunarlander-v3`. A model submits the controller object.
`validate_policy` rejects JavaScript and does not start Node. `run_episode`
resets the same landscape and the same standard start for every seed, then
returns `EpisodeResult` with `fuel_used` and the pad coordinates. `success` is
true only for a verified designated-zone landing.

The sample runner config is `examples/apollolander/development_numerical.yaml`.
Construct the adapter with `make_environment("apollolander")`. Pass
`record_dir` and `record_video=True` when a revision should also write the
1920×1080 recording. The definitions in `rewardbench.contracts` are not copied
into this package.

## Programmable API

Node session (`experiment/session.js`), one JSON object per line:

`reset`, `observe`, `step`, `result`, `geometry`, `replay`.

Python: `ApolloLanderAdapter` in `src/rewardbench/environments/apollolander/`.
`make_environment("ApolloLander")` registers it beside `LunarLander-v3`.
Controllers are `rewardbench.apollolander.controller.v1` with `guidance` or
`constant` commands. Thrust is 0 to 1. Rotation is a multiple of 10 from
-90 to 90. Fields named code, js, javascript, script, eval, function, or
python are rejected and the episode is not started.

The guidance numbers in `demonstration_guidance_controller()` were tuned by
hand. Reports that use them must keep `origin` as
`hand_specified_demonstration` and `autonomous_learning` false.

## Local game

Original: serve `frontend/apollolander/upstream` and open `index.html`.

Fixed map: serve `frontend/apollolander` and open `experiment/index.html`.
Arrow keys rotate, space thrusts, R resets, L and K switch the camera.

```bash
node frontend/apollolander/experiment/physics.test.js
PYTHONPATH=src .venv/bin/python -m pytest tests/environments -q
PYTHONPATH=src .venv/bin/python examples/apollolander/run_demonstrations.py
```
