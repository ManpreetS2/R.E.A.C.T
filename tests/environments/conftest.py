"""Make the environment packages importable and load contract 1.0.0 when present."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CONTRACT_ROOT = Path("/tmp/rewardbench-contract-1.0.0")


def _ensure_published_contract() -> None:
    """Expose Agent 1's contract without copying it into this branch."""
    destination = CONTRACT_ROOT / "rewardbench" / "contracts.py"
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shown = subprocess.run(
            ["git", "show", "agent/core:src/rewardbench/contracts.py"],
            cwd=Path(__file__).resolve().parents[2],
            check=False,
            capture_output=True,
        )
        if shown.returncode != 0:
            return
        destination.write_bytes(shown.stdout)
    if str(CONTRACT_ROOT) not in sys.path:
        sys.path.append(str(CONTRACT_ROOT))
    package = sys.modules.get("rewardbench")
    extra = str(CONTRACT_ROOT / "rewardbench")
    if package is not None and hasattr(package, "__path__") and extra not in package.__path__:
        package.__path__.append(extra)


_ensure_published_contract()
