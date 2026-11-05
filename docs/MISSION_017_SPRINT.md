> **Superseded in parts (Mission 019, 2026-11-05).** Current sources: `docs/BLIND_PLAY_PROTOCOL_V1_CANDIDATE.md` (the consolidated text), `PROJECT.md` §0.3 ("P1 v1 owner decisions — 2026-11-05") and `docs/MISSION_018_OWNER_AMENDMENTS.md`. The body below is kept unchanged as the historical record of that mission.
>
> Outdated in the body below: "Owner decision record ... D1-D15, all undecided" and "CANDIDATE, not owner approved" (the owner approved the research settings D1-D15 with two amendments on 2026-11-05; the final text still awaits acceptance; nothing is pre-registered); "`plan` prints the 7 commands" (the plan now prints 14 commands, two conditions of seven, and a plan hash that includes `--max-requests`); "Known remaining gap: the ACL check is a deny-list" (replaced by a fail-closed allowlist in Mission 018); "Baseline request limit ... Key-sweep needs about 400 requests per episode ... add a `--max-requests` flag" (the flag exists and is frozen in the plan hash; the 400-requests-per-episode and "about 4,000 for 10 episodes" claims are wrong because episodes end on a crash, and one disposable measurement of a single key-sweep episode used 90 requests; see candidate protocol §9); "Open: thinking/effort/caps" style open decisions (approved as research settings); and the PR counts ("stack of 16 PRs", "25 PRs open"; now PR #3-#30 is 28 open, stack #12-#30 is 19 PRs). Rule 17 ("the gateway keeps calling the model") was fixed here in Mission 017 and is verified by `test_the_referees_request_budget_error_ends_the_session_with_no_further_model_call`.

# Mission 017: multi-agent v1 completion sprint (2026-11-05)

**Offline only. `LIVE_CALLS_PERMITTED` is still `False`. No Anthropic request of any kind (not even authentication or token counting), no credential, no spend, no formal session, no official baseline, no pre-registration. No model has played.** Nothing here records an owner approval.

Starts from PR #27 (`2419325`, CI green on Windows, macOS, Ubuntu). Claude Code authenticated by `claude.ai` subscription throughout; no `ANTHROPIC_*` variable set.

## Delegation

| Agent | Model | Job | Result |
| --- | --- | --- | --- |
| Haiku 1 (read-only) | haiku | Baseline runner, replay, reporting inventory | Found: `scripted.py` runs unsandboxed with keyset.v1; host CLI had no `--keyset`/`--seed`; no results extractor, no footage tool |
| Haiku 2 (read-only) | haiku | PR graph, divergence, merge-tree | Facts used in `docs/V1_RELEASE_INTEGRATION_PLAN.md` (re-checked by the coordinator and Opus) |
| Opus 1 | opus | Protocol reconciliation brief | 17 contradictions, operative requirements, D1-D15 |
| Sonnet A | sonnet | Candidate protocol and decision record | Written; see below |
| Sonnet A2 | sonnet | Applied Opus review fixes F1-F10 | Applied |
| Sonnet B | sonnet | Offline safety/transport audit | **8 real defects found, each with a failing-first test, then fixed** |
| Sonnet C | sonnet | Baseline readiness, results tooling | `baselines.py`, `results.py`, host CLI flags |
| Sonnet D | sonnet | Replay-time footage capture | `footage.py` |
| Opus 2 (independent) | opus | Consistency/scientific-integrity review | No blockers; 4 major, remaining minor findings; all applied (one needs an owner decision) |

All agents ran on the requested model aliases; no substitution. The coordinator (Sonnet 5.5) integrated everything, ran the suites and wrote the PR. At most three workers ran at once and each owned disjoint files.

## Defects fixed (all in offline code, each with a regression test in `tests/blindplay/test_audit_017_live.py`)

1. **Credential ACL check** accepted an empty string, garbage, a missing `D:` and a **NULL DACL** (which grants everyone access); verified with a real file given a NULL DACL. Missing/NULL DACL is now refused, the last `D:` header is used, and more broad trustees are refused (anonymous, guests, domain users, restricted code, power users, capability SIDs, conditional ACEs, lower-case SIDs).
2. **Authorization file:** a pricing date in the future was accepted; a failing `git status` was read as "clean". Both refused now.
3. **Free calls:** a reply reporting `input_tokens: 0` was charged $0. Now treated as missing usage: worst-case charge and the session stops.
4. **Opening balance:** a ledger with spending but no opening-balance record was accepted as having the $0.106019 historical balance. The ledger now tracks the opening record explicitly.
5. **Billing on odd statuses:** unlisted 5xx and non-200 1xx/2xx statuses (for example 204) were settled as "not billed". Now charged at worst case.
6. **Crash on odd replies:** a `stop_reason` that was a list/dict raised `TypeError` inside the gateway. Now a malformed reply, charged at worst case.
7. **Screenshot replay:** a screenshot sequence number that had scrolled out of the 4-image window could be accepted again. All accepted sequence numbers are now remembered.
8. **Request limit:** the gateway kept calling the model after the referee reported `request budget exhausted` (reachable: 150 calls x 8 tool calls = 1,200 requests > 1,000). The session now ends with `game_request_limit`. The match is on the referee's message text; a shared constant in `contract.py` would be sturdier (not changed).

Also covered by existing or new tests with no fix needed: model-ID mismatch, price and token bounds, redirects, refusals, oversized/malformed replies, crash-durable reservations, privileged-data and key leakage.

**Checked against the official documentation on 2026-11-05 (no API use):** `Authorization: Bearer` is the documented primary key header (`x-api-key` legacy), so the transport is right. The docs now show `anthropic-version: 2026-10-21`; its only Messages API changes are removed `temperature`/`top_p`/`top_k` and two 400 cases, none sent by this transport, and `2023-06-01` remains a documented version. The transport keeps `2023-06-01` (the tested format); the candidate protocol records this.

**Known remaining gap:** the ACL check is a deny-list of broad groups. A grant to one specific other user's SID looks private because the checker does not know the owner's SID.

## New deliverables

| Deliverable | File(s) | Status |
| --- | --- | --- |
| Candidate protocol | `docs/BLIND_PLAY_PROTOCOL_V1_CANDIDATE.md` | **CANDIDATE, not owner approved, not pre-registered.** Historical draft unchanged |
| Owner decision record | `docs/BLIND_PLAY_V1_OWNER_DECISIONS.md` | D1-D15, all undecided |
| Baseline tooling | `src/rewardbench/blindplay/baselines.py`, host CLI `--keyset/--seed/--max-wall-seconds` | Tested; `plan` prints the 7 commands and a plan hash; `run` refuses without an approval reference and never overwrites; no official baseline recorded |
| Results/integrity report | `src/rewardbench/blindplay/results.py` | Chronological episodes from trusted referee data, completeness, integrity (hashes, hash chain), optional replay (on a copy), cost summary. Exercised on scripted sessions only |
| Footage | `src/rewardbench/blindplay/footage.py` | Per-frame deterministic replay capture, refuses unless replay reproduces and screenshots match recorded hashes, burned-in provenance label. Rendered a scripted session and inspected a frame by eye |
| Evidence tools | `src/rewardbench/evidence_backup.py`, `docs/EVIDENCE_BACKUP_PROCEDURE.md` | Read-only verify, inventory, check-copy |
| Integration plan | `docs/V1_RELEASE_INTEGRATION_PLAN.md` | Rehearsal results recorded; nothing merged |

## Open items found (not hidden)

* **Baseline request limit:** the baselines run under host defaults (20,000 requests), while the study limit is 1,000. Key-sweep needs about 400 requests per episode, so the study limit would cut it short. Decision needed (owner/protocol) before official baselines: add a `--max-requests` flag and say whether baselines share the limit.
* The candidate protocol's rule on unlisted 5xx statuses now matches the code (any 5xx is retried and charged); the earlier suggestion that they end the session was not what the code does.
* Footage shows the recorded outcome on every frame, as a label from the trusted record.

## Verification

Windows 11 build 26300, Python 3.13.5, real AppContainer sandbox and Chromium required (not skipped), all provider traffic from the loopback mock:

| Check | Command | Result |
| --- | --- | --- |
| Full suite | `.\.venv\Scripts\python.exe -m pytest --tb=short -p no:cacheprovider` | **1,005 collected: 996 passed, 9 skipped (POSIX/macOS only), 0 failed** (baseline at #27: 892 passed, 9 skipped). It ran after all code changes; only docs and the mutation script changed afterwards |
| Mutation check (50 deliberately broken safety rules) | `python docs/assets/offline-ai-gateway/verify/mutation_check.py . <report>` | First run 49/50 caught, 0 survived, **1 not applied** because the opening-balance fix changed the mutated text; mutation updated to the new code (`docs/assets/offline-ai-gateway/verify/mutation_check.py`), rerun **50/50 caught, 0 survived, 0 not applied** |
| Historical manifest | `python -m rewardbench.evidence_backup verify --root C:\Users\sh1ft\R.E.A.C.T` | 383 ok, 0 missing, 0 mismatched (before and after the sprint); backup zips present; `runs/` untouched |
| Replay determinism | in the suite (`test_results`, `test_footage`, `test_baselines`, existing replay tests) | passed; tamper cases detected |
| Footage | `python -m rewardbench.blindplay.footage <session> --out <new>` on a disposable scripted session | rendered, 106 frames; a gameplay frame viewed by eye shows the real game with the provenance strip |
| Clean-clone install | disposable clone of GitHub at #27, new venv, `pip install -e`, `playwright install`, `pytest --collect-only` | installed and collected (clone then deleted) |
| Cross-platform CI | GitHub Actions on the PR | recorded in the PR |

No live network request was made by any check. Nothing was run against reserved evaluation cohorts or written to `runs/`.
