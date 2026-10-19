#!/usr/bin/env bash
# One authorized V5 PPO pilot. Creates log/output dirs BEFORE tee; preserves exit status.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$ROOT/../.." && pwd)"
RUN="ppo_pilot_v5_commitment"
OUT="$ROOT/outputs/$RUN"
LOGS="$ROOT/logs/$RUN"
MODELS="$ROOT/models/$RUN"

mkdir -p "$OUT" "$LOGS" "$MODELS" "$OUT/monitor" "$MODELS/checkpoints"

PYTHON="${REPO}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

echo "V5 train start $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee "$OUT/train.log"
echo "python=$PYTHON" | tee -a "$OUT/train.log"

set +e
"$PYTHON" "$ROOT/scripts/train_ppo.py" \
  --run-name "$RUN" \
  --start-template sh_contact \
  --reward-mode progress_a_prime_v5 \
  --potential-scale 10.0 \
  --time-cost 0.005 \
  --commitment-shaping \
  --timeout-as-terminated \
  --seed 0 \
  --action-repeat 4 \
  --episode-max-frames 2000 \
  --max-physics-frames 200000 \
  --auto-seed-base 100000 \
  --port 18800 \
  2>&1 | tee -a "$OUT/train.log"
status=${PIPESTATUS[0]}
set -e

echo "V5 train exit_status=$status $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$OUT/train.log"
exit "$status"
