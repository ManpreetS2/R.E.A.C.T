# Reward: `touchdown_v1` (frozen before training)

Training signal only. **Physics and native landing/scoring rules never change.**
Success is judged solely by native landings (`rotation == 0` and `vy < 0.15` on a
landable pad line; perfect if `vy < 0.075`).

| Term | Value | Notes |
| --- | ---: | --- |
| Perfect native landing | **+200** | Designated pad, perfect |
| Hard native landing | **+100** | Designated pad, hard |
| Crash | **−100** | Native crash |
| Timeout | **−100** | Same as crash (no hover escape) |
| Per-physics-frame time cost | **−0.02** | Discourages lingering |
| Potential shaping | **0.25 × ΔΦ** | Φ = −‖pad offset‖/100 − \|rotation\|/90 |
| Fuel penalty | **0** | Removed (fuel already scarce via physics) |

Implemented in `frontend/apollolander/rl_overnight/upstream_engine_host.js` as
`rewardMode: "touchdown_v1"`. This table is frozen for the whole curriculum run.
