**CANDIDATE — NOT OWNER APPROVED — NOT PRE-REGISTERED**

# Blind-play P1 v1 — owner decision record

**ALL DECISIONS BELOW ARE UNDECIDED.** This file approves nothing. Approval is valid only when the owner records it as a dated entry in
`PROJECT.md`. Source: `docs/BLIND_PLAY_PROTOCOL_V1_CANDIDATE.md` (candidate, not approved, not pre-registered). The recommendations are the
research team's proposals, not decisions.

| ID | Decision | Proposed value | What rejecting changes | Recommendation | Owner mark | Owner / date |
| --- | --- | --- | --- | --- | --- | --- |
| D1 | Adopt the candidate as protocol P1 v1 (the draft stays unchanged as history) | The candidate document | Milestone 2 stays blocked until another protocol is adopted | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D2 | Key set `keyset.v2` (11 keys, no `KeyS`) | `keyset.v2` | Needs a code change to offer `S`; frame budgets no longer measure game time uniformly | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D3 | Thinking mode | `disabled` | Build option B, C or D (C drops the last-4-images policy and raises cost); re-test | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D4 | Effort, same for smoke test and study | `low` | Higher cost and a new configuration hash; splitting the value weakens the smoke test | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D5 | Provider and model | Anthropic `claude-haiku-5-5` | Transport supports Anthropic only; other models are untested and costlier | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D6 | Platform | Windows on this PC (build 26300) | macOS has a different start frame; verification would have to be redone on the Mac | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D7 | Excluded technical smoke test, with the order of work changed for it alone | Smoke test before pre-registration, excluded from the study | Either no smoke test (a technical defect could waste the study) or a pre-registered session (baselines and pre-registration first; it counts) | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D8 | Smoke test scope | 1 episode, at most 30 model calls | Different cost and coverage | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D9 | Study scope | 1 session, 10 episodes, 150 calls, 8,000 frames per episode | More sessions would not fit $1.00 | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D10 | Spend caps (**record before the smoke test**) | $0.50 per session; $1.00 cumulative including the $0.106019 already spent on OpenAI ($0.893981 remains) | Excluding historical spend would make the $1.00 fresh; other caps change what can run | Approve with the sub-decision below; both must be recorded in PROJECT.md before the smoke test, because a cap set after seeing the smoke cost is a budget change after the smoke test | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D11 | Merged stopping rules and the disclosure of the 20,000-character reply cut | Candidate §10 and §7 | A code change would be needed | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D12 | Rule limiting changes after the smoke test (technical defects only, defined in §8; fields that must stay identical; change record; proposed repeat rule of at most 2 smoke-test attempts, all excluded, reported and counted toward the cumulative cap) | Candidate §8 | Researcher degrees of freedom remain uncontrolled | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D13 | Authorize recording the scripted baselines (`idle`, `key-sweep`, `seeded-random` 0–4; `keyset.v2`, 10 episodes, 8,000 frames; host-default 20,000 requests and 3,600 s, not the study limits; a `--max-requests` flag is an open engineering item) | Candidate §9 | Landing rates cannot be interpreted against chance | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D14 | Standard-library transport (no provider SDK) | `http.client` transport as built | Swap in an SDK class and re-test | Approve | [ ] Approve  [ ] Reject  [ ] Amend: | |
| D15 | Owner-only actions: timing of the flag commit, Console billing and spend limits, off-machine backup of raw data | The owner's own actions, in the owner's time | Nothing can start without them | Owner schedules | [ ] Scheduled  [ ] Not yet scheduled | |

## Open sub-decision on D10: the study session cap

To be recorded before the smoke test (candidate §6, §15 step 1).

The study cost is estimated at about $0.25, uncertain by a factor of 2–3, so a $0.50 session cap may cut the study short. The gateway also stops
before any call whose worst-case reservation does not fit. Options:

* [ ] Keep $0.50 for the study session.
* [ ] Set the study session cap to the remaining cumulative balance (recommended), which must be at most the cumulative cap.
* [ ] Exclude the historical $0.106019 so that $1.00 is fresh.
* [ ] Amend:

Owner / date:

## How to record approval

Copy the decisions you accept into `PROJECT.md` as a dated entry in your own words, naming the IDs. Until then the protocol remains a candidate and no
authorization file, flag change or model session is permitted.
