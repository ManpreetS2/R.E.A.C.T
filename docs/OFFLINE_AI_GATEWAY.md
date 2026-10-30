# Offline AI gameplay gateway (Mission 015A)

**Status (2026-10-30): built and verified offline with a mocked provider. No model has played. No API was called,
authenticated to or charged. There is no network code in the gateway. Nothing in this document selects a model, approves
a protocol or authorizes spending.**

*Update 2026-10-30 (Mission 015B):* a live transport now exists behind a closed gate, and still nothing can reach a provider. See `docs/LIVE_TRANSPORT_PREPARATION.md`, which also corrects this document on
thinking, the SDK and 529 charging. The gateway modules described here still contain no network code. Everything below describes Mission 015A as delivered.

Builds on the isolated runtime (`docs/ISOLATED_PLAYER_RUNTIME.md`) and the environment
(`docs/BLIND_VISUAL_FOUNDATION.md`). The research protocol is `docs/BLIND_PLAY_PROTOCOL_V1_DRAFT.md`. Chronology:
`docs/assets/offline-ai-gateway/DEVLOG.md`.

## Architecture

```
 TRUSTED HOST                                                            ISOLATED PLAYER (sandbox)
 ┌──────────────────────────────────────────────────────────────┐        ┌───────────────────────────┐
 │ provider <- transport (offline only) <- adapter <- gateway   │ pipes  │ runtime.py --mode model   │
 │                                                    │  history│ <────> │  "next turn"              │
 │                     spend ledger <- reservation ───┤  limits │        │  press what comes back    │
 │                                                    │  checks │        │ no history, no model text │
 │ host.py: forwards a game request only if it is the │         │        │ no network, no files      │
 │          model's next validated tool call ─────────┘         │        └───────────────────────────┘
 │     │                                                        │
 │     v                                                        │
 │ serve.py -> Session -> referee.py (Chromium, upstream game)  │
 └──────────────────────────────────────────────────────────────┘
```

| Module | Role |
| --- | --- |
| `contract.py` | Versioned player contract. `keyset.v1` frozen; `keyset.v2` new. |
| `model_gateway.py` | Provider-neutral core: conversation, image window, validation, limits, cost accounting, stop reasons, transcript. `LIVE_CALLS_PERMITTED = False`. |
| `model_providers.py` | Wire formats only: `MockAdapter`, `AnthropicMessagesAdapter` (never exercised against the real API), `OfflineTransport`, `MockVisionProvider`. |
| `spend_ledger.py` | Durable, hash-chained, lock-protected ledger with pre-call reservations. |
| `host.py` | New `model` and `gateway-probe` modes; refuses mismatched host and gateway settings. |
| `player_runtime/runtime.py` | New `run_model_session`: a relay that holds no conversation. |
| `offline_demo.py` | The mocked end-to-end demonstration and the session audit. |

### Why the host owns the conversation

In Mission 014's `agent` loop the sandboxed player kept the message list and sent it to the host. That is acceptable for a
scripted plumbing test, but not for a billed session: a compromised player could write anything into the model's history,
and dropping a tool call would break the provider's rule that every call is answered. In `model` mode:

* The player's only model request is exactly `{"tool": "model"}`. Any other field is rejected.
* A game request reaches the referee only if it is the opening observe or **exactly** the model's next validated call.
* The player never receives the model's words: `text` is empty in what it gets back.

`agent` mode stays for Mission 014's test, and the host refuses a real model in it.

## `keyset.v2` (proposed; needs owner approval)

**ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Enter, Escape, KeyA, KeyD, KeyW, ShiftLeft, Space.** That is `keyset.v1` minus
`KeyS`, whose upstream handler (`// SPEED MODE!` in `game.js`) runs 4 physics updates per frame. Protocol
`react.blindplay.player.v2`; every field other than the key enumeration is unchanged, which a test pins.

* The upstream game is untouched and still has the speed mode (pinned hashes unchanged). The key is simply not offered, and
  is refused by the gateway, the host and the referee session.
* `keyset.v1` is frozen by a hash recorded before this mission (`083d655c…`). `Session`, `serve`, `HostConfig` still default
  to it, so nothing historical changes meaning. `replay.py` reads the keyset from each session's own `session.json`.
* The same inputs give byte-identical screens under v1 and v2 (tested).
* `GatewayConfig` refuses `keyset.v1`. Choosing to offer `S` to a model needs an owner decision and a code change.

