**CANDIDATE — NOT OWNER APPROVED — NOT PRE-REGISTERED**

# Blind-play protocol P1 v1 — consolidated candidate (2026-11-05)

Status: a single consolidated proposal for owner review. It supersedes nothing by itself: `docs/BLIND_PLAY_PROTOCOL_V1_DRAFT.md`
stays byte-identical as history, and PROJECT.md is not changed by this file. Every value below is **proposed**. No decision in
the companion record `docs/BLIND_PLAY_V1_OWNER_DECISIONS.md` has been made; nothing here selects a model, authorizes a key, or
approves spending. Approval, if any, is a dated owner entry in PROJECT.md. No model session has been run. Numbers were checked against
`src/rewardbench/blindplay/{contract,model_gateway,model_providers,live_transport}.py` on 2026-11-05; where this text and the code
would differ, the code is authoritative and the difference is listed in Appendix A or reported to the owner.

Sources: the draft (§1–§14), `docs/OFFLINE_AI_GATEWAY.md`, `docs/LIVE_TRANSPORT_PREPARATION.md`, `docs/ISOLATED_PLAYER_RUNTIME.md`.

## 1. Purpose and question

Can a vision-capable model, told only **"Land the rocket."**, land the original ApolloLander by looking at screenshots and pressing
keyboard keys? Pilot P1 is a technical-feasibility measurement for one configuration. It also describes, without causal claims, how
the model's behaviour looks across the episodes of one session.

## 2. Claim limits (binding wording)

1. **Design label.** "Feasibility case study of one configuration on one fixed start." P1 is n = 1 session. It supports no claim about
   model families, generalisation or feedback effects.
2. **Forbidden words.** The reports never say the model "learns", "improves because of" anything, "can play", or that "model X is
   better". Changes across episodes are described without causal claims, because they are confounded with the growing text context and
   the sliding four-image window.
3. **Thinking.** "Results describe claude-haiku-5-5 at low effort with thinking disabled under this harness, not the model's full
   capability."
4. **Landing by chance.** Every landing count is reported next to the scripted baselines (§9). No claim that the model reads the HUD is
   made unless the model's own visible text shows it.
5. **Failures are results.** Early stops (likely at low effort), refusals, tool calls written as plain text, a 30-call cutoff, a session
   with no landing: each is reported as a result.
6. **Money.** Cost figures are estimates until reconciled with the provider Console.
7. **Smoke test label.** "Technical smoke test; not a study session; not pre-registered; excluded from all study analyses; reported in full."

## 3. Platform and environment (proposed)

