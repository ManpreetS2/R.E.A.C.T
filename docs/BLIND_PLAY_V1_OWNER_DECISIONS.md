**OWNER SETTINGS APPROVED WITH AMENDMENTS ON 2026-11-05 — CANDIDATE IMPLEMENTATION PENDING — NOT PRE-REGISTERED — NO PAID EXECUTION AUTHORIZED**

# Blind-play P1 v1 — owner decision record

**The owner approved the proposed research settings with two amendments on 2026-11-05.** See the dated binding decision record in `PROJECT.md` §0.3. This is **protocol/settings approval only**, conditional on changes and independent review, not permission to spend, use credentials, activate the live gate, run official baselines, pre-register, or merge. The candidate remains unfinalized until the two amendments are implemented and reviewed. Source: `docs/BLIND_PLAY_PROTOCOL_V1_CANDIDATE.md` (candidate, not approved, not pre-registered). The recommendations are the
research team's proposals, not decisions.

| ID | Decision | Proposed value | What rejecting changes | Recommendation | Owner mark | Owner / date |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | Adopt the candidate as protocol P1 v1 (the draft stays unchanged as history) | The candidate document | Milestone 2 stays blocked until another protocol is adopted | Approve | [x] Approve conditionally: incorporate two amendments and verify before finalizing | Owner, 2026-11-05 |
| D2 | Key set `keyset.v2` (11 keys, no `KeyS`) | `keyset.v2` | Needs a code change to offer `S`; frame budgets no longer measure game time uniformly | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D3 | Thinking mode | `disabled` | Build option B, C or D (C drops the last-4-images policy and raises cost); re-test | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D4 | Effort, same for smoke test and study | `low` | Higher cost and a new configuration hash; splitting the value weakens the smoke test | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D5 | Provider and model | Anthropic `claude-haiku-5-5` | Transport supports Anthropic only; other models are untested and costlier | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D6 | Platform | Windows on this PC (build 26300) | macOS has a different start frame; verification would have to be redone on the Mac | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D7 | Excluded technical smoke test, with the order of work changed for it alone | Smoke test before pre-registration, excluded from the study | Either no smoke test (a technical defect could waste the study) or a pre-registered session (baselines and pre-registration first; it counts) | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D8 | Smoke test scope | 1 episode, at most 30 model calls | Different cost and coverage | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D9 | Study scope | 1 session, 10 episodes, 150 calls, 8,000 frames per episode | More sessions would not fit $1.00 | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D10 | Spend caps (**record before the smoke test**) | $0.50 per session; $1.00 cumulative including the $0.106019 already spent on OpenAI ($0.893981 remains) | Excluding historical spend would make the $1.00 fresh; other caps change what can run | Approve with the sub-decision below; both must be recorded in PROJECT.md before the smoke test, because a cap set after seeing the smoke cost is a budget change after the smoke test | [x] Approve: smoke $0.50; cumulative $1 incl. $0.106019; study cap = remaining reconciled balance (see below) | Owner, 2026-11-05 |
| D11 | Merged stopping rules and the disclosure of the 20,000-character reply cut | Candidate §10 and §7 | A code change would be needed | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D12 | Rule limiting changes after the smoke test (technical defects only, defined in §8; fields that must stay identical; change record; proposed repeat rule of at most 2 smoke-test attempts, all excluded, reported and counted toward the cumulative cap) | Candidate §8 | Researcher degrees of freedom remain uncontrolled | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D13 | Authorize recording the scripted baselines (`idle`, `key-sweep`, `seeded-random` 0–4; `keyset.v2`, 10 episodes, 8,000 frames; host-default 20,000 requests and 3,600 s, not the study limits; a `--max-requests` flag is an open engineering item) | Candidate §9 | Landing rates cannot be interpreted against chance | Approve | [x] Amend: 1,000-request matched baselines + separately labeled 20,000-request diagnostics; implement and hash max-requests before execution | Owner, 2026-11-05; implementation/review pending |
| D14 | Standard-library transport (no provider SDK) | `http.client` transport as built | Swap in an SDK class and re-test | Approve | [x] Approve research settings only; no execution authorization | Owner, 2026-11-05 |
| D15 | Owner-only actions: timing of the flag commit, Console billing and spend limits, off-machine backup of raw data | The owner's own actions, in the owner's time | Nothing can start without them | Owner schedules | [ ] Scheduled  [x] Not yet scheduled; no paid or off-machine action authorized | Owner, 2026-11-05 |

## Open sub-decision on D10: the study session cap

To be recorded before the smoke test (candidate §6, §15 step 1).

The study cost is estimated at about $0.25, uncertain by a factor of 2–3, so a $0.50 session cap may cut the study short. The gateway also stops
before any call whose worst-case reservation does not fit. Options:

* [ ] Keep $0.50 for the study session.
* [x] Set the study session cap to the **remaining reconciled cumulative balance** when the study is separately authorized, at most the cumulative cap. **Owner approved as a research setting on 2026-11-05; this is not approval to spend.**
* [ ] Exclude the historical $0.106019 so that $1.00 is fresh.
* [ ] Amend:

Owner / date: Owner, 2026-11-05 (research setting only; execution remains separate).

## Additional owner-approved amendments (2026-11-05)

1. **Credential ACL:** Require fail-closed allowlisting of the owner's Windows SID plus narrowly justified operating-system principals, rather than only rejecting broad-group SIDs. Test a credential file accessible to another specific user SID before touching any real key.
2. **Baseline budgets:** Add and freeze `--max-requests` in the baseline planner and plan hash. Record 1,000-request budget-matched baselines and separately labeled extended 20,000-request diagnostics. Censored 10-episode runs must be plainly marked; do not conflate conditions. No official runs authorized by this decision.

The exact owner consent and conditions are captured in `PROJECT.md` §0.3. This record does not enable live execution, approve billing or constitute pre-registration. The candidate document and implementation need corresponding amendments and independent verification.

## How to record approval

The dated owner response has been recorded in `PROJECT.md` §0.3. The adopted settings are conditional until the two amendments are implemented, code and protocol text are aligned, and a reviewed version is available. Nothing here authorizes any API request, spending, a live-flag change, official baseline execution, study pre-registration or a merge.
