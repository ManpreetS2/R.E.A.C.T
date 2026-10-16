# R.E.A.C.T.

**Reward-Enhanced Adaptive Controller Testing**

R.E.A.C.T. measures how a language model changes a constrained controller when it can see numerical rewards and penalties. Adaptation is **in-context**. Model weights stay fixed. A simulator, not another model, assigns the score.

| | |
| --- | --- |
| Official project name | **R.E.A.C.T.** |
| Internal Python package | **`rewardbench`** (do not rename casually) |
| Contract / SQLite schema | `1.0.0` / `1` |
| Repository | https://github.com/ManpreetS2/R.E.A.C.T |

This tree holds the runner, Gymnasium LunarLander-v3, ApolloLander, four model providers, analysis tools, and the offline/live CLI. No log in this repository is marked `independently_validated`, so the project publishes **no model ranking**.

## Controller kinds (do not confuse them)

| Kind | What it is | What it is **not** |
| --- | --- | --- |
| Scripted mock controller | Offline `ScriptedFeedbackModel` / deterministic mock for infrastructure tests | Evidence of LLM learning |
| Hand-specified reference controller | Human-tuned Apollo guidance / constants for difficulty baselines | Evidence of LLM learning |
| Real LLM-generated controller | JSON from a live provider after an authorized call | A finished benchmark by itself |
| Repeated LLM adaptation experiment | Multiple revisions with numerical vs no-feedback arms, then held-out eval | Something this README authorizes you to spend money on |

## Install

Python **3.11+** (3.12 preferred). Node.js is required for ApolloLander physics.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,analysis,environments]"
```

Windows: `py -3.12 -m venv .venv` then `.\.venv\Scripts\Activate.ps1`.

## Tests

No API key is required.

```bash
python -m pytest tests -q
node frontend/apollolander/experiment/physics.test.js
```

Provider tests use recorded/mocked HTTP and the placeholder key `sk-test-secret-value`. They do not spend money.

## Launch ApolloLander locally

```bash
cd frontend/apollolander
python3 -m http.server 8766
```

Open http://localhost:8766/experiment/index.html  
Controls: arrows rotate, space thrust, R reset, L/K camera.

## Offline mock experiments (infrastructure only)

Paired development configs share seeds and simulator settings; only feedback differs.

```bash
python -m rewardbench.run \
  --config configs/apollolander_offline_development_numerical.yaml \
  --mode mock

python -m rewardbench.run \
  --config configs/apollolander_offline_development_nofeedback.yaml \
  --mode mock
```

Optional: `--database path/to.sqlite`. With `metadata.record_flights: true`, manifests land under `runs/flights/<experiment_id>/` (no HD video by default).

These runs use a **scripted** model against **real** Apollo physics. They are not LLM learning results.

## SQLite reports

```bash
python -m rewardbench.analysis report \
  --logs runs/apollolander_offline_numerical.sqlite \
  --out reports/offline_numerical
```

Gymnasium and ApolloLander stay in separate report sections. Empty databases produce empty reports.

## Flight replay

Flight manifests (`.flight.json`) record start state, controller, trace hash, and terminal outcome.

```python
from rewardbench.environments import make_environment
from rewardbench.environments.apollolander import load_flight_record

adapter = make_environment("ApolloLander", research_mode=True)
verified = adapter.verify_flight_record("path/to/flight.flight.json")
assert verified["matched"] is True
```

Research-mode development baselines (scripted only; held-out unused) live under:

- `examples/apollolander/run_research_development_baselines.py`
- `examples/apollolander/research_development_baseline/`

## Provider dry-run (no key, no network spend)

```bash
python examples/providers/dry_run_first_call.py
```

This checks local catalog pricing / preflight for the recommended OpenAI pilot settings. It does not call the network.

## What a real API pilot requires

1. Explicit owner approval to spend.
2. Vendor account billing limits set by a human.
3. `export OPENAI_API_KEY=...` in the local shell only (never commit keys).
4. Pilot config: `configs/apollolander_pilot_openai_gpt54mini.yaml`
   - Model: `gpt-5.4-mini`
   - `max_output_tokens: 800`
   - `reasoning_effort: none`
   - `max_model_retries: 0`
   - Software ceiling `budget.max_cost_usd: 0.05` (**not** a vendor billing guarantee)
5. First invocation (at most **one new** paid `propose`, then pause):

```bash
python -m rewardbench.run \
  --config configs/apollolander_pilot_openai_gpt54mini.yaml \
  --mode live --i-authorize-paid-api-calls
```

6. After reviewing SQLite, a separately authorized continuation:

```bash
python -m rewardbench.run \
  --config configs/apollolander_pilot_openai_gpt54mini.yaml \
  --mode live --i-authorize-paid-api-calls --authorize-continuation
```

Live mode without `--i-authorize-paid-api-calls` refuses. Missing credentials refuse before network use. A paused one-call stop is **not** a completed learning experiment.

Paired no-feedback live twin: `configs/apollolander_pilot_openai_gpt54mini_nofeedback.yaml`.

## Scoring rules (short)

- Controller revisions and simulated episodes are different records.
- Development and held-out seeds stay in different experiments (`SplitGuard`).
- Invalid controllers are not flown.
- Gymnasium and ApolloLander scores are never pooled.
- Average reward change across different research starts alone does **not** prove improvement; compare revisions on matched conditions, then evaluate final policies on a sealed held-out set.

## Documentation

- `docs/INTERFACES.md` — contract, SQLite, live CLI controls
- `docs/EXPERIMENTS.md` — conditions and export
- `docs/ANALYSIS.md` — figures and sessions
- `docs/LIMITATIONS.md` — seed leakage and fairness
- `docs/AGENT3_AI_INTEGRATIONS_REPORT.md` — provider/pilot readiness notes
- `PLAN.md` — engineering roadmap (Agent 4 maintains)

## Credits

**ApolloLander was created by Seb Lee-Delisle and published under the MIT License.** Upstream snapshot `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`. See `frontend/apollolander/upstream/LICENSE` and `frontend/apollolander/THIRD_PARTY.md`.

## License

R.E.A.C.T. experiment code does not yet include a project-wide license. ApolloLander game files keep their MIT license.
