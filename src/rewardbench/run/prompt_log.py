"""Record the exact prompts a model receives and report each call as it happens."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from rewardbench.contracts import ModelClient, ModelRequest, ModelResponse
from rewardbench.prompts import render_messages


class PromptRecorder:
    """``ModelClient`` wrapper that saves each rendered prompt before delegating.

    The text is produced by ``render_messages``, the same function the provider
    adapters use, so the log shows what a real model would be sent. It does not
    change the request or the response.
    """

    def __init__(
        self,
        inner: ModelClient,
        directory: str | Path | None,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self._inner = inner
        self._directory = Path(directory) if directory is not None else None
        if self._directory is not None:
            self._directory.mkdir(parents=True, exist_ok=True)
        self._progress = progress
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
        revision = request.revision_index
        if self._directory is not None:
            system_text, user_text = render_messages(request)
            name = f"revision_{revision:02d}_call_{self._calls:02d}.txt"
            (self._directory / name).write_text(
                f"# provider={self.provider} model={self.model_id} "
                f"feedback_condition={request.feedback_condition.value}\n\n"
                f"## SYSTEM\n{system_text}\n\n## USER\n{user_text}\n",
                encoding="utf-8",
            )
        self._calls += 1
        self._say(f"revision {revision}: prompt built, calling {self.provider}/{self.model_id}")
        response = self._inner.propose(request)
        controller = json.dumps(dict(response.parameters), sort_keys=True, separators=(",", ":"))
        self._say(
            f"revision {revision}: controller {controller} "
            f"(tokens={response.total_tokens}, cost_usd={response.estimated_cost_usd})"
        )
        return response

    def _say(self, message: str) -> None:
        if self._progress is not None:
            self._progress(message)
