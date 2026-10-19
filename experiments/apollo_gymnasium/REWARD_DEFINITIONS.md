# Training rewards (native game score unchanged)

Upstream physics, collisions, LANDED/CRASHED, and on-screen `score` are **never** modified.
Training reward `R_t` is computed in Python only.

## Potential (progress)

\[
\Phi(s) =
-1.0\,|dx_{\mathrm{norm}}|
-1.2\,alt_{\mathrm{norm}}
-0.8\,|vx_{\mathrm{norm}}|
-1.0\,\mathrm{relu}(vy_{\mathrm{norm}})
-1.5\,|angle_{\mathrm{norm}}|
\]

Using the same normalized features as the observation (see `OBSERVATIONS.md`).
`relu(vy)` penalizes downward speed more than upward.

## Pilot / Experiment A (progress + terminals)

\[
R_t =
\begin{cases}
+100 & \text{perfect landing (native)} \\
+40 & \text{hard landing (native)} \\
-100 & \text{crash} \\
-100 & \text{timeout (truncated)} \\
(\Phi_t - \Phi_{t-1}) - 0.05 & \text{otherwise}
\end{cases}
\]

Timeout matches crash severity so delaying forever is not preferred to attempting a landing
(early pilot with timeout=−20 learned deterministic hover-until-timeout; see report).
Per-step time cost \(0.05\) further discourages lingering. Potential **deltas** (not absolute
“looks good” payments) follow the LunarLander tutorial lesson.

## Experiment B (planned — do not train until A lands)

\[
R_t^{B} = R_t^{A} + \mathbf{1}[|angle|<10^\circ \land \sqrt{vx^2+vy^2}<0.2]
\]

(per physics-aware definition documented at run time; upright+slow bonus).

## Experiment C (planned)

Potential-delta form of A with explicit time cost retained / tuned; no static occupancy bonus.

## Experiment D — sparse / outcome-only (planned)

\[
R_t^{D} =
\begin{cases}
0 & \text{non-terminal Gym step} \\
+1 & \text{native landing (perfect or hard)} \\
-1 & \text{crash or timeout}
\end{cases}
\]

PPO must treat timeouts as truncated terminals with the −1 applied on the truncated transition (documented in the training script when enabled).

**Gate:** Do not start B/C/D/E until Experiment A (pilot) demonstrates genuine learned landings on a nontrivial start where no-input fails.
