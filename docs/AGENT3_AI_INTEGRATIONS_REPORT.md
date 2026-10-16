# Agent 3 — AI Integrations Report

**Branch:** `work/providers-preflight`  
**Worktree:** `~/Projects/R.E.A.C.T-worktrees/providers`  
**Scope:** OpenAI, Google Gemini, Anthropic Claude, xAI Grok readiness for the first reward-feedback experiment.  
**Constraint honored:** no real API calls, no key purchase, no spending, no `PLAN.md` edits, no physics/runner edits.

---

## Executive status

| Item | Status |
| --- | --- |
| Four-provider ModelClient compatibility | Ready (mocked) |
| Controller JSON parse safety | Ready |
| Spending reservations / overrun stop | Ready (in-process only) |
| API key handling (env only, redacted logs) | Ready |
| ApolloLander schema presentation | Ready (fixture from real environment document) |
| Pricing catalog vs official pages | Base rates verified 2026-10-15; cache intentionally unpriced |
| Live paid pilot | **Not ready until owner configures one key and approves capped calls** |
| API setup ready? | **No** — keys unset by design; mocked path only |

---

## 1. Four-provider compatibility

All four live adapters implement the shared `ModelClient.propose(ModelRequest) -> ModelResponse` contract via `RewardModelClient`:

| Provider | Adapter | Endpoint | Env key(s) |
| --- | --- | --- | --- |
| OpenAI | `OpenAIBackend` | `https://api.openai.com/v1/chat/completions` | `OPENAI_API_KEY` |
| Google | `GeminiBackend` | `…/v1beta/models/{id}:generateContent` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Anthropic | `AnthropicBackend` | `https://api.anthropic.com/v1/messages` | `ANTHROPIC_API_KEY` |
| xAI | `GrokBackend` | `https://api.x.ai/v1/chat/completions` | `XAI_API_KEY` |

`build_model_client` resolves keys from the environment (or an explicit test `api_key`). It does not open a socket. Only `propose` talks to the transport.

### Prompt payload every provider receives

`rewardbench.prompts.render_messages` builds one system + one user string for all adapters:

1. Environment description (`display_name`, `task_description`, action/observation summaries)
2. Controller schema JSON from `EnvironmentSpec.controller_schema`
3. Prior attempts (valid/invalid + optional validation error)
4. Numerical reward feedback only when `FeedbackCondition.NUMERICAL_REWARD`
5. Instruction to revise the controller and reply with one JSON object

Adapters differ only in wire format (chat messages vs Anthropic `system` vs Gemini `systemInstruction`). The wording is identical.

### Sampling / reasoning knobs (not interchangeable)

Documented in `PROVIDER_DIFFERENCES`. Highlights for the future resource economy (document only; not implemented):

| Provider | Reasoning control today | Limitation |
| --- | --- | --- |
| OpenAI | `reasoning_effort` | When set, temperature/top_p omitted. Reasoning tokens inside `completion_tokens`. |
| Gemini | `gemini_thinking_budget` / `max_reasoning_tokens` → `thinkingBudget` | Thoughts billed separately at output rate; live/capped calls refused without a ceiling. |
| Anthropic | `anthropic_thinking_budget_tokens` → `thinking.budget_tokens` | Must be `< max_output_tokens`. Haiku 5.5 docs also describe adaptive **effort**; adapter does not send effort yet. |
| xAI | `grok_reasoning_effort` on Chat Completions | Newer docs emphasize Responses API `reasoning.effort`; Responses not wired. |

Parallel proposals, purchased extra reasoning, and purchased extra simulation attempts are **not** implemented.

---

## 2. Model response parser

`parse_controller` returns `(parameters | None, parse_error | None)` and never raises for bad model text.

Covered cases:

