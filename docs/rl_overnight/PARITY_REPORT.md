# Parity report — ApolloLander overnight RL

Generated: 2026-10-18T07:32:32Z

## Upstream identity

- Expected commit: `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`
- Local `UPSTREAM_COMMIT.txt`: `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`
- File-hash match vs GitHub clone: **PASS**
- Detail: all files match

## Action mapping (player controls only)

| Control | Upstream API | Notes |
| --- | --- | --- |
| Thrust | `lander.thrust(power)` | Keyboard UP/space = 0/1; touch allows continuous `[0,1]` |
| Rotation | `lander.setRotation(angle)` | Quantized to 10° in `[-90, 90]` (touch/mouse path) |
| Rotate keys | `lander.rotate(±1)` | 15° steps, 80ms rate limit — **not used** by RL (setRotation covers player capability) |
| Abort | `lander.abort()` | **Not exposed** to the agent |

## Headless path

- **Implementation:** Node `vm` host loading unmodified `Lander.js`, `Landscape.js`,
  `Vector2.js`, `perlin.js` from `frontend/apollolander/upstream/`.
- Collision/scoring helpers are executable copies of `game.js` logic living **outside** `upstream/`.
- Controlled clock replaces `Date` so rotation rate limits do not nondeterministically block.

## Browser vs headless-upstream (PARITY GATE)

- Overall: **PASS**

| Trajectory | Frames | Mismatches | Node terminal | Browser terminal | Exact terminal | Pass |
| --- | ---: | ---: | --- | --- | --- | --- |
| hover_thrust_sequence | 120 | 0 | flying | flying | PASS | PASS |
| descent_near_pad | 310 | 0 | flying | flying | PASS | PASS |
| crash_boundary | 115 | 0 | crashed | crashed | PASS | PASS |
| long_coast | 400 | 0 | flying | flying | PASS | PASS |

### Tolerances

- Continuous state (Node↔browser): abs tol `1e-6` (JSON float path).
- Terminal classification: **exact** match required.

### Per-item checklist

- PASS: position
- PASS: velocity
- PASS: rotation
- PASS: thrust buildup
- PASS: fuel
- PASS: gravity and drag
- PASS: terrain contact / landing vs crash
- PASS: native scoring class
- PASS: timeouts
- PASS: varied seeded starts
- PASS: repeated action sequences
- PASS: long trajectories near collision

## Custom physics.js vs upstream

The old pilot trained on `frontend/apollolander/experiment/physics.js`
(Python port for train, Node session for eval). Comparison vs upstream host:

| Trajectory | Frames | Mismatches@1e-9 | Upstream terminal | Custom terminal | Exact terminal |
| --- | ---: | ---: | --- | --- | --- |
| hover_thrust_sequence | 120 | 0 | flying | flying | YES |
| descent_near_pad | 310 | 0 | flying | flying | YES |
| crash_boundary | 115 | 1 | crashed | crashed | YES |
| long_coast | 400 | 0 | flying | flying | YES |

### Interpretation

- If mismatches are zero and terminals match, the custom simulator is a faithful
  reimplementation of the upstream integrator + collision rules for these starts.
- If mismatches are nonzero, **do not** label custom-sim training as original-game.
- Overnight training uses the upstream-vm host when this gate passes; otherwise
  training (if any) must be labeled **custom simulator**.

## Verdict

**Original-game equivalence: VERIFIED (PASS)**
