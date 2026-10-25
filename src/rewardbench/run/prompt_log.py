"""Write the exact prompts a model receives, for audit and demonstration."""

from __future__ import annotations

from pathlib import Path

from rewardbench.contracts import ModelClient, ModelRequest, ModelResponse
from rewardbench.prompts import render_messages


class PromptRecorder:
    """``ModelClient`` wrapper that saves each rendered prompt before delegating.

    The text is produced by ``render_messages``, the same function the provider
    adapters use, so the log shows what a real model would be sent. It does not
    change the request or the response.
    """

    def __init__(self, inner: ModelClient, directory: str | Path) -> None:
        self._inner = inner
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._calls = 0

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def propose(self, request: ModelRequest) -> ModelResponse:
        system_text, user_text = render_messages(request)
        name = f"revision_{request.revision_index:02d}_call_{self._calls:02d}.txt"
        self._calls += 1
        (self._directory / name).write_text(
            f"# provider={self.provider} model={self.model_id} "
            f"feedback_condition={request.feedback_condition.value}\n\n"
            f"## SYSTEM\n{system_text}\n\n## USER\n{user_text}\n",
            encoding="utf-8",
        )
        return self._inner.propose(request)
