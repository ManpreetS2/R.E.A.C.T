# R.E.A.C.T. — PROJECT.md

> **Canonical GitHub project plan (effective 2026-10-26).** Read this document before making research or architecture decisions. The full earlier Google Docs research plan is migrated below; the current-status and decision sections at the top resolve any outdated statements in that historical plan.

**Original source:** [R.E.A.C.T. — Master Research Plan | Blind Visual Game Learning](https://docs.google.com/document/d/1fX8ReqGUKCmd_N_cwY6Fa9KfY_P5reKn6jizJcZUDQM/edit) (last observed updated 2026-10-25).  
**Repository:** https://github.com/ManpreetS2/R.E.A.C.T  
**Canonical project specification:** `PROJECT.md` in this repository. Google Doc is the historical source, not the active planning location.

## 0. Current direction and rules of interpretation

### 0.1 Owner-approved primary research vision: blind visual game learning

**The primary R.E.A.C.T. ambition is to test whether an AI, told only “Land the rocket,” can learn to play the original ApolloLander through screenshots and bounded keyboard actions, with no privileged physics variables, hand-specified guidance controller, concealed score leakage, or source access.** This direction was explicitly chosen on **2026-10-17** in the original master research plan (see full migrated Section 20 below). The authentic original game's isolated visual/action bridge is an intended research deliverable; this document does not claim it has been implemented or validated.

**Separate track: structured controller-tuning experiments.** The existing `rewardbench` pipeline, scripted/guidance controllers, simulator tests, paid prompts and study v1/v2 runs are valuable engineering and exploratory research. They are **not** the blind-screen game-playing result and must not be presented as such. An AI selecting parameters for an 18-parameter, hand-designed closed-loop guidance law is not inventing its own flight-control structure. These tracks may share infrastructure, but results, protocols and claims must remain separate.

### 0.2 What has actually happened (2026-10-26 checkpoint)

| Item | Verified/report status | Evidence |
| --- | --- | --- |
| Offline `rewardbench` infrastructure, ApolloLander/LunarLander adapters, SQLite, deterministic replay and evaluation | Built and repeatedly tested; study claims remain separate from mock tests | `docs/OFFLINE_V1_VERIFICATION.md`; draft PRs #12–#17 |
| Study v2 protocol / guidance-only prompt v4 / matched-round autopilot | Implemented; Mission 009 reported 425 passing local tests and CI passed on Windows, macOS, Ubuntu | [PR #18](https://github.com/ManpreetS2/R.E.A.C.T/pull/18), `docs/STUDY_V2_PROTOCOL.md` |
| Real model controller-tuning pilot (Mission 010) | **Completed** 3 arms × 4 revisions = 12 paid `gpt-5.4-mini` calls; all controllers valid, some 8/8 gentle landings; **no demonstrated improvement caused by reward feedback** | [PR #19](https://github.com/ManpreetS2/R.E.A.C.T/pull/19), `docs/assets/study-v2-pilot/RESULTS.md` |
| Experimental budget/accounting | Mission 010 pilot cost **$0.039129**; cumulative recorded cost including Missions 006 and 008 **$0.042646**, estimates from local ledgers, not a provider invoice | `docs/assets/research-results/RESULTS.md` |
| Mission 011 — controlled feedback v3 design | **Designed and tested offline, no v3 model calls yet.** Three feedback arms now share an identical fixed failure controller per block; 2-block pilot = 18 paid calls, with crash/timeout starts and matched scripted hill-climber and random-walk baselines. **440 local tests; GitHub CI passed on Windows/macOS/Ubuntu.** | [PR #21](https://github.com/ManpreetS2/R.E.A.C.T/pull/21), `docs/STUDY_V3_PROTOCOL.md` on PR #21's branch |
| Experimental data backup | Some summaries/checksums on GitHub; raw `.sqlite` and `.flight.json` data remain **local-only** in gitignored `runs/`, including ~45 MB from Mission 010; preserve and back up privately with owner approval | `docs/assets/research-results/MANIFEST.json` |
| Blind screenshot-and-keyboard original-game player | Owner-approved **primary next direction**; not verified as completed in the source Google Doc; do not extrapolate completion from controller-tuning missions | Migrated original Section 20 |

### 0.3 Critical findings and next decisions

- **Mission 010 result:** no-feedback moved from −39.47 to +79.39; reward-only stayed near −51 with 8/8 timeouts; detailed numerical feedback declined from +80.72 to +76.16. These are *one session per arm*, with very different revision-zero controllers. No sound causal effect or cross-model ranking can be inferred; this was an exploratory pilot.
- **Mission 011 design is implemented but not run live:** v3 uses a fixed identical failing start for all three arms in each block, with crash/timeout starts and prespecified no-feedback, random-walk and reward-driven hill-climber comparisons. Two-block pilot: 18 paid calls, proposed **$0.21 cumulative recorded-spend ceiling**, projected **$0.063659** additional API spend, worst-case **$0.264735** additional. The $0.21 cap is a conditional opportunity to finish both blocks, **not a guarantee**: if spend from block 1 is higher than expected, the whole-block budget gate may refuse block 2 safely. No v3 paid calls or future full-study budget have been approved by this document. See [PR #21](https://github.com/ManpreetS2/R.E.A.C.T/pull/21) and `docs/STUDY_V3_PROTOCOL.md`.
- **Research scope alignment:** the v3 controlled-feedback experiment still tests the hand-designed 18-parameter guidance law, not the owner's October 17 primary blind screenshot-and-keyboard gameplay goal. Do not silently replace the latter with increasingly sophisticated parameter tuning.
- **Blind original-game track:** prioritize genuinely isolated screenshot observations and bounded input batches (full specifications and gates in Section 20). Never substitute a hidden-state API or prebuilt controller to manufacture visual learning.
- **Cost authorization:** older $50/$75 planning allowances in the migrated historical doc are **not current spending authorizations**. The owner expressed willingness to spend about $1 exploring R.E.A.C.T.; previously specified Mission 010's $0.18 cumulative software ceiling is not perpetual authorization for future experiments. Obtain explicit provider/model/limit/call approval for each new paid experiment, preserve vendor-side spending controls.
- **Evidence integrity:** keep initial controllers, prompts, individual calls, exact simulator build, seed splits, request IDs, receipts, deterministic replays, hashes and negative findings. Never mislabel hand-tuned/scripted flights as LLM achievements. Preserve historical configs and raw records; no unapproved merges or uploads of private evidence.
- **Attribution:** Original ApolloLander by Seb Lee-Delisle, ©2017, MIT, https://github.com/sebleedelisle/apollolander. Preserve license/credit; no affiliation or endorsement implied.

### 0.4 Repository workflow and document authority

1. **`PROJECT.md` is the main living project specification.** Update the *current-direction, decision, roadmap and results* portions whenever an owner-approved mission changes scope. Add dated decision entries; avoid rewriting past experiments to imply a different original hypothesis.
2. **Do not silently overrule the owner-approved blind-visual direction** with the easier guidance-parameter experiment. Explicitly ask for or document owner approval before changing the primary objective.
3. **Keep experiment-specific specs and receipts** in `docs/STUDY_V2_PROTOCOL.md`, `docs/assets/study-v2-pilot/`, `docs/assets/research-results/`, `docs/PROJECT_HANDOFF.md`, and future versioned protocols. `PROJECT.md` links them and adjudicates research goals; it does not replace reproducible data.
4. **All code/research changes via reviewed draft PRs** unless otherwise authorized. PRs #12–#19 form the historical stacked sequence. **PR #20 (`docs/project-md-master-plan`) and PR #21 (`feature/study-v3-controlled-design`) are sibling draft branches both based on #19**, not a linear stack. Reconcile both before merging; PR #21 does not automatically include this PROJECT.md migration. Never casually merge the full stack.
5. **Future Claude, Codex and other agents** must read this file first, identify whether their mission concerns blind gameplay or historical controller tuning, follow the task's budget and safety limits, and document source-of-truth changes back here.

### 0.5 Migration completeness and precedence

The section below includes **all 421 text paragraphs** (about 92,269 original text characters) returned from the Google Docs document, in the same order, including original sections 1–20, the 2026-10-17 owner decision, references, legacy budgets, architecture, milestones, safety controls, integration/credit plan and 2026-10-24 optional resources. The native Google Docs heading and bullet paragraph styles are translated to Markdown. The source has no native tables according to the document-table inventory. This text migration preserves source wording but not Google Docs fonts/visual styling.

**Precedence:** For current research direction and budget approval, §0 of this `PROJECT.md` and subsequent dated owner-approved amendments supersede stale lines in the migrated historical document. For historically accurate descriptions of the original plan and complete design detail, consult the full sections below. Conflicts are recorded rather than silently erased.

---

## Complete migrated master research plan (original text)

### R.E.A.C.T. — Reward-Enhanced Adaptive Controller Testing

> CURRENT PRIORITY: blind visual game learning with the original ApolloLander | Historic controller benchmarks retained

Master research & build plan | Version 1.3 | Updated 17 October 2026 | Status: public v1 released; blind visual-gameplay protocol approved, implementation pending

CREATOR CREDIT — ApolloLander by Seb Lee-Delisle (© 2017; MIT License). Planned fixed-map game integration. Original source: https://github.com/sebleedelisle/apollolander . Our research modifications are independent; no endorsement is implied. Full integration and attribution plan: Section 18.

CURRENT central question: Can an AI learn to play an unfamiliar game given only “Land the rocket,” actual screenshots, and its own keyboard actions? Former API-model numerical-reward comparisons remain a separate historical/follow-on research track; see Section 20.

### Executive summary

HISTORICAL CONTROLLER-TUNING TRACK (preserved; no longer the primary near-term experiment): Build a reusable reward-feedback experimentation framework. In the first environment, each tested LLM writes or revises a small constrained rocket-controller policy for Gymnasium LunarLander-v3. A local simulator executes each policy at physics speed, returns a numerical score and/or pre-registered diagnostics, and the LLM proposes its next version using its prior attempts. We compare GPT, Gemini, Claude, and Grok under matched experimental conditions. We record complete attempt histories, scores, latency, token counts, API costs, and held-out flight outcomes. Then we port the same experiment engine to Minecraft AI Civilization by replacing only the environment/action adapter and task metrics—not by rewriting the entire benchmark.

Scientific terminology: this is in-context reward-guided adaptation (sometimes described as in-context reinforcement learning), not gradient-based fine-tuning or permanent updates to model weights. The controller code and prompt history change; the API model parameters do not. Say 'adapts from feedback' or 'learns in context,' never 'we trained GPT/Claude/Grok weights' unless a later experiment truly performs optimization.

Starting budget: target USD $50, hard initial project spend guardrail USD $75, with automatic stop at configured provider and aggregate caps. These are planning allowances rather than guaranteed invoices. Student-only, simple 500-call example below estimates about $2.59 in text token charges; a sample GPT-5.4 teacher condition adds about $4.75. Development iterations, retries, context growth, additional experimental arms, and reasoning-token accounting can raise the real bill.

### 1. Scope, non-goals, and relationship to existing work

#### 1.1 What this project will accomplish

- Create an environment-independent ExperimentRunner, an adapter per model provider, a standardized reward/feedback protocol, and a versioned results store.
- Compare improvement over attempts, final generalization, cost efficiency, latency, validity, and stability across repeated runs, not just highest score.
- Publish methods, configurations, code, raw machine-readable results with appropriate redactions, learning curves, uncertainty intervals, a GitHub repo, an accessible research blog, and a concise LinkedIn summary.
- Preserve a migration path to the existing Minecraft AI Civilization project using its Paper/Mineflayer/verified-skills boundary.

#### 1.2 What this is not

- Not LLM fine-tuning or PPO weight updates for GPT/Gemini/Claude/Grok.
- Not a claim that similarly priced models have equal intelligence or equal compute.
- Not a human-safety evaluation or a general intelligence ranking.
- Not real-time 60-Hz LLM flight control: the NEW blind gameplay protocol uses paused screenshot-and-keyboard batches, so an AI can visually learn to act without keeping pace with rendering. See Section 20.
- Not permission to modify the production Minecraft world, unmerged project branches, or persistent citizen database.

#### 1.3 Existing projects to preserve

Original LunarLander concept (read-only reference): https://docs.google.com/document/d/1ZRb6rnFXx0_B_YsEMk3RJpMctR2w6rzyRJn8D-dL8VY/edit . Its original PPO and reward-shaping experiments remain a useful classical RL baseline; do not conflate PPO training with LLM in-context adaptation.

Existing Minecraft AI Civilization (prior project snapshot; revalidate with current code before integration): TypeScript/Node.js orchestration, Paper 1.21.11 world, Mineflayer physical bodies, bounded skills including navigation, gathering, crafting, storage and survival, SQLite memory/state, verification of actions, and local optional Ollama cognition. Five persistent citizens are Atlas, Maya, Theo, Ava, and Kai. The longer-term goal is population-scale simulation. Previously reported Cloud Passes 1–6 and 133 tests passing are not proof of completed full five-citizen live integration; do not overwrite existing worlds or data.

### 2. Research grounding and precise hypothesis

This design is closely related to 'Reward Is Enough: LLMs Are In-Context Reinforcement Learners' (ICLR 2026), which examines multi-round prompts with previous outputs and scalar rewards; it also builds on Reflexion's episodic feedback. These studies motivate the experiment but do not prove our specific rocket or Minecraft hypotheses. See sources section.

#### 2.1 Research questions

- RQ1: Under identical feedback, how much does held-out LunarLander performance improve between the first and last controller revision for each model?
- RQ2: Does numeric reward-only feedback help more than no-feedback controls? Do deterministic diagnostics or AI coaching produce additional gains?
- RQ3: Which model reaches a pre-registered performance threshold in the fewest controller revisions, least wall-clock time, and lowest total marginal cost?
- RQ4: Do successful improvements generalize to unseen starts, seeds, perturbations, and eventual Minecraft tasks?
- RQ5: How do observed rankings change when conditioning on cost budget, input/output token budget, and model-tier mismatch?

#### 2.2 Pre-registered hypotheses (testable, not conclusions)

- H1: At least one model will show a positive paired held-out improvement after numerical feedback compared with its own initial policy.
- H2: Numeric feedback will outperform no-informative-feedback on average, controlling for the same number of revisions.
- H3: Diagnostic feedback may produce faster improvement, but could also encourage metric gaming; held-out evaluation will determine whether gains are real.
- H4: Results on simple physics control will not automatically predict performance on partially observed multi-agent Minecraft tasks.

Null findings are reportable. Do not choose a winner when confidence intervals overlap substantially or when comparisons are confounded by model availability or budgets.

### 3. Model cohorts and bias controls

#### 3.1 Provisional API cohort (verify slugs and prices on run day)

OpenAI: gpt-5.4-mini — published $0.75 input / $4.50 output per 1M tokens.

Google: gemini-3.1-flash-lite — published $0.25 input / $1.50 output per 1M tokens.

Anthropic: claude-haiku-5-5 — published $0.10 input / $0.50 output per 1M tokens for prompts up to 100k tokens (higher above 100k).

xAI: grok-4.3 — published $1.25 input / $2.50 output per 1M tokens for short context; xAI retired the older Grok 4.1 Fast model slugs in May 2026, so DO NOT budget or label Grok 4.1 Fast as an active, like-for-like competitor.

As of the consulted xAI API pricing, there is no obviously like-priced public fast Grok student aligned with the other three. Report xAI as a 'cross-tier reference' in primary charts or create an additional carefully labeled budget-normalized cohort. Never manufacture model equivalence.

#### 3.2 Controls for a publishable comparison

- Pin exact model IDs and run dates, and record API release/alias resolution when provider exposes it; avoid 'latest' aliases for final reproducibility.
- Use one canonical task spec, system instruction, allowed schema, sample controller, output limit, feedback encoding, simulator version, environment wrapper, and evaluation harness.
- Fix maximum revisions per run, max prompt-history tokens, response tokens, timeouts, retries, run ordering/randomization, and approximate sampling/effort settings. Record any provider-specific mismatch explicitly.
- Counterbalance run order to mitigate API load/time-of-day effects; run independent replicated sessions with separate histories and shared matched seed lists.
- Separate initial performance, relative gain, final held-out score, price-performance, and time-to-target. Never equate the four with one vague 'best model' claim.
- Keep development seeds distinct from held-out seeds. Prohibit access to held-out trajectories and summary metrics until a controller is frozen.
- Blind the optional teacher to provider names and model identity. Better still, compute primary rewards locally to avoid judge preference bias.
- Do not enable provider browsing/web search, repository tools, or external search in benchmark calls; all contestants receive the same closed task.
- Run source terms, licensing, and API rate-limit reviews before publishing; don't disclose API keys or private user data in traces.

### 4. The experiment's 'learning' mechanism

#### 4.1 One iteration, precisely defined

- 1) Runner creates a new session with a stable task specification and starter controller format.
- 2) Student model emits a constrained controller (initially parameterized controller JSON or a safe restricted policy DSL; no unconstrained execution).
- 3) Validator rejects malformed/unsafe commands, recording failure and applying a predeclared penalty rather than silently retrying forever.
- 4) Gymnasium worker executes the valid controller over a fixed development bundle (e.g., 5 training seeds). One controller revision can result in several actual rocket episodes.
- 5) Worker returns aggregate numeric Gymnasium return plus predeclared diagnostics permitted by the study arm.
- 6) Runner appends a bounded, deterministic memory record of prior controller revisions and rewards, then requests the next revision.
- 7) After each scheduled checkpoint, evaluate the current best-so-far frozen controller on the same reserved held-out seed set and store performance privately. Never feed held-out information back to the student.
- 8) Repeat to the preset revision or dollar cap. Freeze final controller, independently test it, and save all artifacts with a run ID.

