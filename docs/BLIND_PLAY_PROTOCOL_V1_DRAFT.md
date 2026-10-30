# Blind-play protocol v1 — DRAFT for owner review

**Status (2026-10-27, amended 2026-10-28 for the macOS backend — see §12 — and 2026-10-30 for `keyset.v2` and the model
gateway — see §13): DRAFT. Not approved, not pre-registered, not executed.** Nothing in this document selects a
model, authorizes an API key, or approves spending. Every value marked *proposed* is a recommendation for the owner
to accept, change or reject. Prepared in Mission 014 on top of the isolated runtime (`docs/ISOLATED_PLAYER_RUNTIME.md`)
and the Mission 013 environment (`docs/BLIND_VISUAL_FOUNDATION.md`), following PROJECT.md section 20.

## 1. Question and claim limits

Can a vision-capable model, told only **"Land the rocket."**, land the original ApolloLander by looking at
screenshots and pressing keyboard keys, and does its behaviour change across attempts within one session?

Pilot **P1** is a feasibility case study: one fixed start, one session per approved model. It cannot support claims
about model families, generalisation, or feedback effects (PROJECT.md 20.6–20.8). Every session is reported,
including crashes, refusals, errors and sessions with no landing.

## 2. Environment and start (fixed)

| Item | Value |
| --- | --- |
| Environment | `apollolander-upstream-fixed-start` (PROJECT.md 20.3 A), upstream `0da09dc`, SHA-256-pinned |
| Seed | 0 (fixed start). The reserved cohorts 1000000–1000007 and 2000000–2000015 are **not used** |
| Start | Every episode: fresh browser context, unmodified game, 2 title frames, referee click, 4 playing frames; first screenshot is always frame `fbcbb40b641e…` on Windows, `aa31f5af16ad…` on macOS (same physics, different text rasterization) |
| Platform | **Fixed at pre-registration** (one OS, OS version, Chromium build and runtime-image digest for the whole study); never mixed within a comparison |
| Reset | Automatic. After a terminal state the referee shows 60 more frames (the authentic outcome screen); the next `observe`/`act` starts the next episode. The player cannot reset early |
| Deviations from the live game | As recorded in every `session.json` (virtual clock, seeded RNG, muted audio, fresh game per episode, title screen not shown) |
| Isolation | Windows AppContainer or macOS Seatbelt runtime (Mission 014); host refuses to start if any check fails |

## 3. Budgets (*proposed*)

| Limit | P1 value | Notes |
| --- | --- | --- |
| Episodes per session | **10** | Section 20.6 allowed up to 20; 10 keeps cost near the owner's stated scale |
| Frames per `act` | **1–120** | Unchanged contract cap |
| Simulated frames per episode | **8,000** (133 s of game time) | Unchanged; idle descent crashes at frame 1,293 |
| Model calls per session | **150** | Hard stop in the host |
| Tool calls per model reply | **≤ 8** (extra calls dropped and logged) | Host-enforced; each is validated like any other request |
| Game requests per session | **1,000** | Referee `max_requests` |
| Screenshots per model call | **4** (the most recent; older ones replaced by a text note) | Host-enforced |
| Wall-clock per session | **2 hours** | Host-enforced |
| Spend per session / cumulative | **Owner to set** | Host stops *before* a call whose worst-case cost would exceed a cap (`docs/OFFLINE_AI_GATEWAY.md`, Money) |
| Output tokens per model call | **2,048** (added 2026-10-30) | Sets the worst-case cost; a reply cut off here is not executed |
| Estimated context per model call | **90,000 tokens** (added 2026-10-30) | The estimate is a deliberate overestimate; history is never silently shortened, the session stops instead |

## 4. Permitted inputs and the upstream `S` key

*Proposed since 2026-10-30:* the player may press any subset of **`keyset.v2`** (alphabetical, no meanings given):
ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Enter, Escape, KeyA, KeyD, KeyW, ShiftLeft, Space. Several do nothing in this
game; finding out which is part of the task. `keyset.v2` is built and tested but **still needs owner approval**; the
gateway accepts only it. `keyset.v1` (the same plus KeyS) remains frozen for replaying earlier sessions.

