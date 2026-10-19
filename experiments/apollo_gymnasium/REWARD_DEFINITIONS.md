# Training rewards (native game score unchanged)

Upstream physics, collisions, LANDED/CRASHED, and on-screen `score` are **never** modified.
Training reward `R_t` is computed in Python only.

**Status:** A/B/C/D are scientific *definitions*. Do not train B/C/D until Experiment A
produces learned landings and budget is approved. Experiment D remains blocked.

## Potential (shared progress basis)

\[
\Phi(s) =
-1.0\,|dx_{\mathrm{norm}}|
-1.2\,alt_{\mathrm{norm}}
-0.8\,|vx_{\mathrm{norm}}|
-1.0\,\mathrm{relu}(vy_{\mathrm{norm}})
-1.5\,|angle_{\mathrm{norm}}|
\]

Normalized features match `OBSERVATIONS.md`. Potential-based shaping uses **deltas**
\(\Phi_t-\Phi_{t-1}\), not absolute occupancy payments.

## Experiment A — Progress baseline (intended)

\[
R_t^{A} =
\begin{cases}
+100 & \text{perfect landing} \\
+40 & \text{hard landing} \\
-100 & \text{crash} \\
-100 & \text{timeout (see termination note)} \\
(\Phi_t-\Phi_{t-1}) - c_{\mathrm{time}} & \text{otherwise}
\end{cases}
\]

**Pilot code currently uses** \(c_{\mathrm{time}}=0.05\). Root-cause analysis proposes
raising dense scale and/or lowering \(|c_{\mathrm{time}}|\) relative to \(\Delta\Phi\)
(see `outputs/root_cause/` and `ROOT_CAUSE_ANALYSIS.md`) before the next approved pilot.

### Termination / truncation (SB3)

| Event | Gymnasium flags | SB3 value bootstrap |
|-------|-----------------|---------------------|
| Land / crash | `terminated=True` | No bootstrap (target 0) |
| Frame budget timeout | historically `truncated=True` | **Bootstraps** \(V(s')\) |

**Proposed fix (not yet trained):** treat learning-failure timeouts as `terminated=True`
(or emit `TimeLimit.truncated` info while setting terminated for PPO), so −100 is a true
episode end for the critic. Keep a separate eval-only truncation flag if needed for logs.

## Experiment B — Intentional hover bait (planned)

\[
R_t^{B} = R_t^{A} + \mathbf{1}\big[|\mathrm{rotation}|<10^\circ \land \sqrt{v_x^2+v_y^2}<0.2\big]
\]

Per **Gym step** (not per physics frame). Same terminals as A. Designed to reward
occupying upright+slow states — the failure mode seen in pilot v1.

## Experiment C — Corrected progress (planned; **distinct from A**)

Must differ from A in at least one structured way:

\[
R_t^{C} =
\begin{cases}
+100 / +40 / -100 / -100 & \text{same terminals as A} \\
\alpha(\Phi_t-\Phi_{t-1}) - c_{\mathrm{time}}^{C} & \text{otherwise}
\end{cases}
\]

with \(\alpha>1\) (amplify potential deltas) and \(c_{\mathrm{time}}^{C}\) chosen so that
\(\mathbb{E}|\alpha\Delta\Phi| \gtrsim 3\,c_{\mathrm{time}}^{C}\) on expert rollouts, **and**
timeouts marked `terminated` for PPO. No upright+slow occupancy bonus.

> **Code bug note (PR #11):** `progress_a` and `progress_c` previously both returned
> \(\Delta\Phi-0.05\). Spec and implementation must diverge before any A/B/C run.

## Experiment D — Sparse / outcome-only (blocked)

\[
R_t^{D} =
\begin{cases}
0 & \text{non-terminal} \\
+1 & \text{native landing (perfect or hard)} \\
-1 & \text{crash or timeout}
\end{cases}
\]

Same physics, obs, legal actions, PPO, starts, and held-out eval as A/B/C.
**Do not train until A lands and budget is approved.**

## Optional E — Zero reward (negative control, blocked)

\(R_t^{E}=0\) always. Pipeline sanity only; clearly labeled.

## Historical pilots (frozen)

| Run | Timeout reward | \(c_{\mathrm{time}}\) | Result |
|-----|----------------|------------------------|--------|
| v1 | −20 (truncated) | 0.01 | 100% timeout hover |
| v2 | −100 (truncated) | 0.05 | 100% crash, 0% land |

Do not rewrite these results; cite them as negative evidence.
