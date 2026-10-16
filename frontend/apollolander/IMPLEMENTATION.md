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
explicit objects. `Math.random` and `Date.now` are not used.

### Demonstration mode (default)

`ApolloLanderAdapter(research_mode=False)` keeps the original fixed spawn.
Episode seeds name matched trials and do not move the terrain or the ship.
`seed_affects_physics` is false.

### Research mode (opt-in)

`ApolloLanderAdapter(research_mode=True)` keeps the same terrain, pad,
physics, and landing verifier. Starting `x`, `y`, `vx`, `vy`, and `rotation`
are derived from the episode seed through schedule version
`apollolander.starts.v1` in `rewardbench.environments.apollolander.starts`.
Fuel stays at 1000 unless `vary_fuel=True`. `scale` stays 0.25.

Derivation is `sha256(f"{version}:{seed}:{channel}")` mapped into documented
ranges. The same seed always yields the same start, so two models compared on
identical seed lists face identical physical conditions. Development seeds
(`0 .. 999_999`) and held-out seeds (`>= 1_000_000`) induce disjoint start
catalogs; use `development_start_catalog` / `held_out_start_catalog` and
`assert_schedules_disjoint` to verify.

Do not pass an explicit `start=` override while research mode is on.

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
`validate_policy` rejects JavaScript and does not start Node. In demonstration
mode `run_episode` resets the same landscape and the same standard start for
every seed. In research mode it resets the same landscape and a seed-derived
start. It returns `EpisodeResult` with `fuel_used`, pad coordinates, and
`start_*` metrics when research mode is on. `success` is true only for a
verified designated-zone landing.

Sample configs:

| File | Mode |
| --- | --- |
| `examples/apollolander/development_numerical.yaml` | Fixed start (demonstration) |
| `examples/apollolander/research_development_numerical.yaml` | Research starts, development seeds |
| `examples/apollolander/research_heldout_numerical.yaml` | Research starts, held-out seeds |

Construct the adapter with `make_environment("apollolander")` or
`make_environment("apollolander", research_mode=True, start_schedule_version="apollolander.starts.v1")`.
Pass `record_dir` and `record_video=True` when a revision should also write the
1920×1080 recording. The definitions in `rewardbench.contracts` are not copied
into this package.

## Agent 1 — wiring research mode

The ExperimentRunner is unchanged. Agent 1 should construct the environment
before calling the runner:

```python
from rewardbench.environments import make_environment

env = make_environment(
    "apollolander",
    research_mode=True,
    start_schedule_version="apollolander.starts.v1",
    vary_fuel=False,  # optional; default false
)
```

Recommended config metadata (already present in the research YAML examples):

```yaml
metadata:
  research_mode: true
  start_schedule_version: apollolander.starts.v1
  vary_fuel: false
  adapter_kwargs:
    research_mode: true
    start_schedule_version: apollolander.starts.v1
    vary_fuel: false
```

Rules for fair comparisons:

1. Keep `development_seeds` and `held_out_seeds` disjoint (existing contract).
2. Give every model under comparison the same seed list for a given split.
3. Bump `start_schedule_version` only when ranges change; record the version in
   experiment metadata so old logs stay interpretable.
4. Leave `research_mode` off for the original fixed-map demonstration flights.
5. Label hand-written controllers with `origin="hand_specified_demonstration"`;
   `autonomous_learning` stays false.

## Agent 1 — flight records and SQLite hooks

Every executed episode from `evaluate` includes a `flight_record` object (schema
`rewardbench.apollolander.flight_record.v1`) with:

| Field | Purpose |
| --- | --- |
| `environment_id` / `environment_version` | Simulator identity (`apollolander.env.v1`) |
| `start_schedule_version` | Research schedule id, or null in fixed mode |
| `episode_seed` / `initial_state` | Exact spawn used |
| `controller` / `controller_hash` | Parameters submitted |
| `revision_index` / `origin` / `model` | Provenance |
| `autonomous_learning` | Always `false` from this adapter for demos/mocks |
| `max_steps` | Episode step budget (required for timeout-faithful replay) |
| `terminal.*` | Reward, status, verified landing, steps, fuel |
| `trace` / `trace_hash` | Action list and replay identifier |
| `video_path` | Optional MP4 path when `record_video=True` |

When `record_dir` and `record_video=True` are set, the adapter also writes:

- `apollo-<model>-revision-<n>-seed-<s>.mp4`
- `apollo-<model>-revision-<n>-seed-<s>.flight.json`

Replay check (environment-side, no ExperimentRunner change):

```python
result = adapter.verify_flight_record(path_to_flight_json)
assert result["matched"]
```

Deterministic tolerances are documented on the record as
`replay_tolerances` (reward/state abs `1e-9`, steps `0`).

**Origin labels** (pass as `evaluate(..., origin=...)`):

- `hand_specified_demonstration` — human-tuned demos
- `deterministic_mock` — scripted/mock controllers
- `model_generated` — future LLM controllers

Never treat hand-specified or mock flights as autonomous AI improvement.

**Hook for linking MP4 to an experiment id:** the ExperimentRunner / SQLite layer
should persist `episodes[].flight_record_path`, `episodes[].video_path`, and
`episodes[].trace_hash` (or the full `flight_record`) onto the episode row or a
sidecar table. Environment code does not know the experiment id and does not
modify the runner. Suggested fields for Agent 1:

```text
episodes.metrics["trace_hash"]
episodes.metrics["environment_version"]  # if metrics stay float-only, store paths in attempt/episode JSON blob
attempt or episode artifact paths: video_path, flight_record_path
```

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