## What a model receives

Exactly (logged per call, images by sha256):

* **System:** `Land the rocket.`
* **Tools:** `contract.V2.tools`: `observe` and `act`, with the 11 keys and `1 ≤ frames ≤ 120`. Nothing else is enabled.
* **First user message:** `Land the rocket.` plus the first screenshot.
* **Assistant turns:** its own visible text and tool calls, as returned.
* **Tool results:** the counters `episode`, `episode_frame`, `episode_frame_budget`, `max_episodes`, `frames_advanced`,
  `episode_ended`, `session_over`, plus the screenshot. Errors are fixed or contract-generated text.
* **Fixed procedural notes:** `Use a tool to continue.`, `[earlier screenshot omitted]`, and the tool-result errors
  `unknown tool`, `invalid arguments`, `unexpected arguments`, `not executed: at most 8 tool calls per reply`,
  `not executed: the episode ended`, `the reply was cut off by the output limit; this call was not executed`, and the
  contract's own validation messages.

**Last four screenshots.** Only the 4 most recent are sent; older ones become the note. The gateway holds only those 4 in
memory, and an outbound guard re-counts images immediately before sending.

**Screenshot checks before use.** Exact contract fields, `image/png`, declared 1280×720, strict base64, sha256 match, PNG
signature, IHDR size, every chunk's CRC, IEND last, nothing after it, at most 5 MB. Any failure ends the session with no
provider call, and the player does not get the bad image.

**No privileged state.** The gateway imports nothing from the referee side, has no session directory, and accepts only
messages with exactly the contract's fields (extra fields stop the session). Counters must be integers or booleans. Isolated
tests scan every outbound request for privileged words and for the actual episode outcome.

## Limits

Defaults are the P1 proposals. All are fixed for a session and hashed into its records (`config_sha256`).

| Limit | Default | When hit |
| --- | --- | --- |
| Episodes / frames per episode | 10 / 8,000 | Referee ends the session; host and gateway must agree or nothing starts |
| Model calls, including retries | 150 | `model_call_limit` |
| Tool calls per reply | 8 | Extras are answered with an error, not executed |
| Tool argument size | 1,024 bytes | That call is rejected |
| Images per call | 4 | Window, plus outbound guard |
| Output tokens per call | 2,048 | Sent as the provider's limit; more reported means `output_limit_violated` |
| Reply text kept | 20,000 chars | Cut in the history |
| Context (estimated input tokens) | 90,000 | `context_limit`, before the call. History is **never** silently shortened |
| Request size | 20 MB | `request_size_limit`, before the call |
| Wall clock | 2 hours | `wall_clock_limit`, plus a host watchdog that kills a silent player |
| Provider timeout | 120 s | Enforced by the gateway on its own thread, so a hung transport cannot hang the session |
| Consecutive provider errors | 3 | `consecutive_provider_errors` |
| Consecutive replies without a valid call | 10 | `consecutive_invalid_replies` |

## Money

**The cap check is on the worst case, before the call, and the reservation is on disk before the provider is contacted.**

1. Estimate input tokens deliberately high (about 2 characters per token for text and schemas, 1,600 per image).
2. Worst case = estimate at the input rate + the output limit at the output rate.
3. `ledger.reserve` holds the lock, re-reads and verifies the whole ledger, and either fsyncs a reservation or raises
   `BudgetExceeded`. On refusal no call is made and the session stops.
4. After the call the reservation is settled:

| Outcome | Charged | Basis |
| --- | --- | --- |
| Reply with valid usage | Exactly the provider's usage × prices | `provider_usage` |
| Reply with missing or nonsensical usage | Worst case, and the session ends | `worst_case_usage_missing` |
| Timeout, connection error, 408/409/5xx, malformed 200 | Worst case, because it may have been processed | `…:worst_case_unverified` |
| 429, 529 | $0, then retry (`retry-after` honoured, capped at 60 s) | `…:not_billed` |
| Other 4xx | $0, and the session ends | `rejected_by_provider:not_billed` |
| Process dies mid-call | Stays reserved at worst case | an open reservation |

A worst-case charge can be corrected later with `SpendLedger.reconcile(reservation, charged=..., note=...)`, which appends
an entry and keeps the earlier ones. Limits of this design are listed below.

