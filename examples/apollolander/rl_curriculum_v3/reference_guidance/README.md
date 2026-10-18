# Reference guidance — PARITY / EVAL ONLY

This directory holds scripts that drive Seb Lee-Delisle ApolloLander with the
hand-tuned `demonstration_guidance_controller` **solely** to:

1. Generate action traces whose episodes end in verified native terminals
   (perfect landing, hard landing, crash, timeout) for browser↔Node parity.
2. Appear as a separately labeled reference baseline in final evaluation.

## Hard separation rules

- **Never** use guidance parameters, traces, or rollouts to initialize, train,
  shape, distill, or otherwise guide the neural network.
- Traces written here are sealed inputs to `parity_check_v2.py` only.
- Training code under `../train_curriculum.py` must not import this package’s
  generators (importing `guidance_action` for a labeled eval baseline is OK in
  `evaluate_final.py` only, with an explicit REFERENCE_ONLY label).
