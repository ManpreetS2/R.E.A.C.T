**NOT AUTHORIZED: this card approves nothing.**

# Baseline execution card (for the owner)

Written in Mission 019 (2026-11-05). It describes how the 14 official non-AI scripted baselines would be recorded, **if and when you authorize it**. Reading or following the commands in the "Plan" step is harmless (it writes nothing); the "Run" step is only for use after you have written the authorization in section 2. The engineering agent does not run it. No baseline has been recorded. The smoke test, any AI session, the live flag, billing, pre-registration and any merge are **not** covered by anything here.

Baselines cost **$0** and use **no API, no credential and no network**. They are recorded **before** the smoke test (candidate protocol §15, step 2), and the smoke test is a separate, later authorization.

## 1. Prerequisites (all must hold; tick each yourself)

- [ ] You have accepted the final text of `docs/BLIND_PLAY_PROTOCOL_V1_CANDIDATE.md` at a named commit (the **accepted-protocol SHA**), as a **dated entry in `PROJECT.md`** (sentence A in section 2). Separately, you have written the **authorization** (sentence B in section 2). Sentence A does not imply sentence B. Without both entries, stop.
- [ ] A **clean checkout at the commit that ADDS your authorization entry (B) to `PROJECT.md`**, call it `<run-sha>`. `git status --porcelain` prints nothing and `git rev-parse HEAD` equals `<run-sha>`. The code, tests and protocol must be exactly those you accepted, so this must print **only `PROJECT.md`**:

  ```powershell
  git diff --stat <accepted-protocol-sha> HEAD
  ```

  Any code, test or protocol-document change in that output means stop. Record **both SHAs** (`<accepted-protocol-sha>` and `<run-sha>`) in the result entry (step 6 of section 4). Use a fresh clone or worktree, not a working copy with `runs\` already full of earlier studies (see the out-root note in step 3).
- [ ] **Set up the fresh clone** (it has no `.venv` and no runtime image). From the clone root, with Python 3.11 or newer (`pyproject.toml` requires `>=3.11`; the verified runs so far used 3.13.5):

  ```powershell
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
  .\.venv\Scripts\python.exe -m pip install -e ".[dev,blindplay,analysis,environments]"
  .\.venv\Scripts\python.exe -m playwright install chromium
  ```

  The hash-verified player runtime image needs no separate step: `host.py` builds it itself (`runtime_image.build`, then `verify`) under `%LOCALAPPDATA%\REACT-blindplay\runtime-images\<digest>` the first time a session starts, and re-hashes every file before each session (`docs/ISOLATED_PLAYER_RUNTIME.md`). Its digest depends on the checkout's line endings, so it can differ between clones; each session records the digest it used. The pytest step below also exercises it.
- [ ] **Green CI on that exact commit** on Windows, macOS and Ubuntu (`gh run list --commit <sha>`).
- [ ] **Tests pass locally with the real sandbox and Chromium**, not skipped (run this after the setup above, with `REACT_REQUIRE_ISOLATION=1` so a missing sandbox fails instead of skipping):

  ```powershell
  $env:REACT_REQUIRE_ISOLATION = "1"
  .\.venv\Scripts\python.exe -m pytest --tb=short -p no:cacheprovider
  ```

  Expect 0 failed. (At Mission 018 the Windows result was 1,049 passed, 9 skipped on POSIX/macOS only, 0 failed.)
- [ ] The historical evidence is intact, checked on the machine that holds the original `runs\` (adjust `--root` to that checkout):

  ```powershell
  .\.venv\Scripts\python.exe -m rewardbench.evidence_backup verify --root C:\Users\sh1ft\R.E.A.C.T
  ```

  Expect `"ok": 383`, `missing` and `mismatched` empty, `"complete": true`.
- [ ] **No `ANTHROPIC_*` variables** (the gate and host refuse them, and there is no reason to have one for baselines):

  ```powershell
  Get-ChildItem Env: | Where-Object { $_.Name -like "ANTHROPIC_*" }
  ```

  This must print nothing. Also keep credential-like variables out of `HKCU\Environment` (the host fails closed on them).
- [ ] The **out root does not exist** (step 3 uses `$out`; `Test-Path $out` must be `False`).
- [ ] **Do not delete the clone or worktree** (no `git worktree remove`, no `git clean -fdx`, no deleting the folder) until `evidence_backup check-copy` (section 4, step 4) reports `"complete": true`: `runs\` is gitignored, so those commands destroy the only copy of the baseline data. Write the clone's absolute path in the result entry.
- [ ] **Free disk space**: the size of 14 sessions has not been measured. Check `Get-PSDrive C` and keep several GB free (earlier studies' whole `runs\` is about 185 MB, for scale only).

## 2. The authorization the owner must give

Two separate sentences. Copy each into `PROJECT.md` as its own dated entry, filling in the placeholders. **Sentence A does not imply sentence B**: A completes milestone 2 only; the baselines are not authorized until B is also written. The exact words:

**(A) Acceptance of the final protocol text** (completes milestone 2 only; authorizes nothing else):

> On `<date>` I accept `docs/BLIND_PLAY_PROTOCOL_V1_CANDIDATE.md` at commit `<accepted-protocol-sha>` as protocol P1 v1 (research settings D1-D15 as recorded 2026-11-05, both amendments). This is acceptance of the text only; it authorizes no execution, spending, credential, billing, smoke test, AI session, live flag, pre-registration or merge.

**(B) Authorization to record the official baselines**:

> On `<date>` I authorize recording the official non-AI scripted baselines exactly as in `docs/BASELINE_EXECUTION_CARD.md`: plan_sha256 `bb527a18a5ad88e82769ee800d97b2bfe8c9de73d856be688024e0286d6922dd` (14 runs, `keyset.v2`, matched-1000 and diagnostic-20000), on this Windows PC, once, at the commit that adds this entry to `PROJECT.md`, whose only difference from `<accepted-protocol-sha>` must be `PROJECT.md`, with no API call, credential or spending. This does not authorize the smoke test, any AI session, the live flag, pre-registration, billing, or a merge.

The `run` command records the quote you give it verbatim in `OWNER_APPROVAL_REFERENCE.txt` and **does not verify it**: the tool grants no approval; the PROJECT.md entry is the approval.

## 3. The commands (PowerShell, from the root of the clean checkout)

**Plan** (prints the 14 commands and the hash; writes nothing). First confirm the commit check of section 1 (`git diff --stat <accepted-protocol-sha> HEAD` shows only `PROJECT.md`):

```powershell
$sha = (git rev-parse --short=8 HEAD)   # this is <run-sha>
$date = Get-Date -Format "yyyy-MM-dd"
$out = "runs\blind-visual\baselines-$date-$sha"
Test-Path $out      # must print False
.\.venv\Scripts\python.exe -m rewardbench.blindplay.baselines plan --keyset keyset.v2 --out-root $out
```

The last line printed must be exactly:

```
plan_sha256 bb527a18a5ad88e82769ee800d97b2bfe8c9de73d856be688024e0286d6922dd
```

If it differs, **stop**: the code or settings are not the ones you accepted. The plan lists 14 runs in two conditions (7 each): `matched-1000` (`--max-requests 1000`, the budget-matched control) then `diagnostic-20000` (`--max-requests 20000`, an extended diagnostic, **not** budget-matched). Every command contains `--max-requests`. `--max-wall-seconds` is not part of the plan hash: the host default of 3,600 s applies to every run and is fixed only by the commit. Run directories are `<condition>_<NN>_<script>[_seedK]`: `matched-1000_01_idle`, `_02_key-sweep`, `_03_seeded-random_seed0` ... `_07_seeded-random_seed4`, and the same seven under `diagnostic-20000_`. Game seed 0 for all runs; script seeds 0 to 4 apply to `seeded-random` only.

**Run** (only after section 2 is in PROJECT.md). Put the date and text of your PROJECT.md authorization into the reference:

```powershell
.\.venv\Scripts\python.exe -m rewardbench.blindplay.baselines run --keyset keyset.v2 --out-root $out --i-have-owner-approval-reference "PROJECT.md entry dated <date>, commit <sha>: <paste sentence B of section 2>"
```

What the tool does and refuses:

* The **out root must not exist**. If it exists, `run` refuses ("never overwriting"). `run` also **refuses an out root inside an existing official-looking directory that holds files** (a parent named `runs` or containing `blind-visual`). In a clean checkout `runs\` does not exist yet, so `runs\blind-visual\baselines-...` is allowed; in the original `C:\Users\sh1ft\R.E.A.C.T` checkout, whose `runs\` is full, it is refused (checked on 2026-11-05 with the tool's own check, nothing written). If refused for that reason, use a new directory outside the repository and say so in the record. `--i-have-owner-approval-reference` is required.
* Exit code 0: all 14 host commands finished and the log says `"complete": true`. 1: a host command exited non-zero (the run stops there; `"complete": false`). 2: `REFUSED: ...` (nothing run).
* **Expected duration:** about 7 s per `key-sweep` episode, **measured once on one disposable episode** (which crashed at frame 1,749 after 90 game requests in 6.6 s). The full plan is **unmeasured**: 14 runs of up to 10 episodes at about 7 s would be roughly 15 to 20 minutes plus per-run start-up, which is an extrapolation, not a measurement. Each host run is capped at 3,600 s wall clock.

Files written under `$out`:

* `OWNER_APPROVAL_REFERENCE.txt` (your quote, unverified, with the plan hash);
* `baseline_plan.json` (the plan and `plan_sha256`);
* `baseline_run_log.json` (per run: name, condition, `max_requests`, exit code, the tail of stdout/stderr; `planned_runs`, `executed_runs`, `complete`);
* for each of the 14 run directories: `baseline_condition.json` (condition label and role, `max_requests`) and the host's own records (`host_session.json`, `referee\session.json`, transcripts, screenshots, per-frame privileged state; see `docs/ISOLATED_PLAYER_RUNTIME.md`).

## 4. After the run

Use the same PowerShell window (`$out`, `$sha`, `$date` set), or set them again.

1. **Compare the plan hash recorded in the output** with the one you authorized:

   ```powershell
   (Get-Content "$out\baseline_plan.json" | ConvertFrom-Json).plan_sha256
   (Get-Content "$out\baseline_run_log.json" | ConvertFrom-Json) | Select-Object plan_sha256, planned_runs, executed_runs, complete
   ```

   Both hashes must equal `bb527a18...6922dd`, `planned_runs` and `executed_runs` must be 14 and `complete` must be `True`.
2. **Assert exactly 14 run directories, then summarize and replay every one** (check the count first: `(Get-ChildItem $out -Directory).Count` must be 14, and no other directory may sit in `$out`). Then summarize and replay (the replay runs on a copy; summaries go to a new directory outside `runs\`):

   ```powershell
   $sum = "baseline-summaries-$date-$sha"
   New-Item -ItemType Directory $sum | Out-Null
   Get-ChildItem $out -Directory | ForEach-Object {
       .\.venv\Scripts\python.exe -m rewardbench.blindplay.results summarize $_.FullName --replay --json "$sum\$($_.Name).json"
       "$($_.Name): exit $LASTEXITCODE"
   }
   ```

   **Check each summary against the plan.** Each summary's header records `script`, `script_seed`, `keyset`, `seed`, `max_requests` and the planned episodes; compare them with the plan (`baseline_plan.json`) entry of the same run name: `keyset.v2`, game `seed` 0, 10 planned episodes, `max_requests` 1000 for `matched-1000_*` and 20000 for `diagnostic-20000_*`, script as in the directory name, `script_seed` 0 for `idle` and `key-sweep` and 0 to 4 for `seeded-random`. Any difference is reported and blocks use of that run.

   Exit code 0 means the integrity checks (hashes, hash chain, replay) passed and the run is complete. Exit code 1 means an integrity problem **or** an INCOMPLETE run. Read each report: **no run may be INCOMPLETE except `CENSORED_BY_REQUEST_LIMIT`, which must be plainly reported** (planned versus finished episodes, the limit, requests used, the partial episode). A `CONFLICT` between a run's condition label and its recorded request limit, or any integrity failure, is reported as such and **blocks use of that run until explained**. Whether any run is censored at 1,000 requests is **not known in advance**: a single key-sweep episode used 90 requests, so a 10-episode key-sweep might need roughly 900, close to but not clearly over 1,000 (one episode measured; the rest unmeasured). A censored run (the scripted player exits on the first rejected request) also lists **"player exit code != 0"** among its problems; that is an expected consequence of censoring, not a separate failure, and is reported as such.

   **Determinism cross-check (report-only).** Each `matched-1000` run is expected to be a deterministic prefix of the corresponding `diagnostic-20000` run (same script, script seed, keyset and game seed; only the request limit differs). Using existing outputs only, compare `<run>\referee\episodes.jsonl` of `matched-1000_NN_*` with `diagnostic-20000_NN_*`: for every episode finished in the matched run, `outcome`, `frames`, `start_frame_sha256` and `end_screenshot_sha256` should be equal (the censored partial episode has no row and is not compared). This has not been run; a difference is **reported, not repaired**, and does not by itself invalidate either run. Also note the expected identity of the 10 `idle` episodes within a run.
3. **Hash the data** (this inventories every file under `runs\` of the checkout, so it includes the baselines; the output must not be inside `runs\`):

   ```powershell
   .\.venv\Scripts\python.exe -m rewardbench.evidence_backup prepare --root . --out "baseline-inventory-$date-$sha.json"
   Get-FileHash -Algorithm SHA256 "$sum\*.json", "$out\baseline_plan.json", "$out\baseline_run_log.json"
   ```
4. **Back up, copy only** (never move or edit the raw data). Copy `runs\` to a private location you control, then verify the copy; see `docs/EVIDENCE_BACKUP_PROCEDURE.md`:

   `<private destination>\runs` **must not exist before the copy** (`Test-Path "<private destination>\runs"` must print `False`); otherwise `Copy-Item` nests `runs\runs`. `check-copy --copy` takes a directory that **contains `runs\`** (the layout `<private destination>\runs\...`), which is exactly what the command below produces.

   ```powershell
   Copy-Item -Recurse .\runs "<private destination>\runs"
   .\.venv\Scripts\python.exe -m rewardbench.evidence_backup check-copy --inventory "baseline-inventory-$date-$sha.json" --copy "<private destination>"
   ```

   Expect `"complete": true` with no `missing`, `mismatched` or `extra`.
5. **Commit only summaries and hashes**: the 14 summary JSON files, the inventory, and a short text with the file hashes. **Raw data stays local** (`runs\` is gitignored; do not force-add it, do not upload it).
6. **Record the result as a dated PROJECT.md entry**: the date, the commit, the plan hash, the 14 run directory names, each run's outcome counts, which runs (if any) were `CENSORED_BY_REQUEST_LIMIT`, the summary hashes, and the backup location. Also record `<accepted-protocol-sha>`, `<run-sha>`, the `git diff --stat` result (only `PROJECT.md`), the absolute path of the clone and the absolute path of the verified backup copy. Report failures and partial runs in the same entry. **Report per run**: the runs and episodes are not independent samples (section 6), so never pool them as n=70 or n=140. For each run give landings / finished episodes with planned versus finished episodes and requests used (protocol §9), never extrapolated to 10 episodes.

## 5. What not to do

* **No reruns to get better numbers.** A failed or partial run is reported as it is and **never silently repeated**. A rerun needs a new out root, a new owner decision and a stated reason, and the first attempt stays in the record.
* **No edits to settings, scripts or the plan after seeing any result.** Baselines tune nothing.
* Do not run `run` twice into the same out root (it refuses), do not delete or edit anything under `$out`, and do not run any AI session, set the live flag or use a credential while doing this.
* Do not present `diagnostic-20000` as a budget-matched control. Any comparison with an AI session uses **`matched-1000`** and discloses censoring.

## 6. What the baselines can and cannot show

They show what blind input produces in this game under these settings: what a script that does nothing, one that sweeps the keys in order, and five seeded random presses achieve (in particular how often they land, which is expected to be rare or never) over the same platform, keyset and frame budget as the study. They are the reference against which an AI landing count is later read. **They are not independent samples.** All 10 `idle` episodes are expected to be identical (same game seed, fixed start, no keys). In `key-sweep` the step counter, and in `seeded-random` the random stream, carry across episodes within a run (verified in `player_runtime/runtime.py`: both are created once per run and not reset at an episode boundary; each episode is a fresh browser context with the same seed). Each `matched-1000` run is expected to be a deterministic prefix of the corresponding `diagnostic-20000` run (same script, seeds and keyset; only the request limit differs; expected, not yet observed), so the two conditions are **not replicates**. Report per run; never pool runs or episodes as n=70 or n=140. The comparison metric under censoring is landings / finished episodes with planned versus finished episodes and requests used, never extrapolated to 10 episodes.

They are **not AI results**, not controllers, and not evidence that any model can or cannot play. They support **no learning claim** of any kind, and no cross-model or cross-condition ranking. A scripted landing, if one occurs, is reported as a baseline outcome, not as an achievement of the project.

## 7. How this relates to the smoke test

The baselines come first, cost $0 and need no credential. The excluded technical smoke test (one episode, at most 30 model calls) is a **separate, later** authorization that also needs the D15 owner-only actions (billing, spend limits, a stored key, a reviewed flag commit, a terminal confirmation). Authorizing the baselines does not authorize it. If a technical defect later changes the keyset, platform, frames per `act` or episode length, the baselines must be recorded again under the re-recording rule (candidate protocol §8).
