# Paper and blog outline

This outline is a structure. It is not a draft of findings. Leave every results subsection empty until an independently validated log exists. Do not paste preliminary curves or test fixtures into these sections.

Working title: In-context adaptation to numerical rewards on a controlled flight task.

Research question: Which language model adapts most effectively to numerical rewards and penalties under controlled experimental conditions?

## Paper

1. Abstract
   - State the question, the environment, the two feedback conditions, and the held-out split.
   - Do not name a leading model until the validated analysis exists.
2. Introduction
   - Why numerical reward is a different signal from a rewritten instruction.
   - Why the comparison is in-context rather than fine-tuning.
3. Related work
   - In-context learning, reflexion-style retries, and reward-conditioned prompting.
   - Separate that literature from weight-updating reinforcement learning.
4. Methods
   - Environment: LunarLander-v3, with the controller schema and the rejection rule for invalid controllers.
   - Models: provider and model id from the config, not a nickname.
   - Conditions: `numerical_reward` and `no_feedback`.
   - Splits: development seeds for pipeline checks, held-out seeds for the reported estimate.
   - Budgets: revisions, episodes, tokens, cost, and wall time.
   - Pre-specified estimands, matching `docs/ANALYSIS.md`:
     - reward by controller revision
     - landing success by episode attempt
     - initial versus final session reward
     - improvement per dollar
     - time to pre-specified reward targets
     - invalid-controller rate and crash rate
   - Session-level Student-t intervals, and Wilson intervals for the share of sessions that reach a target.
   - The rule that resumes of one experiment id are not extra replicates.
5. Results
   - Insert only the independently validated section of `report.md`, plus the log SHA-256.
   - Keep development and held-out tables apart.
   - If the validated section says that no such log is present, this section stays empty.
6. Discussion
   - What a difference between feedback conditions would mean, and what it would not mean.
   - Fairness of provider settings, cost, and token exposure.
7. Limitations
   - Use `docs/LIMITATIONS.md`: fairness, judge bias, seed leakage, and in-context versus weight training.
8. Reproducibility
   - Config files, contract version, schema version, package versions from the report header, and the command that regenerated the figures.

## Blog and LinkedIn post

Write this only after the paper's results section has a validated log.

1. The question, in one sentence.
2. The setup: same task, two feedback conditions, held-out seeds, no weight update.
3. One learning-curve figure, with the log hash and a caption that names the metric and the interval.
4. A short reading guide: compare reward versus no feedback for a model before comparing models.
5. The limitation that cost, tokens, and provider settings can make the comparison unfair.
6. A closing line that points at the repository and the report, without a ranking adjective.

Do not post the synthetic test charts. Do not crop a preliminary chart into a claim about GPT, Gemini, Claude, or Grok.

## Caption checklist

- Metric and unit are in the axis title.
- The sample is sessions, and the interval method is named.
- The validation status is in the caption.
- Model order is described as alphabetical.
- The target reward, if shown, is described as pre-specified.
