> **Historical (2026-10-15).** The current project state is in `docs/PROJECT_HANDOFF.md`.

# Handoff — Agent 4, analysis

Date: 2026-10-15

Open this worktree in Cursor:

`/Users/manpreet/rewardbench-worktrees/analysis`

Branch: `agent/analysis`

Shared git directory: `/Users/manpreet/rewardbench/.git`

Foundation this branch contains: `af4803d` (`Add the experiment runner, SQLite log, and core tests.`), replayed under the analysis commit. The original contract commit remains `1fceef7`.

Do not open `/Users/manpreet/Projects/rewardbench`. That directory is a separate repository (`git rev-parse --git-common-dir` is `/Users/manpreet/Projects/rewardbench/.git`). It has no commits and no origin. It is not this branch.

## Repository layout

`git rev-parse --absolute-git-dir` from this worktree is `/Users/manpreet/rewardbench/.git`. The same common directory is used by:

- `/Users/manpreet/rewardbench` on `agent/lunarlander`
- `/Users/manpreet/rewardbench-providers` on `agent/providers`
- `/Users/manpreet/rewardbench-worktrees/core` on `agent/core`
- `/Users/manpreet/rewardbench-worktrees/analysis` on `agent/analysis`

There is no `origin` remote. That is intentional. Do not add one and do not push until the human transfer tonight.

## What this branch contains

Analysis, tests, the workflow, the README, and the docs listed below. `docs/INTERFACES.md` is unchanged from `1fceef7`.

Owned paths:

- `src/rewardbench/analysis/`
- `tests/analysis/`
- `docs/` except `docs/INTERFACES.md`
- `README.md`
- `.github/workflows/analysis-checks.yml`
- `examples/analysis/run_report.py`

The loader reads schema version 1 as documented in `docs/INTERFACES.md`. This branch already contains Agent 1's runner and SQLite store from `af4803d`. It does not contain Agent 3's provider adapters or Agent 2's Gymnasium and ApolloLander packages.

## Tests already run

Command, from this worktree, with Python 3.12.1:

```bash
MPLBACKEND=Agg .venv/bin/python -m pytest tests/core tests/analysis -q
```

Result on 2026-10-15: `65 passed, 1 skipped in 8.49s`.

The skip is `test_real_simulator_adapter_waits_for_agent_2`. Agent 2's adapters are not committed on `agent/analysis`, so that test does not claim a real Gymnasium or ApolloLander flight. The other new checks drive the real runner and SQLite store with a mock model and a stand-in environment. They confirm stored rewards, hidden no-feedback history, held-out seed isolation, resume without a duplicate attempt, failed episodes left out of the chart mean, and separate Gymnasium and ApolloLander report sections.

The GitHub Actions workflow was updated and was not executed from this machine. Do not describe it as a green check.

`.venv/` is local and gitignored. Recreate it with the README instructions. `pip install -e ".[dev]"` is required before `tests/core` because the config loader imports PyYAML.

## Another MacBook tomorrow

1. Copy the shared repository at `/Users/manpreet/rewardbench`, not `/Users/manpreet/Projects/rewardbench`. The git directory is `/Users/manpreet/rewardbench/.git`. Worktrees break if the absolute paths change. On the other MacBook, once GitHub has the branch, clone it and check out `agent/analysis`. Until then, copy the shared repo and run `git worktree add /path/to/analysis agent/analysis` from that copy.
2. Confirm `git rev-parse --abbrev-ref HEAD` is `agent/analysis` and `git merge-base HEAD agent/core` is `af4803d` when `agent/core` is present.
3. Create a new virtual environment. Do not copy `.venv/`.
   - macOS: `python3.11 -m venv .venv` then `source .venv/bin/activate`
   - Windows: `py -3.11 -m venv .venv` then `.\.venv\Scripts\Activate.ps1`
   - Then: `python -m pip install --upgrade pip` and `python -m pip install -e ".[dev]"` and `python -m pip install numpy scipy matplotlib`
4. Run `python -m pytest tests/core tests/analysis -q`. Expect the real-simulator test to stay skipped until Agent 2's package is on the branch.
5. Do not describe a stand-in episode as a Gymnasium or ApolloLander result. The report keeps those families in separate sections.
6. Do not push, merge, or call a paid model API.

## Tonight: GitHub transfer

1. Confirm `git status` in this worktree is clean and the branch is `agent/analysis`.
2. Confirm `docs/INTERFACES.md` has no analysis edits (`git diff 1fceef7 -- docs/INTERFACES.md` is empty on this branch before any later merge).
3. Create the GitHub repository from the shared history, not from `/Users/manpreet/Projects/rewardbench`.
4. Push `agent/analysis` only when the human asks. Do not force-push. Do not merge into another agent's branch from this worktree.
5. Leave `agent/core`, `agent/lunarlander`, and `agent/providers` for their owners.
6. After the remote exists, the other worktrees can add `origin`. Until then, a fetch of `origin/agent/analysis` will fail because the remote is absent.

## Tomorrow

1. When Agent 2's Gymnasium and ApolloLander adapters are committed, replace the skipped test in `tests/analysis/test_integration.py` with a run through those adapters. Do not mark that test passed before it executes.
2. Bring in `agent/providers` only when the human integrates branches. Do not call the live adapters.
3. Re-read `docs/INTERFACES.md` before changing the loader. Do not edit that file from this branch.
4. Keep preliminary logs out of any public chart.
5. Do not copy `tests/analysis/fixtures.py` into a paper, blog, or LinkedIn post. Those rows are synthetic.

## Unresolved

- No independently validated experiment log exists.
- `agent/providers` (`af51315`) is not contained in this branch.
- `agent/lunarlander` has no commits, so the real simulators are not integrated.
- The real-simulator integration test is skipped for that reason.
- GitHub Actions has not run.
- Local git identity is unset. Analysis commits use a per-command author and do not change `git config`.
