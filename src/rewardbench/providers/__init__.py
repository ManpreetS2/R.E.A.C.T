"""Model adapters for in-context reward adaptation.

Live providers read API keys from the environment:

- OpenAI: ``OPENAI_API_KEY``
- Gemini: ``GEMINI_API_KEY`` or ``GOOGLE_API_KEY``
- Anthropic: ``ANTHROPIC_API_KEY``
- xAI: ``XAI_API_KEY``

Do not put keys in source or in a committed ``.env``. ``build_model_client``
does not call the network; ``propose`` does. Use ``provider="mock"`` for
offline experiments. Prices live in ``providers/data/pricing_2026-10-14.json``
and can be replaced with ``pricing_catalog``.

Controller text comes from ``EnvironmentSpec``. This package does not validate
environment-specific controller fields. The spending lock is in-process only.
"""

from rewardbench.providers.capabilities import PROVIDER_DIFFERENCES
from rewardbench.providers.client import RewardModelClient, build_model_client
from rewardbench.providers.preflight import FirstCallPreflight, preflight_first_call, require_preflight_ok

__all__ = [
    "PROVIDER_DIFFERENCES",
    "FirstCallPreflight",
    "RewardModelClient",
    "build_model_client",
    "preflight_first_call",
    "require_preflight_ok",
]
