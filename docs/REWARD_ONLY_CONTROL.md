# Reward-only information control

**Status:** implemented and offline-tested. No paid study has been run. No reserved
final-evaluation seeds (`2000000`–`2000015`) were used. Kept separate from the
completed offline v1 evidence.

## Why

`numerical_reward` shows the scalar reward **plus** `success`, `steps`, `crashed`,
and simulator `metrics`. Comparing it with `no_feedback` therefore tests richer
simulator feedback, not the causal effect of the reward number.

## The control

`feedback_condition: reward_only` prints, per scored episode, only
`episode N reward=X`. Everything else is rendered exactly as in the other conditions.

| Condition | History shows |
| --- | --- |
| `no_feedback` | controllers only |
| `reward_only` | controllers + reward |
| `numerical_reward` | controllers + reward + success/steps/crashed/metrics |

Valid contrasts:

* `reward_only` vs `no_feedback` → effect of the scalar reward value.
* `numerical_reward` vs `reward_only` → added effect of outcome and simulator metrics.

## Proof the prompts differ only in the intervention

`tests/prompts/test_reward_only.py` renders one identical stored history under
each condition and asserts:

* system prompts are identical;
* after removing the single `Earlier revisions ...` condition-disclosure sentence,
  `reward_only` and `no_feedback` differ only by the added `episode N reward=X` lines;
* `reward_only` never prints `success=`, `steps=`, `crashed=`, `metrics=`, or any metric name/value;
* `numerical_reward` minus its extra fields equals `reward_only` line for line.

The disclosure sentence is part of the intervention: each condition tells the model
what it is (not) being shown. It is unavoidable and symmetric.

## Run (offline, scripted)

```bash
python -m rewardbench.operate run \
  --config configs/apollolander_offline_development_nofeedback.yaml \
  --config configs/apollolander_offline_development_rewardonly.yaml \
  --config configs/apollolander_offline_development_numerical.yaml
```

The scripted model reacts to any non-empty feedback, so this only exercises the
plumbing. A genuine causal comparison requires real-model runs, which need
separate owner approval (provider, model, USD ceiling).