#### 4.2 Learning versus selection

We must distinguish model-driven adaptation from merely retaining a lucky earlier controller. Log the final controller and the best-so-far controller separately. Report both. Include a random-search/parameter-sampling baseline and a simple hand-written controller as references. A model that simply selects the best previously tried policy can improve best-so-far scores without demonstrating effective feedback-based revision.

#### 4.3 Experimental arms

Arm A — No-feedback: each new request gets the same specification and a neutral attempt counter, but no scores or outcome details; test repeated generation and selection under an equivalent budget.

Arm B — Scalar-reward-only (PRIMARY): prior proposals and a numeric return; no written coaching, exception explanations, or teacher analysis. This is the closest test of reward-incentive adaptation.

Arm C — Numeric + structured diagnostics: reward plus landing-rate, median fuel proxy, crash count, instability and validation errors, all computed deterministically.

Arm D — Optional teacher coaching: same numeric reward plus a short, blind, structured critique from a stronger model, only after checking applicable provider terms. Treat this as a secondary experiment, not the primary mechanism.

Negative control: shuffled or randomly assigned historical rewards in a small matched subset (clearly labeled) to test whether apparent improvement really depends on informative feedback.

'Loss' here means negative reward / penalty, not a backpropagation loss function. Numeric reward and penalty should not be presented as weight updates.

### 5. LunarLander environment and scoring

#### 5.1 Core environment

Use Gymnasium LunarLander-v3, discrete actions 0 idle, 1 left orientation engine, 2 main engine, 3 right orientation engine. Observation: 8 state values (x, y, horizontal velocity, vertical velocity, angle, angular velocity, left-leg contact, right-leg contact). Existing stepwise rewards favor proximity, low speed, upright posture, leg contact, and fuel efficiency; terminal safe landing receives +100 and crash −100. A return ≥200 is Gymnasium's customary solved criterion, but it is NOT the same variable as counted safe landings.

Keep official unmodified environment return as the primary comparator. If an experimental shaped reward is added later, do not use that shaped metric alone to proclaim success. Publish the original return, explicit success/failure classification, and fuel/time indicators independently.

#### 5.2 Controller interface and sandbox

Initial safe policy format should expose a small, bounded set of meaningful parameters (target descent rate, horizontal correction gain, angle correction gain, throttle thresholds) or an expression/AST grammar with whitelisted operations. Code generator compiles the policy to a controlled callable; do not run arbitrary LLM-written Python, network calls, filesystem access, imports, or shell commands. The policy receives only the current observation and returns one of 0/1/2/3. Run a separate process with CPU/memory/time limits and no secrets.

At later difficulty tiers, permit richer synthesized programs after establishing a hardened sandbox, but never change task expressiveness between model cohorts inside a comparison.

#### 5.3 Primary and secondary outcomes

Primary: mean unmodified return over 30 held-out episodes per frozen controller (same held-out seeds for every model, independent of training). Also report median and 95% uncertainty intervals across independent sessions.

Key secondary: proportion of verified safe landings; proportion ≥200; crash proportion; invalid-controller rate; runtime per simulated episode; student API latency; number of revisions to threshold; tokens/cost; simulated fuel use; horizontal drift/tilt on touchdown.

Clarify denominators. 'Revision' = one LLM attempt to propose a controller; 'episode' = one full simulated rocket run. Example 25 revisions × 5 development seeds = 125 rocket episodes in ONE session, not 25.

#### 5.4 Environment splitting

Suggested starter: 5 development seeds per revision, 30 held-out seeds per frozen result, 5 independent sessions per student/condition, all logged and fixed before running. Add stress-test seed sets with gravity/wind/turbulence variations only when configured consistently and supported by the environment. Don't peek at held-out scores during optimization.

### 6. Evaluation methodology and statistics

#### 6.1 Pilot and main study

Pilot: 2 models × 1–2 feedback arms × 2 independent sessions × 10 revisions, use to verify pricing, controller validity, score ingestion and no leakage. Do not present pilot results as definitive.

Main study first pass: 4 models × 5 sessions × 25 revisions × 1 primary arm = 500 student calls plus simulations. To demonstrate reward effects, replicate the no-feedback control: another 500 calls. Diagnostic/coaching arms extend the budget; run only after pilot power, feasibility and spend audit.

