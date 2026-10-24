# First genuine LLM comparison protocol (not executed)

The offline v1 release establishes infrastructure only. No paired real-model
result or feedback-effect claim is established. Paid development and final
research evaluation each require explicit owner approval. A ChatGPT/Codex
subscription does not supply provider API billing credits.

## Two separate future stages

1. **Connectivity/feasibility:** optionally use the existing pilot templates,
   one authorized call per invocation, then a separately approved continuation.
   Their default fixed-start settings and previously used engineering holdout
   make this a pipeline check, not the registered research study. Do not consume
   the reserved cohort for a connectivity demonstration.
2. **Genuine paired study:** create study-specific configs from the reviewed
   pilot templates, with the exact changes below. Freeze the plan and config
   hashes before the first paid call. Execute only after owner approval.

## Freeze the study specification

- One exact provider/model version for both arms; record any returned resolved
  model id. Record prompt version, pricing catalog, applied/ignored settings,
  request ids, costs, tokens, failures, simulator version, git SHA and dependency
  versions. Provider estimates are not invoices.
- Two conditions: `numerical_reward` and `no_feedback`. The current numerical
  prompt includes reward **plus** success/crash, steps, fuel and start-state
  metrics. Pre-register this as richer simulator feedback versus none. If the
  intended hypothesis is scalar reward's incremental effect, use the matched
  information control below; the present intervention cannot isolate that effect.
- Match all model settings, schema, history window, simulator parameters,
  retry policy, revision and episode budgets across arms. Change only condition,
  experiment name, database path and explanatory notes/paired-config pointers.
- Set `metadata.adapter_kwargs` identically to `research_mode: true`,
  `start_schedule_version: apollolander.starts.v1`, `vary_fuel: false`,
  `locked_camera: true`, `max_steps: 8000`; set `max_episode_steps: 8000`.
  Existing connectivity pilot templates do **not** enable research mode.
- Small feasibility study: `num_revisions: 2`, `episodes_per_revision: 8`,
  `development_seeds: [0,1,2,3,4,5,6,7]`, one fixed master seed for both arms,
  `history_window: 4`, `max_model_retries: 0`. The
  `matched-development.v2` schedule reuses all eight starts each revision.
- Set matching limits permitting exactly two calls, two revisions and sixteen
  development episodes per arm. Explicitly approve the token, wall-time and
  dollar limits; they are ceilings, not guaranteed vendor billing limits.
  Retain the one-new-call-per-invocation gate. Any output ceiling/reasoning
  setting must be accepted identically by the selected model and preflight.
- Research cohort: `held_out_seeds` exactly `2000000–2000015`, identity
  `apollolander.final_eval.v1`. List integers only before freeze; do not derive,
  preview, record or score its physical starts. Seeds `1000000–1000007` are
  previously used engineering/demo data and cannot replace this cohort.
- Pre-declare selection `last_valid_selected`, treatment of invalid controllers,
  billed failures, incomplete arms, missing episodes, and any stopping rule.
  Never replace a failed run silently or tune after seeing final evaluation.
- Declare independent paired replicate count and model-sampling policy. One
  paired replicate with two revisions is a feasibility result, not a reliable
  effect estimate or ranking. More replicates require a new explicit budget.

## Authorized execution order

1. Re-run offline tests and inspect the paired config diff. Check pricing and
   provider limits against current official information before requesting spend
   approval. Credentials remain private; do not commit or paste them into logs.
2. Run each arm's first development call with the existing explicit live
   authorization flag. Review the stored attempt and applied settings, then
   authorize continuation separately. Counterbalance/order the paired arms as
   pre-registered; do not change settings between conditions.
3. Confirm both arms completed the declared budget. Freeze final controllers
   from development only and archive source attempt identities and hashes.
   Do not select by final evaluation reward.
4. Only after explicit approval to consume the reserved cohort, use the
   dedicated `rewardbench.heldout` CLI on those completed study databases.
   It makes no model calls. Save flight records, SQLite hashes and final reports;
   never route held-out scores back into prompts or tune another revision.
5. Report all outcomes, including worse rewards and failures. Separate
   development, engineering/demo and final research evidence. Compare frozen
   policies on paired seeds; uncertainty must respect paired seeds and
   independent experiment replicates. Session resumes are not extra replicates.
   Do not pool Gymnasium, ApolloLander, scripted controllers, or PPO training.

## Smallest future control for scalar reward (recommendation only)

Keep the existing offline conditions and their evidence unchanged. A separate
experiment should compare **identical non-reward information, with versus without
the true scalar reward**. Removing metrics only from the numerical arm would not
hold the information supplied by the current arms constant.

For the smallest controlled revision probe, start each pair from the same frozen
baseline controller and a single previously recorded development transcript.
Both model requests receive identical controller history, validity information,
success/crash outcomes, steps, fuel/start metrics, schema, system instructions,
revision index and model settings. The only intervention is the scalar reward
field: its true value versus a fixed withheld marker. Diff the rendered requests
before any approved call to verify that treatment is their sole difference.
Use separate conversations, randomize/counterbalance request order, and permit
one proposal per condition (two calls per pair). Do not retry/select for success.

Immediately freeze both proposals and score them with no further model calls on
the same pre-declared engineering evaluation panel. Compare their paired reward
changes from the common baseline; keep invalid proposals and billed failures in
the pre-declared accounting. Repeat independently paired draws to estimate
uncertainty; one two-call pair checks feasibility and cannot establish an effect.
Pre-register replicate count, sampling policy, budget and failure handling before
approval. This identifies the effect of explicitly displaying scalar reward
conditional on those fixed metrics, even if the reward is inferable from them.
It does not yet establish long-horizon closed-loop adaptation.

This design requires a separately reviewed prompt/control implementation; it is
not implemented or executed by this integration PR. It needs paid-call approval
before using a real model. Use previously exposed demo evaluation cases for a
feasibility check; do not consume `apollolander.final_eval.v1` for this probe.

No command in this document authorizes spending or final-cohort execution.
