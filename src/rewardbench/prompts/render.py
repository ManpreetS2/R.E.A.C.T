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

PROMPT_TEMPLATE_ID = "rewardbench.prompts.v4"

SYSTEM_PROMPT = """You are proposing a controller for a closed reward-adaptation experiment.
Revise only the controller. Do not update, train, or fine-tune neural network weights.
When a numeric reward is shown, it is the environment's own score. A negative number is a penalty from that environment.
Do not invent a score and do not treat your own judgment as the reward.
Do not write Python, shell commands, imports, or tool calls.
Do not call tools, browsers, or code interpreters.
Reply with one compact JSON object and no surrounding prose, markdown fences, or commentary.
The object must be a controller instance of the schema in the user message: concrete values for its fields, never the schema itself."""

_NO_FEEDBACK_HEADER = (
    "Earlier revisions are listed without simulator scores. Scores were withheld on purpose."
)
_NUMERICAL_HEADER = (
    "Earlier revisions include the simulator's numeric reward for each scored episode. "
    "Use those rewards. Do not replace them with your own assessment."
)
_REWARD_ONLY_HEADER = (
    "Earlier revisions include only the simulator's numeric reward for each scored episode. "
    "Use those rewards. Do not replace them with your own assessment."
)
_INSTANCE_KEY = "instance"
_OUTPUT_RULE = (
    "Reply with one compact JSON object that is a controller instance of the schema, not the schema itself. "
    "Include only schema fields and give every required field a concrete value you chose. "
    "Missing or out-of-range values are rejected, not filled in. Do not include a score of your own."
)


def render_messages(request: ModelRequest) -> tuple[str, str]:
    """Return ``(system_text, user_text)`` for any provider."""

    environment = request.environment
    sections = [
        f"Task: {environment.display_name}. {environment.task_description}",
        f"Actions: {environment.action_space_summary}",
        f"Observations: {environment.observation_space_summary}",
        _briefing_section(environment.controller_schema),
        "Controller schema:\n" + _json(_schema_only(environment.controller_schema)),
        _instance_section(environment.controller_schema),
        f"Revision: {request.revision_index}",
        _history_section(request),
        _OUTPUT_RULE,
    ]
    return SYSTEM_PROMPT, "\n\n".join(section for section in sections if section)


def _schema_only(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    return {key: value for key, value in schema.items() if key != _INSTANCE_KEY}


def _briefing_section(schema: Mapping[str, Any]) -> str:
    """Objective and flight mechanics. Identical in every feedback condition; carries no scores."""

    guide = schema.get(_INSTANCE_KEY)
    if not isinstance(guide, Mapping):
        return ""
    lines = []
    if isinstance(guide.get("objective"), str):
        lines.append("Objective: " + guide["objective"])
    mechanics = guide.get("mechanics") or ()
    if mechanics:
        lines.append("Flight mechanics:")
        lines += [f"- {line}" for line in mechanics]
    return "\n".join(lines)


def _instance_section(schema: Mapping[str, Any]) -> str:
    """Tell the model the schema is not the answer. Environment-specific detail comes from ``instance``."""

    lines = [
        "Controller format: the JSON above is the SCHEMA. It describes what is allowed and is not a controller. "
        "Do not reply with the schema, its policies, ranges, or notes."
    ]
    guide = schema.get(_INSTANCE_KEY)
    if isinstance(guide, Mapping):
        required = guide.get("required_fields") or ()
        if required:
            text = (
                "Reply with a controller INSTANCE: one JSON object of concrete values with the top-level fields "
                + ", ".join(f'"{name}"' for name in required)
                + " plus the fields of your chosen policy"
            )
            if isinstance(schema.get("schema"), str):
                text += f'; "schema" must be exactly "{schema["schema"]}"'
            lines.append(text + ".")
        policies = guide.get("policy_fields")
        if isinstance(policies, Mapping) and policies:
            lines.append('"policy" must be one of: ' + ", ".join(f'"{name}"' for name in policies) + ".")
            lines += [f'- "{name}": {description}' for name, description in policies.items()]
        lines += list(guide.get("guidance_law") or ())
        parameters = guide.get("parameter_guide")
        if isinstance(parameters, Mapping) and parameters:
            lines.append("What each guidance parameter changes (bounds are in the schema):")
            lines += [f"- {name}: {effect}" for name, effect in parameters.items()]
        if isinstance(guide.get("shape"), str):
            lines.append(
                "Shape of the reply. Replace every <number> with a concrete value you choose within its bounds; "
                "the shape itself is not a valid controller:"
            )
            lines.append(guide["shape"])
    return "\n".join(lines)


def render_history(request: ModelRequest) -> str:
    """History text only. No-feedback mode never prints rewards."""

    return _history_section(request)


def _history_section(request: ModelRequest) -> str:
    reward_only = False
    if request.feedback_condition is FeedbackCondition.NO_FEEDBACK:
        header = _NO_FEEDBACK_HEADER
        show_rewards = False
    elif request.feedback_condition is FeedbackCondition.NUMERICAL_REWARD:
        header = _NUMERICAL_HEADER
        show_rewards = True
    elif request.feedback_condition is FeedbackCondition.REWARD_ONLY:
        header = _REWARD_ONLY_HEADER
        show_rewards = True
        reward_only = True
    else:
        raise ValueError(f"unsupported feedback condition {request.feedback_condition!r}")
    if not request.history:
        return header + "\nThis is the first revision. No earlier controller is available."
    lines = [header]
    for attempt in request.history:
        lines.append(_attempt_line(attempt, show_rewards=show_rewards, reward_only=reward_only))
    return "\n".join(lines)


def _attempt_line(attempt: PriorAttempt, *, show_rewards: bool, reward_only: bool = False) -> str:
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
        "  " + _feedback_line(item, reward_only=reward_only) for item in episodes
    )
    return f"{line}\n{details}"


def _feedback_line(item: RewardFeedback, *, reward_only: bool = False) -> str:
    parts = [f"episode {item.episode_index}", f"reward={_number(item.total_reward)}"]
    if reward_only:
        return " ".join(parts)
    parts += [f"success={str(item.success).lower()}", f"steps={item.steps}"]
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
