# Windows desktop GPU handoff (RTX 4080 Super, 64GB RAM)

Local PyTorch CUDA; **no paid APIs**. This overnight branch trained on CPU with the
original ApolloLander JS physics. JS physics does **not** accelerate on GPU —
only the PPO update / network forward passes benefit from CUDA.

## Clone and install

```powershell
git clone https://github.com/ManpreetS2/R.E.A.C.T.git
cd R.E.A.C.T
git checkout cursor/apollolander-rl-overnight-v2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[rl,environments,analysis,dev]"
# CUDA torch (example cu124 — pick the index matching your driver):
pip install torch --index-url https://download.pytorch.org/whl/cu124
# Node.js LTS required for upstream_engine_host.js
node -v
```

## Verify CUDA

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)"
```

Expect `True` and `NVIDIA GeForce RTX 4080 Super` (or similar).

## Resume vs restart

```powershell
# Resume an overnight run (keeps optimizer + global_step):
$env:PYTHONPATH="src"
python examples/apollolander/rl_overnight/train.py `
  --config examples/apollolander/rl_overnight/configs/C_step_cost.yaml `
  --output examples/apollolander/rl_overnight/results/C_step_cost_s6 `
  --resume examples/apollolander/rl_overnight/results/C_step_cost_s6/checkpoints/final.pt `
  --total-env-steps 10000000

# Fresh random-init run (new run_name / output dir — never present as continuous):
python examples/apollolander/rl_overnight/train.py `
  --config examples/apollolander/rl_overnight/configs/C_step_cost.yaml `
  --run-name C_step_cost_gpu_s10 `
  --output examples/apollolander/rl_overnight/results/C_step_cost_gpu_s10
```

Set `device: cuda` in the YAML `ppo:` block (or edit after load) for GPU updates.

## GPU vs CPU benchmark

```powershell
python examples/apollolander/rl_overnight/benchmark_throughput.py
# Then compare PPO-only step: time a few update() calls with device=cpu vs cuda
# while holding n_envs fixed. Expect:
#   - env / JS physics frames/s: similar on CPU vs GPU host (JS is single-thread Node)
#   - PPO update/s: substantially faster on 4080 Super
```

Measure wall time to 1M physics frames with `n_envs` sized to CPU cores for env
workers and leave GPU for the learner.

## Eval and videos

```powershell
python examples/apollolander/rl_overnight/evaluate.py `
  --run-dir examples/apollolander/rl_overnight/results/C_step_cost_s6 `
  --checkpoints final --suite held_out_test

# Original-renderer videos (Playwright Chromium + upstream draw calls):
pip install playwright
playwright install chromium
python examples/apollolander/rl_overnight/record_videos.py `
  --checkpoint examples/apollolander/rl_overnight/results/C_step_cost_s6/checkpoints/final.pt `
  --seed 1000100 --out artifacts/final_seed1000100.mp4
```

## Proposed next step: screenshot / pixel RL

Keep the same upstream reward/verifier and native landing classification. Add a
downscaled pixel stack (e.g. 84×84×4) from the browser bridge `renderFrame`,
CNN+PPO (or Impala) on the 4080 Super. Cost estimate: overnight CPU days, or
~2–12 h on a single consumer GPU. Prefer proving a **state** policy can land
before investing heavily in pixels — this overnight CPU run did not yet.