* **Caps have no defaults.** The session cap may not exceed the cumulative cap. Money is never a float.
* **Mock and live money cannot mix:** a ledger is bound to its mode at creation, and an offline transport refuses a live
  ledger.
* **Price thresholds:** Claude Haiku 5.5 is $0.10/$0.50 per MTok only up to 100K input tokens, then $0.50/$2.50.
  `ModelPricing` carries the threshold and `GatewayConfig` refuses a context limit above it.
* **Concurrent sessions** share the cumulative cap under an OS lock (tested with 6 threads); the kernel releases the lock if
  a process dies, so a crash cannot leave the ledger blocked.

## Failures and recovery

| Failure | Behaviour | Tested |
| --- | --- | --- |
| Provider refusal | Charged, recorded, `provider_refusal`, session ends (P1 §8) | yes |
| Timeout / hang | Worst-case charge, retry, stop after 3 | yes |
| Rate limit | No charge, bounded wait, retry, stop after 3 | yes |
| Malformed reply | Worst-case charge, never interpreted | yes |
| Hallucinated tool, bad arguments, extra fields | Answered with an error; nothing reaches the game | yes |
| A different model answers | `model_mismatch` (protects the pre-registered id) | yes |
| Invalid screenshot | Session ends, no call, player not shown it | yes |
| Gateway exception | `aborted_gateway_failure`; player gets the fixed message; reservation stays open | yes (real sandbox) |
| Player killed | Host closes; records and ledger consistent; referee session replays | yes (real sandbox) |
| Referee killed | `aborted_host_failure`, manifest written, no further model call | yes (real sandbox) |
| Host killed mid-call | Open reservation at worst case; transcript verifies; manifest visibly says `running`; no stale lock | yes (real sandbox) |
| Torn final ledger line | Sealed by the next write; changes no number | yes |
| Edited ledger | `LedgerCorrupt`; nothing can be spent until a human looks | yes |

**There is no automatic resume.** P1 forbids restarting a session for a better result. A crashed session is reported as
such. `offline_demo.audit_session(session_dir, ledger_path)` cross-checks the transcript chain against the ledger and lists
open reservations; it works on a crashed session too.

## Records

Inside the host session directory (raw data stays local and gitignored; never upload it):

* `gateway_transcript.jsonl`: hash-chained. One record per call attempt: messages sent (images by sha256, never bytes),
  `wire_sha256`, estimate, worst case, reservation, outcome, provider request id and model string, usage, charge, the reply
  text and calls. Also rejected calls, refused game requests and the stop reason.
* `host_session.json`: `gateway_session` block with the config and its hash, contract, tool-schema hash, counts, stop
  reason, charge and transcript tip.
* `referee/`: unchanged Mission 013 layout, including the privileged files. Replays with `replay.py`.

**Safe logging.** The gateway never holds a credential, and transport headers are never logged. Provider error bodies and
model text pass through `redact()` (known key prefixes, bearer tokens). The player sees only one fixed "session ended"
message; the reason stays on the host.

The referee's environment now excludes credential-like variables, so a provider key in the host's environment does not reach
the browser side.

## The Claude adapter (written, never used)

`AnthropicMessagesAdapter` translates to and from the Messages API JSON as documented in the bundled Claude API reference
(prices and models cached 2026-10-06). **It has never been run against the real API**, so real behaviour remains unverified.
It is unreachable: there is no live transport, and `VisionGateway` refuses any transport that is not offline.

**A finding the owner should know about.** On current Claude models (Fable 5.1, Opus 5.5, Sonnet 5.5, Haiku 5.5), thinking
is on by default and thinking blocks are bound to the exact earlier conversation. Replacing an old screenshot with a note
is an edit of an earlier turn; on enforced accounts (created on or after 2026-08-31), replaying a thinking block after such
an edit returns a 400. So the adapter **discards thinking blocks and never replays them**. Consequences:

* The model keeps its visible text and tool calls, but not its private reasoning, across turns. This matches P1 §5.
* Thinking is still billed as output tokens, so P1's 600-output-token assumption may be low for these models. Use
  `effort: low`, and treat cost estimates as uncertain until a smoke test.
* The edit also limits prompt caching, so the gateway does not enable it.
* Alternatives (provider-side context editing, or keeping every screenshot) would be provider-specific or change P1, and need
  an owner decision.

