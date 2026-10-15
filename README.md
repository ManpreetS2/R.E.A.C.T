# R.E.A.C.T.

**Reward-Enhanced Adaptive Controller Testing**

R.E.A.C.T. measures how a language model changes a controller when it can see numerical rewards and penalties. Adaptation is in-context. Model weights stay fixed. A simulator, not another model, assigns the score.

The Python package is `rewardbench` 0.1.0. The shared contract is version `1.0.0`. The SQLite schema is version `1`.

**Repository:** https://github.com/ManpreetS2/R.E.A.C.T

This default branch holds the full public tree: the runner, Gymnasium LunarLander-v3, ApolloLander, the four model providers, and the analysis tools. The original workstream branches (`agent/core`, `agent/lunarlander`, `agent/providers`, `agent/analysis`) are still on GitHub if you want the separate histories.

## Where the work stands

This is an engineering snapshot from 15 October 2026. No log in this repository is marked independently validated, so the repository publishes no model ranking and no headline score.

| Area | Location |
| --- | --- |
| Contract, runner, SQLite log, spending cap | `src/rewardbench/core/`, `src/rewardbench/storage/`, `docs/INTERFACES.md` |
| Gymnasium LunarLander-v3 | `src/rewardbench/environments/lunarlander/` |
| ApolloLander | `src/rewardbench/environments/apollolander/`, `frontend/apollolander/` |
| OpenAI, Gemini, Anthropic, xAI clients | `src/rewardbench/providers/` |
| Log summaries, figures, reports | `src/rewardbench/analysis/` |

## The question

Which model changes its controller more effectively when the prompt includes numerical rewards and penalties, under one fixed protocol?

An answer needs repeated runs, a held-out seed split, and logs whose metadata says `independently_validated`. The analysis tools summarize logs that exist. An empty database produces an empty report.

## How a run is scored

- A controller revision and a simulated episode are stored as different records.
- Development seeds and held-out seeds stay in different experiments. `SplitGuard` rejects a seed from the other pool.
- Before a model call, the runner reserves the remaining dollar and token budget. That reservation is shared across overlapping runs and is restored correctly on resume.
- An adapter rejects an invalid controller. This package does not execute model-authored Python.
- The primary score is the environment's own reward. Penalties are negative rewards.
- Gymnasium LunarLander-v3 and ApolloLander are different games. Their scores are never pooled.

Sample configs live in `configs/` and `examples/`. The development sample caps spend at 2.00 USD.

## Install and test

Python 3.11 or newer. No API key is required for the test suite.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Windows, create the environment with `py -3.11 -m venv .venv` and activate it with `.\.venv\Scripts\Activate.ps1`.

```bash
python -m pytest tests/core tests/providers tests/prompts -q
```

Analysis extras (NumPy, SciPy, Matplotlib) and the Gymnasium simulator are optional:

```bash
python -m pip install -e ".[dev,analysis,environments]"
MPLBACKEND=Agg python -m pytest tests/analysis tests/environments -q
```

`tests/core` uses stand-in models and environments. `tests/providers` uses recorded HTTP replies and the placeholder key `sk-test-secret-value`. Neither path spends money.

## Analysis

Point these commands at a SQLite log written by the experiment runner. The sample configs use `runs/rewardbench.sqlite`.

```bash
python -m rewardbench.analysis export --logs runs/rewardbench.sqlite --out exports/run.jsonl
python -m rewardbench.analysis report --logs runs/rewardbench.sqlite --out reports/run1
```

An empty database produces a report that says no logs were loaded. Reward targets are caller-supplied:

```bash
python -m rewardbench.analysis report --logs runs/rewardbench.sqlite --out reports/run1 --reward-targets 0,200
```

A log stays preliminary until `metadata.validation_status` is `independently_validated`. Rows in `tests/analysis/fixtures.py` are labeled synthetic fixtures so the figure code can run in tests. They are not results.

## Keys and cost

A live client reads one of these environment variables:

| Provider | Variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| xAI | `XAI_API_KEY` |

Keep keys in the environment of the machine that runs an experiment. This history contains no `.env` file and no live key. Generated logs (`runs/`, `*.sqlite`) are gitignored.

`build_model_client` does not call the network. `propose` does. Use `provider="mock"` for offline work. A live call needs a person who accepts the charge. The sample cap in the YAML files is a ceiling in the config, not permission to start a paid run from this page.

## Environments

Gymnasium LunarLander-v3 and ApolloLander keep separate environment ids (`lunarlander-v3` and `apollolander`). Reports keep the two families in separate sections.

```python
from rewardbench.environments import make_environment

gym = make_environment("LunarLander-v3")
apollo = make_environment("ApolloLander")
```

A hand-specified ApolloLander demonstration controller is a demonstration. Reports that use it keep `origin` as `hand_specified_demonstration`.

## Credits

**ApolloLander was created by Seb Lee-Delisle and published under the MIT License.** The snapshot in this repository is upstream commit `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2` (22 June 2017, "changed fonts to Hershey").

- Project: https://github.com/sebleedelisle/apollolander
- License: https://github.com/sebleedelisle/apollolander/blob/master/LICENSE
- Local copy: `frontend/apollolander/upstream/LICENSE`
- Copyright (c) 2017 Seb Lee-Delisle

Keep that notice with any copy of the game. The experiment code around the game is separate from the original MIT grant. Bundled files are listed in `frontend/apollolander/THIRD_PARTY.md`:

| Path | Status |
| --- | --- |
| `upstream/perlin.js` | Public domain. Stefan Gustavson, optimisations by Peter Eastman, JavaScript port by Joseph Gentle. Attribution is in the file header. |
| `upstream/libs/Vector2.js`, `KeyTracker.js`, `TouchController.js` | Covered by the ApolloLander MIT license. |
| `upstream/libs/rAF.js` | requestAnimationFrame polyfill credited to Erik Möller, Paul Irish, and Tino Zijdel. |
| `upstream/libs/audio.js`, `jsfx.js`, `jsfxlib.js` | Procedural sound shipped inside the upstream game. Those files have no license header. The experiment simulator does not load them. |
| `upstream/fonts/avhersheysimplexmedium-webfont.woff` and `.woff2` | Hershey vector fonts are U.S. government work and are public domain. The webfont packaging has no extra license file in the snapshot. |

Gymnasium LunarLander-v3 is a separate project and a separate score.

## Documentation

- `docs/INTERFACES.md` — contract 1.0.0 and SQLite schema version 1
- `docs/EXPERIMENTS.md` — conditions, logs, and export
- `docs/ANALYSIS.md` — session statistics and figures
- `docs/LIMITATIONS.md` — fairness, seed leakage, and judge bias
- `docs/MINECRAFT.md` — what a later environment must keep stable
- `docs/PAPER_AND_BLOG_OUTLINE.md` — paper structure, with the results left blank
- `PLAN.md` — engineering roadmap checked against git on 15 October 2026
- `docs/HANDOFF.md` — historical transfer note from the analysis worktree

## License

The R.E.A.C.T. experiment code in this repository does not yet include a project license. The source is public to read. Reuse of that code waits on a license added by the maintainer.

The ApolloLander game files keep the MIT license above. That license covers the game. It does not by itself license the rest of this repository.