Five independent sessions is a pragmatic minimum pilot-scale replication, not a guarantee of statistical power. Conduct a sensitivity/power analysis using pilot variance before making strong published significance claims. Prefer 10+ independent sessions if resources permit.

#### 6.2 Exact endpoints

- Baseline: held-out score of the initial revision, before any outcome feedback.
- Final: held-out score of the final revision after the fixed number of steps.
- Best-so-far: independently evaluated score of the highest development-ranked policy at the stopping point.
- Adaptation gain: final minus initial paired held-out mean for each independent session; report uncertainty.
- Feedback effect: (scalar arm gain − no-feedback arm gain), compared with matched budgets, independent replicated sessions, and appropriate intervals.
- Sample efficiency: revisions or actual simulated episodes to reach a pre-registered held-out threshold, with runs that never reach it treated as censored, not silently discarded.
- Economic efficiency: gain per total billed dollar, plus performance versus cumulative cost; retain a separate equal-dollar comparison.

#### 6.3 Statistical presentation

Plot each model's mean held-out return versus revision number with 95% bootstrap confidence intervals clustered by independent session (not by individual correlated flight). Also show safe-landing probability with binomial intervals and scatter/box plots of session-level gains. Prefer effect sizes and uncertainty to rank-only conclusions; correct/explain multiple exploratory comparisons.

Test for baseline ceiling: strong models may begin near maximum. Include relative headroom consumed as a descriptive supplement, not as a substitute for raw score gain. Avoid mixing model quality with reward responsiveness.

#### 6.4 Failure and bias registry

- Selection bias: champion controller chosen on development seeds only; frozen once before held-out test.
- Feedback leakage: separate scorer and evaluation split; hide unreleased evaluation aggregates.
- Reward hacking: hovering or exploiting shaped rewards; count physical landing success independently.
- Context growth: bounded structured memory (e.g., last 5 proposals + best 3), identical compression rules and token caps.
- Sandbox/coding advantage: fixed DSL controls coding surface; invalid-output handling identical.
- Model mismatch: public API tiers not equal, especially current xAI; label cohort as 'pragmatic comparison,' not controlled parameter-size study.
- Provider variance: use pinned versions where possible, request usage data, fixed generation settings when supported; disclose unsupported controls.
- API failure handling: rate limits and transient 5xx retried with bounded exponential backoff; both retries and original request logged, never counted as new intentional revision.
- Prompt sensitivity: report the canonical prompts, then optional robustness check with alternative phrasing on a frozen secondary sample.
- Teacher bias and policy: primary signal is verifiable engine scores; provider-specific critique is optional and separately analyzed.

### 7. Provider architecture and model contracts

#### 7.1 Shared API contract

StudentClient.generate({task_spec, allowed_actions, history, attempt_number, seed_context, max_tokens, generation_settings}) -> {candidate_policy, raw_text, model_id, request_id, latency_ms, billed_input_tokens, billed_output_tokens, reasoning_tokens_if_exposed, total_cost_estimate, finish_reason, errors}. Normalize errors, but preserve original provider response metadata.

EnvironmentAdapter.reset(config, seed) -> Observation; execute(policy, episode_config) -> EpisodeResult; validate(policy) -> ValidationResult; score(episodes, rubric_version) -> RewardFeedback; snapshot/restore() when supported. RewardFeedback = {scalar_reward, deterministic_metrics, rubric_version, status, public_feedback_fields}. Different environments must implement the same core semantics.

Benchmark coordinator: Session -> Attempt -> Candidate -> Validation -> DevelopmentEpisodes -> Reward -> NextAttempt; separate EvalJob for frozen candidates. Persist as append-only events so aborted experiments resume without lost provenance.

#### 7.2 Technical implementation

Python 3.11+ runner for Gymnasium + Box2D + NumPy, Pydantic schema validation, asyncio-based provider client wrappers, SQLite (or DuckDB/Parquet exports), Pandas, Matplotlib/Plotly, pytest, Ruff, and pinned dependency lock. Docker or OS sandboxing for generated policies; no shell/network privileges. Python experiment engine exchanges typed JSON messages with the existing TypeScript Minecraft adapter, preferably via localhost HTTP/WebSocket or a bounded message queue.

User-visible local dashboard (optional): study status, per-model cost, score curves, retries, attempt inspector, replay/video archive, and a hard-stop control. Do not spend MVP time on ornate UI before the harness runs correctly.

#### 7.3 Provenance schema (sample fields)

run_id, session_id, arm_id, model_vendor, model_slug, model_revision_if_known, created_at_utc, environment_name, environment_version, dependency_lock_hash, reward_version, prompt_template_sha256, controller_schema_version, dev_seed_ids, heldout_seed_ids_hash, attempt_index, candidate_hash, validity, action_count, episode_count, dev_score_mean, heldout_score_mean_if_released, true_landing_count, crash_count, student_tokens_in/out, teacher_tokens_in/out, billed_usd, wall_seconds, error_code, retry_count, prior_candidate_hash, commit_sha.

Logs should capture all failures, including invalid proposals, bad JSON, sim timeouts, crashes, budget stops, refusals, and missing provider token data; never count only success cases. Save full prompt/response content only with secrets redacted.

### 8. Costs and time plan (as of 14 Oct 2026)

#### 8.1 Current public list-price snapshot

Student candidate | input per 1M | output per 1M: GPT-5.4 mini $0.75 / $4.50; Gemini 3.1 Flash-Lite $0.25 / $1.50; Claude Haiku 5.5 $0.10 / $0.50 for ≤100k prompt; Grok 4.3 $1.25 / $2.50 for short context. Optional GPT-5.4 judge $2.50 / $15.00. Rates exclude taxes, nonstandard endpoint premiums, tool usage, caching choices, and any provider-specific reasoning token charges. Verify again before spending.

#### 8.2 Transparent illustrative cost calculation

Primary cohort: 4 students × 5 sessions × 25 revisions = 500 student calls total; each call averages 5,000 input and 1,000 output tokens. Across 125 calls per model: GPT ~$1.0313, Gemini ~$0.3438, Claude ~$0.1250, Grok ~$1.0938 => students ~$2.5938. Optional teacher: 500 calls × (2,000 input + 300 output tokens) at GPT-5.4 rates => ~$4.75. Combined nominal example ~$7.34, not including repeated controls, long conversations, extra reasoning tokens, retries, other API fees or sandbox cloud compute.

Per-model example formula: USD = (input_tokens / 1,000,000 × input_rate) + (output_tokens / 1,000,000 × output_rate) + separate tool/other fees. Record provider-billed usage whenever possible; revise estimates from real pilot data.

#### 8.3 Practical budgets

Tier 0 validation: $0–$10 suggested API allowance; verify loop, one provider then another, fewer than 100 student calls and local simulator.

Tier 1 initial publishable framework: $25–$75 suggested allowance; multiple models, reward and no-feedback arms, 5-session replication, local simulation, and headroom for coaching/prompt costs. Do not promise significance solely on this budget.

Tier 2 expanded robustness: $100–$250+ suggested allowance; added seeds, additional sessions, alternate prompts/feedback arms, more frequent independent teacher calls, and heavier Grok configurations. These are buffers, not source-quoted prices.

Compute budget: Gymnasium runs locally on a normal workstation; APIs dominate marginal cash cost in the first version. Minecraft Paper simulation has greater CPU/RAM/runtime burden, especially live five-citizen tests. User PC previously reported RTX 4080 Super, 64 GB RAM; running hosted API models requires no local model GPU training.

#### 8.4 Cost safety controls

- Request global max_spend_usd=75 and preferred experimental target=50; account-level API billing alert/limits are separate provider settings and must be configured by the owner.
- Track per-vendor, per-arm, per-session, and optional teacher budgets; reserve an estimated upper-bound cost before sending each request and stop when remaining budget is insufficient.
- Cap generated output and memory length, avoid web search tools in benchmark runs, and charge/account retries.
- Record real usage before upgrading from pilot to main study; cost forecast may shift materially if models emit many hidden reasoning tokens or very long code.

### 9. Portable Minecraft integration—without redesigning the civilization

#### 9.1 Non-negotiable integration principle

Retain the current Minecraft AI Civilization's ownership of world state, citizen identity, persistence, task planner, and verified actions. The benchmark is a sidecar experiment runner, not a rewrite of the simulator. The Paper server, Mineflayer bots, pathfinding/collecting/crafting skills, and SQLite event provenance remain source-of-truth for execution.

#### 9.2 Migration adapter design

MinecraftTaskAdapter implements the same contracts as LunarLanderAdapter. Observation = filtered citizen/world summary: position, inventory, health/hunger, assigned task, reachable resources, time/nearby hazards, permissible tools, and resource reservations. Action = bounded high-level skill call or small validated task plan, not direct arbitrary console commands, shell scripts, raw Java plugins, or model-generated unreviewed Mineflayer code. Reward = verified objective task outcome minus explicit penalties. Termination = success, failure, death, timeout, or resource cap. Reset = load isolated seeded snapshot of Paper world and citizen DB.

Transport: Python experiment runner ↔ typed JSON/HTTP service in current TS orchestrator ↔ bounded deterministic skill planner ↔ Mineflayer/Paper ↔ actual world/inventory receipts. Existing adapter @civ/minecraft-adapter, @civ/skills, and production MechProbe body are integration candidates; verify exact current interfaces and code state before implementation.

#### 9.3 First Minecraft tasks (in difficulty order)

- M1 — Navigation: move one controlled citizen to a specified reachable checkpoint with bounded time, no damage, and verified final position.
- M2 — Resource collection: gather a predeclared quantity of wood, return home and deposit it in a specified chest, with inventory/chest changes verified.
- M3 — Survival routine: obtain food or shelter/bed before night while preserving hunger/health and avoiding unnecessary resource damage.
- M4 — Cooperative two-citizen task: allocate gathering and crafting to separate citizens, share storage, and prove both tasks completed.
- M5 — Five-citizen settlement task: use Atlas, Maya, Theo, Ava, and Kai with persistent identities, bounded tasks, and resource contention. This is an advanced milestone and must wait for reliable one-citizen runtime verification.

#### 9.4 Minecraft reward examples (pre-register carefully)

Example M2: +100 for chest receipt proving required logs deposited; +20 for verified safe return; −30 for death; −5 for unnecessary tool breakage; −0.1 per simulation-second; −20 for unauthorized chest access. Use event receipts rather than an LLM's narrative as ground truth. These are experimental proposed values, NOT production rules; test whether time penalties inadvertently reward unsafe shortcuts. Report completion rate and resources independently of shaped reward.

#### 9.5 Isolation and replay

- Create a benchmark-only world/DB clone; preserve production world backups and all original SQLite citizen records.
- Snapshot starting inventory, health, time, weather, world seed, resource locations, and all relevant task state. Minecraft execution may not be perfectly deterministic because of tick timing, network latency, and concurrent agents; log event receipts and repeat seeds.
- Disable unrestricted mining/building/chat, external network, operator privileges, and irreversible live-world actions for generated policies.
- Start with one citizen under simulation-only experiment ownership; gate multiple concurrent citizens and social behaviors behind proven deterministic skill outcomes.
- Have rollback and server restart health checks; freeze/unmerged branch and environment dependencies before attempting integration.

