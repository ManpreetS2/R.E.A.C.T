# Technical demonstration plan (v1)

Audience: a technical reviewer with ~15 minutes. Goal: show the **real** simulator loop, controller proposals, revision history, scores, and replay evidence—without claiming unvalidated LLM success.

## Narrative (30 seconds)

R.E.A.C.T. measures whether numerical rewards change in-context controller revisions versus a matched no-feedback arm. Physics scores the flight. Held-out evaluation freezes the final controller and never calls a model.

## Demo script

### 1. Show the problem and architecture

- Open `README.md` (mermaid diagram + proven vs empty slots).
- Point at `docs/INTERFACES.md` for `ModelClient` / `EnvironmentAdapter` / splits.

### 2. Live ApolloLander physics (optional visual)

```bash
cd frontend/apollolander && python3 -m http.server 8766
```

Open the experiment UI. Emphasize: this is the same physics Node harness the adapter drives.

### 3. Offline paired development (scripted mock)

```bash
python -m rewardbench.run \
  --config configs/apollolander_offline_development_numerical.yaml --mode mock

python -m rewardbench.run \
  --config configs/apollolander_offline_development_nofeedback.yaml --mode mock
```

Show CLI summary: revisions, episodes, mean reward, SQLite path. State clearly: **scripted model**, not an LLM.

### 4. Inspect revision history and scores

```bash
sqlite3 runs/apollolander_offline_numerical.sqlite \
  "SELECT revision_index, selected, valid, substr(parameters,1,80) FROM attempts ORDER BY revision_index, call_index;"

sqlite3 runs/apollolander_offline_numerical.sqlite \
  "SELECT revision_index, episode_seed, total_reward, success FROM episodes ORDER BY revision_index;"
```

Contrast with the no-feedback database: rewards stored for analysis, withheld from model history.

### 5. Freeze and sealed held-out evaluation

```bash
python -m rewardbench.heldout \
  --database runs/apollolander_offline_numerical.sqlite \
  --source-config configs/apollolander_offline_development_numerical.yaml
```

Show: `freeze_id`, `controller_hash`, held-out seed list, `success_count`, note that **no model calls** occurred. Repeat for the no-feedback database to show matched sealed starts.

### 6. Report figures

```bash
python -m rewardbench.analysis report \
  --logs runs/apollolander_offline_numerical.sqlite \
  --out reports/demo_numerical
```

Open `report.md` and the PNGs under `preliminary/`. Or use tracked samples in `docs/assets/v1-evidence/figures/`.

### 7. Replay evidence

```python
from rewardbench.environments import make_environment
adapter = make_environment("ApolloLander", research_mode=True)
print(adapter.verify_flight_record(
    "docs/assets/v1-evidence/flights/offline_mock_development_episode.flight.json"
)["matched"])
```

### 8. Research baselines (difficulty, not learning)

Point at `examples/apollolander/research_development_baseline/DEVELOPMENT_BASELINE_REPORT.md`:

- Random / coast / hover: **0/16** landings  
- Hand-specified guidance: **16/16** landings  
- Held-out unused during baseline tuning  

### 9. Close with honesty

- Empty slots: real multi-provider LLM results; independently validated rankings.  
- Live pilot requires explicit owner spend approval.  
- Do not present scripted demos as model success.

## Timing guide

| Segment | Minutes |
| --- | ---: |
| Problem + architecture | 2 |
| Offline run + SQLite | 4 |
| Held-out freeze | 3 |
| Report + replay | 3 |
| Baselines + limitations | 3 |
