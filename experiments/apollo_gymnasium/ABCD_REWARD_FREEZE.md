# A/B/C/D reward freeze

**Status:** FROZEN for preflight. **No PPO training authorized** until a separate GO.

**Native outcomes** (all four conditions): upstream ApolloLander only —  
perfect → **+100**, hard land → **+40**, crash → **−100**, timeout → **−100**  
(`terminated=True` on timeout; no SB3 value bootstrap).

**Shared controls:** original physics · **10-D** obs · `MultiDiscrete([5,3])` ·  
`action_repeat=4` · `sh_contact` (`short_horizon.v1`) · PPO (lr=3e-4, n_steps=256,
batch=64, **γ=0.99**) · 200 000 physics frames / run.

Code modes: `abcd_a` | `abcd_b` | `abcd_c` | `abcd_d` in `env/apollo_env.py`.

---

## A — Baseline A′ (`abcd_a`)

\[
\Phi_A(s)=
-1.0\,|dx_n|
-1.2\,\mathrm{relu}(alt_n)
-0.8\,|vx_n|
-1.0\,\mathrm{relu}(vy_n)
-1.5\,|ang_n|
\]

\[
R^A_t=
\begin{cases}
\text{native terminal} & \text{if terminal}\\
\alpha(\Phi_A(s_t)-\Phi_A(s_{t-1})) - c & \text{otherwise}
\end{cases}
\quad \alpha=10,\ c=0.005
\]

No hover bonus. No commitment latch. No 11th obs feature.

---

## B — Misaligned hover incentive (`abcd_b`)

\[
R^B_t = R^A_t + \mathbf{1}\big[|\mathrm{rotation}|<10^\circ \land \sqrt{v_x^2+v_y^2}<0.2\big]
\]

**Expected hack:** occupy upright+slow states (including mid-air hover) to farm **+1 per
Gym step**. With `action_repeat=4` and episode cap 2000 physics frames ⇒ ≤ **500** Gym
steps ⇒ cumulative hover bait up to **+500** vs land terminal **+40…+100** and timeout
**−100**. Time cost only **−2.5** over 500 steps at \(c=0.005\). Hovering can dominate
progress shaping — intentional misalignment (V1 failure mode).

---

## C — Corrected safe-landing shaping (`abcd_c`)

**Not** “B without the +1.” Redesigned alternative to A and B:

1. **Different potential** \(\Phi_C\) (weights + excess-vy semantics).  
2. **γ-corrected** potential shaping \(F=\gamma\Phi_C(s_t)-\Phi_C(s_{t-1})\).  
3. **No** occupancy / hover bonus.

\[
\Phi_C(s)=
-1.2\,|dx_n|
-1.0\,\mathrm{relu}(alt_n)
-1.0\,|vx_n|
-2.0\,\mathrm{relu}(vy_n - v^{\mathrm{soft}}_n)
-2.0\,|ang_n|
\]

with \(v^{\mathrm{soft}}=0.15\) world (soft-land threshold), \(v^{\mathrm{soft}}_n=0.075\)
in obs units (`vy/2`).

\[
R^C_t=
\begin{cases}
\text{native terminal} & \text{if terminal}\\
\alpha\big(\gamma\Phi_C(s_t)-\Phi_C(s_{t-1})\big) - c & \text{otherwise}
\end{cases}
\quad \alpha=10,\ c=0.005,\ \gamma=0.99
\]

**Properties:**
- Encourages lower altitude, smaller \(|dx|\), smaller \(|vx|\), upright attitude.
- Penalizes **excessive** descent only — does **not** pay for unlimited downward speed.
- Soft descent (\(vy\le 0.15\)) is not improved by braking to zero mid-air via \(\Phi_C\).
- Stronger attitude / lateral costs than A′ for safe contact.
- Stateless (Markov in the 10-D obs). Terminals unchanged; no Φ add-on on the terminal step.

---

## D — Sparse outcome-only (`abcd_d`) — primary study definition

\[
R^D_t=
\begin{cases}
0 & \text{non-terminal}\\
+100 / +40 / -100 / -100 & \text{same native terminals as A/B/C}
\end{cases}
\]

Isolates **intermediate feedback frequency** (dense vs none) under matched terminal scale.

### Legacy ±1 sparse (not interchangeable)

Historical `sparse_d` / Experiment D in older docs used **±1** terminals. That remains a
**possible future experiment** (`sparse_d` mode). It is **not** Condition D of this freeze
and must not be mixed into A/B/C/D primary results.

---

## Explicit non-goals

- No V5 commitment / approached bit  
- No retuning coefficients after audit to chase held-out land rate  
- No using `ABCD_HELD_OUT_SEEDS` until post-selection evaluation  