Other deliberate omissions: no `fallbacks` (it could change the model mid-session), no betas, no provider-side tools, no
sampling parameters, `tool_choice` always `auto`.

## Guarantees, and what is not guaranteed

Guaranteed by tests in `tests/blindplay/`: no code path can reach a provider; a sandbox player can neither read the gateway's
files nor influence what a model is told; only validated model calls reach the game; no call goes out without a durable
reservation that fits both caps.

**Limitations:**

1. **Nothing has been tested against a real provider or a real model.** Image handling, tool-call formats, usage numbers,
   refusals and rate limits are all simulated. The mock is written from documentation.
2. **A cap can be exceeded by a provider that reports more input than the estimate.** The estimate is a deliberate
   overestimate and output is bounded by the request, but only the provider's invoice is authoritative. Such a call is charged
   in full, and no further call can then pass. Keep a provider-side spending limit as an independent backstop.
3. **Truncating the end of the ledger is not detectable by the chain alone** (a chain proves no middle record was changed).
   The transcript's charges and `audit_session` catch a mismatch, unless both are truncated. Same-user access to the host's
   files is outside the threat model, as in Mission 014.
4. **Redaction is pattern-based**; an unfamiliar credential format in a provider's error body could be logged locally. Keep
   transcripts private, and review before publishing anything.
5. **Worst-case charges for uncertain failures are estimates.** They overstate spending until reconciled.
6. **A timed-out transport thread cannot be cancelled** in Python. Its result is discarded, and a live transport must also
   enforce its own timeout.
7. **Same sandbox limits as Mission 014** (`docs/ISOLATED_PLAYER_RUNTIME.md`), including the file-existence oracle and no
   defence against kernel exploits. Linux has no backend; the gateway's logic tests run there, the sandbox tests do not.
8. **macOS was verified by CI only in this mission**; this work was done on the Windows PC.

## Verification

On the Windows PC (Python 3.13, Chromium, AppContainer required): **774 tests collected, 765 passed, 9 skipped (POSIX or macOS
only), 0 failed**, including 334 blind-play tests, of which 235 are new. Evidence: `docs/assets/offline-ai-gateway/evidence-2026-10-30.json`.

* **Real sandbox, real game, mocked provider:** normal play, hostile replies, budget exhaustion, gateway crash, and the player,
  referee and host each killed mid-session. The Mission 014 attack suite still passes unchanged.
* **Attacks from inside the sandbox with a gateway attached:** reading the ledger, the gateway's records and a fake credential file;
  network; 13 protocol attacks (smuggled history, choosing the model, forged actions, the speed key, replaying a call). All denied,
  none reached the referee or the provider.
* **Mutation check** (`docs/assets/offline-ai-gateway/verify/mutation_check.py`): 32 of 32 deliberately broken safety rules were
  caught by the browser-free tests.
* **Offline demo:** the mocked session's referee record replays identically; ledger and transcript agree; at most 4 images in any
  call; no privileged word in anything sent.

CI results are recorded in the devlog.

## Commands

```powershell
$env:PYTHONPATH='src'; $env:REACT_REQUIRE_ISOLATION='1'; $env:REACT_REQUIRE_BROWSER='1'
.\.venv\Scripts\python.exe -m pytest tests/blindplay -q
.\.venv\Scripts\python.exe -m rewardbench.blindplay.offline_demo --out runs/blind-visual/<new-id>
```

The demo costs nothing and contacts nothing. Its "model" is a fixed script that ignores the screen, so its crashes say nothing
about AI. The host CLI still starts only scripted NON-AI stand-ins.

## Exact candidate model requirements

A model is a candidate for P1 only if **all** of these are confirmed from the provider's current documentation, and then by
the smoke test (none has been tested):

