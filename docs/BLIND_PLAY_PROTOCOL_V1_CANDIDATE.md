**OWNER-APPROVED RESEARCH SETTINGS (2026-11-05, WITH TWO AMENDMENTS) — AMENDMENTS IMPLEMENTED AND INDEPENDENTLY REVIEWED — FINAL TEXT AWAITS OWNER ACCEPTANCE — NOT PRE-REGISTERED — NO EXECUTION AUTHORIZED**

# Blind-play protocol P1 v1 — consolidated text (2026-11-05)

Status: this is the single consolidated text of protocol P1 v1. On 2026-11-05 the owner approved the research settings D1–D15 with two
amendments; the dated record is `PROJECT.md` §0.3 ("P1 v1 owner decisions — 2026-11-05") and the per-decision marks are in
`docs/BLIND_PLAY_V1_OWNER_DECISIONS.md`. That approval is conditional and covers **research settings only**: it authorizes no execution, no
spending, no credential use, no live flag, no pre-registration and no merge. Both amendments are implemented and were independently reviewed (PR #30,
head `e44d149`, CI green on Windows, macOS and Ubuntu; `docs/MISSION_018_OWNER_AMENDMENTS.md`). **The owner has not yet accepted this final consolidated
text**: that needs a dated PROJECT.md entry, and until then this file is not the adopted protocol. Nothing is pre-registered, no official baseline has been
recorded, no model session has been run, and `LIVE_CALLS_PERMITTED` is `False`. `docs/BLIND_PLAY_PROTOCOL_V1_DRAFT.md` stays byte-identical as history, and
PROJECT.md is not changed by this file. Numbers were checked against
`src/rewardbench/blindplay/{contract,model_gateway,live_transport,host,baselines,session}.py` at commit `e44d149` on 2026-11-05; where this text and the
code would differ, the code is authoritative and the difference is listed in Appendix A or reported to the owner.

Sources: the draft (§1–§14), `docs/OFFLINE_AI_GATEWAY.md`, `docs/LIVE_TRANSPORT_PREPARATION.md`, `docs/ISOLATED_PLAYER_RUNTIME.md`.

### Status of each part

Three different things are kept apart: what the owner approved as a research setting, what has been independently verified in code, and what still needs its
own separate authorization. A filled middle column is not permission to act; an approved setting is not permission to spend.

| Part | Owner-approved research setting (conditional; no execution authority) | Independently verified implementation (test or evidence pointer) | Separately authorized action still required |
| --- | --- | --- | --- |
| Model, effort, thinking, platform (D3–D6) | `claude-haiku-5-5`; effort `low`; thinking `disabled`; Windows on this PC (build 26300) | Gate accepts only `thinking: disabled`; adapter and request-field tests in `tests/blindplay/test_live_transport.py`; isolation tests on Windows (`docs/ISOLATED_PLAYER_RUNTIME.md`). Real endpoint never tested | Owner accepts the final text; a smoke-test authorization names the exact configuration hash |
| Keyset (D2) | `keyset.v2` (11 keys, no `KeyS`) | Gateway refuses `keyset.v1` (`contract.py`, gateway tests); the plan uses `keyset.v2` | None beyond the acceptance of the final text |
| Smoke test (D7, D8) | One excluded technical episode, at most 30 model calls, before pre-registration | Limits are `GatewayConfig` fields, tested offline against a loopback mock only | Owner-only items (D15), billing, a reviewed live-flag commit, an authorization file, a typed terminal confirmation, and a separate approval for every attempt |
| Study (D9) | One session, 10 episodes, at most 150 model calls, 8,000 frames per episode | Same limits, tested offline against a mock only | Pre-registration (§14), the smoke-test outcome, billing, the flag, and a separate approval to run |
| Spend caps (D10) | Smoke test $0.50; cumulative $1.00 including $0.106019 (opening balance; $0.893981 remains); study session cap = remaining reconciled cumulative balance at launch | Reservation before every call and session and cumulative caps tested offline (`tests/blindplay/test_model_gateway.py`, `test_spend_ledger.py`, mutation check 60/60 at Mission 018). Console limits untested | Every actual expenditure approved separately, with provider-side (Console) caps set by the owner |
| Stopping rules (D11) | The merged rules of §10 including the 20,000-character reply cut | Rule 17 (game-request limit): `test_the_referees_request_budget_error_ends_the_session_with_no_further_model_call` (`tests/blindplay/test_audit_017_live.py`, Mission 017). The other rules have offline tests | None beyond acceptance of the final text |
| History policy (D11) | Last 4 screenshots as images; full text history with the four disclosed exceptions (§7); no memory across sessions | Gateway tests of the image window, history edits and context limit | None beyond acceptance of the final text |
| Change rule and smoke-test repeats (D12) | §8: technical defects only; at most two excluded smoke-test attempts, each separately approved | A rule of procedure; no code enforces who approves | A separate approval for each attempt |
| Scripted baselines (D13, amended) | Two conditions of seven runs: `matched-1000` and `diagnostic-20000` (§9) | `--max-requests` in every command and the plan hash; censoring and condition-conflict reporting in `results.py`; `tests/blindplay/test_baselines.py`, `test_results.py`; plan hash recomputed 2026-11-05 on `e44d149`. **No official baseline has been recorded** | An owner authorization to record them (the text in `docs/BASELINE_EXECUTION_CARD.md`), given after the owner accepts the final text |
| Credential file allowlist (amendment 1) | Fail-closed allowlist of the owner's SID plus narrowly justified principals | Implemented in Mission 018 and independently reviewed; real-file tests including another specific user SID (`tests/blindplay/test_audit_017_live.py`, `test_live_transport.py`). Never run against a real key | The owner creates and stores a real key (D15); no key exists |
| Transport (D14) | Python standard-library `http.client`, no SDK | Verified against a loopback mock server only; no real, test or token-counting request has been made | The reviewed flag commit and the whole gate of §11 |
| Pre-registration | Not covered by the approval | Not done | The owner's dated record (§14), after the baselines and the smoke test |

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