#### 9.6 Shared experiment schema across games

Keep identical top-level entities: TaskSpec, Observation, ActionProposal, ValidatorResult, EpisodeResult, RewardFeedback, RunConfig, ModelInvocation, SessionHistory, EvalRecord. Only game adapters, score rubric, and input/action schemas change. That is the seamless switch: benchmark mechanics remain constant while the underlying task and environment become much richer. Results from different environments must never be collapsed into a single undifferentiated leaderboard.

### 10. Delivery phases, acceptance gates, and schedule

#### Phase 0 — Research freeze and specification

Deliverables: project charter, method definitions, chosen model IDs, source/terms review, seed protocol, reward rubric, primary metric, power/sampling note, budget guardrails. Gate: no contradictory definitions of 'attempt,' 'episode,' or 'learning'; no unsupported claim about model equivalence.

#### Phase 1 — Local LunarLander harness

Deliverables: reproducible v3 environment, restricted controller grammar, reference/random policies, simulation worker, deterministic reward extraction, video replay, unit tests. Gate: known controllers produce repeatable results on fixed seeds; invalid policies cannot escape sandbox.

#### Phase 2 — Four-provider student adapters

Deliverables: GPT/Gemini/Claude/Grok connectors, JSON schema validation, token and latency accounting, retry behavior, hard cost limit, pseudonymous provider-blind labels for teacher arm. Gate: two smoke-test calls per provider with independent saved traces, no malformed usage statistics.

#### Phase 3 — Pilot and corrections

Deliverables: two-model pilot across no-feedback and scalar arms, inspect simulations, run paired summaries, revise max context and cost assumptions. Gate: observed meaningful variance and correct logging; lock study design before main comparisons.

#### Phase 4 — Main benchmark

Deliverables: at least 5 sessions per model for no-feedback and scalar arms, 25 revisions per session, reserved held-out evaluations, complete failure registry and cost logs. Gate: all expected runs complete or are transparently censored; no data leakage.

#### Phase 5 — Robustness and research report

Deliverables: optional deterministic diagnostic and policy-permitted teacher conditions, uncertainty plots, efficiency curves, prompt robustness, ablation table, limitations and reproducibility README. Gate: every claim has a data figure or is labeled hypothesis; no cherry-picking.

#### Phase 6 — Minecraft adapter proof

Deliverables: standalone benchmark plugin attached to isolated Minecraft test world, first navigation/resource tasks, validated command schema, verified receipts and rollbacks, shared study dashboard. Gate: original five-citizen world and DB remain unchanged; no destructive access to production runtime.

#### Suggested sequence (estimates, not promised timelines)

Weekend 1: Phase 0 and local Phase 1; Week 1–2: Phase 2 and pilot; Weeks 2–3: main runs and analysis; Week 3+: blog/GitHub/LinkedIn; Minecraft proof after validated simulation stability. Progress gates matter more than calendar dates.

### 11. Gap analysis — researched and resolved

Gap G1: 'Reward learning' was being described as fine-tuning. Resolution: formally use in-context reward-guided adaptation with no weight updates; cite ICLR 2026 work. Residual issue: transfer to new tasks requires careful testing.

Gap G2: Heavy model as the sole reward giver creates judge bias and potential policy constraints. Resolution: official Gymnasium numeric return as primary reward; teacher only optional blind textual critique, separately labeled and policy-reviewed.

Gap G3: Prior 'fast Grok 4.1' was retired; previous low-price comparisons were stale. Resolution: use current Grok 4.3 pricing and flag cross-tier mismatch; recheck slugs before launch.

Gap G4: Comparing one flight per policy makes rewards noisy. Resolution: bundles of development episodes per controller and independent held-out flight sets.

Gap G5: Cherry-picking best-of-many samples can masquerade as improvement. Resolution: report initial, final, best-so-far, no-feedback control, and random-search baseline.

Gap G6: LLM-suggested unrestricted Python is unsafe and gives unequal external tool capabilities. Resolution: restricted controller DSL/AST, sandbox, deterministic validation.

Gap G7: Leaderboard results can be contaminated by reward shaping. Resolution: keep unmodified environment return and verified landing metrics, not just a model-designed score.

Gap G8: Model APIs do not expose equal sampling controls or exact architecture sizes. Resolution: pin observable settings and disclose non-equivalence; evaluate several efficiency dimensions.

Gap G9: Costs were guessed without request counts or output assumptions. Resolution: explicit token math, real usage ledger, automatic reserve-before-call budget enforcement.

Gap G10: Minecraft has persistent, multi-agent state unlike episodic LunarLander. Resolution: snapshot/reset protocol, single-agent test start, deterministic bounded skills, event receipts, separate world/DB clone.

Gap G11: Minecraft active development status is not fully validated. Resolution: treat Cloud Passes as code-level progress; no merge or mutation until existing production integration branch and runtime are freshly inspected.

Gap G12: Statistical validity and multiplicity. Resolution: preregister primary metric, matched seeds, independent session-level uncertainty, power analysis, transparent failures and null results.

Gap G13: Closed-model API drift/reproducibility. Resolution: model/version snapshots, provider documentation dates, full configs and raw (redacted) traces, note that provider weights are not controlled.

Gap G14: Cross-vendor teacher outputs might trigger restrictions. Resolution: no teacher-generated cross-vendor student improvement until provider terms are checked, or use engine-only rewards / appropriately licensed independent coach.

### 12. Explicit open decisions (not blockers)

Decision D1: choose constrained parameterized controller as MVP (recommended); only expand to general code if safe sandbox proven.

Decision D2: primary feedback arm = scalar-only, no stronger AI coach; optional coaching is separate secondary work.

Decision D3: hard cap $75, soft planning target $50; actual API account spending controls configured by owner.

Decision D4: treat Grok as a cross-tier comparison pending a similarly-priced verified API option.

Decision D5: publish after main LunarLander controlled study; integrate Minecraft once separate Paper/skills adapter passes isolated replay tests.

Decision D6: preregister 25 controller revisions, 5 development flight episodes per revision, 30 held-out final evaluation episodes, and 5 independent sessions; revise only from pilot data and disclose changes.

### 13. Repository structure and implementation handoff

Proposed repo: reward-adaptation-benchmark/

docs/ (research protocol, model matrix, prompt cards, budget, ethics & terms, methodology, publication assets)

benchmark/core/ (runner, orchestration, session memory, registry, evaluation split, scoring, budgets)

benchmark/models/ (openai, google, anthropic, xai adapters)

benchmark/environments/lunarlander/ (Gymnasium adapter, controller DSL, sim worker, video)

benchmark/environments/minecraft/ (typed bridge and task schema; initially stub)

benchmark/data/ (SQLite event log + safe Parquet/CSV exports)

benchmark/analysis/ (plots, bootstrap uncertainty, tables, final report)

tests/ (unit, integration, property, security, replay)

configs/ (experiment YAML, models, reward rubrics, seeds, budget)

artifacts/ (sample replays, published plots only; no secrets or huge raw worlds)

Minimum CI: format/lint/typecheck/tests; schema validation; sandbox rejection tests; deterministic fake-model provider tests; seed replay checks; price computation tests; no provider API keys in CI.

#### First 12 development tasks (in dependency order)

- 1. Initialize repository and versioned experiment protocol; pin env dependencies.
- 2. Define core TaskSpec, CandidatePolicy, EpisodeResult, RewardFeedback, UsageLedger schemas.
- 3. Implement LunarLander-v3 adapter with fixed-seed reset, metrics, and video.
- 4. Implement restricted policy grammar and validator; verify sandbox against malicious code.
- 5. Add deterministic hand-built and random-controller baselines.
- 6. Implement append-only SQLite logging, artifact hashes, and resume.
- 7. Build provider-independent StudentClient and fake-model test backend.
- 8. Implement all four real provider adapters with usage accounting and hard-stop budgets.
- 9. Implement no-feedback and scalar-only prompts plus fixed memory truncation.
- 10. Write dev/held-out split runner and independent evaluation gate.
- 11. Run smoke-test pilot, audit costs/variance, freeze preregistration.
- 12. Run main study, generate automated charts and a data-backed report.

### 14. Publication and reproducibility checklist

- GitHub README: what study tests, environmental assumptions, how to reproduce, exact model slugs and experiment dates, cost expectations, security boundaries.
- Methods: control arms, valid/invalid response treatment, reward equations, seed assignment, holdout protocol, session count, sampling settings, stopping/budget rules, confidence intervals.
- Visuals: reward by revision (with bands), landing success, paired improvement, performance vs dollars, wall time, sample flight videos, invalid proposal rates.
- Evidence: all session-level records, data dictionary, source code, dependency versions, hash of protocol, reproducible analysis script; do not publish API keys or private Minecraft DB/world.
- Writing: use 'in-context reward-guided adaptation' consistently, state explicitly no weight updates, describe cross-tier non-equivalence, disclose limitations and null findings.
- LinkedIn: short visual summary with three grounded results, exact scope of experiment, link to GitHub/blog. No fabricated winner, and avoid marketing the study as definitive across all AI models.
- Blog outline: Motivation → related research → core experiment → controls and fairness → learning curves → cost/speed → failure cases → Minecraft migration → limitations → reproducibility.

### 15. References and verification links

[R1] Gymnasium LunarLander-v3 official environment: https://gymnasium.farama.org/environments/box2d/lunar_lander/

[R2] 'Reward Is Enough: LLMs Are In-Context Reinforcement Learners,' ICLR 2026: https://proceedings.iclr.cc/paper_files/paper/2026/hash/b7511dfe2e7a1fa45e093cc75389abc2-Abstract-Conference.html

[R3] Reflexion: Language Agents with Verbal Reinforcement Learning: https://arxiv.org/abs/2303.11366

[R4] OpenAI GPT-5.4 mini API model/rates: https://developers.openai.com/api/docs/models/gpt-5.4-mini

[R5] OpenAI GPT-5.4 API model/rates: https://developers.openai.com/api/docs/models/gpt-5.4

[R6] Google Gemini API pricing: https://ai.google.dev/gemini-api/docs/pricing

[R7] Anthropic Claude Haiku API and pricing: https://www.anthropic.com/claude/haiku

[R8] xAI model availability: https://docs.x.ai/developers/models

[R9] xAI current token pricing: https://docs.x.ai/developers/pricing

[R10] xAI May 2026 model retirement notice: https://docs.x.ai/developers/migration/may-15-retirement

[R11] Mineflayer official source/API: https://github.com/PrismarineJS/mineflayer

[R12] Mineflayer Pathfinder official source: https://github.com/PrismarineJS/mineflayer-pathfinder

[R13] OpenAI Services Agreement (competition-output restrictions and permitted exceptions): https://openai.com/policies/services-agreement/

[R14] Multi-agent adaptation limitations, ICML 2026: https://proceedings.mlr.press/v306/jing26d.html

