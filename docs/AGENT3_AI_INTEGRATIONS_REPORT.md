# Agent 3 — AI Integrations Report

**Branch:** `work/providers-preflight`  
**Worktree:** `/Users/manpreetsingh/Projects/R.E.A.C.T-worktrees/providers`  
**Previous tip:** `0f234eb`  
**Constraint honored:** no real API calls, no keys installed, no spending, no `PLAN.md` edits, no edits to Agent 1/2 production packages (merged `main` read-only for Apollo + runner).

---

## GO / NO-GO

| Gate | Verdict |
| --- | --- |
| Mocked provider → parse → Apollo validate → real physics → SQLite | **GO** |
| Four-provider usage accounting (mocked authentic shapes) | **GO** |
| Fail-closed unknown model / missing pricing / unbounded Gemini reasoning | **GO** |
| No-feedback reward isolation in next provider request | **GO** |
| Live paid pilot today | **NO-GO** until owner exports one key, sets vendor billing limits, and gives explicit spend approval |

**Summary:** The provider-to-controller boundary is ready for a **small, explicitly authorized** real-model pilot. Software caps are **not** a billing guarantee. Do not treat `$0.05` as a hard maximum real charge.

---

## Executive status

| Item | Status |
| --- | --- |
| ModelClient contract vs four adapters | Compatible |
| End-to-end mocked flow with real Apollo physics | Passing |
| Numerical reward history in next request | Passing |
| No-feedback never leaks rewards to provider | Passing |
| Malformed / wrong schema / missing fields | Validated, not flown |
| API errors / 429 retries / exhaustion | Passing |
| Pricing catalog vs official docs (2026-10-15) | Base rates verified; cache intentionally null |
| Recommended pilot config | `configs/apollolander_pilot_openai_gpt54mini.yaml` (not invoked) |
| API keys present | No (by design) |

---

## 1. Contract recheck

`RewardModelClient.propose(ModelRequest) -> ModelResponse` implements `ModelClient`.

Every live adapter receives the same rendered prompt pair from `rewardbench.prompts.render_messages`:

1. Environment description  
2. Controller schema  
3. Prior attempts  
4. Numerical rewards only under `FeedbackCondition.NUMERICAL_REWARD`  
5. Instruction to revise controller parameters as one JSON object  

`ExperimentRunner` then: interpret/parse → `environment.validate_policy` → `run_episode` → SQLite. Providers never run physics.

| Provider | Adapter | Endpoint | Env var |
| --- | --- | --- | --- |
| OpenAI | `OpenAIBackend` | `https://api.openai.com/v1/chat/completions` | `OPENAI_API_KEY` |
| Google | `GeminiBackend` | `…/generateContent` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Anthropic | `AnthropicBackend` | `https://api.anthropic.com/v1/messages` | `ANTHROPIC_API_KEY` |
| xAI | `GrokBackend` | `https://api.x.ai/v1/chat/completions` | `XAI_API_KEY` |

---

## 2. End-to-end mocked proof

Suite: `tests/providers/test_e2e_apollolander.py` (+ `e2e_helpers.py`).

Flow exercised with **FakeTransport only**:

`build_model_client` / `RewardModelClient` → shared prompts → JSON parse → Apollo `validate_policy` → **real Node ApolloLander physics** → `SqliteStore`.

Covered cases:

