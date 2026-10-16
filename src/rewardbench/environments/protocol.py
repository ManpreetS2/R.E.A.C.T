"""Bridge from environment adapters to contract version 1.0.0.

The type definitions stay in ``rewardbench.contracts``. This module only
imports them. Physics and controller checks stay in the environment packages.
"""

from __future__ import annotations

from typing import Any


def load_contracts() -> Any:
    """Import the shared contract. The core package owns the definitions."""
    try:
        import rewardbench.contracts as contracts
    except ImportError as exc:
        raise ImportError(
            "rewardbench.contracts 1.0.0 is required for the experiment runner. "
            "It is published on the core branch and is not redefined here."
        ) from exc
    version = getattr(contracts, "CONTRACT_VERSION", None)
    if version != "1.0.0":
        raise ImportError(f"expected rewardbench contract 1.0.0, found {version!r}")
    return contracts


def adapter_error(message: str) -> Exception:
    return load_contracts().EnvironmentAdapterError(message)
