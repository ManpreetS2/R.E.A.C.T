# RewardBench

RewardBench measures how language models adapt to numerical rewards and penalties under controlled conditions. The first environment is Gymnasium LunarLander-v3. Models revise a controller from earlier attempts. They do not update neural network weights.

The research question is: which language model adapts most effectively to numerical rewards and penalties under controlled experimental conditions?

This repository does not answer that question until independently validated logs exist. The analysis tools summarize logs. They do not invent scores or rank models.

## Requirements

- Python 3.11 or newer
- A virtual environment
- No API key is required to run the analysis, tests, or report generator

Analysis depends on NumPy, SciPy, and Matplotlib. The core package depends on PyYAML. Experiment runs that call a model provider are separate from this analysis path and can spend money. Do not start those runs from the analysis commands below.

## macOS

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/macos/) or with Homebrew:

```bash
brew install python@3.11
```

From the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install numpy scipy matplotlib
```

## Windows

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/) and enable the `py` launcher.

From the repository root, in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip install numpy scipy matplotlib
```

If activation is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again. Command Prompt uses `.venv\Scripts\activate.bat` instead of the PowerShell script.

## Tests

From the repository root, with the virtual environment activated:

```bash
python -m pytest tests/analysis -q
```

On Windows the same command works inside PowerShell or Command Prompt. The test suite uses Matplotlib's non-interactive backend. Synthetic rows inside `tests/analysis/fixtures.py` exist only so figures can be drawn when no experiment log is present. They are labeled and are not results.

GitHub Actions runs the same tests on Ubuntu, macOS, and Windows. See `.github/workflows/analysis-checks.yml`.

## Analysis commands

Point these commands at a SQLite log written by the experiment runner. The default config path is `runs/rewardbench.sqlite`.

```bash
python -m rewardbench.analysis export --logs runs/rewardbench.sqlite --out exports/run.jsonl
python -m rewardbench.analysis report --logs runs/rewardbench.sqlite --out reports/run1
```

`examples/analysis/run_report.py` calls the same command line. An empty database produces a report that says no logs were loaded.

Reward targets are caller-supplied. They are not discovered from the data:

```bash
python -m rewardbench.analysis report --logs runs/rewardbench.sqlite --out reports/run1 --reward-targets 0,200
```

## Experiments

Shared configuration files live in `configs/`. The runner, store, and provider clients are described in `docs/INTERFACES.md`. Read `docs/EXPERIMENTS.md` before starting a run, `docs/ANALYSIS.md` for the statistics, and `docs/LIMITATIONS.md` before quoting a number.

## Documentation

- `docs/EXPERIMENTS.md` — run, export, and read a learning curve
- `docs/ANALYSIS.md` — pipeline and figures
- `docs/LIMITATIONS.md` — fairness, judge bias, seed leakage, in-context adaptation
- `docs/PAPER_AND_BLOG_OUTLINE.md` — paper and blog structure with no filled results
- `docs/MINECRAFT.md` — what changes when a Minecraft environment is added
- `docs/HANDOFF.md` — branch, worktree, and transfer notes
