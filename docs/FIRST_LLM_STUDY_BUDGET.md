# First real-LLM study: budget

**No money has been spent and none is authorized by this document.** Execution needs the owner to approve
the provider, the model and a **total USD ceiling**. The figures below are computed worst cases, not requests.

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
| first call per arm | 1 | 1 | 3 | - | $0.0203 |
| pilot | 4 | 1 | 12 | 112,368 | $0.1203 |
| study | 6 | 5 | 90 | 1,061,730 | $1.0663 |

Per arm, per replicate (worst case):

| Tier | Arm | Calls | Largest prompt (token ceiling) | Output ceiling/call | USD |
| --- | --- | ---: | ---: | ---: | ---: |
| pilot | no_feedback | 4 | 7,568 | 800 | $0.0320 |
| pilot | reward_only | 4 | 8,544 | 800 | $0.0335 |
| pilot | numerical_reward | 4 | 22,699 | 800 | $0.0548 |
| study | no_feedback | 6 | 8,718 | 800 | $0.0523 |
| study | reward_only | 6 | 9,998 | 800 | $0.0557 |
| study | numerical_reward | 6 | 28,873 | 800 | $0.1053 |

Same designs priced on the other catalog models (indicative only; settings for these providers are not live-tested):

| Model | first_call | pilot | study |
| --- | ---: | ---: | ---: |
| openai:gpt-5.4-mini | $0.0203 | $0.1203 | $1.0663 |
| google:gemini-3.1-flash-lite | $0.0069 | $0.0407 | $0.3598 |
| anthropic:claude-haiku-5-5 | $0.0025 | $0.0151 | $0.1350 |
| xai:grok-4.3 | $0.0218 | $0.1525 | $1.4172 |
| openai:gpt-5.4 | $0.0677 | $0.4009 | $3.5543 |

Expected (not guaranteed) spend is far below these bounds because real prompts are a fraction of the byte
ceiling and real outputs are shorter than 800 tokens; do not budget from the expectation.
Each additional study replicate adds roughly one-fifth of the study row.

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
