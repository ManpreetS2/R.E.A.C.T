# First real-LLM study: launch guide

**STATUS: NOT EXECUTED.** No command in this file has been run against a provider. Do not run any
live command until the owner has approved the provider, the model and a total USD ceiling in writing
(template in section 1). Design and outcomes: `FIRST_LLM_STUDY_PROTOCOL.md`. Spend: `FIRST_LLM_STUDY_BUDGET.md`.

**Prompt history.** The first live request (prompt `rewardbench.prompts.v2`, experiment
`exp_26eb2593d31e4a72c041`, `runs/first-llm-study/pilot/`) returned the schema document instead of a controller
(`unknown controller policy None`; one call, about $0.0026). That database is kept for audit and is never resumed;
its configs are archived byte-for-byte in `configs/study/archive/prompt_v2/`. The current configs use
`rewardbench.prompts.v3`, which is recorded in `metadata.prompt_template` (so it changes the experiment id), tagged
`p3` in names, and written under `runs/first-llm-study/pilot-p3/`. Live preflight refuses a config whose recorded
prompt template differs from the code. The ledger scan still counts the v2 attempt toward `--total-usd-ceiling`.

Safeguards that stay in force (existing code, covered by tests): no paid call without
`--i-authorize-paid-api-calls`; no key, no unpriced model or no bounded budget means refusal before any
network use; `max_model_retries: 0`; **one new paid call per config per invocation**; another call only with
`--authorize-continuation` after you have reviewed stored results; terminal `failed` / `budget_exhausted`
sessions are not resumed; the reserved final cohort is only referenced by study-tier configs and the
operator refuses `--heldout` on it.

## 0. Free checks (safe to run any time; no key, no network)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev,analysis,environments]"
python -m pytest tests -q && node frontend/apollolander/experiment/physics.test.js
python -m rewardbench.study write-configs --check   # committed configs equal the generator
python -m rewardbench.study preflight               # real live preflight, placeholder key, matched arms
python -m rewardbench.study budget                  # worst-case spend tables
python -m rewardbench.study rehearse --out runs/first-llm-study-rehearsal   # scripted rehearsal + audit
```

## 1. Owner approval record (fill in; nothing runs without it)

```
Provider:                 openai            (proposal)
Model:                    gpt-5.4-mini      (proposal)
Tier(s) approved:         [ ] first call per arm  [ ] pilot  [ ] study
Total USD ceiling:        $________  (must be >= the worst case of the approved tiers; see budget doc)
API key exported by owner in own shell: [ ]    Provider-side hard limit set: [ ]
Approved by / date:       ____________
```

```bash
read -s OPENAI_API_KEY && export OPENAI_API_KEY   # hidden prompt; your shell only. Never commit it or paste it into chat or a log.
export APPROVED_CEILING_USD=...                    # the total you wrote above; every live command requires it
```

Billing and provider-side limits (what OpenAI can and cannot enforce) are in `OPENAI_BILLING_SETUP.md`: read it
before buying credits. `--total-usd-ceiling` is a software guard over the summed recorded spend of every live
database under the parent of `--out`; the provider-side hard limit and a small prepaid balance are the controls
that do not depend on this code.

## 2. FIRST PAID MODEL CALL: NOT EXECUTED

One call (revision 0 of arm A, `no_feedback`), then the session pauses. Worst-case cost of this call: see the budget doc.

```bash
python -m rewardbench.operate run --mode live --i-authorize-paid-api-calls --total-usd-ceiling "$APPROVED_CEILING_USD" --config configs/study/pilot_no_feedback.yaml --out runs/first-llm-study/pilot-p3
```

Review before anything else:

```bash
python -m rewardbench.operate status --out runs/first-llm-study/pilot-p3
cat runs/first-llm-study/pilot-p3/prompts/llmstudy-pilot-openai-gpt54mini-nofeedback-p3-r1/revision_00_call_00.txt   # exactly what was sent
sqlite3 runs/first-llm-study/pilot-p3/llmstudy-pilot-openai-gpt54mini-nofeedback-p3-r1.sqlite \
  "SELECT revision_index, valid, provider, model_id, total_tokens, estimated_cost_usd, parameters_json FROM attempts"
