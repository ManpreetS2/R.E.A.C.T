# First genuine LLM call — execution checklist

This is a **connectivity and controller-generation pilot**, not evidence of
learning. One paid `propose` cannot support adaptation claims.

Config: `configs/apollolander_pilot_openai_gpt54mini.yaml`

## Pre-flight (owner)

- [ ] Approve a USD spend ceiling (software file uses `$0.05`; set **vendor** billing limits separately).
- [ ] Confirm OpenAI account billing alerts / hard limits in the provider console.
- [ ] `export OPENAI_API_KEY=...` in the local shell only — never commit, never paste into chat/logs.
- [ ] Confirm no other process is using the same key for unbounded jobs.
- [ ] Read the YAML: `gpt-5.4-mini`, `max_output_tokens: 800`, `reasoning_effort: none`, `max_model_retries: 0`.

## Offline agreement checks (already tested; re-run if desired)

```bash
python examples/providers/dry_run_first_call.py
python -m pytest tests/providers/test_first_call_safety.py tests/core/test_live_cli.py -q
```

Expected software behavior:

- Live without `--i-authorize-paid-api-calls` → refuse  
- Missing key → refuse before network  
- At most **one new** paid `propose` per CLI process, then pause  
- No automatic continuation  

## Authorized first invocation

```bash
python -m rewardbench.run \
  --config configs/apollolander_pilot_openai_gpt54mini.yaml \
  --mode live --i-authorize-paid-api-calls
```

Do **not** pass `--authorize-continuation` on this first run.

## Artifacts to inspect after pause

| Artifact | Where | What to check |
| --- | --- | --- |
| Run state | CLI stdout | `run_state: paused` (not a completed learning experiment) |
| Proposed controller | SQLite `attempts` | `parameters_json`, `valid`, `validation_error` |
| Tokens / cost | SQLite `attempts` | `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `estimated_cost_usd` |
| Simulator episode | SQLite `episodes` | reward, success/crash, seed |
| Optional flight | `runs/.../*.flight.json` | replay with `verify_flight_record` if recorded |

```bash
sqlite3 runs/apollolander_pilot_openai_gpt54mini.sqlite \
  "SELECT revision_index, valid, prompt_tokens, completion_tokens, estimated_cost_usd, substr(parameters_json,1,120) FROM attempts;"
```

## After inspection

- If invalid / truncated / unexpected spend → **stop**. Do not continue.
- If continuing a second revision later: explicitly approve again and pass
  `--authorize-continuation` (does not repeat call 1).
- Label any write-up: **single-call pilot**, not adaptation evidence.
