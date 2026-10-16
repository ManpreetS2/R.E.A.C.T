# Agent 3 — AI Integrations Report

**Branch:** `work/v1-provider-safety`  
**Worktree:** `~/Projects/R.E.A.C.T-worktrees/provider-safety`  
**Base:** offline v1 `11da2e1`  
**Constraint:** no real provider requests, no credentials inspected/created, no credit purchase, no PLAN.md edits, no core/runner edits, no push/merge.

---

## GO / NO-GO

| Gate | Verdict |
| --- | --- |
| Mocked provider suite + first-call safety | **GO** |
| Source-verified `gpt-5.4-mini` pricing / Chat Completions support | **GO** |
| Recommended first-call ceiling with `reasoning_effort: none` | **GO** (`800`) |
| Keyless dry-run example | **GO** (`examples/providers/dry_run_first_call.py`) |
| Live paid call today | **NO-GO** until explicit owner approval + vendor billing limits + shell key export |

**A software `$0.05` cap is not a provider-side billing guarantee.** Concurrent processes, reservation underestimates, and invoice discrepancies can exceed it.

---

## 1. Adapter recheck vs official docs (2026-10-15, rechecked this pass)

| Provider | Model id | Endpoint used | Env var | JSON handling | Reasoning |
| --- | --- | --- | --- | --- | --- |
| OpenAI | `gpt-5.4-mini` | Chat Completions `v1/chat/completions` | `OPENAI_API_KEY` | `response_format: json_object` by default | `reasoning_effort`: none/low/medium/high/xhigh; tokens count against `max_completion_tokens` |
| Google | `gemini-3.1-flash-lite` | `generateContent` | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | `responseMimeType: application/json` | `thinkingBudget`; thoughts billed at output rate |
| Anthropic | `claude-haiku-5-5` | Messages `v1/messages` | `ANTHROPIC_API_KEY` | prompt-only JSON (no json_object field) | `anthropic_thinking_budget_tokens` wired; effort not wired |
| xAI | `grok-4.3` | Chat Completions `api.x.ai/v1/chat/completions` | `XAI_API_KEY` | json_object requested, not guaranteed | `grok_reasoning_effort`; Responses API not implemented |

Sources:  
https://developers.openai.com/api/docs/models/gpt-5.4-mini  
https://developers.openai.com/api/docs/pricing  
https://developers.openai.com/api/docs/guides/reasoning  
https://ai.google.dev/gemini-api/docs/pricing  
https://platform.claude.com/docs/en/about-claude/pricing  
https://docs.x.ai/developers/pricing  

Catalog `pricing_2026-10-14.json` base rates unchanged and still match those pages. Cache rates remain intentionally null so unexpected cache usage fails closed after one live response and blocks further calls in-process.

---

## 2. Can 400 output tokens produce a valid ApolloLander controller?

Measured compact JSON (separators, sorted keys):

| Controller | Chars | ~Tokens (chars/3) |
| --- | --- | --- |
| `constant` | ~99 | ~33 |
| `guidance` (demo) | ~467 | ~155 |

**Yes, if reasoning does not consume the budget.**  
OpenAI reasoning tokens count against `max_completion_tokens`. With `reasoning_effort` other than `none`, a **400** ceiling can truncate before a full guidance object is emitted (e.g. 300 reasoning + incomplete JSON → `finish_reason=length`).

**Recommended first-call ceiling: `max_output_tokens: 800` with `reasoning_effort: none`.**  
Prefer a compact **constant** controller on the first live call. 400 remains a minimum only for compact JSON under `reasoning_effort: none`.

Pilot config updated accordingly: `configs/apollolander_pilot_openai_gpt54mini.yaml` (1 revision, 800 out, reasoning none, `$0.05` software target). Local reserved quote for Apollo schema ≈ **$0.0057** (estimate, not an invoice).

---

## 3. Prompt / parsing / payload improvements

- Prompt template bumped to `rewardbench.prompts.v2`: compact JSON, no markdown fences, no tool/browser/code-interpreter calls; no-feedback still never prints rewards.
- `RewardModelClient` records `usage["truncated"]` and explains `finish_reason=length` in `parse_error` when JSON is incomplete.
- OpenAI payloads continue to send explicit `model`, `max_completion_tokens`, no `tools` / `web_search`.
- Offline `preflight_first_call` / `require_preflight_ok` refuse unsafe local quotes before any transport is used.

