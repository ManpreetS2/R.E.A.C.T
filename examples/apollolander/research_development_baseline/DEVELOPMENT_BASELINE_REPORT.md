# ApolloLander research-mode — development baseline report

Scripted baselines only. Not an LLM result. Held-out seeds were not used.

- Schedule: `apollolander.starts.v1`
- Environment: `apollolander.env.v1`
- Development seeds: `[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]`
- Max steps: 8000
- Held-out used: `False`

## Summary table

| Baseline | Land % | Crash % | Timeout % | Mean reward | Mean fuel | Replay OK |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| random_seed0 | 0.0 | 0.0 | 100.0 | -94.87 | 798.5 | True |
| constant_coast | 0.0 | 100.0 | 0.0 | -98.88 | 0.0 | True |
| constant_hover_upright | 0.0 | 18.8 | 81.2 | -66.99 | 500.7 | True |
| hand_specified_guidance | 100.0 | 0.0 | 0.0 | 83.29 | 395.9 | True |

## Fixed-start control

Hand-specified guidance on the original spawn: land=1.0, status episodes=[{'seed': 0, 'status': 'landed', 'reward': 83.42380160701299, 'fuel_used': 396.23765624836824, 'steps': 5748, 'start': {'x': 6803.200000000001, 'y': 150.0, 'vx': 0.415, 'vy': 0.0, 'rotation': -90.0, 'fuel': 1000.0, 'scale': 0.25}, 'trace_hash': 'sha256:a42b66acbcf93ce0d5af7693c3b693cc217bb57585ac1674957fad4bef77f579', 'controller_hash': 'sha256:4e905b988d6b3537ae794d9e3759ae4f7d2b6f9f6cca22be395b8677c88dc8dd'}], replay_ok=True.

## Assessment

- Difficulty: **achievable_with_current_guidance**
- Hand-specified guidance verified landing rate on development research starts is 1.000 (mean reward 83.29; 16 designated perfect touchdowns). Weak scripted baselines do not land. A first LLM pilot on apollolander.starts.v1 is credible; no easier tier is required from this evidence.
- Recommended tier proposal: `None`
- v1 schedule left unchanged: `True`
- Suggested pilot seeds: `[0, 1, 2, 3, 4, 5, 6, 7]`

## Reproducibility spot-check

```json
{
  "seed": 7,
  "starts_equal": true,
  "rewards_equal": true,
  "trace_hashes_equal": true,
  "model_names_differ": true
}
```

## Provenance

Origins are `hand_specified_demonstration` or `deterministic_mock`. `autonomous_learning` is false for every baseline.