- Plain JSON object and fenced ` ```json ` object
- Prose / arrays / trailing junk → parse_error, parameters `None`
- Forbidden code-like keys (`code`, `exec`, `import`, …)
- Non-finite numbers, oversized strings/lists, deep nesting

Invalid JSON is a scored revision failure path for the runner, not an HTTP retry trigger.

---

## 3. Mocked integration tests

Command (Python ≥ 3.11):

```bash
cd ~/Projects/R.E.A.C.T-worktrees/providers
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest tests/providers tests/prompts -q
```

**Result:** all provider + prompt tests passing (see commit message / local run). Suites covered:

- `test_adapters.py` — four interchangeable providers, sampling differences, retries, redaction, caps
- `test_compatibility.py` — LunarLander + **real ApolloLander schema**, overrun/failure billing stop
- `test_reliability.py` — quote-before-call, Gemini reasoning ceiling, malformed payloads
- `test_parsing.py` — valid/invalid controller JSON
- `test_pricing.py` — catalog math, long-context Claude rates, cache-null guard
- `tests/prompts/test_render.py` — reward isolation in prompts

No sockets to provider hosts are opened; `FakeTransport` / `mock` only.

---

## 4. Pricing and model-support findings (verified 2026-10-15)

Catalog file: `src/rewardbench/providers/data/pricing_2026-10-14.json`  
Sources checked: OpenAI API pricing, Gemini Developer API pricing, Anthropic pricing / Haiku 5.5 docs, xAI pricing.

| Catalog key | Input / output (USD per 1M) | Verification | Gaps / intentional omissions |
| --- | --- | --- | --- |
| `openai:gpt-5.4-mini` | 0.75 / 4.50 | **Verified** | Official cached input 0.075 left **null** |
| `openai:gpt-5.4` | 2.50 / 15.00 | **Verified** | Long-context >272K rates filled; cached input null |
| `google:gemini-3.1-flash-lite` | 0.25 / 1.50 | **Verified** | Thoughts billed at output rate; cache null |
| `anthropic:claude-haiku-5-5` | 0.10 / 0.50 (≤100K) | **Verified** | >100K now **0.50 / 2.50** (was previously unpriced). Cache rates published by Anthropic but left **null** |
| `xai:grok-4.3` | 1.25 / 2.50 | **Verified** | ≥200K long-context **2.50 / 5.00** filled; cached input null |

**Why cache stays null:** adapters never send cache breakpoints. If a response still reports cache tokens, an unpriced status records the known non-cache portion and **blocks further live calls** in-process. Putting official cache rates into the catalog without a reservation would allow unreserved cache charges through.

Retired / absent by design: `grok-4.1-fast`.

---

## 5. Token accounting

| Provider | Prompt | Completion | Reasoning | Cached input |
| --- | --- | --- | --- | --- |
| OpenAI | `prompt_tokens` | `completion_tokens` | `completion_tokens_details.reasoning_tokens` (included in completion; not double-billed) | Supported by API; catalog null |
| Gemini | `promptTokenCount` | `candidatesTokenCount` | `thoughtsTokenCount` (separate; billed at output) | Catalog null |
| Anthropic | `input_tokens` | `output_tokens` | `thinking_tokens` if present; thinking blocks ignored for text | Recorded; catalog null → reject |
| xAI | Chat Completions usage (OpenAI-shaped) | same | reasoning in completion when reported | Catalog null |

Reservation before a live call: UTF-8 byte ceiling + framing for input, `max_output_tokens` for output, Gemini/Anthropic reasoning ceilings when billed separately, times (`max_retries + 1`) attempts.

---

## 6. Retries, rate limits, spending safeguards

Confirmed in code + tests:

1. **Pre-call quote** — unpriced / unbounded reasoning / missing catalog rate → `ModelClientError`, **zero HTTP requests**.
2. **Reservation** — `SpendingGuard.reserve` under a process-local lock; concurrent double-spend blocked.
3. **Retries** — only retryable HTTP/transport errors; 401/auth not retried; Retry-After honored.
4. **Failed attempt usage** — billed tokens from failed tries are kept, not released.
5. **Over-reservation bill** — actual spend recorded; `BudgetExceeded` / non-retryable error; next `propose` stops via `blocked_reason`.
6. **Unpriced live charge** (e.g. cache) — known portion recorded; process blocked.
7. **Scope limit** — spending lock is **in-process only**, not a provider-side hard cap and not cross-process.

Known limitations:

- Runner `max_model_retries` is a separate outer loop; each `propose` reserves only its own HTTP retries.
- No provider dashboard hard stop; owner must also set account limits at the vendor.
- Catalog UTF-8 byte ceiling assumes ≤1 token/byte for message text.

---

## 7. API key safety

- Keys read only from env vars listed above (or explicit test injection).
- Gemini key sent as `x-goog-api-key` header; URL placement refused.
- Logs and `ModelClientError` strings pass through `_redact` with the live key.
- Package docstring: do not commit keys or `.env`.

---

## 8. ApolloLander controller schema

Frozen fixture exported from main’s `controller_schema_document()`:

- `tests/providers/fixtures/apollolander_controller_schema.json`
- `tests/providers/fixtures/apollolander_constant_controller.json`

All four providers receive the full schema (including guidance bounds such as `vx_gain`) in the user prompt. Providers do **not** environment-validate controllers; invalid numeric bounds remain the environment adapter’s job after parse.

This worktree still lacks the Apollo physics package (lives on `main`). Schema presentation is verified without importing simulation code.

---

## 9. First paid-pilot checklist

Do nothing below until the owner explicitly approves spending.

### Pre-flight (offline)

- [ ] Confirm this branch’s mocked tests are green locally.
- [ ] Choose **one** provider key (recommendation below).
- [ ] Export only that key in the shell (not in git).
- [ ] Set a process cap: `max_spend_usd` tight enough for ≤2 calls (suggest **$0.05** for gpt-5.4-mini pilot).
- [ ] Set `max_output_tokens` ≤ 400 and `max_retries` ≤ 1 for the pilot client.
- [ ] For Gemini only: set `max_reasoning_tokens` or `gemini_thinking_budget` or the call is refused.
- [ ] Prepare one ApolloLander (or LunarLander) `ModelRequest` with numerical reward history disabled or enabled as intended.
- [ ] Confirm vendor account billing alerts / hard limits are set outside this repo.

### Live sequence (owner-approved)

1. Build client for the single chosen provider + catalog model id.
2. Call `propose` **once**; record `usage`, token fields, `estimated_cost_usd`, `parse_error`, parameters.
3. If structure validates against the environment adapter, run **one** objective simulator episode on that controller (outside this agent’s edits).
4. Record real usage vs estimate; stop.
5. Optional second call only after reviewing step 4 and remaining cap.
6. Do **not** proceed to other providers in the same session without a fresh review.

### Abort conditions

- Any `BudgetExceeded` or “blocked in this process”
- Unpriced / cache / long-context surprise
- Key appearing in logs
- Parse success but environment validation failure rate unexpected — pause before more spend

---

## 10. Recommendation: configure OpenAI first

**First key / model:** `OPENAI_API_KEY` + `gpt-5.4-mini`

Reasons (not “cheapest wins”):

1. **Already the sample-config default** (`configs/lunarlander_*.yaml`), so pilot wiring matches existing experiment configs.
2. **Clearest spending math** for reasoning: reasoning tokens are inside completion tokens; no separate unbounded thought stream unless you opt into Gemini-style budgets.
3. **Verified list price** and mature Chat Completions path used by the adapter; json_object response format available.
4. **Mid cost**, not the cheapest: Claude Haiku 5.5 is cheaper per token but lacks `json_object`, has cache-rejection edge cases, and an incomplete effort-parameter wiring vs current Haiku 5.5 docs.
5. **Gemini** is cheaper than OpenAI mini but requires an explicit thinking ceiling before any capped call — good safety, more moving parts for the first two live calls.
6. **Grok 4.3** is a cross-tier reference (higher short-context output relative to the student cohort) and Responses-API reasoning is not yet adapted.

Configure Anthropic second if the goal is cost-sensitive JSON-via-prompt checks; Gemini second if the goal is separate reasoning-token accounting; xAI later once Responses vs Chat Completions policy is decided.

---

## Files changed (this agent pass)

- `src/rewardbench/providers/data/pricing_2026-10-14.json` — verified notes, Anthropic/xAI/OpenAI long-context where published, cache remains null
- `src/rewardbench/providers/capabilities.py` — reasoning/API limitations updated
- `pyproject.toml` — include `providers/data/*.json` in package data
- `tests/providers/fixtures/apollolander_*.json` — real Apollo schema + constant controller
- `tests/providers/test_compatibility.py` — Apollo fixture presentation across four providers
- `tests/providers/test_pricing.py` — long-context + cache-null guards
- `docs/AGENT3_AI_INTEGRATIONS_REPORT.md` — this report

## Tests

```text
.venv/bin/python -m pytest tests/providers tests/prompts -q
```

## Commit hash

`fb5d4ca62afb257618c3d6fa05329faf43b58d8a` on `work/providers-preflight`

## Blockers

1. No API keys configured (intentional).
2. Worktree based on `origin/agent/providers` — Apollo **physics** not present here; schema fixture only. Full episode pilot needs `main` (or a merge) for environments.
3. Owner approval required before any paid call.
4. In-process spend cap is not a vendor hard stop.

## API setup ready?

**No for live calls. Yes for mocked preflight.** After owner sets `OPENAI_API_KEY` and a tight `max_spend_usd`, OpenAI gpt-5.4-mini is the recommended first live configuration.
