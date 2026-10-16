# First genuine LLM comparison protocol (not executed)

## Feasibility study vs statistical benchmark

| | Smallest defensible **feasibility** pilot | Later **benchmark** |
| --- | --- | --- |
| Goal | Prove live paired arms + freeze + sealed eval work with a real model | Estimate feedback effect with uncertainty |
| Model | One model (`gpt-5.4-mini`) | Same, then replicate across providers |
| Revisions | 2 (one paid call per invocation; human pause) | Pre-registered larger K if needed |
| Development seeds | Matched small set (e.g. 8) | Same matched set across arms |
| Final eval | `apollolander.final_eval.v1` (16 reserved seeds) once frozen | Same cohort; no re-tuning |
| Replicates | 1 paired run | Multiple independent experiment ids |
| Claim allowed | “pipeline ran; costs/tokens recorded” | Descriptive held-out comparison with CI / caveats |

**Recommendation:** run the feasibility pilot first. Do not claim statistical
adaptation superiority from a single paired run.

## Design (feasibility)

1. **Arms:** `numerical_reward` vs `no_feedback`  
   Configs: `configs/apollolander_pilot_openai_gpt54mini.yaml` and
   `configs/apollolander_pilot_openai_gpt54mini_nofeedback.yaml` (or copies
   with study-specific `experiment_name` / `database_path`).
2. **Same:** model, schema, simulator, development seeds, revision count,
   `max_output_tokens: 800`, `reasoning_effort: none`, retries `0`, software
   spend policy.
3. **Development:** matched starts; record flights; log tokens and estimated USD.
4. **Freeze:** `last_valid_selected` after each arm completes (or after the
   pre-declared revision budget).
5. **Held-out:** `python -m rewardbench.heldout` on cohort
   `apollolander.final_eval.v1` (`2000000`…`2000015`) — **no model calls**.
   Do **not** use burned seeds `1000000`…`1000007` for the research claim
   (see `docs/FINAL_EVALUATION_PROTOCOL.md`).
6. **Report:** development curves + sealed held-out table; costs; flight
   replays. Publish honest outcomes even if numerical feedback is worse.
7. **Forbidden:** changing starts mid-study; selecting controllers by held-out
   score; feeding held-out rewards into prompts; pooling Apollo with Gymnasium.

## Spend posture

- Prefer the same per-process one-call pause used by the live CLI.
- Keep vendor billing limits below the owner’s comfort threshold.
- Software `max_cost_usd` is not a provider hard stop.

## Pre-registration note

Before the first paid development call of this study, freeze in writing:

- model id and settings  
- revision count and selection rule  
- development seed list  
- final-eval cohort id (`apollolander.final_eval.v1`)  
- spend ceiling  

Do not execute this protocol in the release-audit sprint.