[R15] Original user Lunar Lander project brief: https://docs.google.com/document/d/1ZRb6rnFXx0_B_YsEMk3RJpMctR2w6rzyRJn8D-dL8VY/edit

### 16. Final acceptance criteria

DONE for LunarLander v1 when: (a) all four students and a fake provider pass test harness; (b) primary reward-only and no-feedback experiments are logged, including errors; (c) model rankings are supported by held-out data and session-level uncertainty; (d) source costs can be recomputed from usage logs; (e) no external model weights were described as fine-tuned; (f) docs, code, data/plots and reproducibility steps are publication-ready. DONE for Minecraft adapter v1 only when isolated single-citizen skill tasks succeed and revert reliably, with verified state receipts and no effect on the original settlement.

### 17. Public project narrative — from rocket experiment to Minecraft

Publishing strategy: treat LunarLander as Chapter 1 of an ongoing public build/research series, not as the final destination. The first post/blog should introduce the method and the evidence from the rocket benchmark, then close by clearly announcing that the same reward-feedback framework will be ported to the existing Minecraft AI Civilization project. Chapter 2 shows the migration design. Later chapters share real gameplay footage, failures, iterations and results. This is a publication plan, not a promise that those results already exist.

#### 17.1 The personal-page narrative

Opening: “I wanted to test something simple: if different language models receive the same repeated rewards and penalties, which one adapts its strategy the most effectively?” Explain that in this experiment an LLM proposes and improves a rocket controller, a simulation assigns objective scores, and the model uses those scores in its next attempt—without changing its underlying weights.

Middle: show the actual study setup, identical environment and feedback constraints, no-feedback comparison, costs, learning curves, held-out landings and surprising failures. Only name a winner if results support that conclusion. The project should feel like a transparent engineering experiment rather than an advertisement for one AI provider.

Closing: connect this to the broader question of reward-guided agents in rich worlds, where tasks are multi-step, resources matter, and decisions have consequences. Announce the isolated Minecraft adaptation and link the planned follow-up build videos.

#### 17.2 Ready-to-edit ending for the first study/blog

“LunarLander is just the starting point. It lets me compare how different language models respond to the same rewards and penalties in a controlled environment. My next step is to bring this experiment into Minecraft, using my AI Civilization project as a much more complex test world. Instead of only trying to land a rocket, agents will need to navigate, gather resources, survive, complete tasks and eventually coordinate with other agents—all with outcomes verified by the game itself. I’ll share the architecture, mistakes, experiments and actual gameplay as I build it. The goal is to find out whether the same models that adapt well in a small simulation can carry that ability into a persistent, changing world. This is chapter one.”

If the blog is written before experiments finish, change its framing to “research plan and introduction” rather than asserting measured outcomes. Publish performance findings only after the benchmark and independent analysis are complete.

#### 17.3 Recommended public release sequence

Release 0 — Project introduction: brief visual teaser, what reward-based adaptation means, question to test, and a preview of the rocket simulator. Mark early experiments as in progress.

Release 1 — LunarLander research results: reproducible GitHub code, token/cost methodology, flight clips (successes and failures), performance curves, no-feedback control, caveats, blog and a summary post.

Release 2 — Minecraft architecture announcement: an animation/diagram showing the same ModelClient → RewardFeedback → ExperimentRunner flow, with LunarLanderAdapter replaced by MinecraftTaskAdapter; document the existing Minecraft AI Civilization architecture and the isolation/safety plan.

Release 3 — First Minecraft proof video: one citizen completes one navigation task in a disposable test world with before/after position receipt, numeric reward and a trace of changed decisions.

Release 4 — Reward progression videos: gather and deposit wood, manage survival, and compare first attempt against later attempts using fixed constraints. Present successful and failed episodes without hiding retries.

Release 5 — Cooperative agents: two agents, then five citizens, only after reliable one-citizen skills, reset/replay, logging, and resource contention checks. Show coordination and failures; do not imply an achieved milestone until demonstrated.

Release 6 — Cross-world analysis: examine which findings generalize from rocket to Minecraft, which do not, and whether differences relate to memory, planning depth, model cost or stochastic world conditions.

#### 17.4 Suggested short-form video format

Each clip (approximately 20–60 seconds, flexible) opens with a specific challenge and an observable attempt, overlays the model name, attempt number, numeric reward, and mission status, shows the actual failure or success, then includes a quick comparison or next-step teaser. Use real capture from the simulator—not dramatized fabricated runs. Avoid faces, private usernames, API keys, world addresses, or private chat logs.

Possible videos: (a) rockets crashing on attempt 1 versus later; (b) a controller that exploits reward but never safely lands; (c) side-by-side model learning curves and simulation clips; (d) code/architecture transition from LunarLanderAdapter to MinecraftTaskAdapter; (e) Minecraft bot wandering versus reaching a verified waypoint; (f) verified logs entering a chest; (g) two citizens coordinating and resolving task conflicts. Make content engaging but prioritize authenticity.

#### 17.5 Blog, GitHub and LinkedIn content roles

LinkedIn: concise hook, main learning, one meaningful chart or video, explicit distinction between reward-guided in-context adaptation and model-weight training, and a link to the study. GitHub: verifiable experiment code/data/configs with results and limitations. Blog/personal site: full story, research method, model comparisons, costs, results, reproducibility, and final transition to Minecraft. Shorts or demo videos: evidence of the behaviors claimed, tagged with experiment IDs.

#### 17.6 Milestones required before every claim

Before saying 'model X learned best': run matched no-feedback and reward arms, holdout evaluations, uncertainty calculations, and cost checks; explain model-tier limitations.

Before showing 'the Minecraft experiment works': demonstrate a complete, isolated citizen task with actual world-state receipts and reset; do not reuse development clips as proof of an unrun benchmark.

Before presenting 'five AI citizens': verify actual concurrent five-citizen runtime, identity persistence, bounded skills and shared-state consistency; otherwise label a clip as a simulation mock-up or staged demo.

Every post should link the relevant research methodology, source code or experiment log where practical and distinguish implemented features from planned ones.

#### 17.7 Immediate next actions for the series

Choose the working series headline: 'Can AI Learn from Rewards? From Rocket Landings to Minecraft Civilizations' (or a shorter personal-page variant).

Capture a baseline random-rocket clip and a small schema illustration first; no model-performance claim is required to share the project introduction.

Complete LunarLander harness, run feedback/no-feedback comparison, and freeze the full results before publishing a winner or relative performance claim.

Build an isolated Minecraft benchmark branch and world snapshot, starting with one navigation skill and numeric completion rewards.

Save experiment footage with matching run IDs so each social post can point back to technical evidence.

### 18. ApolloLander Integration — Fixed Moon Map, High-Quality Gameplay, and Creator Credits

Decision approved for investigation (15 October 2026): integrate Seb Lee-Delisle’s MIT-licensed ApolloLander source as a first-class optional browser-playable benchmark environment with one persistent, standardized moon arena. Agent 2 — LunarLander Simulation has been assigned its implementation. This is a planned integration, not a claim that the adaptation has already been completed or verified.

#### 18.1 Original creator — prominent acknowledgement

Original creator: Seb Lee-Delisle. Original project: ApolloLander. Original source code: https://github.com/sebleedelisle/apollolander . Creator’s GitHub: https://github.com/sebleedelisle . Associated Moonlander website provided by the project owner: http://moonlander.seb.ly/ . The repo can be independently verified as ApolloLander by Seb Lee-Delisle; whether the live Moonlander site uses the identical version of this source is not confirmed. Do not claim exact code identity or endorsement without evidence.

Source license: MIT License — Copyright (c) 2017 Seb Lee-Delisle. License text: https://github.com/sebleedelisle/apollolander/blob/master/LICENSE . The MIT license permits use, modification, redistribution and commercial use provided the copyright and permission notice are retained in all copies or substantial portions of the licensed software. 'Free to play' is not the legal basis; the repository’s MIT license is.

Recognition is a project value, not an afterthought. When we reuse original files or substantial code, retain their original credit and license and call out the contribution visibly in our GitHub repository, site, long-form research post, and demo-video descriptions. Credit the original game creator separately from the authors of our experiment framework, model integrations, fixed-map changes, and benchmarks. Do not imply collaboration, sponsorship or endorsement.

#### 18.2 Public-facing credit language (approved template)

README and website: “ApolloLander game originally created by Seb Lee-Delisle (© 2017), released under the MIT License. We adapted its original source for deterministic, fixed-map AI benchmarking, experiment replay, and reward-feedback studies. Original project: https://github.com/sebleedelisle/apollolander . This research adaptation is independent and is not affiliated with or endorsed by Seb Lee-Delisle.”

Blog: “The interactive lunar lander environment builds on ApolloLander, created by Seb Lee-Delisle. We thank Seb for releasing the project under an MIT license, allowing developers to explore and build on the original game. All benchmarking logic, model comparisons, instrumentation and modifications should be attributed to their actual respective authors.”

Video description / public demo credit: “Original ApolloLander game: © 2017 Seb Lee-Delisle — MIT License. Source: https://github.com/sebleedelisle/apollolander . Adapted for an independent AI reward-feedback benchmark.” Include a concise on-screen acknowledgment or ending-card credit when meaningful. Only name the project when its code/assets were actually used in that particular demo.

Repository action items: include the untouched original MIT LICENSE file (or full notice) in vendor/apollolander/LICENSE; list third-party obligations in THIRD_PARTY_NOTICES.md; create a visible CREDITS.md linking the maker and the project; and add credits to the root README and any web UI footer/about page. Do not strip copyright notices or conceal adapted files. Fonts and bundled libraries can have separate rights and must be audited before redistribution.

#### 18.3 Why the actual game rather than merely an HD replay

We want the original ApolloLander game code integrated as a possible playable environment: its own JavaScript rocket dynamics, collisions, terrain, starfield, camera and game UI—not only a video overlay. It uses HTML5 Canvas plus files such as game.js, Lander.js, Landscape.js and InfoDisplay.js. This provides a genuine second experiment environment with recognizable visuals, rather than changing the validated Gymnasium Box2D visuals without disclosure.

Keep existing Gymnasium LunarLander-v3 fully functional and untouched as an independent research baseline. ApolloLander physics, actions, scoring, win conditions and timestep are different; do not compare their raw numerical returns directly or claim the Apollo environment is exactly equivalent to Gymnasium. All four student models must compete inside the same named environment version within a particular cohort.

#### 18.4 Single persistent map design (same moon, fair trials)

Original Landscape.js uses fixed noise.seed(12039) for terrain construction and repeats terrain tiles. However, original game.js restartLevel() randomizes initial horizontal spawn; Landscape.setZones() randomizes landing-zone multipliers; view framing follows the lander. Replace those uncontrolled aspects in BENCHMARK MODE with one fixed mapped arena and a fixed designated landing pad, constant physics configuration, static pad rewards and deterministic reset.

