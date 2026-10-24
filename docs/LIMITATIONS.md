# Limitations

These limits apply to every chart and table this repository produces. They are reasons to withhold a ranking, not footnotes to add after one.

## No result is a default

Logs are preliminary unless `metadata.validation_status` is `independently_validated`. Preliminary curves can be used to debug the pipeline. They are not evidence about which model adapts. An empty log produces an empty report. The software does not fill that gap with a demonstration ranking.

Synthetic rows exist in the test suite so the figure code can be exercised when no researcher has produced a log. Those rows are labeled `SYNTHETIC FIXTURE — NOT EXPERIMENTAL RESULTS`. They must not appear in a paper, a blog, or a LinkedIn post as if they were flights.

## Model fairness

A higher curve is not a fair comparison when the models did not receive the same task.

Check, before comparing models:

- the same environment id
- the same split
- the same feedback condition
- the same number of revisions and episodes per revision
- the same history window
- the same budget limits
- provider settings that were actually held fixed, including temperature and reasoning effort when the provider exposes them

Token counts and dollar cost can still differ because providers tokenize and price differently. The report flags session cost, token count, or episode-count gaps larger than 25%, and any gap in the last revision index. That flag is a warning about exposure. It is not a corrected score.

Model identity should be the configured model id, not a marketing name. A later change of model id is a different experiment.

## Feedback intervention

The current numerical arm includes simulator reward **and** success, crash, step,
fuel, and start-state metrics. No-feedback withholds all those outcomes while
retaining controller/validation history. This measures richer simulator feedback
versus none; it cannot isolate the causal contribution of the reward number from
the accompanying information. A scalar-only study needs a separately reviewed,
pre-registered prompt change before any paid development.

Current development uses the same seed panel at every revision. Older rotating
seed curves remain historical engineering evidence; their initial-to-final
difference is confounded by starting conditions. A two-revision, one-start mock
demo is neither statistical evidence nor an estimate of real model adaptation.

## Judge bias

LunarLander success and crash flags come from the simulator. They are not scores from another language model. Reward is the environment's own return, including penalties as negative reward.

If a later environment uses a model, a human, or a rubric as a judge, that judge is a new source of bias. Judge preference for writing style, verbosity, or a particular provider can look like adaptation. Those scores need a judge-agreement check and a frozen judge configuration before they are treated as outcomes. Do not reuse the LunarLander success plots as if they already solved that problem.

## Seed leakage

Development seeds and held-out seeds are different pools, and the split is part of the experiment id. A development run that executes a held-out seed has seen the evaluation case. The report compares executed development seeds with held-out pools stored in the log.

Leakage also includes reusing a world, a level, or a prompt example from development while scoring held-out. The SQLite check cannot see material that was never stored. The seed lists in the config are the record of what was supposed to be reserved.

Intervals across sessions overstate the evidence when those sessions are resumes of one experiment. The report names experiment ids that have more than one session.

## In-context adaptation is not weight training

The model is asked to revise a controller after seeing earlier attempts and, in the numerical-reward condition, the rewards. The provider is not asked to fine-tune, and this repository does not apply gradients or edit model weights.

That distinction matters for the claim:

- A rise across revisions is consistent with in-context adaptation, memorization of the feedback text, or a change in the sampled controller that is unrelated to the reward.
- It is not evidence of a learned weight update.
- The no-feedback condition is the comparison that asks whether the numerical reward, rather than simply another attempt, is associated with the change.
- A single run cannot separate those stories. The held-out split is what asks whether the revision rule still helps on seeds the development loop did not use.

## Other limits

- Provider cost is the provider's estimate, stored on the attempt. It is not an invoice.
- Invalid controllers are excluded from the flight, so their absence can make a later revision look cleaner without a better landing policy.
- Confidence intervals describe sampling variation across the observed sessions. They do not correct for multiple targets, multiple models, or a target chosen after seeing the curve.
- Overlapping intervals are not a hypothesis test, and this package does not emit one.
- Charts are suitable for a later research report only together with the log hash, the config, the validation status, and this page.
