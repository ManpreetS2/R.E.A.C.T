> **Superseded in parts (Mission 019, 2026-11-05).** Current sources: `docs/BLIND_PLAY_PROTOCOL_V1_CANDIDATE.md` (the consolidated text), `PROJECT.md` §0.3 ("P1 v1 owner decisions — 2026-11-05") and `docs/MISSION_018_OWNER_AMENDMENTS.md`. The body below is kept unchanged as the historical record of that mission.
>
> Outdated in the body below: the open-PR counts ("open drafts #3 to #26 (24)", "24 open drafts" in milestone 9; PR #3-#30 is now 28 open, with the stack #12-#30 being 19 PRs); the row "Protocol text: Incomplete" (the text is consolidated and reconciled; only the owner's dated acceptance is outstanding); "Protocol conflicts (thinking, history): needs owner decision" and launch-card step 1 "Decide ... thinking, effort, smoke test versus pre-registered session, keyset.v2, ..." (the owner approved these as research settings on 2026-11-05, with two amendments, conditional and with no execution authority); "Scripted baselines ... none recorded under final settings ... settings are unapproved" (the settings are approved as research settings; still none recorded; recording needs a separate owner authorization, see `docs/BASELINE_EXECUTION_CARD.md`); the credential check described as an English-name/broad-group refusal (it is now a fail-closed SID allowlist, Mission 018); the test totals (881/892 are old; 1,049 passed at Mission 018). Also superseded: milestone 3's "Owner action: no (after 2)" (recording the baselines needs a separate owner authorization, see `docs/BASELINE_EXECUTION_CARD.md`). Still true: completion 29/100, no API call, credential or spend, the gate closed.

# Mission 016: recovery, audit and the route to v1 (2026-11-05)

**No API call, credential, or spending. `LIVE_CALLS_PERMITTED` is still `False`. No model has played.** Nothing here approves anything.

## 1. This PC

| Item | Result |
| --- | --- |
| OS | Windows 11 Pro 10.0.26300 (a newer build than the one Mission 014 was verified on; see the clipboard finding below) |
| Tools | Python 3.13.5, Git 2.49.0, GitHub CLI 2.97.0 (logged in as `ManpreetS2`), Node 22.17.1 |
| Disk | about 2.2 TB free |
| Repository | `C:\Users\sh1ft\R.E.A.C.T` existed but was **stale** (PR #23, `8259458`). It was not touched. Work happens in a clean worktree, `C:\Users\sh1ft\REACT-m016`, branch `mission-016-recovery`, based on PR #26's head `923e209` |
| Environment | Fresh venv in the worktree: `pip install -e ".[dev,blindplay,analysis,environments]"`, `playwright install chromium` (playwright 1.64.1, pytest 9.2.0, Pillow 13.0.0) |
| Baseline tests | 881 collected: **880 passed, 9 skipped, 1 failed** (clipboard probe, fixed below) |

**Environment: ready.**

## 2. GitHub state (verified by `gh`, not assumed)

PR #26 `feature/live-transport-preparation` @ `923e209` (draft, stacked on #25 → #24 → #23 → #22 → #21 → #19 → #18 → #17 → #16 → #15 → #14 → #13 → #12 → `main`).
The latest CI on it (runs 41127825866 push, 41129835227 push, 41127835643 and 41129844299 PR) all succeeded. #20 and #3–#11 are older draft branches. `main` only contains #1 and #2. Open drafts: #3 to #26 (24).
No PR in the stack has been merged and none should be without approval.

## 3. Old-PC research data

The "old PC" premise did not hold for this machine: `runs/` (185 MB) and `C:\Users\sh1ft\R.E.A.C.T-backups\` (3 zip snapshots, 35 MB) are present here.

**Verified read-only:** all 383 artifacts in `docs/assets/research-results/MANIFEST.json` exist under `runs/` and match their recorded SHA-256 (0 missing, 0 mismatched). Also present: `runs/blind-visual/` (Missions 013 and 014 sessions).

**Not verifiable from here, and not assumed to exist:** Mission 014 macOS (Seatbelt) and Mission 015A/B session records, which were produced on the owner's MacBook. If they matter, they live only on that Mac. Nothing was regenerated or overwritten.

**Safe migration procedure (when moving to another machine; copies only, never move or edit):**
1. On the source: `Compress-Archive -Path runs -DestinationPath react-runs-<date>.zip` (read-only on `runs`), then `Get-FileHash -Algorithm SHA256` on the zip.
2. Copy the zip and the hash to an **off-machine private** location (external drive or private cloud). Do **not** commit it or put it in a public place (PROJECT.md: no raw-data uploads).
3. On the target: extract into an **empty new directory**, never into an existing `runs/`.
4. Verify with a manifest check: for every `path`/`sha256` in `docs/assets/research-results/MANIFEST.json`, compare against the extracted copy. Expect 0 missing, 0 mismatched.
5. Only then use it. Keep the source until a second copy is verified.

Open since Mission 012: **an off-machine backup has still not been made** (owner approval, §9 of PROJECT.md).

## 4. Audit

| Area | State | Evidence / action |
| --- | --- | --- |
| Original-game integrity, deterministic replay | Complete | Upstream `0da09dc` file hashes and replay tests pass here |
| Sandbox isolation (Windows) | Complete, **one defect found and fixed** | Clipboard probe now reads a canary (below). All other attacks denied |
| Credential security | Complete, **one weakness fixed** | The Windows credential-file permission check was English-name based and had only ever been tested with a monkeypatch. Now SDDL/SID-based and tested on real files |
| Real API transport | Built; **real endpoint untested** | Only a real call can settle it. Cannot be done without owner authorization |
| Screenshot / tool-call compatibility | Offline-verified; real behaviour unknown | Image tokens 1,196 at 1280×720 per docs |
| Budget enforcement | Complete offline | Reservation before each call, session and cumulative caps, historical spend counted. Console spend limits are the independent backstop |
| Windows ACL validation | **Fixed this mission** (below) | `test_real_windows_acl_check_on_real_files` |
| Protocol conflicts (thinking, history) | Documented; **needs owner decision** | `docs/LIVE_TRANSPORT_PREPARATION.md` Incompatibility 1. Only `thinking: disabled` passes the gate |
| Scripted baselines | Runner exists (`rewardbench.blindplay.scripted`: `idle`, `key-sweep`, `seeded-random`); **none recorded under final settings** | Protocol §7 asks for final settings, which are unapproved. Deliberately not run |
| Pre-registration | Not started | Needs approved protocol |
| Evidence preservation | Complete for historical data, off-machine backup missing | §3 |
| Release readiness | Not started | §6 |
| **Protocol text** | **Incomplete** | P1 is a draft with amendments §12–§14 appended, and §5/§13 contain statements that §14 corrects. The owner cannot approve it cleanly until it is consolidated into one clean text. Not done in this mission; first item of milestone 2 |

### Defects fixed

1. **Clipboard isolation test failure on Windows 11 build 26300.** `OpenClipboard` now succeeds inside the AppContainer, where earlier builds denied it. This was checked rather than assumed harmless: the probe now reads a per-run canary that the host places on the clipboard (and restores afterwards). From inside the sandbox `GetClipboardData` returned no data; an unsandboxed control read the canary back. So **data does not cross**; only the open call changed. The test now asserts the data path (`clipboard_read` denied), and the docs state the exact guarantee. This relaxes nothing that carried data.
2. **Credential permission check was name-based and untested on real files.** It now reads the file's SDDL via `icacls /save` and refuses any allow entry for Everyone, Users, Authenticated Users, Interactive, Network, All Application Packages or any AppContainer SID, by SID, regardless of Windows language. It also refuses when the ACL cannot be read. Tested on real files for each case, and on SDDL strings on every platform.

### Tests

Full suite after the changes: see §8 (filled in from the final run).

## 5. First real flight: provisional configuration (approves nothing)

| Setting | Value | Verified 2026-11-05 |
| --- | --- | --- |
| Provider / model | Anthropic API, `claude-haiku-5-5` | Pricing page lists it |
| Price | $0.10 in / $0.50 out per MTok up to 100K prompt tokens; $0.50 / $2.50 above | **Unchanged since 2026-10-30** |
| Tool overhead | 286 tokens with `tool_choice: auto` | Unchanged |
| Thinking / effort | `disabled` / `low` | Owner decision (Incompatibilities 1 and 2) |
| Scope | 1 episode, at most 30 calls, `keyset.v2`, Windows | Owner decision |
| Caps | $0.50 session; $1.00 cumulative including $0.106019 (so $0.893981 remains) | Owner decision |
| Expected cost | about $0.03 for 30 calls; the gateway reserves about $0.06 | Estimate, not a measurement |

**Date constraint:** the authorization must record prices checked within the last 7 days. The check above is dated 2026-11-05, so the file must be filled in and used by 2026-11-12, or re-checked.

### Owner-only launch card

Do each step yourself. **Never paste the key into any chat or tool, including Claude Code.** Steps 1 to 4 spend nothing.

1. **Decide** (record dated entries in `PROJECT.md`): thinking, effort, smoke test versus pre-registered session, `keyset.v2`, protocol text, provider/model/caps, platform. Owner decisions list: `docs/LIVE_TRANSPORT_PREPARATION.md`.
2. **Console** (platform.claude.com): buy the smallest credit amount, auto-reload **off**, org spend limit $1, workspace `react-smoke` with a $1 limit, workspace-scoped key `react-smoke-1` with a 1 to 7 day expiry. Exact clicks: `docs/LIVE_TRANSPORT_PREPARATION.md`, "Configuring API billing".
3. **Store the key** with the PowerShell block in that document (`Read-Host -AsSecureString`, file under `%USERPROFILE%\.react-secrets`, `icacls /inheritance:r`). The gate checks the permissions, now by SID.
4. **Keep Claude Code on your subscription**: confirm `claude auth status` says `claude.ai`, and no `ANTHROPIC_*` variable is set (the gate refuses if one is).
5. **A reviewed commit** sets `LIVE_CALLS_PERMITTED = True`. CI must be green on it, and the checkout clean.
6. `python -m rewardbench.blindplay.live_session template` → fill in the values, name that commit, store the file **outside the repository**, validity at most 7 days.
7. In your own terminal run the `live_session run ...` command shown in that document and type the confirmation sentence.
8. Afterwards: reconcile with Console → Usage, **delete the key**, set the flag back to `False`.

## 6. Route to a finished v1

Weights sum to 100. "Verified" credit is given only when the acceptance criterion is met and was re-run on this PC today. **There are no estimated points** in the total below; estimates are in the table's last column and are not counted.

| # | Milestone | Weight | Earned (verified) | Deliverable, acceptance criterion | Depends on | Owner action | Spend |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | Authentic original-game bridge + deterministic replay | 8 | **8** | Done: upstream hashes verified, scripted sessions replay byte-identically (tests pass on this PC) | none | no | $0 |
| B | OS-isolated player runtime on the chosen platform (Windows) | 7 | **7** | Done: all probes denied, with the clipboard check strengthened today | A | no | $0 |
| C | Offline model gateway + budget ledger | 7 | **7** | Done: offline tests pass, historical spend counted | B | no | $0 |
| D | Gated live transport built and verified against a mock server | 5 | **5** | Done, plus the ACL fix; **does not** include the real endpoint | C | no | $0 |
| 1 | Real-provider screenshot-to-action smoke test | 10 | 0 | One authorized session: provider returns a valid tool call from a real screenshot and the game advances; ledger reconciled with Console; flag set back to `False`. A failure, with cause, still counts as a result | Owner decisions, billing, steps 1 to 8 above | **yes** | est. $0.03 to $0.06 (cap $0.50) |
| 2 | Final protocol approval | 5 | 0 | One consolidated clean protocol text (merge §12 to §14 into the body, remove superseded statements), dated owner approval in `PROJECT.md` | none (I can prepare the text) | **yes** | $0 |
| 3 | Scripted baselines | 5 | 0 | `idle`, `key-sweep`, `seeded-random` seeds 0 to 4 recorded through the isolated host under the approved keyset, platform and budgets; summary + hashes committed, raw local | 2, keyset decision | no (after 2) | $0 |
| 4 | Protocol pre-registration | 5 | 0 | Commit hash + configuration hash recorded in `PROJECT.md` before the first study call; no edits afterwards | 1, 2, 3 | **yes** | $0 |
| 5 | Formal 10-episode blind-gameplay study | 15 | 0 | Session finished or stopped by a predeclared rule; all episodes reported, none dropped | 4, billing | **yes** | est. about $0.25 for Haiku (±2 to 3×); cumulative cap $1.00 leaves room for only one session |
| 6 | Independent terminal-outcome and replay verification | 6 | 0 | Each study episode replayed in fresh Chromium reproducing every screenshot; outcomes read from the privileged referee record agree with the HUD; mismatches reported | 5 | no | $0 |
| 7 | Results and limitations | 6 | 0 | Chronological results with hashes, an explicit "no learning claim" unless supported, a limitations section | 6 | review | $0 |
| 8 | Authentic demonstration footage | 5 | 0 | Footage rendered from the replayed referee record of the actual study (a landing is not required; crashes are shown honestly) | 6 | no | $0 |
| 9 | Safe integration of existing PRs | 6 | 0 | The 24 open drafts (#3 to #26) have an owner-approved order and disposition (merge, close, or leave), tests green after each step | 7 | **yes** | $0 |
| 10 | Docs, install verification, v1 release | 10 | **2** | Install from a clean clone on a clean machine, run tests, README quick-start works, tag and GitHub release. Earned so far: install and tests run on this PC (20%) | 9 | **yes** (tag) | $0 |

**Verified completion: 8 + 7 + 7 + 5 + 2 = 29 / 100.** The earlier 53% was subjective; this figure counts only milestones whose acceptance criterion was met and re-run today, and it gives no credit for the study, which has not run. Working infrastructure (A to D) is 27 of the 29 points; the points that would show an AI playing are all still 0. 71 points remain, of which 15 would be the study itself.

**Shortest path:** owner decisions (milestone 2 and billing) → milestone 3 → milestone 1 → milestone 4 → milestone 5 → 6, 7, 8 → 9 → 10. Total new spend if everything goes as estimated: about $0.30 to $0.40 against $0.894 remaining. A bad estimate (Haiku at 3× of the P1 figure) would use about $0.75 for the study alone, so a second study session is not affordable under the $1.00 cap without a new decision.

## 7. What was deliberately not done

* No baseline was recorded (settings are not final), no key was created or read, no network request was made, no flag was changed.
* The protocol was not consolidated or "approved"; that is the owner's decision.
* Nothing was merged. Historical evidence and `runs/` were only read.

## 8. Test results

Windows 11 build 26300, Python 3.13.5, real Chromium and the real AppContainer sandbox required: **901 collected, 892 passed, 9 skipped (POSIX or macOS only), 0 failed** (baseline before changes: 880 passed, 1 failed). The 11 new tests are 10 SDDL cases and the real-file ACL test. CI for this branch is recorded by the PR.