| Test | What it proves |
| --- | --- |
| `test_numerical_two_revisions_flow_through_physics_and_sqlite` | ≥2 valid revisions; SQLite rewards appear in revision-1 provider history |
| `test_nofeedback_never_puts_rewards_in_the_next_provider_request` | Rewards stored in SQLite but absent from next HTTP/user prompt |
| `test_malformed_wrong_schema_and_missing_fields_are_validated_not_flown` | Bad JSON / wrong schema / missing fields → no episodes |
| `test_rate_limit_retries_then_exhaustion_aborts` | 429 retries then FAILED run, zero episodes |
| `test_transport_timeout_is_retryable_and_exhausts` | Retryable transport errors exhaust client retries |
| `test_four_providers_usage_accounting_with_authentic_shapes` | OpenAI/Gemini/Anthropic/xAI token + cost conventions |
| `test_anthropic_cache_charge_fails_closed_and_blocks_followup` | Unpriced cache blocks further live calls |
| `test_unknown_model_and_gemini_without_reasoning_ceiling_fail_before_http` | Fail closed with zero HTTP |
| `test_pilot_quote_for_gpt54mini_is_bounded_before_any_call` | Pilot YAML loads; reservation under software target |
| `test_guidance_controller_from_mocked_provider_can_complete_a_short_episode` | Real Apollo guidance object executes physics |

Command:

```bash
cd /Users/manpreetsingh/Projects/R.E.A.C.T-worktrees/providers
.venv/bin/python -m pytest tests/providers -q
```

---

## 3. Usage accounting (mocked authentic shapes)

| Provider | Prompt | Completion | Reasoning | Cost rule in catalog |
| --- | --- | --- | --- | --- |
| OpenAI | `prompt_tokens` | `completion_tokens` | in `completion_tokens_details`; **not** double-billed | input + completion |
| Gemini | `promptTokenCount` | `candidatesTokenCount` | `thoughtsTokenCount` separate | thoughts billed at output rate |
| Anthropic | `input_tokens` | `output_tokens` | thinking tokens if present | input + output; cache null → reject |
| xAI | OpenAI-shaped chat usage | same | reasoning in completion when reported | input + completion |

Retry charges: failed attempt token usage is retained and summed into the successful bill when present.

---

## 4. Pricing verification (sources + effective check date)

Checked **2026-10-15** (and reconfirmed for this E2E pass):

| Source | URL |
| --- | --- |
| OpenAI pricing | https://developers.openai.com/api/docs/pricing |
| OpenAI gpt-5.4-mini | https://developers.openai.com/api/docs/models/gpt-5.4-mini |
| Gemini pricing | https://ai.google.dev/gemini-api/docs/pricing |
| Anthropic pricing | https://platform.claude.com/docs/en/about-claude/pricing |
| xAI pricing | https://docs.x.ai/developers/pricing |

| Catalog key | Input / output USD per 1M | Notes |
| --- | --- | --- |
| `openai:gpt-5.4-mini` | **0.75 / 4.50** | Verified. Official cached input 0.075 left **null** |
| `openai:gpt-5.4` | **2.50 / 15.00** | Verified; long-context >272K filled |
| `google:gemini-3.1-flash-lite` | **0.25 / 1.50** | Verified; thoughts at output rate |
| `anthropic:claude-haiku-5-5` | **0.10 / 0.50** (≤100K); **0.50 / 2.50** (>100K) | Verified; cache rates left null |
| `xai:grok-4.3` | **1.25 / 2.50**; ≥200K **2.50 / 5.00** | Verified; cache null |

Cache rates stay null **on purpose** so unexpected cache usage fails closed instead of billing without a reservation.

---

## 5. First real-model pilot — safe launch requirements

**Recommended config file (not executed):** `configs/apollolander_pilot_openai_gpt54mini.yaml`

| Requirement | Value |
| --- | --- |
| Environment variable | `OPENAI_API_KEY` only (shell export; never commit) |
| Model id | `gpt-5.4-mini` |
| Cost per 1M input tokens | **$0.75** |
| Cost per 1M output tokens | **$4.50** |
| Cached input (official) | $0.075 / 1M — **not** in catalog; unexpected cache fails closed |
| Output-token ceiling | `max_output_tokens: 400` |
| Client retry ceiling | `max_retries: 0` (match `max_model_retries: 0`) |
| Runner revisions | 2 × 1 episode (review after first) |
| Software spend target | `max_spend_usd` / `budget.max_cost_usd` = **$0.05** |
| Estimated reservation (Apollo schema, 400 out, 1 attempt) | ~**$0.003** (UTF-8 ceiling math; not an invoice) |
| Estimated maximum software exposure | **$0.05 per process** if caps hold |
| Required approval | **Explicit user approval before any live `propose`** |

