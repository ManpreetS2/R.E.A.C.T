"""Launch a configured experiment through :class:`ExperimentRunner`.

Offline mock mode uses a scripted feedback-responsive model. That path tests
the experiment machinery against real simulator physics. It is not evidence of
language-model learning. Live mode requires explicit paid-call acknowledgment
and builds clients only through ``rewardbench.providers.build_model_client``.
"""

from rewardbench.run.cli import main
from rewardbench.run.factory import build_environment, build_model, prepare_config
from rewardbench.run.live import SessionPaidCallGate, preflight_live
from rewardbench.run.mock_model import ScriptedFeedbackModel

__all__ = [
    "ScriptedFeedbackModel",
    "SessionPaidCallGate",
    "build_environment",
    "build_model",
    "main",
    "preflight_live",
    "prepare_config",
]