| # | Requirement | Why |
| --- | --- | --- |
| 1 | Accepts PNG screenshots as base64 at 1280×720 in tool results, without reducing them below legibility of the HUD | The whole task is reading the screen; record any provider-side resizing |
| 2 | At least 4 images per request | Last-four policy |
| 3 | Client-defined tools with JSON Schema, including an `enum` of keys and integer bounds | The contract's exact schemas |
| 4 | No provider-side tools are forced on; none will be enabled | No web, code execution or memory |
| 5 | Every successful reply reports input and output tokens | Otherwise the session ends at its first call |
| 6 | A signal that distinguishes refusal from a normal stop | Stopping rule |
| 7 | A fixed, exact model ID that the reply echoes (no silent routing or fallback) | Pre-registration; otherwise `model_mismatch` |
| 8 | Works with a history where old images were replaced by text, with no replay of hidden reasoning | Last-four policy; see the finding above |
| 9 | Published per-token price, including any long-context tier, verified on the day of approval | Budget gate |
| 10 | A per-call output limit is honoured; thinking tokens are bounded by it or their billing is understood | Worst-case calculation |
| 11 | Context window comfortably above the 90,000-token limit, and rate limits that allow a session in 2 hours | Otherwise the session ends early |
| 12 | Provider-side monthly spending limit available | Independent backstop |
| 13 | Data-use terms acceptable to the owner (screenshots, the objective and the model's text leave the machine) | By design; the data is game imagery only |
| 14 | No account-level memory or personalization across sessions | P1 §5: nothing carried over |

Candidate prices from `docs/BLIND_PLAY_PROTOCOL_V1_DRAFT.md` §10 must be re-verified on the provider's pricing page. Only the
Claude entries have an adapter; any other provider needs its own, tested offline first.

## Owner approval checklist

Each needs an explicit, dated decision recorded in `PROJECT.md`. No default applies.

- [ ] **Keyset:** approve `keyset.v2` as the set offered to models (recommended), or require keeping `S`, which needs new code.
- [ ] **Protocol:** accept or amend P1, including §13's additions: cut batches at episode end, the output and context limits,
      the disclosed fixed error texts, and thinking not replayed.
- [ ] **Model:** provider and exact model ID, after checking requirements 1–14.
- [ ] **Effort level** (if the model has one): `low` is suggested as a cost control, but it is part of the experiment and must
      be fixed.
- [ ] **Spend caps:** per-session and cumulative USD. Decide whether the cumulative cap includes the $0.106019 already recorded
      in earlier missions (`record_opening_balance` supports this).
- [ ] **Billing:** a provider API account with its own spending limit, set by the owner. **A Claude Pro subscription does not pay
      for API calls**; this is separate paid billing, which this mission did not enable. The key must stay in host-only
      storage, never `setx`/`HKCU\Environment`.
- [ ] **Scope:** smoke test (1 episode, about 30 calls) first, then full P1 (10 episodes, 150 calls), and how many sessions.
- [ ] **Platform:** Windows or macOS, fixed for the study.
- [ ] **Authorize the live code:** a live transport (see below), and setting `LIVE_CALLS_PERMITTED = True`.
- [ ] **Scripted baselines:** authorize recording §7's baselines under the final settings.
- [ ] **Off-machine backup** of raw data (still open since Mission 012).

## Future pre-registration procedure

Do **not** perform this until the checklist above is complete. Nothing has been pre-registered.

1. Record the owner's dated decisions in `PROJECT.md`.
2. Finalize `docs/BLIND_PLAY_PROTOCOL_V1_DRAFT.md` into a new versioned protocol file, keeping the draft unchanged as history.
3. In a separate reviewed commit, add the live transport (use the official provider SDK, in a module outside `blindplay/`'s
   no-SDK test, or amend that test with owner approval), and set the flag. Re-run all tests with a mocked provider. Add a test
   that no live call is possible without an explicitly supplied credential path and owner-set caps.
4. Re-verify prices and fill in the `GatewayConfig` values. Save its `config_sha256`.
5. Run isolation, replay and offline tests on the target platform at that exact commit, and require green CI on all three OSes.
6. Record the §7 scripted baselines through the isolated host with those final settings.
7. Commit the protocol, configuration and baseline summaries. In `PROJECT.md` record: commit hash, config hash, tool-schema
   hash, runtime image digest, platform, Chromium build, model ID, caps, and the planned number of sessions. **Then no edits.**
8. Only then may an approved session start, and every session is reported, whatever happens.

## What remains before a genuine model session

1. All owner decisions above.
2. A provider account, spending limit and host-only credential (owner).
3. A live transport and the flag change, reviewed, in a separate commit (about one small module; the gateway does not change).
4. Confirming requirements 1–14 for the chosen model. Some can only be confirmed by real calls, which is what an approved smoke
   test is for. Token counting of the real screenshots would also tighten cost estimates.
5. Scripted baselines under final settings, then pre-registration.
