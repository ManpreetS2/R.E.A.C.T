# OpenAI API billing: what can and cannot cap the pilot's cost

Checked 2026-10-25 against OpenAI's developer documentation. **Nothing was purchased, no key was created
or read, and no provider call was made.** Some account-specific Platform settings cannot be inspected remotely. The official prepaid-billing
help article and spend-limit developer guide were checked; verify the actual toggles in your own dashboard.

## What the current docs say (verified)

| Question | Answer | Source |
| --- | --- | --- |
| Are the Limits-page numbers (10 RPM, 100,000 TPM, 50,000 input TPM) a spending cap? | **No.** RPM/TPM/IPM limit request and token volume per time, not dollars. | [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits) |
| Does OpenAI offer a dollar cap? | **Yes: a "hard spend limit", per organization and per project.** A *spend alert* only notifies ("Spend alerts do not enforce a cap"); the cap is a separate **Enforce a hard limit** toggle. | [Spend limits](https://developers.openai.com/api/docs/guides/spend-limits) |
| Where is it? | Project: **Project settings → Limits → Spend → Edit spend limit** (enter *Monthly spend limit*, switch on *Enforce a hard limit*, Save). Organization: **Organization limits → Spend → Edit spend limit**. This is a separate "Spend" area from the per-model rate-limit table you were looking at. | Spend limits page |
| What happens at the cap? | Further requests fail with HTTP 429 `project_spend_limit_exceeded` (or `organization_spend_limit_exceeded`). Resets monthly or when you raise/remove it. | Spend limits, [Error codes](https://developers.openai.com/api/docs/guides/error-codes) |
| Is it exact? | **No.** "Enforcement is not instantaneous"; recorded spend "can slightly exceed the configured amount". | Spend limits page |
| Out of prepaid credit? | 429 `credit_balance_exhausted`: "Your organization has no prepaid credits remaining." | Error codes |
| Separate OpenAI-assigned cap? | An *approved monthly usage limit* per organization, set by OpenAI by tier; not something you configure (`organization_usage_limit_exceeded`). | Rate limits, Error codes |
| API key hygiene | Project-scoped keys; set an expiration date when creating one; admins can cap key lifetime. | [Production best practices](https://developers.openai.com/api/docs/guides/production-best-practices) |
| Price of `gpt-5.4-mini` today | $0.75 input / $4.50 output per 1M tokens (cached input $0.075 is not assumed); Chat Completions supported, which is what R.E.A.C.T. uses. Regional-processing endpoints add 10%. | [Model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini) |

The earlier advice that a project-level hard spending limit exists was therefore **correct per the docs**;
it is in a different section from the rate limits, and its availability on your account's UI is the thing to
confirm (step 3 below). I could not see your dashboard, so I cannot confirm the toggle appears for you.

## Prepaid billing (verified in OpenAI Help Center)

[Setting up and managing prepaid API billing](https://help.openai.com/en/articles/8264644-setting-up-and-managing-prepaid-api-billing)
confirms:

* The minimum first prepaid purchase is **$5** (default shown $10).
* **Auto-reload starts ON** during setup. Explicitly turn it OFF before paying.
* Credits expire after one year and are generally non-refundable, subject to documented exceptions.
* Auto-reload has an optional monthly purchase limit; manual purchases do not count toward it.
* **Prepaid credit is NOT an instantaneous hard cutoff.** The API can process additional usage during
  exhaustion and show a negative balance, which can be deducted from the next purchase.

Whether a hard spend limit interacts with prepaid credit in any special way is not documented in what I could read:
treat the two as independent limits, both of which can stop traffic.

## Realistic exposure

| Control | What it bounds | Depends on |
| --- | --- | --- |
| Prepaid balance, auto-recharge **off** | Avoids automatic repeat purchases, but does **not** guarantee an exact spend cutoff; processing delays can create a negative balance. | You disabling auto-recharge and checking billing |
| Project hard spend limit (e.g. $0.50) | API spend from that project (a leaked key included), with slight overshoot | The toggle being available and enabled |
| `--total-usd-ceiling` (this repo) | R.E.A.C.T.'s own calls: refuses a call whose worst case would push recorded spend over the ceiling; serializes live runs under one ledger and refuses unreadable ledger files | The code, keeping all databases under the same root, and estimated costs being accurate |
| Per-experiment `budget.max_cost_usd` | One session | The code |
| `max_model_retries: 0`, one paid call per config per invocation | No hidden spend; no auto-continuation | The code |

If OpenAI will not let you set a hard project limit, say so and rely on a small prepaid balance with
auto-recharge off plus the software ceiling; do not describe the software ceiling as a vendor guarantee.

Concurrent runs under different ledger roots, or bypassing `rewardbench.operate` with a direct live command lacking the aggregate ceiling, are **not** covered by the aggregate guard. The repo's recorded costs are estimates and can omit a billed request whose usage was never returned. Run paid experiments only sequentially, use the SAME ledger root, and prefer the provider-side enforced project limit too.

## Pilot cost versus limits

Worst case (computed, not expected): first call per arm **$0.0179**, entire 12-call pilot **$0.1105**; the
full study **$0.9929** (see `FIRST_LLM_STUDY_BUDGET.md`). Rate limits are not a problem: the pilot makes at most
three sequential calls per invocation (limit 10 requests/minute), and real prompts are a few thousand tokens
(limit 50,000 input tokens/minute).

## Safe setup, one step at a time (do not continue past a step that does not match your screen)

1. **Dedicated project.** Create a project named e.g. `react-pilot`; do the following inside it.
2. **Data residency.** Leave the project on the default region (a regional-processing project adds 10% to prices).
3. **Hard limit first.** *Project settings → Limits → Spend → Edit spend limit*: monthly limit **$0.50**
   (about 4.5x the pilot worst case, well under the study worst case so it also blocks accidental study expansion),
   **Enforce a hard limit ON**. If you do not find a Spend section or the toggle, stop and tell me what you see.
4. **Credits.** Billing → buy prepaid credit at the *minimum the page offers*. Read the screen for the minimum, refund and
   expiry wording. **Turn auto-recharge off** (and confirm it shows off after saving). Do not enter more than the minimum.
5. **Key.** Project → API keys → create a project-scoped key, restricted permissions if offered, with an
   **expiration date a few days out**. Copy it once.
6. **Load it without leaving a trace** (hidden prompt, nothing goes into history, chat or files):
   ```bash
   read -s OPENAI_API_KEY && export OPENAI_API_KEY
   ```
7. **Free local checks.** `python -m rewardbench.study preflight` validates the configs and pricing with a *placeholder* key; it
   does not test your key. The real credential check happens inside the first-call command's own preflight, before any
   network use. Then follow `FIRST_LLM_STUDY_LAUNCH.md` section 1 to write your approval (provider, model, total USD
   ceiling) and set `APPROVED_CEILING_USD`. Suggested ceilings, your decision: **$0.03** (first call of each arm only),
   **$0.15** (the whole pilot, about 36% above its worst case), $0.25 (your earlier figure; fine, but it is not what limits the loss).
8. Run **only** the single first-call command; stop and review (section 2 of the launch guide).

## View actual usage

Dashboard usage/cost pages in the project (compare with `python -m rewardbench.operate status` and the `attempts` table:
`total_tokens`, `estimated_cost_usd`). R.E.A.C.T.'s figures are catalog estimates, not an invoice; if they disagree with
the dashboard, believe the dashboard and stop.