| Item | Proposed value |
| --- | --- |
| Environment | `apollolander-upstream-fixed-start`, upstream `0da09dc`, SHA-256-pinned; seed 0; the reserved cohorts are not used |
| Platform | Windows on this PC (Windows 11 build 26300, newer than Mission 014's build), isolated runtime in an AppContainer with a Job Object |
| Recorded at pre-registration | OS build, Chromium build, runtime-image digest, container SID, browser/Playwright/Python versions |
| First screenshot | frame sha256 begins `fbcbb40b641e` (Windows). macOS records (`aa31f5af16ad…`) are not on this PC and are not used |
| Each episode | fresh browser context, unmodified game, 2 title frames, referee click, 4 playing frames; 60 outcome frames after a terminal state; the player cannot reset early |
| Deviations from the live game | as written to every `session.json` (virtual clock, seeded RNG, muted audio, fresh game per episode, title screen not shown) |

The platform is fixed for smoke test, baselines and study, and never mixed within a comparison.

## 4. Game and keyset (proposed)

Keys offered: **`keyset.v2`**, alphabetical, no meanings given: ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Enter, Escape, KeyA, KeyD, KeyW,
ShiftLeft, Space (11 keys). `keyset.v1` additionally holds `KeyS`, which triggers the upstream developer speed mode (4 physics updates
per frame, `// SPEED MODE!`). `keyset.v2` omits it so that frame budgets mean the same game time for every action; the deviation is recorded
as "upstream developer speed mode not offered". Several offered keys do nothing in this game; finding out which is part of the task. The
gateway refuses `keyset.v1`; `keyset.v1` stays frozen for replaying earlier sessions. Protocol string `react.blindplay.player.v2`.

## 5. Model, API and configuration (proposed)

| Setting | Proposed value |
| --- | --- |
| Provider and model | Anthropic Messages API, `claude-haiku-5-5` |
| Thinking | `{"type": "disabled"}` (the only mode the live gate accepts) |
| Effort | `low`, `output_config: {"effort": "low"}`; **one value for smoke test and study**, recorded in the configuration hash |
| Tool choice | `{"type": "auto"}` |
| Request fields sent | exactly: `model`, `max_tokens` (2,048), `system`, `tools`, `tool_choice`, `messages`, `output_config`, `thinking`. The transport refuses any other field |
| Not sent | no `temperature`/`top_p`/`top_k`, no `cache_control` (no prompt caching), no `fallbacks`, no `metadata`, no provider-side tools, no streaming |
| Headers | `Authorization: Bearer <key>` (the documented primary form, checked 2026-11-05; `x-api-key` is documented as legacy), `anthropic-version: 2023-06-01`, `content-type`; no beta header, no workspace header. **API version note (2026-11-05):** the documentation now shows a newer version, `2026-10-21`, whose only Messages API changes are 400 errors for `document` blocks in assistant messages, citations on user text blocks, and the removed `temperature`/`top_p`/`top_k` parameters. This transport sends none of those, and `2023-06-01` remains a documented version, so the tested wire format is kept. Moving to `2026-10-21` is a configuration change that would need re-testing and a new configuration hash |
| Transport | Python standard library `http.client`: one attempt per call, no redirects, proxy settings ignored, no SDK |
| Price basis | $0.10 input / $0.50 output per MTok for prompts up to 100,000 tokens ($0.50 / $2.50 above). Re-verify on the pricing page on the day of authorization |

The adapter refuses `thinking: disabled` together with effort `xhigh` or `max` (`model_providers.py`); at `low` it is accepted.

Thinking blocks: with thinking disabled none are expected. If one appears it is logged by type and never replayed or executed. The
documentation's rule to echo thinking blocks during tool use is therefore not triggered; the alternative modes (adaptive thinking with
replay, append-only history, provider-side context editing) are not built and are out of scope for P1.

## 6. Budgets and caps (proposed)

Defaults in `GatewayConfig` equal the P1 values below; all are fixed for a session and hashed (`config_sha256`).

| Limit | Smoke test | Study |
| --- | --- | --- |
| Sessions | 1 | 1 |
| Episodes per session | 1 | 10 |
| Simulated frames per episode | 8,000 (133 s of game time) | 8,000 |
| Frames per `act` | 1–120 | 1–120 |
| Model calls incl. retries | ≤ 30 | 150 |
| Tool calls per reply | ≤ 8 | ≤ 8 |
| Game requests per session | 1,000 | 1,000 |
| Output tokens per call | 2,048 | 2,048 |
| Estimated context per call | 90,000 tokens | 90,000 tokens |
| Wall clock | 2 hours | 2 hours |
| Consecutive provider errors | 3 | 3 |
| Consecutive replies without a valid call | 10 | 10 |
| Per-reply text kept in history | 20,000 characters | 20,000 characters |
| Tool-argument size | 1,024 bytes | 1,024 bytes |
| Request size | 20 MB | 20 MB |
| Provider timeout | 120 s | 120 s |
| Images sent per call | last 4 | last 4 |