```

Stop and investigate (do not continue) if: the controller is invalid or unparsable, `model_id` is not the
approved model, tokens/cost exceed the worst-case bound, or `logs/*.run.log` shows an error.

## 3. First call of the other two arms (still revision 0)

```bash
python -m rewardbench.operate run --mode live --i-authorize-paid-api-calls --total-usd-ceiling "$APPROVED_CEILING_USD" --config configs/study/pilot_reward_only.yaml --out runs/first-llm-study/pilot-p3
python -m rewardbench.operate run --mode live --i-authorize-paid-api-calls --total-usd-ceiling "$APPROVED_CEILING_USD" --config configs/study/pilot_numerical_reward.yaml --out runs/first-llm-study/pilot-p3
```

## 4. Pilot continuation (revisions 1-3), each step a separate explicit command

After reviewing the stored results of the previous step, advance **every arm by one paid call**:

```bash
python -m rewardbench.operate run --mode live --i-authorize-paid-api-calls --authorize-continuation \
  --total-usd-ceiling "$APPROVED_CEILING_USD" \
  --config configs/study/pilot_no_feedback.yaml --config configs/study/pilot_reward_only.yaml \
  --config configs/study/pilot_numerical_reward.yaml --out runs/first-llm-study/pilot-p3
```

Repeat three times (revisions 1, 2, 3). Each repetition shows the new prompt, controller change and the
simulator rewards of the previous revision. An interrupted run resumes with the same command and the same `--out`.

## 5. Free evaluation and reports after the pilot (no model calls; engineering seeds only)

```bash
for arm in nofeedback rewardonly numericalreward; do
  python -m rewardbench.heldout --database runs/first-llm-study/pilot-p3/llmstudy-pilot-openai-gpt54mini-$arm-p3-r1.sqlite \
    --source-config configs/study/pilot_$(echo $arm | sed 's/nofeedback/no_feedback/;s/rewardonly/reward_only/;s/numericalreward/numerical_reward/').yaml \
    --record-dir runs/first-llm-study/pilot-p3/heldout-flights/$arm
  python -m rewardbench.analysis report --logs runs/first-llm-study/pilot-p3/llmstudy-pilot-openai-gpt54mini-$arm-p3-r1.sqlite \
    --out runs/first-llm-study/pilot-p3/reports/$arm
done
```

## 6. Inspect results and flights

```bash
python -m rewardbench.operate status --out runs/first-llm-study/pilot-p3
python3 -m http.server 8767
# http://localhost:8767/frontend/apollolander/experiment/replay.html?file=/runs/first-llm-study/pilot-p3/flights/<experiment_id>/<flight>.flight.json
```

The page replays the recorded actions through the same physics and shows `REPLAY MATCHES RECORD` or the exact
mismatch. Live-model flights are labeled `model_generated`; scripted ones are labeled as non-LLM.

## 7. Study tier (separate approval, not part of the pilot)

```bash
python -m rewardbench.study write-configs --tier study --out runs/first-llm-study/study-configs
```

writes 15 matched configs (`study_<arm>[_rK].yaml`, K = 2..5). Run replicates in rotated arm order
(r1: A,B,C; r2: B,C,A; r3: C,A,B; r4: A,B,C; r5: B,C,A), each with the section 2-4 pattern and its own `--out`
(for example `runs/first-llm-study/study-r1`), six paid calls per arm.

**Final evaluation: NOT EXECUTED.** Only after every session is complete, the frozen controllers and their
source attempt ids have been reviewed, and the owner explicitly approves consuming the reserved cohort
(`2000000-2000015`, `apollolander.final_eval.v1`):

```bash
python -m rewardbench.heldout --database runs/first-llm-study/study-r1/<name>.sqlite \
  --source-config runs/first-llm-study/study-configs/study_<arm>.yaml --record-dir runs/first-llm-study/study-r1/final-flights/<arm>
```

(no model calls; one command per session database). Report every session, including failures and worse rewards.

## 8. Failure handling summary

| Situation | Behaviour | Your action |
| --- | --- | --- |
| Missing key / unpriced model / budget too small | refused before any network use | fix config or approval |
| Invalid or unparsable controller | recorded, not flown, shown to the model as invalid | continue only if within the pilot go/no-go rule |
| Provider error on a billed call | session ends `failed`; no retry | report; replacement needs new approval as a new replicate |
| Process killed | re-run the same command; stored attempts are not re-billed | review `status` first |
| Aggregate ceiling would be exceeded | call refused before any request; session paused (resumable) | raise `APPROVED_CEILING_USD` only by new written approval, then re-run with `--authorize-continuation` |
| Per-experiment budget reached | `budget_exhausted` (terminal) | stop; start a new replicate only with new written approval |
| OpenAI returns 429 `project_spend_limit_exceeded` / `credit_balance_exhausted` / rate limit | no retry (`max_model_retries: 0`); the session ends `failed` (terminal) although nothing was billed | fix the limit or credits, then start the pilot again in a **new** `--out` under the same ledger root so earlier spend still counts |
