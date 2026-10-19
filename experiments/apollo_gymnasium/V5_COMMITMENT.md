# V5 — Late-approach commitment shaping (frozen)

**Status:** Formula / thresholds / coefficient frozen from development diagnostics
before training. Sole intentional change vs V3 A′.

**V4 negative result preserved:** global `c: 0.005 → 0.02` did not fix
post-approach re-ascent (DEV 10%, held-out 15%). V3-40k remains incumbent until
V5 demonstrates native-landing improvement.

## Diagnosis (V3-40k + V4)

Timeouts are **commitment aborts**, not never-approaching:

| | Land | Timeout (post-approach re-ascent) |
|--|-----:|----------------------------------:|
| Frames | ~80–170 | 2000 |
| `min_alt` | ≈ 0 | ≈ 5 |
| `alt_last` | ≈ 0 | ≈ 1000 |
| At ascent onset | — | `alt≈5`, `vy≈0→neg`, `rot=0`, thrust≈0.75 |

Successful held-out V3 landings: **zero** soft-ascent samples (`vy < 0` while near
pad / upright). Failures climb away after a soft near-pad approach.

## Frozen term (ONE component)

Latch (episode-local, exposed in obs):

\[
\texttt{approached} \leftarrow \texttt{True when } \mathrm{alt} < H_{\mathrm{app}}
\land |dx| < D_{\mathrm{app}}
\]

Dense add-on (per Gym step, after A′ potential / time cost):

\[
r_{\mathrm{commit}} =
\begin{cases}
-\beta\,\max(0,-v_y)
& \texttt{approached}
\land v_y < V_{\mathrm{soft}}
\land |\mathrm{rotation}| < R_{\mathrm{soft}} \\
0 & \text{otherwise}
\end{cases}
\]

| Symbol | Value | Rationale |
|--------|------:|-----------|
| \(H_{\mathrm{app}}\) | **25** | Timeouts reach ~5; covers early climb-out |
| \(D_{\mathrm{app}}\) | **60** | Near-pad corridor (land \|dx\|~11) |
| \(V_{\mathrm{soft}}\) | **0.15** | Native soft-land `vy` threshold — hard falls may abort |
| \(R_{\mathrm{soft}}\) | **15°** | Attitude recovery allowed when tilted |
| \(\beta\) | **1.0** | Offline: land commit≈0; re-ascent ≪ 0 |

**Not rewarded:** occupying low altitude.  
**Not rewarded:** unsafe falling.  
**Not penalized:** ascent while `vy ≥ V_soft` or `|rot| ≥ R_soft` (braking / recovery).

## Observation change (required by stateful latch)

When commitment shaping is on, obs is **11-D**: original 10 + `approached ∈ {0,1}`.
The reward process does not depend on hidden history beyond this explicit feature.

## Controlled variables (unchanged from V3 A′)

- `α = 10`, `c_time = 0.005`, terminals +100/+40/−100/−100
- `sh_contact`, `action_repeat=4`, MultiDiscrete `[5,3]`
- Same PPO hyperparams, upstream physics
- Timeout = `terminated`

## Reward mode

`progress_a_prime_v5` (or `commitment_shaping=True` with A′).