**Money.** The worst-case cost of each call (estimated input at the input rate plus 2,048 output tokens at the output rate) is reserved
durably on disk before the request; if the reservation does not fit a cap, no call is made and the session stops. The input estimate is
deliberately high (about 2 characters per token, 1,600 tokens per image, plus 256). Proposed caps: **$0.50 per session** and **$1.00
cumulative including the $0.106019 already recorded on OpenAI** (opening balance; $0.893981 remains). The session cap may not exceed the
cumulative cap. Open sub-decision on the study session cap: see `docs/BLIND_PLAY_V1_OWNER_DECISIONS.md` (D10). **D10 and its study-session-cap sub-decision must be
recorded in PROJECT.md before the smoke test**: a session cap chosen after seeing the smoke test's cost would be a budget change made after the smoke test (§8). The provider Console spend limits
(organization and workspace) are the independent backstop, and the owner sets them. The ledger for each later session must open with a
balance that includes the then-reconciled earlier spend.

## 7. What the model sees, and memory (proposed)

Sent on every call: system text `Land the rocket.`; the two tools `observe` and `act` verbatim from `contract.V2.tools` (with the 11-key
enumeration, `1 ≤ frames ≤ 120`); the first user message `Land the rocket.` plus the first screenshot; after each tool call a result with
the counters `episode`, `episode_frame`, `episode_frame_budget`, `max_episodes`, `frames_advanced`, `episode_ended`, `session_over` and the
1280×720 PNG screenshot (1,196 image tokens). All game information (score, fuel, altitude, outcome) comes only from the on-screen HUD.

Fixed procedural texts (none describes the game): `Use a tool to continue.` when a reply has no tool call; `[earlier screenshot omitted]`;
`unknown tool`; `invalid arguments`; `unexpected arguments`; `not executed: at most 8 tool calls per reply`; `not executed: the episode ended`;
`the reply was cut off by the output limit; this call was not executed`; `the reply stopped early; this call was not executed`; and the contract's own
validation messages.