---

## 4. Tests

```bash
cd ~/Projects/R.E.A.C.T-worktrees/provider-safety
.venv/bin/python -m pytest tests/providers tests/prompts -q
```

New/updated coverage in `tests/providers/test_first_call_safety.py`:

- Apollo controller size vs 400/800 ceilings  
- OpenAI bounded payload + no tools  
- Truncated `finish_reason=length`  
- Budget / unknown-price refuse before HTTP  
- Preflight OK / fail-closed mismatch  
- No-feedback isolation after v2  
- Keyless dry-run subprocess  

---

## 5. Real-money risks that in-process locks cannot prevent

1. Concurrent processes each with their own `$0.05` cap.  
2. Reservation underestimate (tokenizer emits more tokens than UTF-8 byte ceiling).  
3. Provider bills reasoning/partial/failed attempts differently than the catalog.  
4. Account-level minimums, retries outside this config, or dashboard lag.  
5. A truncated call can still charge input + reasoning with no usable controller.  
6. Cache tokens (if ever returned) cost a live round-trip before fail-closed stop.

**Do not claim a `$1` or `$0.05` software cap makes a larger real charge impossible.**

---

## 6. Coordination for Agent 1 (interfaces; no core edits made)

Agent 1 should wire the first live run so that:

1. `ExperimentConfig.budget.max_cost_usd` equals the client `max_spend_usd` (pilot: `0.05`).  
2. `max_model_retries` equals client `max_retries` (pilot: `0`).  
3. `model_settings` include `max_output_tokens: 800` and `reasoning_effort: none`.  
4. Call `preflight_first_call` / `require_preflight_ok` before constructing a live transport when possible.  
5. Abort after one revision until SQLite usage is reviewed.  
6. Do not treat runner `BudgetLimiter` alone as a provider hard stop.

No changes were made under `src/rewardbench/core/`.

---

## 7. First-call preflight checklist

- [ ] Explicit written approval to spend  
- [ ] OpenAI account billing hard limit / alert set outside this repo  
- [ ] `export OPENAI_API_KEY=…` in a local shell only  
- [ ] Run keyless dry-run: `python examples/providers/dry_run_first_call.py`  
- [ ] `build_model_client("openai", "gpt-5.4-mini", max_spend_usd=0.05, max_retries=0, …)`  
- [ ] Keep `reasoning_effort=none`, `max_output_tokens=800`  
- [ ] One revision only; inspect SQLite before any second call  
- [ ] Stop on BudgetExceeded / unpriced / truncated / blocked  

### Dry-run (no key, no network)

```bash
python examples/providers/dry_run_first_call.py
```

Prints local reservation, mocked constant controller validated against Apollo schema, and the owner checklist.

---

## Files changed

- `src/rewardbench/prompts/render.py` — v2 compact/no-tools instructions  
- `src/rewardbench/providers/client.py` — truncation accounting  
- `src/rewardbench/providers/preflight.py` — offline first-call quote helper  
- `src/rewardbench/providers/__init__.py` / `capabilities.py` — exports + OpenAI reasoning notes  
- `configs/apollolander_pilot_openai_gpt54mini.yaml` — 800 / none / single revision  
- `examples/providers/dry_run_first_call.py` — keyless dry-run  
- `tests/providers/test_first_call_safety.py` (+ e2e/prompt assertion updates)  
- `docs/AGENT3_AI_INTEGRATIONS_REPORT.md` — this report  

## Commit hash

Work: `bcf5ef333058979046a065ab37051f341f871ff5`  
Tip: `d2a7e40b2de0aaaa74cb31b50a25540c9e922781` on `work/v1-provider-safety`

## Approval required before first paid call

Explicit spend approval, vendor billing limits, and agreement to start with **`OPENAI_API_KEY` + `gpt-5.4-mini`** under **800 output tokens**, **`reasoning_effort: none`**, **`max_retries=0`**, **`max_spend_usd=0.05`**.
