# Analysis pipeline

The analysis package reads experiment logs and writes descriptive summaries. It does not call a model provider, start a simulation, or choose a winning model.

Import the public helpers from `rewardbench.analysis`, or run `python -m rewardbench.analysis`.

## Inputs

`load_logs` accepts:

- SQLite databases ending in `.sqlite`, `.sqlite3`, or `.db`
- JSONL exports ending in `.jsonl`

SQLite reads are opened with a read-only URI. Required tables are `experiments`, `sessions`, `attempts`, and `episodes`, with the columns named in `docs/INTERFACES.md` schema version 1. The `errors` table is included when it is present. The `scores` view is not required; reward is read from `episodes.total_reward`.

`metadata.validation_status` in the stored config may be `preliminary` or `independently_validated`. Any other value, including a missing value, is stored as preliminary.

`metadata.synthetic` marks fixture rows. A log that mixes synthetic and non-synthetic rows is rejected. A synthetic row cannot be labeled independently validated.

Rows are dropped when the reward is non-finite, a cost or duration is negative, an index is negative, or an episode is both a success and a crash. Dropped rows are listed in the report and are not entered into the means.

## Session, then interval

The session is the unit of the published interval.

For each session the pipeline records:

- mean reward at the first scored revision and at the last scored revision
- improvement, defined as final minus initial
- improvement per dollar, defined only when total estimated cost is positive
- invalid rate among selected attempts
- crash rate among executed episodes with a non-null crash flag
- success rate among executed episodes with a non-null success flag
- cumulative seconds to each revision, using episode elapsed time plus the latency of selected model calls

Group tables then take the mean of those session values. The interval is a two-sided Student-t interval. It is omitted when fewer than two sessions contribute. Wilson intervals are used for the proportion of sessions that reach a reward target.

A repeated experiment is a distinct experiment id with the same model, condition, split, and environment. Sessions that share an experiment id are one replicate, including resumes. The repeated-experiment interval uses one row per experiment id. Its reward change comes from the session with the highest revision index, and its cost is the sum of that experiment's sessions.

Episode-level pooling is not used for those intervals. Episodes inside one session share a controller and a seed schedule, so they are not independent replicates.

## Environment families

`environment_id` selects the benchmark. `LunarLander-v3` is Gymnasium. Any id containing `apollo` is ApolloLander, including an id that also mentions Gymnasium. Other ids stay in their own family. The report writes a separate section and a separate figure directory for each family. Those scores are never averaged together.

## Figures

| File | Question the axis answers |
| --- | --- |
| `reward_vs_revision.png` | How did mean reward change across controller revisions? |
| `landing_success_vs_attempt.png` | How did landing success change across episode attempts? |
| `initial_vs_final.png` | Where did each session start and finish? |
| `improvement_per_dollar.png` | How large was the reward change relative to recorded cost? |
| `time_to_target.png` | Which sessions reached a pre-specified reward, and when? |
| `invalid_and_crash_rates.png` | How often was a selected controller rejected, and how often did a flight crash? |

Figures use the Okabe-Ito palette, DejaVu Sans (bundled with Matplotlib), and alphabetical model order. The Matplotlib backend is Agg, so the same PNG is produced on macOS, Windows, and Linux without a display.

An empty log still produces a figure. The figure says `No experiment logs loaded`. It does not substitute fictional scores. Tests that need a non-empty chart use `tests/analysis/fixtures.py`, which marks every row synthetic.

## Diagnostics

The report adds three checks that qualify a comparison:

- Seed overlap between a development run's executed seeds and a held-out seed pool, and overlap stored inside one config.
- Multiple sessions that share an experiment id, which usually means a resume rather than a new replicate.
- Exposure differences above 25% in cost, tokens, or scored episodes, and any difference in how far the revision index went. The note lists models alphabetically and does not say which one adapted more.

## Reproducibility

Each report records the log path, SHA-256, schema version, UTC timestamp, and the NumPy, SciPy, and Matplotlib versions. Regenerate a figure from the same file and the same code to reproduce it. Do not transcribe numbers out of a chart by hand when the report table is available.

Paths in the code use `pathlib`. JSONL is written as UTF-8 with `\n` newlines. The GitHub Actions workflow installs the analysis dependencies on each runner instead of assuming a local virtual environment, and it invokes `python -m pytest` so the check does not depend on a shell-specific path.
