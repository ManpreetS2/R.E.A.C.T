# v1 release integration plan (Mission 017, 2026-11-05)

Nothing in this document was executed against GitHub. **No PR was merged, closed, rebased or retargeted; `main` did not move; no branch was force-pushed.** Every owner approval point is marked **[OWNER]**.

## 1. Verified topology (read with `gh` and `git` on 2026-11-05)

`main` = `5e624c7`. It is a **strict ancestor of PR #27**, so nothing on `main` is missing from the stack.

Linear stack (each PR is based on the previous one's branch):

`main` → #12 `t3/verify-offline-v1` → #13 → #14 → #15 → #16 → #17 → #18 → #19 → #21 → #22 → #23 → #24 → #25 → #26 → #27 `mission-016-recovery` → this sprint's PR.

* #20 (`docs/project-md-master-plan`) is a sibling of #21 based on #19. Its head is **already reachable from #27**, because Mission 012 merged it into #21's branch. Nothing is lost if it is never merged on its own.
* Net change `main..#27`: 227 files, +44,804 / −414. Largest blob 128 KB (no large binaries enter `main` through the stack).
* Side branches, not ancestors of #27: **#3–#11**, all based on `main`, containing the structured controller-tuning / RL track (RL pilot, curricula v3 to v7, Gymnasium editions). They are 57 to 743 files each and include model checkpoints and footage. Their documented outcomes are mostly negative or retracted claims.

## 2. Rehearsal results (non-destructive)

| Check | Result |
| --- | --- |
| `git merge-base --is-ancestor main #27` | yes, so merging the stack into `main` is a fast-forward-able merge with no content conflicts |
| `git merge-tree --write-tree main #27` | clean, no conflicts |
| `git merge-tree` of **each** of #3–#11 against #27 | all 9 clean, no conflicts (nothing prevents merging any of them later) |
| Clean clone of the GitHub repo at #27, new venv, `pip install -e ".[dev,blindplay,analysis,environments]"`, `playwright install chromium`, `pytest --collect-only` | installs and collects on this PC (PowerShell, Python 3.13.5) |
| CI on #27 | green on Windows, macOS and Ubuntu (a fast-forward of `main` to #27 yields an identical tree, so that CI covers the merged state) |

Not rehearsed: a full test run in a second checkout, because two checkouts running the AppContainer tests at once share runtime-image state on this PC; the full suite is run once on the sprint branch instead (see the PR).

## 3. Why not merge the stacked PRs one by one

* The stack is now **19 PRs (#12 to #30)** and 28 PRs are open in total (#3 to #30); when this plan was first written it was 16 PRs (#12 to #27) and 25 open (updated in Mission 019, 2026-11-05). Each upper PR already **contains** all the lower ones; merging layer by layer produces 19 merges of the same commits and 19 CI cycles for no new content.
* The docs, manifests and evidence summaries **cite commit SHAs and CI run IDs** (for example `923e209`, `2419325`, runs 41127825866). **Squash or rebase would orphan those references** (GitHub rewrites the SHAs; the originals would stay reachable only through the kept branches and tags, not from `main`). Use a merge that preserves the commits.
* GitHub does not retarget stacked PRs automatically when their base merges unless the base branch is deleted.

## 4. Recommended strategy [OWNER approves each step]

1. **Do not touch #3–#11 for v1.** They are the separate, historical controller-tuning track (PROJECT.md §0.1). Keep the branches. Optionally tag each head (`archive/pr-<n>`) so the evidence survives branch deletion. Leave them as drafts or close them with a comment pointing at this plan; closing is the owner's call.
2. **Do not merge anything before the results exist.** A v1 release that contains infrastructure but no study is not the v1 defined in PROJECT.md. The release PR is created after milestones 1 to 8 (see `docs/MISSION_016_RECOVERY_AND_V1_ROUTE.md`).
3. **One release PR.** From the final head of the stack to `main`, a **merge commit** (not squash, not rebase), titled "R.E.A.C.T. v1". `main`'s existing commits remain first-parent ancestors (the stack itself already contains one merge commit, `a5ba931`, which brought #20's branch into #21's). Its tree equals the release head, so it adds no untested content.
   **Alternative (equally valid, owner's choice):** fast-forward `main` to the release head. That keeps exactly the commits whose CI runs are cited and creates no new SHA; the cost is that GitHub shows no merge event for a release PR. Either way, the **pre-registration commit must be reachable from the release head**.
4. **Before merging**, the owner tags the current `main`: `git tag pre-v1-main 5e624c7` (and pushes the tag). That is the rollback anchor.
5. **After merging**, tag `v1.0.0` on the merge commit and publish the GitHub release with the results document. An earlier `v1.0.0-rc1` on the infrastructure may be tagged for review if wanted.
6. **Child PRs #12–#30**: after the release PR is merged they show their commits as contained in `main`. Close them with a comment pointing at the release. **Never delete their branches** (they are the cited provenance).
7. **#20**: close after release (content already included).

## 5. CI checkpoints

* Green Windows, macOS and Ubuntu CI on the release PR head, **plus** the local Windows full run with the AppContainer and real Chromium required (not skipped).
* `python -m rewardbench.evidence_backup verify` must report 383 ok, 0 missing, 0 mismatched on the machine that holds `runs/`.
* The three isolation-required jobs (Windows and macOS) must have run isolation, not skipped it.

## 6. Rollback

* Before the merge: `pre-v1-main` tag at `5e624c7`.
* If the merge is wrong: `git revert -m 1 <merge-commit>` on a new PR (keeps history). Resetting `main` back to `5e624c7` is possible only by a force-push, which needs the owner's explicit approval and should be avoided.
* The stack branches are untouched by the merge, so they can be re-used.

## 7. Technical problems that would prevent a clean release (today)

1. **No study results exist**, so there is nothing to release as v1 yet (milestones 1 to 8).
2. `PROJECT.md` still contains migrated historical statements (for example "public v1 released; blind visual-gameplay protocol approved" at line 93 of PROJECT.md at `e44d149`, in the historical plan header, whose full text is "Master research & build plan | Version 1.3 | Updated 17 October 2026 | Status: public v1 released; blind visual-gameplay protocol approved, implementation pending"; the earlier "line 74" was wrong) overridden only by §0.5. `main` carries that text until a merge happens; a small docs-only correction of that header line could land earlier if the owner wants (the original wording would stay in the Google Doc and in history). The release README should link the current status rather than the historical text.
3. Mac-only evidence (Missions 014 macOS and 015A/B session records) is not on this PC; cross-platform claims in the release must cite the committed summaries only.
4. An off-machine backup of `runs/` still does not exist (`docs/EVIDENCE_BACKUP_PROCEDURE.md`).
5. Nothing in the repository forbids merging the stack, but PROJECT.md §0.4 says "never casually merge the full stack": merging stays a recorded owner decision.

## 8. Owner approval points

* A. Which PRs are closed after release and whether #3–#11 are tagged and closed or left open.
* B. Tagging `pre-v1-main`.
* C. Merging the release PR as a merge commit.
* D. Tagging `v1.0.0` and publishing the release.
* E. Deleting no branches (recommended default; any deletion needs a separate approval).
