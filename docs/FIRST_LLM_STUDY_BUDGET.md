# First real-LLM study: budget

**Spent so far (recorded estimates, not an invoice): $0.042646**, all under the ledger root
`runs/first-llm-study/`: Mission 006 (prompt v2, one call, $0.00258375), Mission 008 (prompt v3, one call,
$0.00093225) and Mission 010 (the v2 pilot, 12 calls, $0.039129; `docs/assets/study-v2-pilot/RESULTS.md`). All are
counted by every later `--total-usd-ceiling` check. **Nothing in this document authorizes
spending.** Execution needs the owner to approve the provider, the model and a **total USD ceiling**. The figures
below are computed worst cases for the current design (`first_llm_study.v2`, prompt `rewardbench.prompts.v4`,
`docs/STUDY_V2_PROTOCOL.md`), not requests.

## How the worst case is computed

`python -m rewardbench.study budget` (deterministic, offline, from `providers/data/pricing_2026-10-14.json`):

* Every call is priced at the **output ceiling** (`max_output_tokens = 800`) even though a controller is about
  150-300 tokens, and `max_model_retries = 0` so there is exactly one attempt per call.
* Input is priced at the catalog's ceiling of **one token per UTF-8 byte plus 64**, which over-counts real
  BPE tokens several times over (a revision-1 prompt is ~3-7 KB; see `docs/assets/first-llm-study-rehearsal/prompts/`).
* Each call's history is built at its practical maximum: 4 earlier revisions, 17-digit parameter values,
  8 episodes each with full metrics (arm C), plus a 400-character validation-error allowance per entry.
* The per-experiment `budget.max_cost_usd` in each config is that arm's worst-case sum rounded up to the cent;
  the client refuses any call whose reservation would exceed the remaining budget.
* Pricing for `gpt-5.4-mini` ($0.75 in / $4.50 out per 1M tokens) matched OpenAI's model page on 2026-10-24.
  Cached-input discounts are deliberately not assumed. Re-check before approving.

Proposed model `openai:gpt-5.4-mini`, catalog `2026-10-14`.

| Tier | Revisions | Replicates | Paid calls | Worst-case tokens | Worst-case USD |
| --- | ---: | ---: | ---: | ---: | ---: |
| first call per arm | 1 | 1 | 3 | - | $0.0311 |
| pilot | 4 | 1 | 12 | 169,956 | $0.1635 |
| study | 6 | 5 | 90 | 1,493,640 | $1.3902 |

Per arm, per replicate (worst case):

| Tier | Arm | Calls | Largest prompt (token ceiling) | Output ceiling/call | USD |
| --- | --- | ---: | ---: | ---: | ---: |
| pilot | no_feedback | 4 | 12,367 | 800 | $0.0464 |
| pilot | reward_only | 4 | 13,343 | 800 | $0.0479 |
| pilot | numerical_reward | 4 | 27,498 | 800 | $0.0692 |
| study | no_feedback | 6 | 13,517 | 800 | $0.0738 |
| study | reward_only | 6 | 14,797 | 800 | $0.0773 |
| study | numerical_reward | 6 | 33,672 | 800 | $0.1269 |

Same designs priced on the other catalog models (indicative only; settings for these providers are not live-tested):

| Model | first_call | pilot | study |
| --- | ---: | ---: | ---: |
| openai:gpt-5.4-mini | $0.0311 | $0.1635 | $1.3902 |
| google:gemini-3.1-flash-lite | $0.0105 | $0.0551 | $0.4677 |
| anthropic:claude-haiku-5-5 | $0.0039 | $0.0208 | $0.1782 |
| xai:grok-4.3 | $0.0398 | $0.2244 | $1.9571 |
| openai:gpt-5.4 | $0.1037 | $0.5449 | $4.6341 |

Expected (not guaranteed) spend is far below these bounds because real prompts are a fraction of the byte
ceiling and real outputs are shorter than 800 tokens; do not budget from the expectation.
Each additional study replicate adds roughly one-fifth of the study row.

**What this means for the current $0.03 ceiling.** Prompt v4 carries the flight mechanics, so each first call
reserves about $0.0104 and one matched round of three first calls reserves $0.031100. With $0.003516 already
recorded, $0.026484 remains: **not even round 0 of the matched comparison fits**, and
`python -m rewardbench.autopilot plan` refuses it before any request. A single arm would fit, but the v2 protocol
never advances one arm alone. The whole 4-revision pilot needs a ceiling of at least
$0.003516 + $0.1635 = $0.1671 at these reservations; that is the owner's decision, and no code raises it.
Expected real spend is much lower: a v4 revision-0 prompt is about 8.9 KB (roughly 2,200 tokens) and a guidance
controller about 300 output tokens, about $0.003 per call, or very roughly $0.04-0.07 for the 12-call pilot
because history grows each revision. That estimate is not a bound; budget from the worst case.

## What the owner must decide

1. Provider and model (proposal: `openai:gpt-5.4-mini`; the table prices alternatives, but only the OpenAI
   settings are configured and exercised by tests).
2. A total USD ceiling covering the tiers to run: e.g. first call per arm, then pilot, then study. Each tier's
   worst case above is a floor for that tier's approval; a ceiling below it will make the preflight refuse.
3. Whether to run the first call, the pilot and the study as separate approvals (recommended).

## API requirements

* An API key exported in your own shell (`OPENAI_API_KEY`); never commit it or paste it into chat.
* A provider-side hard spending limit/alert configured in the provider dashboard.
* The T3 Code / Codex membership used to build this does not provide API credits. No key was present in the
  environment where this package was prepared, and none was created.
