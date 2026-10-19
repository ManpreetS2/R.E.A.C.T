# A/B/C/D reward study — design only (not launched)

**Status:** Proposed. **Do not train** until a separate go decision after research reset.

This document defines a scientifically interpretable four-condition experiment about
whether **reward design** changes learning on original ApolloLander (`sh_contact`
short-horizon starts). It is **not** a continuation of the V3–V5 exploratory pilots.

---

## How this differs from V3–V5 pilots

| | V3–V5 exploratory pilots | Proposed A/B/C/D study |
|--|--------------------------|-------------------------|
| Goal | Find *any* learned landing; iterate one change at a time | Compare **reward conditions** under matched protocol |
| Design | Sequential (V3 A′ → V4 time-cost → V5 commitment) | Parallel 2×2-style four conditions |
| Seeds | One training seed (0); tiny held-outs (n=20) | ≥3 training seeds × 4 conditions; larger held-out |
| Selection | DEV land-rate checkpoint picking (V3-40k) | Preregistered selection rule; same for all conditions |
| Claim risk | Easy to over-read V3-40k as “A′ works” | V3-40k is a **DEV-selected checkpoint from one run**, not an unbiased estimate of a new A′ train |
| Obs | V5 changed to 11-D | **Identical 10-D obs for A/B/C/D** (no commitment latch) |

**Explicit non-claim:** The frozen V3-40k checkpoint is useful as a historical
incumbent / feasibility reference. It is **not** Condition A’s expected outcome
under a fresh multi-seed protocol.

---

## Conditions (identical env except reward)

**Shared for all four:**

- Engine: upstream Seb Lee-Delisle ApolloLander (unchanged native score / physics)
- Start: `sh_contact` seed-varied
- Obs: **10-D** as in V3 A′ (`OBSERVATIONS.md`) — no 11th feature
- Actions: `MultiDiscrete([5,3])`, `action_repeat=4`
- Episode cap: 2000 physics frames; timeout = `terminated` (−100)
- Terminals: +100 perfect / +40 hard / −100 crash / −100 timeout
- PPO: same hyperparameters as V3 pilot (`lr=3e-4`, `n_steps=256`, `batch=64`, γ=0.99)
- Init: independent random weights per (condition × train seed)
- Budget: **identical** physics-frame cap per run (propose **200 000** frames, matching pilots)

### A — Reasonable baseline shaping (progress A′)

\[
R^A_t = \alpha(\Phi_t-\Phi_{t-1}) - c_{\mathrm{time}}
\quad(\alpha=10,\ c=0.005)
\]

plus native terminals. **No** commitment term. **No** hover occupancy bonus.

### B — Intentionally misaligned hovering incentive

\[
R^B_t = R^A_t + \mathbf{1}\big[|\mathrm{rotation}|<10^\circ \land \sqrt{v_x^2+v_y^2}<0.2\big]
\]

per Gym step. Designed to reward upright+slow occupancy (V1 failure mode).

### C — Corrected shaping

Must differ from A in a **preregistered** structured way (not post-hoc V5):

**Proposed freeze (subject to pre-train reward-scale audit only — no mid-study retune):**

\[
R^C_t = \alpha_C(\Phi_t-\Phi_{t-1}) - c_C
\quad(\alpha_C=10,\ c_C=0.005)
\]

plus a **stateless** late-phase descent bonus that does **not** use hidden history:

\[
r_{\mathrm{descend}} = +\beta_C\cdot\max(0, v_y)\cdot\mathbf{1}[\mathrm{alt}<H]\cdot\mathbf{1}[|dx|<D]
\]

with \(\beta_C\) chosen so expert/reference rollouts satisfy
\(\mathbb{E}|R^{\mathrm{dense}}| \gtrsim 3\,c\) and land returns ≫ crash returns
(audit gate). Alternatively, if audit rejects this, C = A with **only**
`timeout` semantics / potential weights corrected as documented in
`REWARD_DEFINITIONS.md` Experiment C (\(\alpha>1\) already in A′ — then C must
use a distinct documented fix such as soft-land velocity shaping without ascent latch).

> Final C formula must be frozen in `ABCD_REWARD_FREEZE.md` after scale audit,
> before any training. No V5 stateful `approached` bit.

### D — Sparse outcome-only

\[
R^D_t =
\begin{cases}
0 & \text{non-terminal}\\
+1 & \text{native land (perfect or hard)}\\
-1 & \text{crash or timeout}
\end{cases}
\]

---

## Protocol

| Item | Spec |
|------|------|
| Train seeds | `{0,1,2}` (≥3) per condition → **12 runs** |
| Physics budget | 200 000 frames / run (hard guard; no overshoot) |
| DEV selection | `ABCD_DEV_SEEDS` (n=50), land-rate → −timeout → −duration |
| Held-out | `ABCD_HELD_OUT_SEEDS` (n=100), **one-shot** after selection |
| Metrics | Native perfect/hard/crash/timeout, frames, fuel, failure modes, Wilson CIs |
| Reporting | Per seed + pooled; unsuccessful policies reported honestly (0% land OK) |
| Preflight | Reward-scale audit on reference + crash + timeout traces for A/B/C/D |
| Hardware | Local CPU + Playwright Chromium (no paid cloud required) |

### Estimated resources

| Quantity | Estimate |
|----------|----------|
| Runs | 12 (4×3) |
| Physics frames | 12 × 200 000 = **2.4 M** |
| Wall-clock @ ~700 frames/s (V5 ~200k in ~285 s) | ≈ **50–70 minutes** train |
| Eval | 12 selected + step0×4 + baselines on n=100 ≈ **~2–4 hours** browser eval |
| Disk | ~0.5–1 GB models/logs/videos |
| Hardware | 1× Apple Silicon / x86 CPU laptop; headless Chromium; ≥8 GB RAM |

---

## Pre-train gates (must PASS)

1. Parity / upstream engine unchanged  
2. Reward-scale audit: for each of A/B/C/D, reference land return ≫ crash return; B shows hover bait on hover traces  
3. Obs/action identical across conditions  
4. Seed pools disjoint and unused  
5. Budget guard unit tests  

---

## Honest handling of unsuccessful policies

- Report native land rate even if 0%.  
- Do not substitute train return for landing.  
- If all checkpoints are 0% land, selection still follows the preregistered rule and is labeled as such (V5 lesson: selected may be step0).  
- Always report a **trained final** and **selected** checkpoint side-by-side on held-out.

---

## Out of scope for this study

- `original_fixed` / full-game spawn curriculum  
- V6 commitment retries  
- Merging PR #11 as “solved landing”  
- Using champion validation pool (`600k`) for selection  