**History within a session.** One continuous conversation. Only the **last 4 screenshots** are sent as images; older ones become
`[earlier screenshot omitted]`. The text history (the model's visible messages, its tool calls, the counters) is complete and is never
shortened, with four disclosed exceptions: (1) each assistant reply is cut at **20,000 characters**; (2) a reply whose tool-call IDs are unusable
(missing, malformed, repeated within the reply or already used earlier in the session) is **removed from the history** and replaced by the user text
`Use a tool to continue.` (`model_gateway._accept` / `_validate_calls`); (3) empty or whitespace-only text blocks are dropped from the request, because the API
rejects them (`AnthropicMessagesAdapter.build_request`); (4) an assistant turn left with no content after that is dropped, and the next user text simply
follows. If the 90,000-token estimate would be exceeded the session **ends** rather than shortening anything.

**Across sessions.** Nothing: new conversation, wiped storage, no provider memory features, no notes. The smoke test therefore carries nothing
into the study.

**Never sent:** control mappings, physics, rules, scores beyond the screen, referee state, previous sessions, other models' results, hints
after failure.

**Every tool call is answered** (providers require it). Calls beyond 8 in one reply, invalid calls and calls after an episode ended inside the
same reply are answered with the fixed errors above and **not executed**; they are not silently dropped. A reply stopped by the output
limit or for any stop reason other than `tool_use`/`end_turn` is not executed, and the session continues (subject to §10).

## 8. Smoke test versus study

**Smoke test (technical; label in §2.7).** One episode, at most 30 model calls, same model, effort, thinking, keyset, start and
budgets as the study. Technical pass criteria, declared now: (a) a valid tool call is made from a real screenshot, (b) the game advances,
(c) the local ledger reconciles with the provider Console. Reaching 30 calls before the episode ends is reported as a session cut short.

**Rule limiting changes after the smoke test.**

* **Technical defect (definition).** Behaviour that contradicts this text, or a provider rejection, or a parse error. It is never anything about how the
  model played: what it pressed, whether or how fast it landed, how it wrote, how many calls it used.
* **Only technical defects may be changed.** Prompt, keys, effort, thinking and budgets may **not** be changed because of how the model played.
* **Must be identical between smoke test and study:** `tools_sha256`, the system text, `adapter_settings` (effort, thinking), the model, the keyset
  and the frame limits (frames per `act`, frames per episode). **Only `max_episodes`, `max_model_calls` and the session cap may differ.** Because those
  three are in the configuration hash, the two hashes differ; the comparison is made field by field, not by hash.
* **Records required:** the smoke test's configuration hash and git commit, and the diff from the smoke-test commit to the pre-registration commit, with
  one stated reason per change. If a change affects the keyset, platform, frames per act or episode length, the baselines (§9) are recorded again
  (re-recording rule).
* **Repeating a failed smoke test (proposed rule, not decided):** at most **2 attempts in total**; every attempt is excluded from the study analyses and
  reported in full; the spend of every attempt counts toward the cumulative cap. A repeat is allowed only after a recorded technical defect was fixed.

**Study.** One session, 10 episodes, all budgets of §6, pre-registered (§14) before it starts. Not stopped on success; not restarted to obtain
a better result; nothing edited mid-session; every session is reported.

## 9. Scripted baselines (non-AI, $0)

Recorded through the same isolated host, keyset and platform, before the smoke test and under settings that must not be tuned. **Exact configuration:**
`keyset.v2`, seed 0, 10 episodes, 8,000 frames per episode, with the frame length per `act` set by each script (`idle` 120; `key-sweep` 20; `seeded-random` 1–120).
Command (`src/rewardbench/blindplay/baselines.py`): `python -m rewardbench.blindplay.baselines plan --keyset keyset.v2 --out-root <dir>` prints every host
command and a `plan_sha256`; `run` (same arguments plus `--i-have-owner-approval-reference <text>`) executes them in order and records that text verbatim
without verifying it. **Owner amendment, 2026-11-05 (PROJECT.md section 0.3, D13): the plan has two separately labelled budget conditions of seven runs each,
and `--max-requests` is frozen in every command and in the plan hash.** The plan hash covers the condition labels and roles, the request limit, the run names,
scripts, script seeds, keyset, episodes and frame budget (not the output path). **The plan hash and its run directories go into the pre-registration record
(section 14).** The tool refuses to overwrite an existing out root.

* `idle`: no keys for 120 frames per act, 10 episodes (previously observed to crash at frame 1,293).
* `key-sweep`: each allowed key alone for 20 frames in enumeration order, then no keys for 20 frames, repeating.
* `seeded-random`: script seeds 0–4; 0–2 random keys for 1–120 frames, ignoring the screen.

**Budget conditions (owner amendment, Mission 018).** Both use the study's platform, `keyset.v2` and 8,000-frame episode limit:

1. `matched-1000` (`--max-requests 1000`): the **budget-matched control**. Every game request counts (brief, observe and act). Once the limit is passed,
   further requests are rejected with "request budget exhausted"; the session is not otherwise ended. Any comparison with the AI player uses this condition
   and discloses censoring.
2. `diagnostic-20000` (`--max-requests 20000`): an **extended scripted diagnostic. It is NOT a budget-matched control** and is never substituted for
   `matched-1000`.

Both budgets are reported side by side. A run that the request limit ended before its planned episodes finished (notably `key-sweep`: 8,000 frames at 20
frames per `act` is about 400 `act` requests per episode, so 10 episodes need about 4,000 and a limit of 1,000 is expected to end that run after roughly 2
episodes; this is not yet measured) is reported as `CENSORED_BY_REQUEST_LIMIT`, never as a complete run: `results.py` states planned versus finished
episodes, the limit, the requests used and the partial episode, from the recorded manifests only. A run's condition is stated only when the run log records
it, and a disagreement between the logged condition and the session's recorded limit is reported as a conflict. The wall clock stays at the host default of
3,600 s for baselines (the study limit is 7,200 s, section 6; the baselines are scripted and do not approach either). **No official baselines are authorized by
this text.**

They show what blind input produces and are not controllers. No hand-written landing controller is used. Baselines tune no setting; their summaries go
into the pre-registration commit. The offline demonstration (`offline_demo`) is a pipeline check, not a baseline.

## 10. Stopping rules (one merged list)

**Session ends at the first of:**

1. all episodes finished (smoke: the one episode);
2. the model-call limit (150; smoke 30), retries included;
3. a cap: the worst-case reservation for the next call does not fit the session or cumulative cap;
4. 2 hours wall clock. It is checked **only before each model call** (`_check_limits`), so a session can overrun by up to the 120 s provider timeout plus
   one retry wait of at most 60 s; waits count toward it;
5. 3 consecutive failed provider calls: a timeout at 120 s, a connection error, a malformed 200, or a retried HTTP status. **Statuses retried (listed in
   the code): 408, 409, 429, 500, 502, 503, 504, 529. The working copy checked on 2026-11-05 also retries every other status of 500 or above
   (`status >= 500`), so an unlisted 5xx is treated as a server error and retried, not as an immediate stop.** Any other status ends the session at once
   (rule 15). *Open point for review:* if the intent is that unlisted 5xx statuses end the session, the code differs from that intent and must change;
6. 10 consecutive replies without a valid executable tool call;
7. a provider refusal;
8. the estimated context exceeds 90,000 tokens (before the call), or the provider reports more input than that (after);
9. a reply from a model string other than `claude-haiku-5-5`;
10. a successful reply without usage numbers;
11. reported output tokens above 2,048;
12. an invalid screenshot (checked before any provider call; the player is not shown it);
13. a game reply with fields outside the contract;
14. a request over 20 MB;
15. any other provider rejection (400, 401, 402, 403, 404, 413 and similar; includes the owner's own spend limit; also an unfollowed 3xx, and a 1xx/2xx other
    than 200, which is charged at the worst case);
16. the provider's monthly spend cap (429 `enforced_spend_limit_reached`);
17. the session ends when the referee reports that its game-request budget (1,000 requests) is exhausted.
    **Engineering status:** at the time of this text the code does **not** do this: the referee answers `request budget exhausted` as an error and the gateway
    keeps calling the model. A fix is being made in `model_gateway.py`; *implemented in Mission 017 PR; verify in the PR's test list.* This text does not claim it is verified.

**Do not end the session:** an unexpected stop reason or a reply cut at 2,048 tokens (those calls are not executed); extra calls beyond 8;
calls after an episode has ended (answered `not executed: the episode ended`); the 8,000-frame episode budget (that episode ends as a timeout and
the next begins).

Retries count toward the call limit and the budget. A 429 is recorded at $0; timeouts, connection errors and 5xx/529 are recorded at the
worst case until reconciled. A session never starts if the preflight, runtime-image verification, sandbox launch or referee start fails, or if the
isolation tests do not pass on the pre-registered commit.

## 11. Start conditions (the gate)

All must hold; none is satisfied automatically: `LIVE_CALLS_PERMITTED` set True in a reviewed commit; no `ANTHROPIC_API_KEY`,
`ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_BASE_URL` in the environment; an owner-written authorization file valid at most 7 days, with prices checked within
the previous 7 days (last check 2026-11-05, so it must be redone by about 2026-11-12), bound to the exact configuration hash and a clean checkout at the
named commit; a credential file outside the repository, private to the owner; a live ledger opened with the historical balance; and a person typing the
confirmation at a real terminal. CI must be green on that commit. After a smoke test the flag returns to False unless further sessions are authorized.

## 12. Logging and replay

Everything in the draft §9 (host, player, gateway and referee transcripts, every screenshot, privileged per-frame state, episode receipts, image
digest, versions, upstream and clock hashes, git commit) plus: effort and thinking settings; thinking tokens; provider request IDs; the model string each
reply reports; the configuration hash and tool-schema hash; stop reasons; discarded block types; the hash-chained call transcript; and the ledger
reconciled against the Console. Every episode's referee transcript is replayed in a fresh browser and must reproduce every screenshot. Raw data stays local
(gitignored); summaries and hashes go to the repository.

## 13. Outcomes and analysis

Referee-defined outcomes only (a model's claim never counts): landed (`landed_perfect` if the upstream score added exactly 50 × zone multiplier, else
`landed_hard`), crashed, out of fuel, timeout (8,000 frames), session cut short (any §10 rule before all episodes finish).
Primary: whether any landing occurs; episodes to first landing; landings per episode, shown beside the §9 baselines. Secondary (descriptive): frames per
episode, terminal HUD values from screenshots, actions and keys used (including irrelevant keys), observe/act counts, model calls, tokens including
thinking tokens, cost, wall time, refusals and errors. No inferential statistics and no causal wording (§2).

## 14. Pre-registration record (before the study session)

Committed with the final protocol, configuration and baseline summaries, then no edits: git commit hash; configuration hash; tool-schema hash; runtime-image
digest; platform (OS build); Chromium build; model ID; effort and thinking; keyset; transport (standard-library `http.client`, Python version); caps; number of sessions; price-check date; the baseline `plan_sha256` and run locations (§9); the smoke
test's configuration hash and commit, and the diff from that commit to this one with a reason per change (§8). The record is written by the
owner in PROJECT.md. The smoke test is not pre-registered and is excluded from the study.

## 15. Order of work (proposed)

1. Owner decisions recorded in PROJECT.md (companion file), **including D10 and the study-session-cap sub-decision, before the smoke test**.
2. Scripted baselines recorded under the frozen settings (no tuning).
3. Technical smoke test (excluded; the only model session permitted before pre-registration).
4. Re-record baselines if the re-recording rule applies.
5. Pre-registration commit and record.
6. The single study session.
7. Replay, ledger reconciliation against the Console, full chronological report.

Owner-only actions: Console billing, spend limits, workspace and key; storing the key; the timing of the flag commit; an off-machine backup of raw data.

## 16. Costs (estimates, not measurements)

Inputs: image 1,196 tokens; about 4,800 image tokens per call at 4 images; about 500 tokens of tools and overhead; text history up to about 4,000 tokens in
the smoke test; tokenizer about 2.5 characters per token; thinking disabled, short replies.

* Smoke test (30 calls): about **$0.03** estimated; about **$0.06** reserved by the gateway. The $0.50 cap should not bind.
* Study (150 calls): about **$0.25**, uncertain by a factor of 2–3 (so possibly up to about $0.75), because history grows over the session.
* Worst-case ceiling for one call at the context limit: about $0.01.
* The cumulative cap of $1.00 includes $0.106019 of earlier OpenAI spend; the Console will not show it.

## 17. Limitations

* Nothing has been tested at the real endpoint. TLS, authentication, real replies, usage reporting and billing are unverified until the smoke test.
* Whether the reply's `model` field echoes exactly `claude-haiku-5-5` is unverified; any difference ends the session.
* Whether 5xx/529 failures are billed is undocumented; the ledger assumes the worst case.
* The model may stop early at low effort, may write tool calls as plain text, or may be refused; all are reported results.
* One session on one start: no generalisation. Context growth and the image window are confounded with episode number.
* A provider that reports more input than the estimate could slightly exceed a cap; only the invoice is authoritative.
* Authorization files are unsigned; the terminal confirmation is the safeguard. The Windows ACL check uses SIDs.
* Sandbox limits as in Mission 014 (file-existence oracle; no defence against kernel exploits). Redaction of logs is pattern-based.
* Haiku with thinking disabled and low effort may play worse than the model's capability.

---

## Appendix A. Amendment reconciliation (brief §1, items 1–17)

Provenance: the 17-item list was produced by the Mission 017 design review; the brief that contains it is not in this repository. Each row therefore restates the
contradiction in full and quotes where this candidate resolves it, so that the table can be read on its own.

| # | Contradiction (restated) | Resolution in this candidate |
| --- | --- | --- |
| 1 | Draft §5 said "on current Claude models thinking cannot be turned off", while the draft's own §14 correction said it can | §5: `thinking: {"type": "disabled"}` is the setting and the only one the live gate accepts; the adapter refuses it at effort `xhigh` or `max` and accepts it at `low` |
| 2 | Draft §13 said returned thinking blocks are dropped and never replayed, while §14 said dropping them is unsafe when thinking is on | §5 and §7: with thinking disabled none are expected; if one appears it is logged by type and never replayed or executed |
| 3 | Draft §3 said tool calls over the cap are "dropped and logged"; draft §13 said they get a "fixed error" | §7 and §10: every call is answered; calls over 8 get `not executed: at most 8 tool calls per reply` and are not executed |
| 4 | Draft §5 did not say what happens to later calls in a batch once the episode ends | §7 and §10: later calls are answered `not executed: the episode ended`; the session does not end for that |
| 5 | Draft §8 had seven stopping rules; later additions made the list inconsistent | §10: one merged list of 17 session-ending rules plus call-level cases that do not end the session |
| 6 | The draft said text history is "full" and "never shortened", but replies are cut at 20,000 characters and other edits exist | §7: four disclosed exceptions (20,000-character cut; reply with unusable tool-call IDs replaced by `Use a tool to continue.`; empty text blocks dropped; emptied assistant turns dropped); exceeding the context estimate ends the session |
| 7 | Draft §4 described keyset v2 as future work; it is now built | §4: `keyset.v2` proposed (no `KeyS`); the gateway refuses `keyset.v1` |
| 8 | Draft §2/§12 allowed either OS | §3: Windows on this PC (build 26300), first frame sha256 begins `fbcbb40b641e`; no Mac records are used |
| 9 | Draft §10 selected no model | §5: `claude-haiku-5-5` proposed |
| 10 | Draft §1–§13 never mentioned effort | §5: effort `low`, one value for smoke test and study, recorded in the configuration hash; §8: effort must be identical between smoke test and study; §14: effort is in the pre-registration record |
| 11 | Draft §10 cost inputs (1,229 tokens per image, 600 output tokens, 8,000 history) were stale | §16: 1,196 tokens per image, thinking off, estimates labelled; smoke test about $0.03 estimated / $0.06 reserved |
| 12 | Draft left spend caps as "Owner to set" | §6: $0.50 per session, $1.00 cumulative including $0.106019; sub-decision in the decision record (D10), to be recorded before the smoke test |
| 13 | The draft asked for baselines and pre-registration before any session, but an excluded smoke test must come first | §8 and §15: baselines, smoke test, pre-registration, study, with the re-recording rule |
| 14 | Draft §11 was stale: it said the live transport was still to be built, omitted items from its decision list, and advised using an SDK | §5: transport built (standard-library `http.client`, no SDK); §11: behind a closed gate; §14: thinking, effort, platform and transport are in the pre-registration record |
| 15 | Draft §12's decision list lacked thinking and effort | Decision record D3 (thinking) and D4 (effort) |
| 16 | Draft pre-registration recorded only the commit and the configuration hash | §14: the full list, including baseline plan hash and smoke-test diff |
| 17 | A PROJECT.md line says the protocol is "approved" | This candidate is not approved; nothing is approved; that text is historical and overridden by PROJECT.md §0.5 |

### Code/text mismatch found and fixed in the Mission 017 review

| # | Mismatch | Status |
| --- | --- | --- |
| 18 | The text (draft and earlier candidate) listed "the referee's 1,000-request limit" as a session-ending rule, but the code did not end the session at that limit: the referee answered `request budget exhausted` as an error and the gateway kept calling the model. | §10 rule 17 now states the intended behaviour. Engineering status: implemented in Mission 017 PR; verify in the PR's test list. Not verified by this document. |

## Appendix B. Superseded statements (history only, not active requirements)

* Draft §5: "On current Claude models thinking cannot be turned off." Superseded by §5 above.
* Draft §13: returned thinking blocks are dropped. Superseded by §5 above.
* Draft §3: extra tool calls "dropped and logged"; draft §8's seven-rule list; draft §10's 1,229 image tokens, 600 output tokens and about $0.05 smoke estimate;
  draft §11 item 2 "live transport still to be added". All superseded by the corresponding sections above.
