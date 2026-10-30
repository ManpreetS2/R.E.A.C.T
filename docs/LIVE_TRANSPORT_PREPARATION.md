# Live transport preparation (Mission 015B)

**Status (2026-10-30): the live transport is built and verified against a local mock HTTP server only. The gate is closed
(`LIVE_CALLS_PERMITTED = False`). No real request, test request or token-counting request was made; nothing authenticated to any API
and nothing was charged. No model has played. Nothing is pre-registered. The candidate below is provisional and approves nothing.**

Builds on `docs/OFFLINE_AI_GATEWAY.md`. Research protocol: `docs/BLIND_PLAY_PROTOCOL_V1_DRAFT.md` §14. Chronology:
`docs/assets/live-transport-preparation/DEVLOG.md`.

## Provisional candidate

| Setting | Value | Status |
| --- | --- | --- |
| Provider, model | Anthropic Claude API, `claude-haiku-5-5` | Proposed |
| Effort | `low` | Proposed |
| Thinking | `disabled` | **Proposed by this mission; see Incompatibility 1** |
| Platform | Windows | Proposed |
| Pilot | 1 episode, up to 30 model calls | Proposed |
| Caps | $0.50 session, $1.00 cumulative including $0.106019 already recorded | Proposed |

## Verified against official documentation (read 2026-10-30, no API used)

