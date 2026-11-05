# Mission 018: the two owner-approved amendments (2026-11-05)

**Offline only. `LIVE_CALLS_PERMITTED` is still `False`. No API request, no credential, no spend, no official baseline, no pre-registration, no merge.** This implements the two amendments recorded by the owner in `PROJECT.md` §0.3 (PR #29); it does not finalize the protocol, which stays "candidate" until the owner accepts the reviewed result.

## Amendment 1: fail-closed credential-file allowlist (`live_transport.py`)

Replaces deny-list checking. On Windows the file passes only if **all** hold: the current user's SID is read from the process token; the file's **owner** is that SID, SYSTEM or Administrators; the DACL exists, is not NULL and parses completely; every allow-type ACE (`A`, `OA`) names only the current user, SYSTEM (`SY`/`S-1-5-18`), Administrators (`BA`/`S-1-5-32-544`) or OWNER RIGHTS (`OW`/`S-1-3-4`). Deny ACEs are ignored; every other ACE type (conditional, callback, audit), alias, SID, group, service account, AppContainer or unknown token is refused; any failure to read the ACL, owner or current SID refuses. SYSTEM and Administrators are tolerated because they can read or take ownership of any file anyway; OW is safe because the owner must already be on the list. The file is also re-checked after it is read (identity and ACL), so a swap between check and read is refused.

Tests (real files, fake content, `tests/blindplay/test_audit_017_live.py`, `test_live_transport.py`): a real file shared with **another specific user SID** (current user's domain plus RID 503 and 504) is refused and the tests fail rather than skip if the grant fails; real files granted LOCAL SERVICE, NETWORK SERVICE, Backup Operators, Remote Desktop Users and all-services are refused; an Everyone grant on the fixture credential is refused by the **unpatched** gate; NULL DACL, foreign owner, unknown current SID and malformed SDDL are refused; swap-during-read, rewrite-in-place, link-swap and ACL-widened-during-read are refused.

Known limits: group membership is not expanded; SDDL prints the built-in Administrator (RID 500) and Guest (RID 501) accounts as the aliases `LA`/`LG`, so those aliases are accepted only when they are the current user's own account (found by CI: GitHub's Windows runner runs as the built-in Administrator and its own files were refused; fixed with tests); a swap that restores identical file index, size and mtime is not detectable without opening once and using the handle; the tests run on Windows only (CI's macOS and Ubuntu runners skip them); never exercised on a real key.

## Amendment 2: budget-matched baseline request limits (`host.py`, `baselines.py`, `results.py`)

* `host.py` CLI: `--max-requests` (default unchanged, 20,000).
* `baselines.py`: the plan (`react.blindplay.baseline-plan.v2`) has two **labelled** conditions of seven runs: **`matched-1000`** (`--max-requests 1000`, the budget-matched control) and **`diagnostic-20000`** (`--max-requests 20000`, extended scripted diagnostic, **not** budget-matched). `--max-requests` is in every command and in the plan hash (which also covers labels and roles, not the output path). A known label can never carry another limit; custom labels exist for dry-label tests only and are labelled "NOT budget-matched, NOT an official condition"; `only_scripts` is refused on an approved run. `run` still needs `--i-have-owner-approval-reference`, never overwrites and refuses official-looking directories. The default plan hash for `keyset.v2`, 10 episodes, 8,000 frames is recorded by `baselines plan` (see the tests).
* `results.py`: a session ended early by the request limit is reported as **`CENSORED_BY_REQUEST_LIMIT`** (planned versus finished episodes, the limit, requests used, the partial episode, from recorded data only, `unavailable` otherwise) and is INCOMPLETE; a condition label that disagrees with the session's recorded limit is `CONFLICT`; the condition is stated only if the run log records it.
* Observed behaviour of the limit (code, `session.py`): every game request counts (brief, observe, act); past the limit each request is rejected with "request budget exhausted" and the scripted player then exits; unplayed episodes leave no record. The expectation that key-sweep is censored after about 2 episodes at 1,000 requests is from arithmetic, **not measured**.
* Candidate protocol §9 and `docs/LIVE_TRANSPORT_PREPARATION.md` updated to match.

## Review and verification

Independent Opus review: no blockers; 3 major and 6 minor findings (a "matched" label could carry any limit; a disagreeing condition was only a warning; no real-file test for another specific user; fake end-to-end refusal; file-swap window; censoring boundary; run-log matching by name; `only_scripts` on approved runs). All fixed except one residual noted above.

| Check | Result (Windows 11 build 26300, real AppContainer + Chromium) |
| --- | --- |
| Full suite | **1,058 collected: 1,049 passed, 9 skipped (POSIX/macOS only), 0 failed** |
| Mutation check | **60/60 caught, 0 survived, 0 not applied** (mutations for the new ACL and file-swap guards added) |
| Live gate | `LIVE_CALLS_PERMITTED = False`; pinned by `test_the_real_flag_is_false` |
| CI | recorded in the PR |

Nothing here authorizes execution. Remaining owner-only actions (D15) are unchanged.