Expose arena_id, arena_version, terrain_seed, pad_coordinates, initial_state, wind/gravity parameters if supported, physics_dt, max_steps, fuel_budget, and an observation/action schema. For comparisons, use the exact same arena and matched initial states across students. Keep camera 'fixed entire arena' for clear side-by-side comparison, with optional follow/zoom mode only for replay. Record coordinate-space transforms and pad bounds in the run manifest.

Prevent automatic map switching, mid-run respawn, randomized crash penalty, bonus multipliers, and camera/view changes from altering the benchmark score. Preserve original arcade mode as a separate optional interactive mode if practical, clearly labeled not comparable to controlled evaluation. Set one static arena for video consistency, but use separate hidden starting states / withheld arena variants later to test generalization rather than rewards that only teach memorization.

#### 18.5 Deterministic physics, inputs and safety

Refactor original wall-clock/requestAnimationFrame-dependent updates into fixed-timestep simulation advancement. Original Lander.js includes Date.now()-based rotation throttling; game.js and Landscape.js use Math.random() for some events. Separate any cosmetic randomness from gameplay, seed all physics-affecting randomness and remove asynchronous timer dependence from evaluation. Rendering FPS must not change simulation results. Run 30/60/144 Hz render checks against one physics sequence.

API proposal: reset(config) -> normalized observation; observe() -> read-only state; step(validated_action) -> next state, scalar reward, terminal status and deterministic metrics; getResult() -> score, terminal classification, landing receipts; replay(trace) -> faithful rendering. Use constrained actions and policy parameters; never execute arbitrary LLM-generated JS in the browser context. Keep timeouts, input checks and isolation boundaries.

Apollo's native controls include rotation/angle and variable thrust, unlike Gymnasium-v3's four discrete actions. Document native control parameterization, bounds, quantization and controller expressiveness. Do not pretend an identical-looking prompt makes two physics/control environments numerically comparable. Use a deterministic scorer with success, crash, fuel, time and trajectory measurements, and guard against hovering/reward exploitation.

#### 18.6 Recording and visual-quality target

Aim for crisp vector-based video, 1920×1080 at 60 FPS, readable rocket at display scale, full fixed landing arena, optional zoomed cinematic replay, legible text and overlays for model, attempt, score and fuel. Use browser Canvas resolution scaling/devicePixelRatio appropriately and verify rendered output rather than assuming setting the export dimensions alone improves clarity. Export recorded traces and MP4/WebM (e.g., browser capture or headless renderer pipeline) while ensuring renderer output cannot change underlying flight results.

Preserve a development clip plus a matched failure/success clip for publication; never fabricate an AI improvement by comparing unrelated starting conditions. Footage must show whether controller came from a reference heuristic, human tuning, random actions or a named LLM. Tie each clip to experiment ID, model ID, environment revision and replay hash.

#### 18.7 Agent ownership and integration gates

Owner: Agent 2 — LunarLander Simulation. Begin with a clean upstream vendor/import and license provenance. Verify the original game can run locally unchanged. Then create benchmark mode with one fixed map and one pad, repeatable resets, programmable controls, a replay pipeline and tests. Preserve prior 39 passing Gymnasium simulation tests and existing output evidence.

Agent 1 — Core Systems: agree on EnvironmentAdapter and EpisodeResult interfaces; no competing foundational contract. Agent 3 — AI Integrations: reuse provider-neutral student calls and constrained controller output; don't hardwire to Gymnasium actions. Agent 4 — Testing & Analytics: treat Apollo and Gymnasium as different environments, add graphics credit notice and tests for score integrity, and produce separate within-environment charts. No master/automatic agent delegation; user controls ownership and merging.

Required proof before adopting ApolloLander for the main study: 1) upstream source and license/asset audit complete; 2) original playable in browser; 3) identical starting snapshot yields identical outcome across at least two runs; 4) one locked map and fixed target clearly visible; 5) scripted control loop works without manual keyboard intervention; 6) reward calculation and physical landing detector independently tested; 7) no-fine-tuning reward loop interoperates with Agent 1 runner; 8) HD replay preserves recorded state/timestamps; 9) reproducible tests pass; 10) references and copyright notice shown correctly in docs and demo.

#### 18.8 Research plan impact and Minecraft portability

The revised environmental sequence is (A) Gymnasium smoke-test and classical heuristic reference, (B) ApolloLander fixed-arena browser environment with its own objective scorer and high-quality clips, (C) cross-vendor adaptation study on one selected environment with identical version/seed protocol, and (D) future MinecraftTaskAdapter in an isolated Paper/Mineflayer world. Choose the primary research environment only after Apollo deterministic gates pass; do not change the primary benchmark halfway through an active study without recording a protocol amendment.

The core system remains StudentClient -> CandidatePolicy -> EnvironmentAdapter -> RewardFeedback -> SessionHistory -> revised CandidatePolicy -> Evaluation. Each game's physics and presentation layer are independent: ApolloRenderer for this moon, native Minecraft capture later. Minecraft integration remains in a disposable world/DB clone with bounded skills and verified completion receipts.

#### 18.9 Implementation-reference links

Upstream ApolloLander: https://github.com/sebleedelisle/apollolander

Maker: https://github.com/sebleedelisle

MIT LICENSE: https://github.com/sebleedelisle/apollolander/blob/master/LICENSE

Original Moonlander website (association stated by project requester; exact source lineage unverified): http://moonlander.seb.ly/

Original fixed-terrain logic: https://github.com/sebleedelisle/apollolander/blob/master/Landscape.js

Original restart, camera and game-loop logic: https://github.com/sebleedelisle/apollolander/blob/master/game.js

Original lander physics: https://github.com/sebleedelisle/apollolander/blob/master/Lander.js

### 19. HISTORICAL research plan — staged feedback, compute allocation, and competition (15 October 2026; superseded as primary by Section 20)

Status: APPROVED RESEARCH DIRECTION; design choices and sample credit prices below are hypotheses, not implemented features or validated experimental results. Official project identity: R.E.A.C.T. — Reward-Enhanced Adaptive Controller Testing. The repository is github.com/ManpreetS2/R.E.A.C.T; the internal Python package may temporarily remain named rewardbench until a separate tested rename.

#### 19.1 Decision and scientific rationale

Decision: finish and validate the existing end-to-end simulator → policy → reward → revised policy workflow before implementing an in-game credit economy or competitive incentives. The baseline research question is: Does objective numerical feedback improve a language model’s ability to revise a constrained controller, relative to comparable revisions without feedback? Only after that result is measured should the project ask whether models can autonomously allocate scarce inference resources more effectively than a fixed or random policy, and whether competitor information improves adaptation.

Reason for staging: coupling success rewards, crash penalties, reasoning purchases, extra trials, parallel agents, and rival data in one initial study makes causal attribution impossible. Early landing luck can snowball into more purchasing power. A failure of the economy would not invalidate the simpler reward-feedback research; likewise a flashy gaming system is not evidence of model-weight learning. Adaptation here is in-context and in the proposed controller. No model weights are modified.

Working assessment (subjective planning judgment, not a measured benchmark): core feedback experiment is a strong, tractable portfolio research question; the all-in-one credit economy is scientifically weak without controls; the isolated resource-allocation study has promising potential but novelty and results are unproven. It is acceptable and informative if adaptive spending loses to a fixed budget.

#### 19.2 Experiment 1 — Establish whether feedback helps (PRIMARY; build first)

Arms: A0, repeated proposals with no previous outcome/reward feedback; A1, previous numerical reward and terminal outcome; optionally A2, same numerical reward plus structured diagnostic metrics (landing accuracy, touchdown speed, fuel, crash classification). Preserve the same base model, policy schema, simulator version, starting conditions, revision count, sampling settings, and total inference-budget ceiling. Use equal-information/prompt-length checks where practical and record actual tokens, rather than claiming perfect input equivalence.

Procedure: initialize independent model sessions, record controller proposal and validity, execute a bounded batch of development episodes, give only the feedback allowed by its assigned arm, request revised controller, and repeat. Evaluate the final selected controller on a separate held-out set with no additional learning. Include random/controller heuristics as context baselines, not as proof of LLM learning. Pre-register conditions, metrics, stopping rules, and model/version identifiers before looking at final results.

Primary outcomes: held-out verified landing success rate and environment-specific native reward; secondary outcomes: reward-versus-revision trajectories, change from first to last revision, time-to-first-success, invalid proposals, crash rate, fuel and touchdown quality, simulation calls, inference tokens, latency, and actual dollars. Report variance and confidence intervals over independent sessions. Do not compare raw ApolloLander and Gymnasium reward values on one scale.

Critical ApolloLander issue: as of the current implementation, repeated trial seed IDs DO NOT change the physical map, initial ship state, or pad. Ten nominal seeds on the same snapshot are NOT ten independent generalization trials. Keep the one fixed recognizable moon map for primary visual identity, but introduce deterministic, pre-specified variations in ship start altitude, horizontal position/velocity, orientation, and possibly fuel; reserve disjoint variations for held-out evaluation. Consider future separate arena variants. All models see exactly matched initial-state schedules within a cohort; keep the untouched fixed-start demonstration as a distinct test, not as evidence of broad generalization.

#### 19.3 Mission scoring — outcome first, process diagnostics second

Proposed human-readable mission-quality index: 100 points maximum, made up of 70 for a physically verified safe landing in the designated pad, up to 10 for fuel efficiency, up to 10 for pad-center precision, and up to 10 for touchdown smoothness. A crash, timeout, or invalid touchdown receives 0 on this presentation index regardless of unused fuel; hard validity and terminal conditions must be determined by physics, not by an LLM judge. Specify normalized measurement ranges, capped terms, and exact touchdown thresholds before the first paid study. Keep each environment’s original numerical reward separately as the primary environment-native measure; do not retroactively replace it with this new score.

Feedback should include objective error diagnostics where assigned: touchdown vertical/horizontal speed relative to safe threshold, position error, attitude, fuel used, terminal reason, and change versus previous attempts. These are observations, not subjective praise. Guard against farming easy partial-score progress, hovering forever, intentional crashes, and sacrificing landing safety to gain fuel/precision points.

#### 19.4 Experiment 2 — Adaptive inference-resource economy (SECONDARY; only after Experiment 1)

Research question: Can a language model choose when to spend scarce inference resources better than a fixed-schedule or random-allocation strategy when evaluated at the same real API cost and attempt limits? This tests planning, risk management, and inference-time resource allocation—not permanent intelligence growth or traditional reinforcement-learning weight updates.

Every model and independent session starts with the SAME initial amount of virtual currency: provisional 20 R.E.A.C.T. Credits (CR). The AI chooses purchases between rounds according to a versioned shop; the purchase decision and opportunity cost are logged. One guaranteed base flight/round prevents a depleted model from losing all ability to participate. Virtual CR are not real dollars; separately enforce an immutable provider/API-level USD cap that no in-game purchase can override.

Provisional shop for calibration (NOT FINAL): extra simulator flight −3 CR; extra explicit strategy critique/reflection −4 CR; higher supported reasoning allowance for one proposal −6 CR; three independently sampled controller proposals −12 CR; access to a verified rival-development performance summary −5 CR (competition-only arm). Each purchased option must map to audited actual token/simulator usage. Where a provider cannot adjust reasoning effort directly, label any substitute extra planning call as a DIFFERENT product; do not pretend heterogeneous APIs expose identical reasoning internals.