**`KeyS` needs an owner decision.** Upstream `game.js` `checkKeys()` contains `// SPEED MODE!` — while `S` is held,
`lander.update()` runs 3 extra times per frame (4× physics). It is an undocumented developer feature: nothing on screen
mentions it. Consequences: one `act` of 120 frames can advance 480 physics updates; an 8,000-frame episode budget can
cover up to 32,000 updates. Options:

| Option | Effect | Cost of choosing it |
| --- | --- | --- |
| **A. Keep `keyset.v1` unchanged** | Most faithful to the original controls; S use is recorded per act and reported | Frame budgets no longer measure game time uniformly; a model that holds S plays a different, faster game |
| **B. `keyset.v2` = `keyset.v1` without `KeyS`** (*recommended for P1*) | Frame and time budgets mean the same thing for every action; the remaining 11 keys still include non-functional distractors | A versioned contract change (`keyset.v2`), its tests and re-verification **before** pre-registration; deviation recorded as "upstream developer speed mode not offered" |

Either way the choice is fixed before the first session and never changed mid-study.

## 5. What the AI sees and remembers

**Sent to the model on every call** (exactly; logged in `gateway_transcript.jsonl`):

* System text: `Land the rocket.`
* Two tools, verbatim from `contract.V2.tools`: `observe` ("Return the current game screen as an image. Does not
  advance the game.") and `act` ("Press and hold the listed keys (none, one or several) for the given number of game
  frames, then release them, and return the game screen. The game is paused between calls; it runs at 60 frames per
  second of game time."), with the key enumeration and `1 ≤ frames ≤ 120`.
* First user message: `Land the rocket.` plus the first screenshot.
* After each tool call: a tool result containing the procedural counters (`episode`, `episode_frame`,
  `episode_frame_budget`, `max_episodes`, `frames_advanced`, `episode_ended`, `session_over`) and the new screenshot
  (1280×720 PNG). Everything about the game (score, time, fuel, altitude, velocities, outcome messages) comes only from
  the authentic on-screen HUD.
* If a reply contains no tool call, the host adds the fixed procedural text `Use a tool to continue.` (disclosed
  here; it carries no strategy).
* A rejected tool call is answered with a fixed or contract-generated error (the full list is in
  `docs/OFFLINE_AI_GATEWAY.md`). None describes the game.

**Never sent:** control mappings, physics, rules, scores beyond the screen, referee state, previous sessions, other
models' results, any hint after failure. No provider-side tools (web search, code execution, memory) are enabled.

**Memory (*proposed*):**

* *Within a session (all episodes):* one continuous conversation. The full text history — the model's own visible
  messages, its tool calls, and the counters — is kept; only the last 4 screenshots are sent as images, older ones
  become `[earlier screenshot omitted]`. So the model can remember what it tried in earlier episodes in its own words.
* *Across sessions:* nothing. New conversation, container storage wiped (macOS: the sandbox has no writable storage at all), no provider memory features, no notes
  carried over. Prompt caching (if used) is a billing feature, not memory.
* Hidden reasoning is not requested, stored or sent back; only what the model visibly returns. On current Claude models
  thinking cannot be turned off and is still billed; see §13.

## 6. Outcomes

| Outcome | Definition (referee only; a model's claim never counts) |
| --- | --- |
| **Success: landed** | Upstream `gameState` LANDED; `landed_perfect` if the upstream score added exactly 50 × the zone multiplier, otherwise `landed_hard` |
| Failure: crashed | Upstream CRASHED (including the native "LUNAR MODULE DESTROYED" screens) |
| Failure: out of fuel | Upstream GAMEOVER |
| Failure: timeout | 8,000 frames used without a terminal state |
| Session cut short | Any stopping rule in §8 before all episodes finished; unfinished episodes are reported as such |

Primary: whether any landing occurs; episodes to first landing; landings / episodes. Secondary (descriptive): frames
per episode, terminal HUD values (from the screenshot), actions and keys used per episode (including irrelevant
keys and, under option A, `S`), observe/act counts, model calls, tokens, cost, wall time, refusals and errors.
Behaviour change is described episode by episode, with no causal claim (n = 1 per model).

## 7. Scripted baselines (NON-AI, $0, run before any model session)

Through the same isolated host, the same budgets and keyset:

* `idle` (no keys, 10 episodes): known to crash at frame 1,293 every time.
* `key-sweep` (each key alone for 20 frames, cycling).
* `seeded-random` with script seeds 0–4 (0–2 random keys for 1–120 frames).

Reported as landing rates and frame distributions next to the model's. They show what blind input produces; they
are not controllers and never look at the screen. No hand-written landing controller is used as a baseline.

## 8. Stopping rules (predeclared)

A session ends at the first of:

1. all episodes finished; 2. 150 model calls; 3. the spend cap (checked before each call against the worst-case
cost of that call); 4. 2 hours wall-clock; 5. 3 consecutive gateway/provider errors; 6. 10 consecutive model
replies without a valid tool call; 7. a provider refusal that ends the turn.

A session never starts if: the credential preflight, runtime-image verification, sandbox launch or referee start
fails, or the isolation tests do not pass on the pre-registered commit.

The session is **not** stopped early on success (all episodes are played to measure consistency), not restarted to
get a better result, and nothing (budgets, keys, prompts, model, start) is changed mid-session.

## 9. Logging and reproducibility

Already implemented and tested: host transcript (every player line), player stderr, gateway transcript (exactly
what the model received, images by sha256, and its replies), referee transcript, every screenshot, privileged
per-frame referee state, episode receipts, runtime-image digest, container SID, browser/Playwright/Python versions,
upstream and clock hashes, git commit. Deterministic replay re-runs the referee transcript in a fresh browser and must
reproduce every screenshot. Since 2026-10-30 the gateway also records, tested with a mocked provider only: provider
request IDs, the model string each reply reports, token usage and computed cost per call, refusal/stop reasons, a
hash-chained call transcript, the configuration hash and the tool-schema hash. Raw data stays local (gitignored);
summaries and hashes go to the repository.

## 10. Model options and approximate cost (for owner review — none selected)

Prices per million tokens. Sources: repository catalog `pricing_2026-10-14.json` (verified 2026-10-15 against the
providers' pricing pages) for OpenAI, Google and Claude Haiku 5.5; Anthropic's model table (cached 2026-10-06) for
Claude Sonnet 5.5, Opus 5.5 and Fable 5.1. **Re-verify on the providers' pricing pages before approving.**

Assumptions per model call: ~600 tokens of system + tools; up to 4 screenshots; text history averaging ~8,000 tokens;
~600 output tokens (visible text, tool call and any thinking). Claude counts an image at roughly
width × height / 750 ≈ **1,229 tokens** for 1280×720 (estimate; to be confirmed with the token-counting endpoint once
a key use is approved). OpenAI and Google count image tokens differently (not verified here); the same ~1,230 per
image is assumed for comparability. Average input ≈ **13,500 tokens/call**.

| Model (vision input required) | $ in / out per 1M | Smoke test: 1 episode, 30 calls | P1 session: 10 episodes, 150 calls |
| --- | --- | --- | --- |
| Claude Haiku 5.5 (`claude-haiku-5-5`) | 0.10 / 0.50 | ≈ $0.05 | ≈ $0.25 |
| Google Gemini 3.1 Flash-Lite | 0.25 / 1.50 | ≈ $0.13 | ≈ $0.64 |
| OpenAI GPT-5.4 mini (used in Missions 010/012) | 0.75 / 4.50 | ≈ $0.38 | ≈ $1.92 |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`) | 2.00 / 10.00 | ≈ $0.99 | ≈ $4.95 |
| OpenAI GPT-5.4 | 2.50 / 15.00 | ≈ $1.28 | ≈ $6.41 |
| Claude Opus 5.5 (`claude-opus-5-5`) | 4.00 / 20.00 | ≈ $1.98 | ≈ $9.90 |
| Claude Fable 5.1 (`claude-fable-5-1`) | 10.00 / 50.00 | ≈ $4.95 | ≈ $24.75 |

Formula: calls × (13,500 × input price + 600 × output price) / 1,000,000. Treat these as ±2–3×: thinking-heavy models
can produce far more output tokens, and history grows within a session. Context: recorded project spend so far is
$0.106019; the owner has mentioned roughly $1 for exploring R.E.A.C.T. Within that scale, a full P1 session fits only
the cheapest options; the larger models fit a smoke test at most. Vision support and tool calling for the Google and
OpenAI entries must be confirmed before choosing them.

## 11. Exact requirements before the first authorized AI session

1. **Owner decisions:** accept or amend this protocol; the `S` option (§4); the model, provider and exact model ID;
   per-session and cumulative spend caps; the number of sessions; smoke test or full P1.
2. **Provider gateway:** built and verified offline on 2026-10-30 (`docs/OFFLINE_AI_GATEWAY.md`). **Still to add, with
   owner approval:** a live transport with credentials read by the host from host-only storage (never
   `setx`/`HKCU\Environment`, which the Windows sandbox can read; on macOS a host-only file or the login keychain,
   both unreadable from the Seatbelt sandbox), and enabling live calls.
3. `keyset.v2` (option B): implemented and tested on 2026-10-30; owner approval outstanding.
4. Provider-side spending limit configured by the owner.
5. Record the §7 scripted baselines through the isolated host with the final settings.
6. **Pre-register:** commit the final protocol, host configuration and gateway code; record the commit hash and
   configuration hash in PROJECT.md before the first call; no edits afterwards.
7. Run the approved sessions, replay each referee session, publish the full chronological results (all episodes,
   all sessions) with hashes; raw data stays local.

Varied starts, held-out evaluation, feedback ablations and cross-model comparisons (PROJECT.md 20.8) are separate,
later protocols.

## 12. Amendments 2026-10-28 (macOS backend; still a draft)

* A macOS Seatbelt backend exists and passed the same attack suite (`docs/ISOLATED_PLAYER_RUNTIME.md`). Either
  platform may host P1, but only one, recorded in the pre-registration (§2 Platform).
* Added the host's existing per-reply tool-call cap (8) to §3; nothing else in the budgets changed.
* Owner decisions are unchanged and still open: accept/amend P1; `S` option A or B (B recommended); model,
  provider, model ID; spend caps; number of sessions; smoke test or full P1. The §10 prices are copied from the
  2026-10-14 catalog and must be re-verified on the providers' pages before any approval; no model was called to
  check them.

## 13. Amendments 2026-10-30 (`keyset.v2` and the model gateway; still a draft)

Everything here was built and tested with a **mocked provider only**. No model has played, and no API has been called.
These are proposals for the owner to accept or change.

* **Keyset:** option B of §4 is implemented as `keyset.v2`. Choosing it is still an owner decision.
* **The host owns the conversation** (changes §5's mechanism, not what the model sees). The sandboxed player only asks for
  the next turn and presses what comes back; a game request is forwarded only if it is the model's next validated call.
* **Batches stop at the end of an episode (new).** If a reply holds several tool calls and one ends the episode, the rest are
  not executed and are answered with `not executed: the episode ended`, so keys meant for one episode cannot land in the next.
* **Every tool call is answered (changes §3's "extra calls dropped").** Providers require an answer for each call, so extras
  beyond 8 get a fixed error instead of silence. Invalid calls are answered the same way, and a reply with no valid call counts
  toward stopping rule 6.
* **New stopping conditions**, all ending the session before further spending: estimated context above the limit, a reply from a
  different model than the pre-registered one, a reply without usage numbers, more output than requested, an invalid
  screenshot, a game reply with fields outside the contract.
* **Stopping rule 5** counts only consecutive failed calls, and each retry counts toward the 150 model calls and the budget.
  Rate-limit waits are capped at 60 s each and count toward the 2 hours.
* **Thinking is not replayed.** Replacing old screenshots with a note edits earlier turns, which current Claude models reject when
  thinking blocks are replayed on enforced accounts. The model keeps its visible text and tool calls only. Thinking still costs
  output tokens, so §10's 600-token assumption may be low for those models, and the cost table's uncertainty stands until a smoke
  test measures it. Output is capped at 2,048 tokens per call, which may also cut off a heavily thinking model; the smoke test must
  check how often this happens.
* **§7 baselines were not run.** The offline demonstration (`rewardbench.blindplay.offline_demo`) is a pipeline check with a fixed
  script, on deliberately small settings, and is not one of those baselines.

Model requirements, the owner checklist, the pre-registration procedure and what remains are in `docs/OFFLINE_AI_GATEWAY.md`.
