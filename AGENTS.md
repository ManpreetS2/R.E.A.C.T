# Repository agent instructions

**Consult [PROJECT.md](PROJECT.md) first.** It is the canonical R.E.A.C.T. research plan. Read its **§0 current-direction/status/decision summary** and only the relevant long-form sections for the task; the full 100 KB historical migration need not be loaded into every coding session.

- **Primary owner-approved goal:** blind visual ApolloLander game learning from screenshots and bounded keyboard actions, without privileged simulator state or a prewritten flight controller. See `PROJECT.md` §0 and its migrated Section 20.
- **Separate historical research:** structured guidance-controller tuning and reward feedback experiments, including Missions 006–010. Do not claim these prove blind gameplay or reward-driven learning.
- Before any mission, identify the research track and whether the owner has approved a change of objective.
- Read the relevant experiment protocol, existing PR stack and `docs/PROJECT_HANDOFF.md` before changing code.
- Do not run paid APIs, change ceilings, evaluate reserved held-out seeds, publish raw/private data, delete historical evidence, or merge PRs without explicit approval for that action.
- Use reviewable changes and keep `PROJECT.md` current when a mission changes project scope, milestone status, or research decisions.
- Treat budgets and future designs quoted in migrated historical sections as planning history, not current approvals.
