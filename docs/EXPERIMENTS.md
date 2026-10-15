# Running, exporting, and reading experiments

RewardBench compares in-context adaptation. A model proposes a controller. The environment scores that controller. The next proposal can see the earlier controller and, in one condition, the numerical reward. Weights are not updated.

The core runner and the SQLite schema are specified in `docs/INTERFACES.md`. This page is the operating guide for logs and figures.

## Conditions

Each config file is one experiment. `feedback_condition` and `split` change the experiment id.

| File | Condition | Split |
| --- | --- | --- |
| `configs/lunarlander_development_numerical.yaml` | `numerical_reward` | `development` |
| `configs/lunarlander_development_nofeedback.yaml` | `no_feedback` | `development` |
| `configs/lunarlander_heldout_numerical.yaml` | `numerical_reward` | `held_out` |

Use the development configs while debugging the pipeline. Use the held-out config only for the evaluation that will be reported. Do not run held-out seeds during development. The core `SplitGuard` rejects that mix, and the analysis report flags it if a log contains it anyway.

## What the runner records

The runner writes `ExperimentConfig.database_path`. The sample configs use `runs/rewardbench.sqlite`.

Tables that the analysis reads:

- `experiments` — model, provider, condition, split, status, config
- `sessions` — one row per start, including a resume
- `attempts` — model calls; `selected = 1` is the controller for that revision
- `episodes` — simulated flights for a selected valid controller
- `errors` — recorded failures

`attempts.valid = 0` on a selected row is an invalid controller. Those revisions do not get episode rows. Rewards stay in `episodes.total_reward`. Landing success is `episodes.success`. Crashes are `episodes.crashed` when the environment records that flag.

A log without `metadata.validation_status` is preliminary. Set that field to `independently_validated` only after a separate check of the config, seeds, and raw database. The analysis will not infer it.

## Export

From the repository root:

```bash
python -m rewardbench.analysis export --logs runs/rewardbench.sqlite --out exports/run.jsonl
```

The JSONL file has one object per line. `record_type` is `episode`, `attempt`, or `error`. The export is a copy of the log. It is not a new run. `report` accepts either the SQLite file or this JSONL file.

Keep the SQLite file as the source of truth. Record its SHA-256 from the generated report next to any figure you share.

## Report

```bash
python -m rewardbench.analysis report --logs runs/rewardbench.sqlite --out reports/run1 --reward-targets 0,200
```

This writes `reports/run1/report.md` and, when rows exist, figures under `preliminary/` or `independently_validated/`. Those directories are never combined into one chart.

`--reward-targets` is a list of reward levels you chose before looking at the curve. `200` is the conventional LunarLander reference level used by Gymnasium discussions. It is not an empirical claim that any model reached it.

## How to read a learning curve

The reward curve plots the mean of session means against controller revision.

- Revision 0 is the first controller, before that controller's reward could have changed the next proposal.
- Later revisions are the in-context updates.
- The numerical-reward series can see prior scores. The no-feedback series cannot. Compare those two series for the same model before comparing models.
- A line that rises shows a change inside the sessions that reached that revision. Sessions that stopped early are not in that point, so the sample size can shrink along the x-axis.
- Error bars are 95% Student-t intervals across sessions. One session has a point and no interval.
- Alphabetical order and color are stable labels. They are not a ranking.

Landing success uses the episode index on the x-axis. That index is an attempt inside the revision's evaluation, not a new controller.

Initial versus final connects the first scored revision to the last scored revision for each session. Improvement per dollar divides that change by the session's total estimated cost, including retries. A session with zero recorded cost has an undefined ratio.

Time to target marks sessions that reached the chosen reward. Sessions that never reached it stay visible as open markers at their observed duration. Do not read an open marker as the time required to reach the target.

Invalid-controller rate uses selected attempts. Crash rate uses executed episodes that recorded a crash flag. An invalid controller is not a crash, because it is not flown.

## What not to claim from a curve

- Do not call a model more adaptive because its preliminary curve is higher.
- Do not pool development and held-out experiments.
- Do not treat several sessions of one experiment id as independent replicates when they come from resuming that experiment.
- Do not fill a paper or a blog with these charts until the report's independently validated section contains the log you intend to cite.