| Fact | Finding | Source |
| --- | --- | --- |
| Model ID | `claude-haiku-5-5`, a pinned snapshot despite having no date. Retirement not before 2027-10-07 | [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Price, prompt ≤ 100,000 tokens | $0.10 input, $0.50 output per MTok | [Pricing](https://platform.claude.com/docs/en/about-claude/pricing) |
| Price, prompt > 100,000 tokens | $0.50 input, $2.50 output, for that whole request, counting cache reads and writes | Pricing |
| Tool overhead | 286 tokens with `tool_choice: auto`, plus the tool definitions | Pricing |
| Context, output | 1M tokens, 128K output. Our limits (90,000 estimated, 2,048) sit far below both | Models overview |
| Image cost | ⌈w/28⌉ × ⌈h/28⌉, so 1280×720 = **1,196** tokens. Protocol §10 assumed 1,229; the gateway's 1,600 bound holds | [Vision](https://platform.claude.com/docs/en/build-with-claude/vision) |
| Image size | High-resolution tier (2,576 px, 4,784 tokens), so 1280×720 is **not resized**. PNG supported, 10 MB base64 limit | Vision |
| Images in tool results | Allowed. Up to 600 per request; a stricter dimension limit applies above 20, which we never reach | Vision |
| Authentication | `Authorization: Bearer <key>`; `x-api-key` is called legacy; `anthropic-version: 2023-06-01` | [Authentication](https://platform.claude.com/docs/en/manage-claude/authentication) |
| Workspace | A key scoped to one workspace needs no workspace header. An unscoped key gets a 400 without it | Authentication |
| Thinking | On by default. `disabled` is accepted at effort `high` or below | [Troubleshooting thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting) |
| `max_tokens` | Hard cap on thinking plus text together | [Steering thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost) |
| Forced tool use, fallbacks | Accepted on this model but skips thinking; no server-side fallback exists for it. We use neither | Bundled API reference |
| Errors | 400 includes your own spend limit; 429 includes the tier spend cap (`enforced_spend_limit_reached`, no `retry-after`); 402 billing; 529 overloaded | [Errors](https://platform.claude.com/docs/en/api/errors), [Rate limits](https://platform.claude.com/docs/en/api/rate-limits) |
| Rate limits | Start tier: 1,000 RPM, 2M input and 400K output tokens per minute. New organizations may start lower, in an Evaluation tier | Rate limits |

**Not stated in the documentation read, so only a real call or the Console can settle them:** whether a reply's `model` field echoes exactly
`claude-haiku-5-5` (the gateway stops on any difference, after one charged call); whether 5xx and 529 failures are billed (the
ledger assumes worst case); the minimum credit purchase.

**Estimated cost of the pilot** (an estimate, not a measurement): each call has about 4,800 tokens of images, 500 of tools and overhead,
and up to about 4,000 of history, with thinking off and short replies. That is about $0.001 per call, so **about $0.03 for 30 calls**. The
gateway's own reservations are higher, about $0.002 per call at that size, so about $0.06 is what it would plan for. Its absolute ceiling
per call at the context limit is about $0.01. The $0.50 cap should not bind.

## Incompatibilities with the protocol

None of these was resolved silently. Each needs the owner's decision; §14 of the protocol lists them.

### 1. Thinking cannot work the way Mission 015A built it (blocker)

Three documented rules collide on this model:

* During tool use, thinking blocks must be passed back, and "rebuilding the message or filtering out `redacted_thinking` blocks triggers a
  400 error."
* A replayed block is rejected if anything before it changed. New accounts (created on or after 2026-08-31) are enforced by default, and a new
  API account for this project would be one.
* P1's last-four-screenshots policy changes earlier turns on every call.

So Mission 015A's approach of omitting `thinking`, which means adaptive thinking on this model, and then dropping the blocks is **not safe**: the
documentation is unclear on whether it gets a 400 at call 2. Protocol §5 also says thinking "cannot be turned off", which is **wrong for this model**. That is corrected in §14.

| Option | What the model gets | Protocol effect | Status |
| --- | --- | --- | --- |
| **A. `thinking: disabled`** (recommended) | No hidden reasoning. Reasons only in visible text, which it keeps | **Matches P1 §5 as written**: "Hidden reasoning is not requested". Cheaper and more predictable | **Built. The only mode the gate accepts** |
| B. Adaptive, replay blocks, `drop_block` beta | Thinks each call; loses replayed reasoning once history is edited | Stores opaque reasoning blocks, contrary to P1 §5; needs a beta header on every request | Not built |
| C. Adaptive, append-only history | Keeps all reasoning and every screenshot | **Abandons the last-four policy**; input cost grows through the session | Not built |
| D. Adaptive, provider-side context editing | Provider clears old tool results | Provider-specific; clears the counters too, changing P1's text memory; beta | Not built |

**The trade-off in A, stated plainly:** Anthropic recommends lowering effort rather than disabling thinking, and this choice may make the model
play worse. For the study that means results describe "Haiku 5.5 at low effort without thinking", never the model at full ability. On a different
model (Claude Opus 5.5), disabling is impossible, so this choice does not carry over to cross-model comparisons.

### 2. Effort is a new study parameter

P1 does not mention effort. `low` is cheapest but, per Anthropic, makes the model more likely to stop early in agentic loops. A model that stops calling
tools receives the fixed `Use a tool to continue.` and hits stopping rule 6 after 10 replies. That would be a real result about this configuration, not a
bug. The gate records effort in the configuration hash.

### 3. The pilot is smaller than P1

1 episode and 30 calls versus 10 and 150. P1 §11 already names a "smoke test", so this fits. But 30 calls may end before the episode does (`model_call_limit`), which is
reported as a session cut short. **The owner must decide whether the pilot is a technical smoke test, excluded from study results, or a pre-registered study
session.** P1 §7 and §11 order baselines and pre-registration before "any model session". A smoke test before those would need that ordering amended.

### 4. Cumulative cap across providers

The $0.106019 already recorded was OpenAI spending. "Cumulative including historical" is supported by opening the live ledger with that balance, leaving about
$0.894. This is a project accounting cap; Anthropic's Console will show none of the earlier spend.

### 5. Corrections to earlier assumptions

* Image tokens are 1,196, not 1,229 (§10's table barely moves).
* The tokenizer yields about 2.5 characters per token, so §10's history assumption may be slightly low. The gateway's estimate of 2 characters per token still overestimates.
* An earlier code comment said 529 was documented as not billed. It is not, so 529 now stays charged at worst case until reconciled.
* `docs/OFFLINE_AI_GATEWAY.md` advised using the provider's SDK for a live transport. This mission used the standard library instead; see below.

### 6. Unknowns only a real call can settle

Whether the model visibly reads the HUD; how often it writes a tool call as plain text with thinking off (documented for Opus 5, unknown here), which would count as an
invalid reply; whether safety classifiers misfire on this task (`general_harms`, `frontier_llm`), which would end the session as a refusal per P1.

## The gate

`src/rewardbench/blindplay/live_transport.py`, checked in this order. Each failure refuses without side effects.

| # | Requirement | Refused when |
| --- | --- | --- |
| 1 | `LIVE_CALLS_PERMITTED` True, in a reviewed commit | **Now.** Nothing else is even read |
| 2 | No `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL` in the environment | Any is set |
| 3 | Authorization file | Missing fields, extra fields, wrong types, unfilled `OWNER_` placeholders |
| 4 | Authorization content | Not the anthropic adapter, unsupported thinking, wrong configuration hash, not yet valid, expired, lasting over 7 days, prices checked over 7 days ago, checkout dirty or not at the authorized commit |
| 5 | Credential file | Missing, a link, inside the repository, readable by other accounts, wrong format. Its content is never echoed |
| 6 | Live ledger | A mock ledger, or missing the authorized opening balance |
| 7 | A person at a real terminal (`live_session.py`) | Input is not a terminal, or the exact sentence is not typed |

After that, the gateway requires the transport to be bound to the exact configuration hash and to a live ledger. The transport re-checks the flag on every send and refuses unexpected request
fields, any other model, and calls beyond the authorized number.

**The human step means no script or agent can start spending on its own**, including Claude Code. Flipping the flag and writing the authorization are not enough.

### Why the standard library

A provider SDK is the usual choice. This mission asked for the smallest possible transport, and `http.client` is it, matching the repository's existing `providers/http.py`. It needs no new
dependency, reads no ambient credentials, ignores proxy settings, makes one attempt per call (so the gateway counts and pays for every attempt) and does not follow redirects, which could carry the key to
another host. The cost is that we own the request format, so an API change would surface as an error at call 1. An owner preferring the SDK can swap this one class; the gateway does not change.

## How it was tested

All of it locally, with a mock server on loopback and a fake key. A fixture fails any test that tries to reach anything else. On the Windows PC: **890 tests collected, 881 passed, 9 skipped (POSIX or macOS only), 0 failed**, with the sandbox and browser required, and
115 of them new. **50 of 50 deliberately broken safety rules were caught** (`docs/assets/offline-ai-gateway/verify/mutation_check.py`), including every gate check. CI results are in the devlog.

* **Wire format:** exact headers and fields, no beta or workspace headers, thinking off, effort low, screenshot bytes identical inside image blocks. Conversation rules hold across awkward replies:
  starts and ends with user, alternates, tool results first, every call answered, no empty text, at most 4 images.
* **Usage:** exact accounting, thinking tokens recorded, worst-case bound, the 100,000-token price threshold.
* **Thinking and output:** returned thinking blocks are never replayed; a reply cut off at 2,048 tokens, spent entirely on thinking, or stopped for an unknown reason is never executed.
* **Authentication and billing failures:** 400, 401, 402, 403, 404, 413 stop at once with no charge or retry; your own spend limit; the tier spend cap is not retried; a key quoted in an error body is redacted.
* **Other failures:** 429 with `retry-after`, 500/504/529 charged at worst case, redirects not followed, malformed and oversized replies, a real socket timeout, connection refused.
* **Budget:** exhaustion stops before any HTTP request; historical spending counts; a session never overspends.
* **The complete path:** real sandbox, real game, real screenshots, real HTTP, mock API. The last four real screenshots reached the request byte for byte, and the fake key appeared in no record.
* **The sandbox** cannot read the credential, the authorization, or the transport's source.

**Never tested:** anything at the real endpoint. TLS to `api.anthropic.com`, the real auth header, real replies and real billing are unverified until an authorized smoke test.

## Configuring API billing without exposing credentials

For the owner, when ready. **Do this yourself in a browser and your own terminal. Do not paste the key into any chat, including Claude Code.**

### 1. Keep Claude Code on your subscription

**Never** set `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` as an environment variable, with `setx`, in a profile, or in a `.env`. [They outrank a subscription login](https://code.claude.com/docs/en/authentication), so Claude Code would start
billing your API account. On Windows, `setx` also stores them where the sandbox can read them. The project's gate and host both refuse to run if they find such variables. Check any time with `claude auth status`: `authMethod` should say `claude.ai`.

### 2. In the Console ([platform.claude.com](https://platform.claude.com))

1. **Create or sign in to a Console account.** API billing is separate: the [billing article](https://support.claude.com/en/articles/8977456-how-do-i-pay-for-my-claude-api-usage) lists monthly API credits only for Max, Ultra and Team plans, not Pro.
2. **Buy the smallest credit amount offered**: Billing → Buy credits. Purchases are non-refundable and expire after one year. The minimum is not documented, so check the page.
3. **Leave auto-reload off.** If it is on: Billing → Manage auto-reload → Turn off, then confirm.
4. **Set an organization spend limit:** Billing → Spend limits → Set limit. `$1` is suggested.
5. **Create a workspace:** Settings → Workspaces → Create workspace, for example `react-smoke`. The Default Workspace cannot have a spend limit.
6. **Set the workspace's limit:** select it → Spend limits → `$1`.
7. **Create a key:** Settings → API keys → Create key. Name it `react-smoke-1`, set Linked account to yourself, **scope it to `react-smoke`**, and pick a short expiry, such as 1 day or 7 days. It is shown once. Do not save it elsewhere.

### 3. Store the key (run in your own PowerShell window)

These exact steps were run on this PC with a fake key, and the gate accepted the result. `Read-Host -AsSecureString` hides the key and keeps it out of your command history.

```powershell
$dir = "$env:USERPROFILE\.react-secrets"
New-Item -ItemType Directory -Force $dir | Out-Null
icacls $dir /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
$secure = Read-Host "Paste the key" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
[IO.File]::WriteAllText("$dir\anthropic-smoke.key", $plain, [Text.UTF8Encoding]::new($false))
Remove-Variable plain, secure
icacls "$dir\anthropic-smoke.key"
```

The last line should list only your own account (plus SYSTEM or Administrators if your PC adds them). Never put this file inside the repository or `runs/`; the gate refuses it there. Agents on your machine run as your user, so the sandbox protects this file from the player, not from other tools you run. Do not ask an agent to read it.

### 4. Afterwards

Check Console → Usage against the local ledger, and record any difference with `SpendLedger.reconcile`. **Delete the key** when the smoke test is done: API keys → menu next to the key → Delete. If you ever suspect a leak, delete it at once.

## What happens at the separately authorized smoke test

Not to be done until authorized. In order:

1. Owner records decisions in `PROJECT.md`, and in a reviewed commit sets `LIVE_CALLS_PERMITTED = True`.
2. Owner re-checks prices, then fills in the output of `python -m rewardbench.blindplay.live_session template`, adding that commit, and stores it outside the repository.
3. CI is green on that commit, and the checkout is clean.
4. In their own terminal, the owner runs the command below and types the confirmation sentence:

```powershell
.\.venv\Scripts\python.exe -m rewardbench.blindplay.live_session run --authorization <file> --credential "$env:USERPROFILE\.react-secrets\anthropic-smoke.key" --ledger <new-file-outside-repo> --out runs\blind-visual\<new-id>
```

5. Whatever happens is reported. Then set the flag back to False in a new commit unless further sessions are authorized.

The authorization file must name the commit that sets the flag, so a commit message or file cannot pre-approve itself.

## Remaining limitations

* **The real endpoint is untested**, as above.
* **Authorization files are not signed.** Anyone able to write files as your user could write one. The terminal confirmation is what stands in the way of unattended use, and a person typing it is taking responsibility for what they typed.
* **The Windows permission check matches English group names.** On a localized Windows it may miss a broad grant.
* **Everything in `docs/OFFLINE_AI_GATEWAY.md`'s limitations still applies**, including that a provider reporting more input than the estimate could slightly exceed a cap. The Console spend limits are the independent backstop.

## Owner decisions

1. **Thinking:** option A, `disabled` (recommended), accepting the trade-off above, or fund the work for B, C or D.
2. **Effort:** confirm `low`, knowing it can make the model stop early.
3. **Status of the pilot:** an excluded technical smoke test (recommended) or a pre-registered session. If a smoke test, amend P1's ordering, which puts baselines and pre-registration first.
4. **`keyset.v2`** and **protocol P1** with amendments §13 and §14.
5. **Provider, model, platform, episode and call limits, caps.** All provisional until you confirm them, including counting OpenAI's $0.106019 toward the $1.00.
6. **Billing:** open the Console account, credits and limits above. You choose the amount.
7. **Transport:** accept the standard-library transport, or ask for the SDK.
8. **The flag:** when, and in which reviewed commit, it may be set to True.
9. **Off-machine backup** of raw data, still open since Mission 012.
