# Operating R.E.A.C.T.

`python -m rewardbench.operate` runs the existing pieces in order — `rewardbench.run`
→ `rewardbench.heldout` → `rewardbench.analysis report` — into one output directory.
It adds no simulation, storage, or provider logic.

## Free, offline (mock) mode

```bash
python -m rewardbench.operate run \
  --config configs/apollolander_offline_development_nofeedback.yaml \
  --config configs/apollolander_offline_development_rewardonly.yaml \
  --config configs/apollolander_offline_development_numerical.yaml \
  --heldout --out runs/my-demo
```

Mock mode uses `ScriptedFeedbackModel` with the real ApolloLander physics. It
proves the machinery; it is **not** a language-model result. Every run prints a
MOCK/LIVE banner and `status` labels each database `[MOCK]` or `[LIVE]`.

Output layout under `--out`:

| Path | Contents |
| --- | --- |
| `<experiment_name>.sqlite` | all attempts, episodes, tokens, cost, freeze, held-out rows |
| `prompts/<name>/revision_NN_call_KK.txt` | the exact system+user prompt for each model call |
| `flights/<experiment_id>/*.flight.json` | verifiable replay manifests (development) |
| `heldout-flights/<name>/` | replay manifests for the frozen controller |
| `reports/<name>/report.md` (+ PNGs) | `rewardbench.analysis` report and figures |
| `logs/<name>.<stage>.log` | full output of each underlying CLI |

**Resume:** re-run the same command with the same `--out`. The runner resumes
unfinished experiments, skips finished ones, and does not repeat a completed
held-out evaluation. `python -m rewardbench.operate status --out DIR` prints
revisions, controller changes, rewards, and artifact paths without running anything.

## Replay and charts

Visual replay of any recorded flight (development or held-out), served from the repo root:

```bash
python3 -m http.server 8767
# http://localhost:8767/frontend/apollolander/experiment/replay.html?file=/runs/my-demo/flights/<experiment_id>/<name>.flight.json
```

Or open `replay.html` and pick/drag a `.flight.json` from anywhere. The page re-runs the
recorded `initial_state` and per-step `{rotation, thrust}` trace through the same `physics.js`
the Python adapter uses, draws each step with play/pause/scrub/speed controls, and ends with the
recorded outcome and `REPLAY MATCHES RECORD` (or the exact mismatch). Records hold actions, not
per-step states, so nothing is invented: positions are regenerated deterministically.

The verdict has two parts, both required for `REPLAY MATCHES RECORD`: **integrity** (`trace_length` and
`terminal.steps` equal the real action count; `trace_hash` recomputed in the browser equals the record) and
**parity** (replaying the actions reproduces the recorded outcome, ends on the step physics terminates, with
no trailing actions and no truncation). Anything else shows `REPLAY MISMATCH` with every reason.
`controller_hash` and re-deriving the start from the episode seed are left to the Python verifier below.
Both verifiers reject extra actions after termination (even when `trace_length` and `trace_hash` are
re-sealed), truncated traces, a `terminal.steps`/`trace_length` that disagrees with the real action count,
wrong hashes, and changed terminal outcome or fuel totals; `tests/environments/test_flight_verifier_integrity.py`
runs both on the same tampered records. Limits that remain: `controller`, `model` and `origin` are *claims* —
verification proves the recorded actions reproduce the recorded outcome, not that the named controller or model
produced them — and `fuel_penalty`/`terminal_reward` are not recomputed.

Browser evidence (26 checks incl. controls, mismatches, file picker, drag/drop, `index.html`) is produced by
`python examples/browser_replay_check.py --out docs/assets/replay-evidence` (needs `pip install playwright`
and `playwright install chromium`); screenshots and `browser_check_results.json` are in that directory.

Python-side verification (independent of the browser):

```python
from rewardbench.environments import make_environment
a = make_environment("ApolloLander", research_mode=True)
print(a.verify_flight_record("runs/my-demo/flights/<experiment_id>/<name>.flight.json"))
```

Live (keyboard) ApolloLander: `cd frontend/apollolander && python3 -m http.server 8766`, then
`http://localhost:8766/experiment/index.html`. Reward charts are the PNGs under `reports/<name>/`.

## Live (real model) mode

Live mode is the same command with `--mode live` and the **existing** safeguards:

```bash
export OPENAI_API_KEY=...   # in your own shell; never paste keys into chat or commit them
python -m rewardbench.operate run \
  --config configs/apollolander_pilot_openai_gpt54mini.yaml \
  --mode live --i-authorize-paid-api-calls --out runs/pilot-1
```

* Keys come only from environment variables: `OPENAI_API_KEY`, `GEMINI_API_KEY`/`GOOGLE_API_KEY`,
  `ANTHROPIC_API_KEY`, `XAI_API_KEY`. A T3 Code, Codex, ChatGPT or Claude subscription is **not** an
  API credit and provides none of these.
* Without `--i-authorize-paid-api-calls`, a key, a priced model, and a consistent budget, `rewardbench.run`
  refuses before any network use. Default is one new paid call per invocation (`--max-new-paid-calls`);
  continuing needs `--authorize-continuation` after you review the SQLite results.
* A mock-provider config cannot run in live mode, and a real-provider config cannot run in mock mode.
* Cost/tokens per call are stored in `attempts` (`total_tokens`, `estimated_cost_usd`) and shown by
  `operate`. The `budget:` block in the YAML sets the software ceiling. It is not a vendor billing cap;
  set a hard limit in the provider dashboard too.
* Failed or interrupted live runs are resumable: stored attempts are never re-billed.
* `--heldout` refuses configs that list the reserved final-evaluation seeds `2000000`–`2000015`.
