"""Generate a report from a real RewardBench log.

This example does not create scores. Pass the SQLite database written by the
experiment runner, or a JSONL file produced by ``rewardbench.analysis export``.
"""

from rewardbench.analysis.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
