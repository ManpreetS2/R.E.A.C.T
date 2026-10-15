# R.E.A.C.T.

**Reward-Enhanced Adaptive Controller Testing**

R.E.A.C.T. measures how a language model changes a controller when it can see numerical rewards and penalties. Adaptation is in-context. Model weights stay fixed. A simulator, not another model, assigns the score.

The Python package on this default branch is `rewardbench` 0.1.0. The shared contract is version `1.0.0`. The SQLite schema is version `1`.

The repository is [ManpreetS2/REACT](https://github.com/ManpreetS2/REACT). The project name uses the periods: **R.E.A.C.T.**

## Where the work stands

This is an engineering snapshot from 15 October 2026. The four workstreams below are preserved as branches. They have not been combined into one tree. No log in this repository is marked independently validated, so the repository publishes no model ranking and no headline score.

| Branch | Commit | What it holds |
| --- | --- | --- |
| `main` | `f1ee28a` | Default branch. Shared contract, experiment runner, SQLite log, spending cap, and core tests. Same commit as `agent/core`. |
| `agent/core` | `f1ee28a` | Runner, storage, and the spending cap shared by overlapping and resumed runs. |
| `agent/lunarlander` | `89ccbad` | Gymnasium LunarLander-v3 and Seb Lee-Delisle's ApolloLander, as separate environments. One commit on top of `main`. |
| `agent/providers` | `8ab8926` | Adapters, prompts, and pricing for OpenAI, Google Gemini, Anthropic, and xAI. |
| `agent/analysis` | `dcaead8` | Log summaries, figures, reports, and the experiment write-up. |

`agent/providers` and `agent/analysis` both diverge from `af4803d`. They do not contain the spending-cap commit that `main` has. A later integration has to reconcile `docs/INTERFACES.md` across those lines.

## The question

Which model changes its controller more effectively when the prompt includes numerical rewards and penalties, under one fixed protocol?

An answer needs repeated runs, a held-out seed split, and logs whose metadata says `independently_validated`. The analysis code on `agent/analysis` summarizes logs that exist. An empty database produces an empty report.

## What the default branch does

`main` runs the protocol around a model client and an environment adapter supplied by the caller.

- A controller revision and a simulated episode are stored as different records.
- Development seeds and held-out seeds stay in different experiments. `SplitGuard` rejects a seed from the other pool.
- Before a model call, the runner reserves the remaining dollar and token budget. That reservation is shared across overlapping runs and is restored correctly on resume.
- An adapter rejects an invalid controller. This package does not execute model-authored Python.
- The primary score is the environment's own reward. Penalties are negative rewards.

The sample files in `configs/` describe LunarLander development and held-out conditions, including a development budget of 2.00 USD. The LunarLander and ApolloLander adapters are on `agent/lunarlander`. The HTTP clients are on `agent/providers`. A checkout of `main` can load those YAML files and can exercise the runner with stand-ins. It does not call a provider, and it does not fly a lander.

## Install and test

Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
```

On Windows, create the environment with `py -3.11 -m venv .venv` and activate it with `.\.venv\Scripts\Activate.ps1`.

The core suite uses stand-in models and environments. It checks configuration, identifiers, seed splits, the SQLite log, resume, and the spending cap. It does not need an API key, and it does not spend money.

`pip install -e ".[dev]"` installs PyYAML and pytest, which is everything `main` imports. NumPy, SciPy, and Matplotlib belong to the analysis branch. Gymnasium belongs to the environment branch.

## Keys and cost

On `agent/providers`, a live client reads one of these environment variables:

| Provider | Variable |
| --- | --- |
| OpenAI | `OPENAI_API_KEY` |
| Google Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| xAI | `XAI_API_KEY` |

Keep keys in the environment of the machine that runs an experiment. This history contains no `.env` file and no live key. Provider tests use the placeholder `sk-test-secret-value`. Generated logs (`runs/`, `*.sqlite`) are gitignored.

A live call also needs the provider package and a person who accepts the charge. The sample cap in `configs/lunarlander_development_numerical.yaml` is a ceiling in the config, not permission to start a paid run from this page.

## Environments

Gymnasium LunarLander-v3 and ApolloLander are different games, with different physics and different scores. Reports keep the two families in separate sections.

**ApolloLander was created by Seb Lee-Delisle and published under the MIT License.** The snapshot on `agent/lunarlander` is upstream commit `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2` (22 June 2017, "changed fonts to Hershey").

- Project: <https://github.com/sebleedelisle/apollolander>
- License: <https://github.com/sebleedelisle/apollolander/blob/master/LICENSE>
- Local copy, on `agent/lunarlander`: `frontend/apollolander/upstream/LICENSE`
- Copyright (c) 2017 Seb Lee-Delisle

Keep that notice with any copy of the game. The experiment code around the game is separate from the original MIT grant. Details of the bundled files are in `frontend/apollolander/THIRD_PARTY.md` on the same branch:

| Path | Status |
| --- | --- |
| `upstream/perlin.js` | Public domain. Stefan Gustavson, optimisations by Peter Eastman, JavaScript port by Joseph Gentle. Attribution is in the file header. |
| `upstream/libs/Vector2.js`, `KeyTracker.js`, `TouchController.js` | Covered by the ApolloLander MIT license. |
| `upstream/libs/rAF.js` | requestAnimationFrame polyfill credited to Erik Möller, Paul Irish, and Tino Zijdel. |
| `upstream/libs/audio.js`, `jsfx.js`, `jsfxlib.js` | Procedural sound shipped inside the upstream game. Those files have no license header. The experiment simulator does not load them. |
| `upstream/fonts/avhersheysimplexmedium-webfont.woff` and `.woff2` | Hershey vector fonts are U.S. government work and are public domain. The webfont packaging has no extra license file in the snapshot. |

A hand-specified ApolloLander demonstration controller is a demonstration. Reports that use it keep `origin` as `hand_specified_demonstration`.

## Analysis

`agent/analysis` reads SQLite logs and writes descriptive reports. It does not call a model, start a simulator, or select a winner. A log stays preliminary until `metadata.validation_status` is `independently_validated`. Rows in `tests/analysis/fixtures.py` are labeled synthetic fixtures so the figure code can run in tests.

The write-up on that branch:

- `docs/EXPERIMENTS.md` — conditions, logs, and export
- `docs/ANALYSIS.md` — session statistics and figures
- `docs/LIMITATIONS.md` — fairness, seed leakage, and judge bias
- `docs/MINECRAFT.md` — what a later environment must keep stable
- `docs/PAPER_AND_BLOG_OUTLINE.md` — paper structure, with the results left blank
- `PLAN.md` — engineering roadmap checked against git on 15 October 2026

`docs/INTERFACES.md` on `main` is the contract those packages follow.

## License

The R.E.A.C.T. experiment code in this repository does not yet include a project license. The source is public to read once the repository is public. Reuse of that code waits on a license added by the maintainer.

The ApolloLander game files keep the MIT license above. That license covers the game. It does not by itself license the rest of this repository.

## Further reading

- `docs/INTERFACES.md` — contract 1.0.0 and SQLite schema version 1
- `pyproject.toml` — package name `rewardbench`, Python 3.11+, PyYAML, pytest