Provisional earnings/penalties for a risk-economy variant (NOT FINAL): verified successful landing +10 CR; new verified personal-best SUCCESS +4 CR; crash −5 CR; timeout −3 CR; no negative balances. The project owner favors equal starting credit and a crash penalty, but the crash-penalty condition MUST be isolated and tested against an identical economy with no crash penalty, because penalties can discourage exploration and compound early randomness. Do not make one lucky landing or one early failure determine the whole research outcome.

Economy anti-exploitation rules: cap or time-limit rewards from repeated identical outcomes; grant improvement bonuses only on new validated development milestones; prevent repeated farming of the fixed easy start; use transaction-ledger entries for each credit grant, penalty, and purchase; prohibit hidden credit subsidies, debt, and extra paid calls when no money remains. Freeze the rules per experiment version. Establish opportunity-cost accounting before adjusting reward prices.

Controls: B0 fixed resource schedule with the same expected or matched dollars/tokens/attempts, B1 random legal shopping policy, B2 AI-chosen spending without crash penalty, B3 AI-chosen spending WITH crash penalty. If affordable, separately ablate reasoning purchases, additional flights, and parallel proposals. Give the selection model a bounded, billed decision budget; otherwise unlimited free planning invalidates the allocation comparison. Compare both at identical external budget caps and, where feasible, matched realized costs. Do not rely on final balance alone as the success metric.

Log: starting and ending CR balance; timestamps and reason for each credit award/deduction; available shop catalog and action selected; each extra proposal and simulator episode; output/hidden reasoning token usage as reported; USD cost; controller version ancestry; reward and mission-quality metrics; wall time and terminal status. Analyze success and score PER DOLLAR, held-out performance, crash/recovery frequency, resource allocation shares, and any advantage over fixed/random policies. Model differences and reward-winning outcomes must be validated rather than assumed.

#### 19.5 Experiment 3 — Does competition-style feedback help?

Condition C0: only own verified development outcomes. C1: own outcomes plus a truthful, versioned, precomputed rival/reference controller performance summary from the SAME environment and matched development initial states. The summary must never disclose another model’s private held-out performance or controller source code unless that data is deliberately part of the pre-registered treatment. Equalize spending/resource limits and control for extra text length/information when analyzing. Competition is an experimental prompt treatment, not a claim models feel motivation.

Question: Does rival-performance feedback increase improvement, reliability, and cost-efficiency, or merely cause imitation, wasted tokens, and overfitting? A benchmark winner is established by held-out objective evaluation, not by claims made in a prompt. Do not mix competitive feedback into all baseline groups; optionally test competition × resource allocation only after each individual effect is understood.

#### 19.6 Validity, fairness, and guardrails

Define independent session replication, randomization/counterbalancing of arm order, development versus held-out schedules, stable model identifiers and API dates, pinned prompts, deterministic simulation configurations, complete measurement receipts, and decision rules before collecting headline results. Include repeated independent sessions per model, confidence intervals, and appropriate tests/effect sizes. Do not publish claims from a single trajectory or from repeated deterministic starts described as independent trials.

Pre-register success thresholds and credit prices; changing a reward formula after seeing outcomes requires a documented new experiment version. Keep real spending caps separate from virtual credits, and include all hidden reasoning/output tokens, retries, parallel model calls, and reflection calls in the real spend ledger. API prices and model availability must be checked against current provider terms just before the pilot. No purchasing API credits or triggering paid requests without human approval.

Safety: restrict proposed controllers to validated numeric schemas; prohibit executing raw LLM-written JavaScript or Python; sandbox every simulator; use authentic records for reports and gameplay. Mark heuristic/human-guidance/stand-in-model demonstrations explicitly. ApolloLander source credit: Seb Lee-Delisle (MIT, ©2017) and maintain bundled third-party notices.

#### 19.7 When to buy API credits (GO / NO-GO gate)

NO-GO now. Begin with mocked and offline tests only. GO for a SMALL, explicitly approved live pilot only after: (1) integrated tests are green on the target commit; (2) an end-to-end mock-model MULTI-REVISION trial on a REAL simulator passes, in BOTH numerical-feedback and no-feedback modes; (3) developmental and genuinely distinct withheld starts are tested without leakage; (4) metrics, SQLite logs, reproducibility manifest, and cost ledger are verified; (5) deterministic replay/video captures match logged episodes; (6) provider model IDs, auth variables, current price schedules, model-specific token accounting, and hard spending caps are checked; (7) spending and attempt ceilings are user-approved. Start with ONE provider, one or two calls, tiny ceilings, and inspect returned controller validity and usage. Scale to the four-model cohort only after the pilot passes. Never equate holding an API key with authorization for paid experiments.

#### 19.8 Execution order and deliverables

Milestone 1 — Finish real offline R.E.A.C.T. loop: validated model-policy schema → simulator run → objective reward and diagnostics → logged next revision → held-out replay. Resolve fixed-start generalization and verify no-feedback isolation. Create real, labeled recordings.

Milestone 2 — Run approved small real-model smoke/pilot and Experiment 1; publish only reproducible logs, score curves, uncertainty, spending, and clear limitations. Ensure each model gets matched conditions and cap.

Milestone 3 — Implement and validate the optional virtual credit ledger and purchasing interface with mock models; calibrate prices using measured token/simulator costs; then Experiment 2 fixed/random versus AI allocation, with crash penalties isolated.

Milestone 4 — Experiment 3 rival-feedback treatment, optional later factorial interactions and robustness study. Do not let scope creep block baseline results.

Milestone 5 — After genuine evidence: record side-by-side model flights linked to run IDs and trace hashes; generate figures, a research write-up, README/portfolio presentation, and only then announce publicly. Minecraft AI Civilization remains future environment expansion, not a prerequisite for the LunarLander/ApolloLander study.

Decision record: user agreed to prioritize proving the original adaptation hypothesis before implementing the economy, while keeping equal starting virtual credits, elective purchases of reasoning/parallel proposals/extra flights, and crash penalties as a distinct controlled follow-on experiment. No claim that any particular model will win, that models' weights improve, or that complex incentive schemes necessarily outperform simple baselines.

### 20. CURRENT RESEARCH DIRECTION — Blind visual game learning (17 October 2026)

Decision status: APPROVED NEW PRIMARY DIRECTION. This section supersedes earlier sections wherever they describe constrained-controller parameter tuning as the project's primary near-term scientific experiment. Earlier sections remain as a historical research track and a useful comparator; no prior engineering result is erased. The official project name remains R.E.A.C.T. — Reward-Enhanced Adaptive Controller Testing.

#### 20.1 Central question and experimental principle

PRIMARY QUESTION: Can an AI learn to play an unfamiliar game through visual observation, keyboard actions, and experience alone? The AI player receives exactly one gameplay instruction: “Land the rocket.” No control map, formulas, game manual, landing strategy, candidate controllers, source files, or previous successful trajectories are supplied. The player must discover the mechanics, select its own actions, and improve—or fail to improve—through actual consequences. The aim is to measure behavior, not to produce a predetermined crash-to-success montage.

The model is not a blank-slate organism: pretrained knowledge about games, rockets, and keyboard conventions may influence its first attempt. “Blind” here means no experiment-specific privileged information or demonstrations, not absence of general prior knowledge. A fresh Cursor conversation alone is not a security boundary.

#### 20.2 What we have already learned (keep these results separate)

Published R.E.A.C.T. engineering v1: https://github.com/ManpreetS2/R.E.A.C.T ; public main merge commit 5e624c7 (PR #2), CI green; at release 260 Python tests and Node physics checks passed according to the release report. Four provider adapters and the constrained-controller numerical/no-feedback benchmark path were mock-tested, but genuine multi-model adaptation findings have not been established. Do not rebrand this infrastructure as proof of blind visual gameplay.

Cursor-assisted controller TUNING on the custom Node-based ApolloLander research simulator: eight guidance-controller revisions on development seeds 0–7. Revision 1 landed 8/8 with mean reward 76.862; Revision 5 landed 8/8 with mean reward 87.185; fuel used decreased from roughly 524.6 to 314.6. The model tuned an existing 18-parameter guidance algorithm; it was not learning keyboard controls from screenshots. Revision 7 produced eight hard landings with lower reported mean reward 28.206. All such figures are development evidence, not sealed generalization.

Original-game bridge on a second MacBook: opt-in Playwright control of original ApolloLander upstream physics and browser rendering (upstream files preserved). Frozen Revision 5 controller landed perfectly in a fixed-start case; repeating seeds 0–7 there reproduced one identical physical spawn, not eight independent starts. Agent 2 subsequently added opt-in versioned research spawn overrides to the original-game bridge; the unchanged controller then perfectly landed on eight distinct development starts, mean R.E.A.C.T. reward 84.271, mean remaining fuel 735.4, native original-game score 50 each. These are still development starts, use the existing guidance template, and are NOT findings about blind visual play. This newer original-game bridge work is reported locally on the second MacBook and has not been confirmed merged into published main.

#### 20.3 Three environments that must never be conflated

A. Original upstream fixed-start ApolloLander: Seb Lee-Delisle's original browser presentation and physics, with a deterministic step-mode bridge. One fixed physical starting state; changed arbitrary seed IDs do not imply independent generalization.

B. Original upstream-physics RESEARCH STARTS: the same upstream lander/game logic, collision and scoring, but documented, deterministic bridge overrides of initial x/y/vx/vy/rotation (and only predeclared optional fuel changes), using a versioned schedule such as apollolander.starts.v1. The terrain, pad, and verifier remain fixed. Label deviations: paused step-mode rather than Date.now catch-up, seeded cosmetic randomness, fixed multipliers where used, and muted audio. Native score and R.E.A.C.T. reward must remain separately labeled.

C. Published custom Node-reimplemented ApolloLander simulator and Gymnasium LunarLander: separate historical benchmarking environments; do not pretend footage, physics or scores are the original upstream game. Do not silently migrate an existing experiment between these environment IDs.

Original creator credit: Seb Lee-Delisle, © 2017 MIT; preserve upstream/LICENSE and THIRD_PARTY.md. No implied affiliation.

#### 20.4 Blind player observation/action contract

The future player has only two generic gameplay capabilities: observe() returns a screenshot of the actual browser game as the MODEL sees it; act(keys, frames) holds specified keyboard keys for a bounded number of deterministic simulation frames and returns a fresh screenshot. A trusted, separately isolated referee controls episode reset, terminal detection, recording, and integrity checks. The player must not receive structured x/y/velocity/fuel telemetry through tools unless it is visibly rendered on the original game screen; no hidden DOM, JS, console, browser DevTools, physics equations, scoring internals or raw flight JSON.

