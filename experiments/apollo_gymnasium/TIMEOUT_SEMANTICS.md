# Timeout semantics (V3 A′ pilot)

For `ppo_pilot_v3_contact_Aprime` the episode frame budget
(`max_physics_frames`, default **2000** for `sh_contact`) is defined as a
**terminal experimental failure**, not a soft computational cutoff.

| Event | `terminated` | `truncated` | Training reward | Native status |
|-------|--------------|------------|-----------------|---------------|
| Perfect land | True | False | +100 | `landed` / perfect |
| Hard land | True | False | +40 | `hard_landing` |
| Crash | True | False | −100 | `crashed` |
| Frame budget hit | **True** | **False** | −100 | `timeout` |

Rationale: SB3 PPO bootstraps the critic on `truncated=True`. Treating the
task budget as `terminated=True` makes −100 a true episode end (no value
bootstrap), matching the scientific intent that “still flying after N frames”
is failure for this short-horizon task.

Native landings and crashes are never invented or relabeled as timeouts.
`timeout_as_terminated=True` is the default when `reward_mode=progress_a_prime`.