## 3. Platform and environment (owner-approved research setting; conditional, no execution authority)

| Item | Approved research value |
| --- | --- |
| Environment | `apollolander-upstream-fixed-start`, upstream `0da09dc`, SHA-256-pinned; seed 0; the reserved cohorts are not used |
| Platform | Windows on this PC (Windows 11 build 26300, newer than Mission 014's build), isolated runtime in an AppContainer with a Job Object |
| Recorded at pre-registration | OS build, Chromium build, runtime-image digest, container SID, browser/Playwright/Python versions |
| First screenshot | frame sha256 begins `fbcbb40b641e` (Windows). macOS records (`aa31f5af16ad…`) are not on this PC and are not used |
| Each episode | fresh browser context, unmodified game, 2 title frames, referee click, 4 playing frames; 60 outcome frames after a terminal state; the player cannot reset early |
| Deviations from the live game | as written to every `session.json` (virtual clock, seeded RNG, muted audio, fresh game per episode, title screen not shown) |

The platform is fixed for smoke test, baselines and study, and never mixed within a comparison.

## 4. Game and keyset (owner-approved research setting; conditional, no execution authority)

Keys offered: **`keyset.v2`**, alphabetical, no meanings given: ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Enter, Escape, KeyA, KeyD, KeyW,
ShiftLeft, Space (11 keys). `keyset.v1` additionally holds `KeyS`, which triggers the upstream developer speed mode (4 physics updates
per frame, `// SPEED MODE!`). `keyset.v2` omits it so that frame budgets mean the same game time for every action; the deviation is recorded
as "upstream developer speed mode not offered". Several offered keys do nothing in this game; finding out which is part of the task. The
gateway refuses `keyset.v1`; `keyset.v1` stays frozen for replaying earlier sessions. Protocol string `react.blindplay.player.v2`.

## 5. Model, API and configuration (owner-approved research setting; conditional, no execution authority)

| Setting | Approved research value |
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

## 6. Budgets and caps (owner-approved research setting; conditional, no execution authority)

Defaults in `GatewayConfig` equal the P1 values below (the source comment still calls them "proposals"; the owner approved them as research settings); all are fixed for a session and hashed (`config_sha256`).

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
deliberately high (about 2 characters per token, 1,600 tokens per image, plus 256). Owner-approved research settings for the caps (D10,
`PROJECT.md` §0.3, 2026-11-05; limits, **not** spending authorization): **$0.50 for the smoke test** and **$1.00
cumulative including the $0.106019 already recorded on OpenAI** (opening balance; $0.893981 remains). The **study session cap is the remaining
reconciled cumulative balance at launch**, not a fixed $0.50, and never more than the cumulative cap (the gateway refuses a session cap above the cumulative cap).
**The D10 study-session-cap sub-decision is RESOLVED** (`docs/BLIND_PLAY_V1_OWNER_DECISIONS.md`): it was fixed before any smoke test, so no cap is chosen after seeing the smoke test's cost (§8).
**Every actual expenditure needs its own explicit owner approval and provider-side caps**: the provider Console spend limits
(organization and workspace) are the independent backstop, and the owner sets them. The ledger for each later session must open with a
balance that includes the then-reconciled earlier spend.

## 7. What the model sees, and memory (owner-approved research setting; conditional, no execution authority)

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
* **Repeating a failed smoke test (owner-approved research setting, PROJECT.md §0.3 D11–D12):** at most **two excluded smoke-test attempts**, each requiring
  its own separate execution approval; every attempt is excluded from the study analyses and reported in full; the spend of every attempt counts toward the
  cumulative cap under the same aggregate budget. A repeat is allowed only after a recorded technical defect was fixed, and the fix is documented and reviewed.

**Study.** One session, 10 episodes, all budgets of §6, pre-registered (§14) before it starts. Not stopped on success; not restarted to obtain
a better result; nothing edited mid-session; every session is reported.

## 9. Scripted baselines (non-AI, $0)

Recorded through the same isolated host, keyset and platform, before the smoke test and under settings that must not be tuned. **No official baseline has been
recorded and none is authorized by this text.** The owner's separate authorization, and the exact procedure, are in `docs/BASELINE_EXECUTION_CARD.md`.

**Exact configuration.** `keyset.v2`; **game seed 0** (`--seed 0`, the fixed start); **10 episodes; 8,000 frames per episode**. The word "seed" means two things: the game seed
is 0 for every run, while **script seeds 0–4 exist only for `seeded-random`** (`--script-seed`; `idle` and `key-sweep` use script seed 0, which they do not consume). The frame length per
`act` is set by each script (`idle` 120; `key-sweep` 20; `seeded-random` 1–120).

**Plan.** `python -m rewardbench.blindplay.baselines plan --keyset keyset.v2 --out-root <dir that does not exist>` prints every host command and a `plan_sha256` and
writes nothing. There are **14 runs = 2 budget conditions x 7 runs** (`idle`; `key-sweep`; `seeded-random` script seeds 0, 1, 2, 3, 4). **`--max-requests` is in every command** (1000 for
`matched-1000`, 20000 for `diagnostic-20000`) and in the plan hash. Recomputed 2026-11-05 on `e44d149`:

`plan_sha256 bb527a18a5ad88e82769ee800d97b2bfe8c9de73d856be688024e0286d6922dd`

The hash covers the schema, the condition labels and roles, the request limit, run names, scripts, script seeds, keyset, game seed, episodes and frame budget; it does **not** cover the output path.
Run directories are named `<condition>_<NN>_<script>[_seedK]` exactly as the plan prints them, for example `matched-1000_01_idle`, `matched-1000_02_key-sweep`,
`matched-1000_03_seeded-random_seed0` ... `matched-1000_07_seeded-random_seed4`, and the same seven under `diagnostic-20000_`.

**`run`** (same arguments plus `--i-have-owner-approval-reference <text>`) executes the 14 commands in order, stops at the first failing command, and records the supplied text verbatim in
`OWNER_APPROVAL_REFERENCE.txt` **without verifying it**: the tool grants no approval. It **refuses without an approval reference, never overwrites (an existing out root is refused) and
refuses an out root inside an existing official-looking directory that holds files** (a parent named `runs` or containing `blind-visual`; in a checkout whose `runs/` already holds data, an out
root under `runs\` is therefore refused). It writes `baseline_plan.json`, a `baseline_condition.json` in each run directory, and `baseline_run_log.json`. **The plan hash and the run locations go into
the pre-registration record (§14).**

* `idle`: no keys for 120 frames per act, 10 episodes (a Mission 014 record under the earlier keyset shows a crash at frame 1,293; not re-measured under `keyset.v2`).
* `key-sweep`: each allowed key alone for 20 frames in enumeration order, then no keys for 20 frames, repeating.
* `seeded-random`: script seeds 0–4; 0–2 random keys for 1–120 frames, ignoring the screen.

**Budget conditions (owner amendment 2026-11-05, PROJECT.md §0.3 D13; implemented and reviewed in Mission 018).** Both use the study's platform, `keyset.v2` and 8,000-frame episode limit:

1. `matched-1000` (`--max-requests 1000`): the **budget-matched control**. Every game request counts (brief, observe and act). Once the limit is passed, further requests are rejected with
   "request budget exhausted". For the **scripted baseline player this means it exits on the first rejected request**; an **AI session is ended by the gateway with stop reason `game_request_limit`**
   (rule 17, §10). **Any comparison between an AI session and the baselines must use `matched-1000` and must disclose censoring.**
2. `diagnostic-20000` (`--max-requests 20000`): an **extended scripted diagnostic. It is NOT a budget-matched control**, is never substituted for `matched-1000`, and is never used as the
   comparison for the AI session.

Both budgets are reported side by side.

**Censoring and conflicts (`results.py`).** A run that the request limit ended before its planned episodes finished is reported as **`CENSORED_BY_REQUEST_LIMIT`**, is counted INCOMPLETE and is never presented as a
complete run: the report states planned versus finished episodes, the limit, the requests used and the partial episode, from recorded manifests only (`unavailable` where the record lacks it). A run's
condition is stated only when `baseline_condition.json`/the run log records it, and a disagreement between the logged condition and the session's recorded request limit is reported as **`CONFLICT`**.

**What censoring is expected to look like, and what is measured.** An earlier arithmetic expectation ("about 400 `act` requests per episode, about 4,000 for 10 episodes, censored after roughly 2 episodes") was
**wrong** and is withdrawn: 8,000 frames at 20 frames per `act` is 400 requests only if an episode lasts the full budget, but episodes end when the rocket crashes. One disposable, non-study measurement
(scratchpad run, **not an official baseline and not a result**): `key-sweep`, `keyset.v2`, game seed 0, **one episode**, 8,000-frame budget, host `--max-requests 20000`: the episode **crashed at frame 1,749
after 90 game requests (89 observations) in 6.6 s of wall time**. If the other nine episodes behave like that one, a 10-episode `key-sweep` would need roughly 900 requests, which is **close to, but not clearly
over, 1,000**. This is measured on **one episode only**; the other nine episodes and the other scripts are **unmeasured**, so whether any run is censored at 1,000 requests is not known. Censoring will be reported from
the recorded data, not predicted. Wall-clock time is not a concern (about 7 s per such episode). The wall clock stays at the host default of 3,600 s for baselines (the study limit is 7,200 s, §6).

**The runs are not independent samples (code read in Mission 019; nothing was executed to check the expectations marked "expected").** Verified in `player_runtime/runtime.py`: a scripted player creates its
`random.Random(script_seed)` and its `key-sweep` step counter once per run and never resets them at an episode boundary, so the key-sweep cycle position and the seeded-random stream **carry across
episodes**; `idle` has no state. Verified in `session.py`/`referee.py`: each episode is a fresh browser context with the same game seed and a fixed start. Expected from that (not run): all 10 `idle`
episodes are identical to one another; each `key-sweep` and `seeded-random` episode differs from the next only through the carried-over script state; and each `matched-1000` run is a deterministic prefix
of the corresponding `diagnostic-20000` run (same script, script seed, keyset and game seed; only the request limit differs), so the two conditions are **not replicates**. Consequently results are
reported **per run**; runs and episodes are **never pooled** as n=70 or n=140, and the two conditions are never treated as independent replicates of each other.

**Comparison metric under censoring (pre-specified).** For each run: landings / finished episodes, reported together with planned versus finished episodes and requests used; **never extrapolated to 10
episodes**.

**Timing measurement disclosure.** Episode 1 of key-sweep is deterministic (game seed 0, fixed start, step counter from 0), so this disposable episode is expected to be identical to episode 1 of both official key-sweep runs. It was observed before authorization; no setting changed after it, and the frozen plan hash comes from code at `e44d149`, which predates the observation. The scratch data was not kept in the repository.

**Wall clock.** `--max-wall-seconds` is **not part of the plan hash**; the baselines use the host default of 3,600 s, fixed only by the commit.

They show what blind input produces and are not controllers. No hand-written landing controller is used. Baselines tune no setting; their summaries go into the pre-registration commit. The offline
demonstration (`offline_demo`) is a pipeline check, not a baseline.

## 10. Stopping rules (one merged list)

**Session ends at the first of:**

1. all episodes finished (smoke: the one episode);
2. the model-call limit (150; smoke 30), retries included;
3. a cap: the worst-case reservation for the next call does not fit the session or cumulative cap;
4. 2 hours wall clock. It is checked **only before each model call** (`_check_limits`), so a session can overrun by up to the 120 s provider timeout plus
   one retry wait of at most 60 s; waits count toward it;
5. 3 consecutive failed provider calls: a timeout at 120 s, a connection error, a malformed 200, or a retried HTTP status. **Statuses retried (listed in
   the code): 408, 409, 429, 500, 502, 503, 504, 529. The code at `e44d149` also retries every other status of 500 or above
   (`status >= 500` in `model_gateway.py`), so an unlisted 5xx is treated as a server error and retried (charged at the worst case), not as an immediate stop; this text matches the code.** Any other status ends the session at once
   (rule 15);
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
17. the session ends, with stop reason `game_request_limit`, when the referee reports that its game-request budget (1,000 requests) is exhausted.
    **Engineering status:** implemented in `model_gateway.py` (`record_game` raises `stop("game_request_limit")` on the referee's `request budget exhausted` error) in Mission 017
    and verified by `test_the_referees_request_budget_error_ends_the_session_with_no_further_model_call` (`tests/blindplay/test_audit_017_live.py`), which asserts that no further model call is made.
    The match is on the referee's message text (a shared constant in `contract.py` would be sturdier; not changed).

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
named commit; a credential file outside the repository, private to the owner and checked by a **fail-closed allowlist** on Windows (see below); a live ledger opened with the historical balance; and a person typing the
confirmation at a real terminal. CI must be green on that commit. After a smoke test the flag returns to False unless further sessions are authorized.

**Credential-file check (owner-approved amendment 1, implemented in Mission 018 and independently reviewed).** On Windows the file passes only if the current user's SID is read from the
process token, the file's owner is that SID, SYSTEM or Administrators, the DACL exists, is not NULL and parses completely, and every allow-type entry names only the current user, SYSTEM,
Administrators or OWNER RIGHTS. Every other principal, ACE type, alias, group, service account or AppContainer is refused, as is any failure to read the ACL, owner or current SID. The SDDL aliases
`LA`/`LG` (built-in Administrator RID 500, Guest RID 501) are accepted only when they are the current user's own account. The file is re-checked after it is read. This replaced the earlier
deny-list. It is tested on real files, including one shared with another specific user's SID, and has never run against a real key (`docs/MISSION_018_OWNER_AMENDMENTS.md`).

## 12. Logging and replay

Everything in the draft §9 (host, player, gateway and referee transcripts, every screenshot, privileged per-frame state, episode receipts, image
digest, versions, upstream and clock hashes, git commit) plus: effort and thinking settings; thinking tokens; provider request IDs; the model string each
reply reports; the configuration hash and tool-schema hash; stop reasons; discarded block types; the hash-chained call transcript; and the ledger
reconciled against the Console. Every episode's referee transcript is replayed in a fresh browser and must reproduce every screenshot. Raw data stays local
(gitignored); summaries and hashes go to the repository.

## 13. Outcomes and analysis

Referee-defined outcomes only (a model's claim never counts): landed (`landed_perfect` if the upstream score added exactly 50 × zone multiplier, else
`landed_hard`), crashed, out of fuel, timeout (8,000 frames), session cut short (any §10 rule before all episodes finish).
Primary: whether any landing occurs; episodes to first landing; landings per episode, shown beside the §9 baselines **per run, using the §9 metric under censoring (landings / finished episodes, with planned versus finished episodes and requests used; never extrapolated, never pooled across runs or episodes)**. Secondary (descriptive): frames per
episode, terminal HUD values from screenshots, actions and keys used (including irrelevant keys), observe/act counts, model calls, tokens including
thinking tokens, cost, wall time, refusals and errors. No inferential statistics and no causal wording (§2).

## 14. Pre-registration record (before the study session)

Not done, and not authorized by anything so far. Committed with the final protocol, configuration and baseline summaries, then no edits. The record **must include**: the git
commit hash; the baseline **`plan_sha256`** (§9) and the run locations; the **baseline summary hashes** (the hash of each run's results summary and of `baseline_plan.json`/`baseline_run_log.json`); the
**tool-schema hash** (`tools_sha256`); the **configuration hash** (`config_sha256`); the **runtime-image digest**; the **platform build** (OS build); the **Chromium build**; the **model ID**; effort and thinking;
keyset; transport (standard-library `http.client`, Python version); the **caps**; the **session count**; the price-check date; and the smoke test's configuration hash and commit, with the diff from that
commit to this one and a reason per change (§8). The record is written by the owner in PROJECT.md. The smoke test is not pre-registered and is excluded from the study.

## 15. Order of work (owner-approved research setting; conditional, no execution authority)

1. Owner decisions: recorded in PROJECT.md §0.3 on 2026-11-05 (research settings, including D10 and its sub-decision). **Still needed:** the owner's dated acceptance of this final text.
2. Scripted baselines recorded under the frozen settings (no tuning), after a separate owner authorization (`docs/BASELINE_EXECUTION_CARD.md`). They cost $0 and use no API or credential.
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
* Authorization files are unsigned; the terminal confirmation is the safeguard. The Windows credential-file check is a fail-closed SID allowlist (§11); it does not expand group membership and has never run on a real key.
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
| 7 | Draft §4 described keyset v2 as future work; it is now built | §4: `keyset.v2` (no `KeyS`), owner-approved research setting; the gateway refuses `keyset.v1` |
| 8 | Draft §2/§12 allowed either OS | §3: Windows on this PC (build 26300), first frame sha256 begins `fbcbb40b641e`; no Mac records are used |
| 9 | Draft §10 selected no model | §5: `claude-haiku-5-5`, owner-approved research setting (D5) |
| 10 | Draft §1–§13 never mentioned effort | §5: effort `low`, one value for smoke test and study, recorded in the configuration hash; §8: effort must be identical between smoke test and study; §14: effort is in the pre-registration record |
| 11 | Draft §10 cost inputs (1,229 tokens per image, 600 output tokens, 8,000 history) were stale | §16: 1,196 tokens per image, thinking off, estimates labelled; smoke test about $0.03 estimated / $0.06 reserved |
| 12 | Draft left spend caps as "Owner to set" | **Resolved (superseded wording).** Owner approved on 2026-11-05 (PROJECT.md §0.3 D10): smoke test $0.50; cumulative $1.00 including $0.106019; study session cap = remaining reconciled cumulative balance at launch; each expenditure separately approved. §6 states this. The earlier "to be recorded before the smoke test" is satisfied |
| 13 | The draft asked for baselines and pre-registration before any session, but an excluded smoke test must come first | §8 and §15: baselines, smoke test, pre-registration, study, with the re-recording rule |
| 14 | Draft §11 was stale: it said the live transport was still to be built, omitted items from its decision list, and advised using an SDK | §5: transport built (standard-library `http.client`, no SDK); §11: behind a closed gate; §14: thinking, effort, platform and transport are in the pre-registration record |
| 15 | Draft §12's decision list lacked thinking and effort | Decision record D3 (thinking) and D4 (effort) |
| 16 | Draft pre-registration recorded only the commit and the configuration hash | §14: the full list, including baseline plan hash and smoke-test diff |
| 17 | A PROJECT.md line says the protocol is "approved" | **Resolved / superseded.** That line (PROJECT.md line 93, historical plan header: "public v1 released; blind visual-gameplay protocol approved, implementation pending") is historical and overridden by §0.5. The accurate status is the dated PROJECT.md §0.3 entry of 2026-11-05: research settings approved with two amendments, final text not yet accepted, nothing pre-registered, no execution authorized |

### Code/text mismatch found and fixed in the Mission 017 review

| # | Mismatch | Status |
| --- | --- | --- |
| 18 | The text (draft and earlier candidate) listed "the referee's 1,000-request limit" as a session-ending rule, but the code did not end the session at that limit: the referee answered `request budget exhausted` as an error and the gateway kept calling the model. | **Resolved.** §10 rule 17 states the behaviour; it is implemented and verified by `test_the_referees_request_budget_error_ends_the_session_with_no_further_model_call` (`tests/blindplay/test_audit_017_live.py`) |

## Appendix B. Superseded statements (history only, not active requirements)

* Draft §5: "On current Claude models thinking cannot be turned off." Superseded by §5 above.
* Draft §13: returned thinking blocks are dropped. Superseded by §5 above.
* Draft §3: extra tool calls "dropped and logged"; draft §8's seven-rule list; draft §10's 1,229 image tokens, 600 output tokens and about $0.05 smoke estimate;
  draft §11 item 2 "live transport still to be added". All superseded by the corresponding sections above.
