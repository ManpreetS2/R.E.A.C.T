# Observation & action specification (upstream ApolloLander)

Engine: Seb Lee-Delisle ApolloLander via `frontend/apollolander/original/`  
(`window.ApolloOriginal` → real `lander.update` / `checkCollisions` / canvas).

## Observation vector (Box, 10 floats)

| Index | Name | Definition | Units / notes |
|------:|------|------------|---------------|
| 0 | `dx_norm` | Horizontal offset to designated pad midpoint, ÷ 200 | Positive = pad to the right of lander |
| 1 | `alt_norm` | Upstream `lander.altitude` ÷ 300 | Height above terrain beneath lander |
| 2 | `vx_norm` | `lander.vel.x` ÷ 2 | World x velocity |
| 3 | `vy_norm` | `lander.vel.y` ÷ 2 | World y velocity (down positive in game sense as used by engine) |
| 4 | `angle_norm` | Actual `lander.rotation` ÷ 90 | Degrees, clipped to [−90, 90] in engine |
| 5 | `cmd_angle_norm` | Last commanded target angle ÷ 90 | Set via `setRotation` (snapped to 10°) |
| 6 | `fuel_norm` | `lander.fuel` ÷ 1000 | |
| 7 | `thrust_norm` | `lander.thrustLevel` (build) | ≈ [0, 3] internally; passed as reported |
| 8 | `pad_width_norm` | Designated landable segment width ÷ 200 | Terrain geometry cue |
| 9 | `dy_pad_norm` | Vertical offset to pad line y ÷ 300 | Pad-relative height |
| 10 | `approached` | **V5 only** — latched 1 once `alt < 25` and `|dx| < 60` | Episodic; required so commitment reward is not hidden-state |

Default / V3 A′ observation is **10-D** (indices 0–9). V5 commitment training uses **11-D**.

Clipped to [−5, 5] after normalization for numerical safety.

**Not observed:** future collisions, expert actions, episode outcome, native terminal bonus before it happens.

## Action space

`MultiDiscrete([5, 3])`:

| Dim | Meaning | Mapping |
|-----|---------|---------|
| 0 | Thrust level | `{0, 0.25, 0.5, 0.75, 1.0}` → `lander.thrust` |
| 1 | Relative steer | `{−10°, 0, +10°}` added to commanded angle, then `setRotation` |

Each Gym `step` holds the chosen thrust/command for **`action_repeat`** physics frames (default **4**; probed in `scripts/probe_action_repeat.py`).

Landing rule (upstream, unchanged): on a landable segment, **`rotation == 0`** and **`vel.y < 0.15`** for a soft/perfect path (hard landings still set `LANDED` with higher impact).

## Native vs training reward

- **Native:** upstream `score` / HUD outcome in `info` (`native_score`, `status`, `perfect`, `hard_landing`, `crashed`).
- **Training:** see `REWARD_DEFINITIONS.md` — never written into the game.