### Hard-stop limitations (must read)

1. **In-process only.** `SpendingGuard` does not bind other processes, machines, or the OpenAI account.  
2. **A $0.05 software cap does not make a larger real charge impossible.** Reservation underestimates, provider billing quirks, dashboard lag, or a second process can exceed it.  
3. **Runner outer retries** are separate from client HTTP retries; keep both at 0 for the pilot.  
4. **Set provider-side billing limits / alerts** in the OpenAI console before the first call.  
5. **No key printing.** Logs redact secrets held by the client; still do not paste keys into chat or commits.

### Owner checklist before first paid call

- [ ] Explicit written approval to spend  
- [ ] OpenAI account hard limit / alert configured  
- [ ] `export OPENAI_API_KEY=…` in a local shell only  
- [ ] Construct client with `max_spend_usd=0.05`, `max_retries=0`, `model_settings.max_output_tokens=400`  
- [ ] Run **one** revision, inspect SQLite usage + cost, then decide on a second call  
- [ ] Abort on any unpriced / blocked / BudgetExceeded signal  

---

## 6. Reasoning-control capabilities (future economy; not implemented)

| Provider | Wired today | Limitation |
| --- | --- | --- |
| OpenAI | `reasoning_effort` | Sampling params omitted when set |
| Gemini | `gemini_thinking_budget` / `max_reasoning_tokens` | Required for capped/live calls; separate bill |
| Anthropic | `anthropic_thinking_budget_tokens` | Must be `< max_tokens`; Haiku 5.5 **effort** not wired |
| xAI | `grok_reasoning_effort` on Chat Completions | Responses API `reasoning.effort` not implemented |

Purchased extra reasoning, extra sims, and parallel proposals are **out of scope**.

---

## 7. Outstanding risks

1. Software spend caps ≠ provider invoices.  
2. Parallel experiment processes can each reserve/spend independently.  
3. Catalog UTF-8 byte ceiling assumes ≤1 token per message byte.  
4. Anthropic / OpenAI / Gemini / xAI cache prices exist officially but are omitted; a provider that returns cache tokens still burns a live call before fail-closed stop.  
5. Example YAML on main still lists `gpt-4.1` for Apollo (`examples/apollolander/development_numerical.yaml`) — that id fails closed against this catalog; use the Agent 3 pilot config instead.  
6. Full 8000-step Apollo episodes are expensive in wall time; E2E tests use short `max_episode_steps`.

---

## 8. Files changed (this E2E pass)

- `docs/AGENT3_AI_INTEGRATIONS_REPORT.md` — this report  
- `configs/apollolander_pilot_openai_gpt54mini.yaml` — recommended pilot (not invoked)  
- `tests/providers/e2e_helpers.py` — E2E helpers  
- `tests/providers/test_e2e_apollolander.py` — end-to-end mocked suite  
- Merge of `origin/main` into `work/providers-preflight` for Apollo + runner availability (no Agent 1/2 package edits)

Prior commits on branch retained: pricing verification, Apollo schema fixtures, capabilities notes.

## Tests

```text
.venv/bin/python -m pytest tests/providers -q
```

All provider tests passing (including E2E).

## Commit hash

`dccaa66abab025c089b95053a42e3a0ecd1d5cb3` on `work/providers-preflight`.

## What user approval is needed

Before the first paid call: **explicit approval to spend**, confirmation that **OpenAI account billing limits** are set, and agreement to start with **`OPENAI_API_KEY` + `gpt-5.4-mini`** under the pilot YAML ceilings. Agent 3 will not install, create, test, or print a live credential.
