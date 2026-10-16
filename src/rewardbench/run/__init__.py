"""Launch a configured experiment through :class:`ExperimentRunner`.

Offline mock mode uses a scripted feedback-responsive model. That path tests
the experiment machinery against real simulator physics. It is not evidence of
language-model learning.
"""

from rewardbench.run.cli import main
from rewardbench.run.factory import build_environment, build_model, prepare_config
from rewardbench.run.mock_model import ScriptedFeedbackModel

__all__ = [
    "ScriptedFeedbackModel",
    "build_environment",
    "build_model",
    "main",
    "prepare_config",
]
