"""Shared experiment prompts. Every provider receives this wording.

The numerical reward printed here is copied from ``RewardFeedback``. This
module does not score flights and does not ask the model to judge itself.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from rewardbench.contracts import (
    FeedbackCondition,
    ModelRequest,
    PriorAttempt,
    RewardFeedback,
)

PROMPT_TEMPLATE_ID = "rewardbench.prompts.v2"

SYSTEM_PROMPT = """You are proposing a controller for a closed reward-adaptation experiment.
Revise only the controller. Do not update, train, or fine-tune neural network weights.
When a numeric reward is shown, it is the environment's own score. A negative number is a penalty from that environment.
Do not invent a score and do not treat your own judgment as the reward.
Do not write Python, shell commands, imports, or tool calls.
Do not call tools, browsers, or code interpreters.
Reply with one compact JSON object and no surrounding prose, markdown fences, or commentary.
The object must match the controller schema in the user message."""

_NO_FEEDBACK_HEADER = (
    "Earlier revisions are listed without simulator scores. Scores were withheld on purpose."
)
_NUMERICAL_HEADER = (
    "Earlier revisions include the simulator's numeric reward for each scored episode. "
    "Use those rewards. Do not replace them with your own assessment."
)
_OUTPUT_RULE = (
    "Reply with one compact JSON object that matches the controller schema. "
    "Include only schema fields. Do not include a score of your own. "
    "Prefer the smallest valid controller that satisfies the schema."
)


def render_messages(request: ModelRequest) -> tuple[str, str]:
    """Return ``(system_text, user_text)`` for any provider."""

    environment = request.environment
    sections = [
        f"Task: {environment.display_name}. {environment.task_description}",
        f"Actions: {environment.action_space_summary}",
        f"Observations: {environment.observation_space_summary}",
        "Controller schema:\n" + _json(environment.controller_schema),
        f"Revision: {request.revision_index}",
        _history_section(request),
        _OUTPUT_RULE,
    ]
    return SYSTEM_PROMPT, "\n\n".join(sections)


def render_history(request: ModelRequest) -> str:
    """History text only. No-feedback mode never prints rewards."""

    return _history_section(request)


def _history_section(request: ModelRequest) -> str:
    if request.feedback_condition is FeedbackCondition.NO_FEEDBACK:
        header = _NO_FEEDBACK_HEADER
        show_rewards = False
    elif request.feedback_condition is FeedbackCondition.NUMERICAL_REWARD:
        header = _NUMERICAL_HEADER
        show_rewards = True
    else:
        raise ValueError(f"unsupported feedback condition {request.feedback_condition!r}")
    if not request.history:
        return header + "\nThis is the first revision. No earlier controller is available."
    lines = [header]
    for attempt in request.history:
        lines.append(_attempt_line(attempt, show_rewards=show_rewards))
    return "\n".join(lines)


def _attempt_line(attempt: PriorAttempt, *, show_rewards: bool) -> str:
    status = "valid" if attempt.valid else "invalid"
    error = ""
    if attempt.validation_error:
        error = f" validation_error={json.dumps(attempt.validation_error)}"
    line = (
        f"- revision {attempt.revision_index}: {status} controller "
        f"{_json(attempt.parameters)}{error}"
    )
    if not show_rewards or not attempt.feedback:
        return line
    episodes = sorted(attempt.feedback, key=lambda item: item.episode_index)
    details = "\n".join(
        "  " + _feedback_line(item) for item in episodes
    )
    return f"{line}\n{details}"


def _feedback_line(item: RewardFeedback) -> str:
    parts = [
        f"episode {item.episode_index}",
        f"reward={_number(item.total_reward)}",
        f"success={str(item.success).lower()}",
        f"steps={item.steps}",
    ]
    if item.crashed is not None:
        parts.append(f"crashed={str(item.crashed).lower()}")
    if item.metrics:
        parts.append("metrics=" + _json(item.metrics))
    return " ".join(parts)


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"))


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(nested) for nested in value]
    return value


def _number(value: float) -> str:
    return json.dumps(value)