Advance the real upstream game in pause/step mode while the model is reasoning. Do not require real-time 60-Hz inference or claim the model personally makes every physics-frame decision. Set a maximum frame batch (proposed <=120 frames) and enforce a per-episode simulation frame budget. Tool names, descriptions, and available key enumeration must avoid telling the player which key accelerates, rotates, or restarts. If the original title screen/HUD explicitly reveals control instructions, mask only those instructions consistently and document the visible-image modification; do not hide genuine outcome feedback. Verify screenshots are actually visible to the model (not inaccessible file paths).

Do not create a premade guidance controller, tune 18 existing parameters, or allow submitted JavaScript/Python to run in the privileged main process as a substitute for blind keyboard play.

#### 20.5 Isolation and anti-contamination requirements

Agent 2 prepares the trusted test environment and must NOT attempt to solve the game in that setup session. The future player runs in a new conversation and a separately constrained workspace/browser interface, ideally no repository checkout or shell/filesystem access at all. It cannot read src/rewardbench, upstream JavaScript, pre-existing controller JSON, tuning reports, successful videos, run databases, or private referee state. A mere instruction “don't read source” is insufficient if tooling can still access it. Verify the isolation technically; if Cursor cannot support a genuinely screenshot-and-keyboard-only player, STOP and state the blocker rather than quietly weakening the protocol. A dedicated constrained tool runner or other separately sandboxed player may be necessary.

Keep only game-visible information in model responses. The independent referee may access private state to verify landings and terminal outcomes, but never leak it into the model's observation. Record exactly which screenshots, button presses, tool descriptions and previous messages were visible to the player; document any contamination or prior exposure. No human hints or mid-run rescue.

#### 20.6 Pilot protocol: the AI gets only “Land the rocket.”

Pre-register a fixed, finite session budget BEFORE the first model attempt: proposal: up to 20 complete gameplay episodes, maximum 8,000 simulated physics frames per episode, maximum 120 frames per act() call, and separately declared model-turn/tool-use/time limits. The referee handles automatic reset after terminal state, with no control-map hints to the player. Begin with original-game fixed-start mode (same physical start per trial), then only as a SEPARATE preregistered study use research-mode varied starts for transfer/generalization. Do not alter terrain, gravity, scoring, permitted keys, or difficulty halfway through a measured session because success came too early or failure looked uninteresting.

On first view the model sees only the game image and instruction “Land the rocket.” It explores keyboard inputs, watches resulting frames, and decides what to try next. Every action, elapsed simulated frames, screenshot response and game terminal outcome is saved in order. If it lands on attempt one, report first-attempt success; if it crashes repeatedly, report those failures; if it never lands, report non-success. Never insert manufactured failures, cherry-pick a highlight to misrepresent the full session, or pre-load successful controller strategies. Exploration is allowed; artificial crash narratives are not.

For a meaningful independent comparison use several fresh player sessions/contexts and record available model/provider/version and Cursor subscription usage; one Cursor run is a feasibility case study, not a universal AI capability claim.

#### 20.7 What to measure and what counts as learning

PRIMARY practical outcomes: game-verified landing (perfect/hard/other), episodes-to-first-success, success rate across episodes, and whether action sequences change in a direction consistent with observed failures. SECONDARY: score, crash classification, collision details (referee only), total simulated frames, number of screenshot observations, number of tool actions, wall-clock time, fuel when visually available, recorded controller/action trace, and model usage/cost if reported by its platform. Separate upstream native score from any computed R.E.A.C.T. score.

Retain immutable chronological trajectories: actual screenshots shown to the model; requested keys/frames; game images at each step; episode IDs; terminal evidence; native HUD screenshots; complete browser recordings; hashes and timestamps; environment version and any reset overrides. A model's own assertion “I landed” is not a success certificate. A trusted deterministic referee establishes objective terminal status and replay correspondence. Save the model's visible decisions or concise explicit justifications, not purported hidden private chain-of-thought.

This tests adaptation during the game/session and its conversation context—not gradient training, RL weight updates, or lasting changes to the foundation model. Visual consequences alone are feedback. Do not infer a causal advantage of numerical rewards without running matched treatment groups. Distinguish novelty discovery, control discovery, memory/reasoning, and fixed-start memorization.

#### 20.8 Research controls, feedback ablations, and unseen evaluation

FIRST demonstrate the authentic blind-visual player can interact with the upstream game safely. THEN run independent-sessions comparisons: visual-outcome-only condition vs visual outcome PLUS numeric score/diagnostics, using matched simulator conditions, equal or disclosed budgets, counterbalanced ordering and fresh sessions. Where possible include a no-history/stateless comparison that sees similar visuals but not previous episode memory, to test whether accumulated experience matters. Additional model families are optional subsequent replications, not a launch prerequisite. Never describe screenshots-plus-controls as a no-feedback condition: observations and game outcomes are feedback.

For varied-start evaluation, predeclare development and untouched final-start cohorts, freeze the player's discovered strategy before evaluating final starts, and never feed final evaluation outcomes back into a development session. Prior test/demonstration seeds 1000000–1000007 were burned for engineering evidence; 2000000–2000015 were reserved for the earlier controller benchmark and must not be exposed or casually reassigned to this new protocol. Choose new nonoverlapping versioned cohorts for the blind-gameplay study with explicit separation, without tuning against the reserved evaluation set.

Because the AI acts interactively rather than submitting one frozen numeric policy, specify an evaluation mechanism that preserves the player's learned context/strategy while preventing any further learning from held-out outcomes, or state clearly that true held-out evaluation of an interactive policy is not yet implemented. Never assert generalization solely from repeated deterministic resets.

#### 20.9 Agent responsibilities and immediate build order

Agent 2 — Environments, NEXT: implement and validate the original-upstream browser screenshot/key-press/frame-step bridge under a true least-privilege player interface. Prepare sandboxing, deterministic episode reset, protected referee, screenshot delivery, outcome verification, input and frame caps, and full action/video logs. Run scripted infrastructure checks ONLY; do not have the setup agent play or optimize. Return a go/no-go report and exact commands for launching a separate blind player. Keep all old experimental evidence intact.

Agent 1 — Core Systems: adapt experiment schemas and session logging only when needed to represent screenshot/action/episode timelines, reset and independent player runs. Do not retrofit 18-parameter guidance as a hidden decision-maker.

Agent 3 — AI Integrations: defer live provider API work. Only after the visual player is genuinely isolated, investigate which supported model/tool runtime can receive rendered screenshots and issue bounded key actions. Do not use keys or spend funds without renewed explicit user approval and configured billing protections.

Agent 4 — Testing & Analytics: audit experiment independence, match attempted actions to recordings, preserve licensing, build honest chronological charts and a reviewer-ready visual case study. Own PLAN.md and final integration. Do not merge/push new blind-game code to public main without explicit owner approval. Other research tracks (virtual credits, rival competition, Minecraft) remain deferred.

#### 20.10 Stop conditions and launch gates

GO for a zero-provider-API local trial only if: (1) genuine original-game browser rendering is shown to the player; (2) action batches advance deterministic upstream physics, not the custom Node simulator; (3) source and hidden game state are inaccessible to the player; (4) exactly which keys can be attempted is not described as a solution; (5) complete timestamped screenshots/actions/episode results are retained; (6) terminal claims are independently checked; (7) crash and success clips are authentic game footage; (8) model can actually consume screenshots; (9) tests show step-frame caps, restart behavior, and no data leakage; (10) no calls to commercial model APIs are required by this phase.

NO-GO if Cursor's tool/working-directory permissions cannot be isolated, if screenshots cannot reach the model, if the bridge substitutes the prebuilt guidance controller, if gameplay scores leak through a privileged API, or if unapproved API spending would occur. Explain the specific blocker and propose a safe contained alternative, not a silently less-blind task.

#### 20.11 Expected outputs and publication ethics

First deliverable: reproducible isolated blind-play runner and one honest pilot including all attempts from first screenshot to final episode, even if it fails. Second: matched visual-only versus visual-plus-numeric-score comparisons with repeated independent sessions, including uncertainty rather than cherry-picked reward curves. Third: a short original-game video that uses actual browser-rendered flight segments and transparently shows chronological failures or first-try success. Link raw traces, timing, screenshot hashes, environment revisions, controller/action decisions, and independent terminal receipts. Label older Cursor tuned-guidance results as HISTORICAL AUTOPILOT TUNING, not blind-play results.

Public story: “Can an AI figure out how to land a rocket when all it gets is the screen and a keyboard?” Credits: Original ApolloLander by Seb Lee-Delisle (MIT, ©2017). Original source https://github.com/sebleedelisle/apollolander . R.E.A.C.T. is independent; no endorsement. No manufactured crash montage, no invented flight metrics, and no model rankings without genuine comparable evaluations.

#### 20.12 Decision record and present status

Owner's explicit decision (17 October 2026): switch the PRIMARY experiment from constrained autopilot-parameter tuning to an open-ended game-playing task where the model is told only “Land the rocket” and must discover keyboard control through screenshots and trial-and-error. The objective is observing whether the AI discovers how to play, not engineering an outcome. Earlier R.E.A.C.T. offline v1, provider adapters, published repo, Cursor-guidance tuning and original-game-bridge successes are retained as separate valuable engineering and historical experiments.

CURRENT IMPLEMENTATION STATUS AT THIS REVISION: blind screenshot/action-only environment NOT YET VERIFIED OR PLAYED; the latest proposed next action is for Agent 2 to build and validate its isolated environment and stop before solving. Existing historical bridge is opt-in and locally reported; it is not a substitute for the blind visual player. No paid API call is required or authorized by this documentation update.

### OPTIONAL OPEN-SOURCE REFERENCES — SCREEN-ONLY CONTROL & PRESENTATION (24 OCTOBER 2026)

Status: research-only references, not integrated or a change to the approved blind ApolloLander experiment. Preserve the existing hard boundary: the player only sees permitted screenshots and submits bounded actions; protected game state and rewards remain inaccessible except through authorized experiment arms.

#### CODEX MINECRAFT GAMEPLAY — CONTROL-LOOP DESIGN STUDY

GitHub: https://github.com/wz1119/Codex-Minecraft-Gameplay

Relevance: screenshot observation, synthetic-image checks, bounded keyboard/mouse execution, interruptibility, before/after verification, stall handling. Study its design for eventual Minecraft portability and compare with R.E.A.C.T.'s own browser screenshot/action adapter. Do not transplant Windows-specific input into the browser physics harness, use it as a shortcut to privileged game state, or change the frozen experiment protocol. Apache-2.0; verify any copied code and required notices.

#### RECORDLY — OPTIONAL DEMO/RESEARCH VIDEO EDITOR

GitHub: https://github.com/webadderallorg/Recordly

Relevance: polished screen-only demonstration videos with zooms, cursor emphasis, annotated timelines, and MP4/GIF export. First keep immutable original screenshots, trial logs, and unedited screen recordings; edit only a separate presentation copy. Never present cropped/highlighted gameplay as the full trial record or conceal failed attempts. Recordly is a separate AGPL-3.0 desktop tool; use it only for public demo editing after testing the Windows audio/video export and checking for visible keys/identifiers.

Decision: small optional references when the genuine visual-play pilot is proven; not a new API-cost or development workstream.

