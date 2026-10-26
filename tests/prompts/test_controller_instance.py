"""The ApolloLander prompt must ask for a controller INSTANCE, not echo the schema (Mission 006 failure)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from rewardbench import study
from rewardbench.config import load_config
from rewardbench.contracts import (
    ConfigError,
    EnvironmentSpec,
    FeedbackCondition,
    ModelRequest,
    PriorAttempt,
    RewardFeedback,
    Split,
)
from rewardbench.core.ids import experiment_id
from rewardbench.environments.apollolander.schema import (
    EXAMPLE_CONTROLLER,
    POLICIES,
    SCHEMA_ID,
    ControllerRejected,
    controller_schema_document,
    demonstration_guidance_controller,
    normalize_controller,
    validate_controller,
)
from rewardbench.prompts import PROMPT_TEMPLATE_ID, SYSTEM_PROMPT, render_messages
from rewardbench.run.factory import build_environment, prepare_config
from rewardbench.run.live import preflight_live

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "configs" / "study" / "archive" / "prompt_v2"
MISSION_006_EXPERIMENT_ID = "exp_26eb2593d31e4a72c041"  # prompt rewardbench.prompts.v2, failed: schema echoed back
CONDITIONS = tuple(FeedbackCondition)
_HISTORY_FEEDBACK = (
    RewardFeedback(
        revision_index=0, episode_index=0, total_reward=-41.5, success=False, crashed=True,
        steps=123, metrics={"fuel_used": 12.5},
    ),
)


def _request(condition: FeedbackCondition, *, history: bool = False) -> ModelRequest:
    attempts = ()
    if history:
        attempts = (PriorAttempt(
            revision_index=0, parameters=dict(EXAMPLE_CONTROLLER), valid=True, validation_error=None,
            feedback=None if condition is FeedbackCondition.NO_FEEDBACK else _HISTORY_FEEDBACK,
        ),)
    return ModelRequest(
        contract_version="1.0.0", experiment_id="exp_test", session_id="ses_test", revision_index=len(attempts),
        feedback_condition=condition, split=Split.DEVELOPMENT,
        environment=EnvironmentSpec(
            environment_id="apollolander", display_name="ApolloLander", task_description="Land on the pad.",
            controller_schema=controller_schema_document(), action_space_summary="thrust, rotation",
            observation_space_summary="position, velocity, fuel",
        ),
        history=attempts, model_settings={},
    )


def _format_block(user_text: str) -> str:
    """Everything the controller format is made of: schema, instance guide, and the closing output rule."""
    start = user_text.index("Controller schema:")
    end = user_text.index("Revision:")
    return user_text[start:end] + user_text[user_text.index("Reply with one compact JSON object"):]


def test_example_controller_passes_the_real_validator() -> None:
    assert validate_controller(EXAMPLE_CONTROLLER).valid
    assert normalize_controller(json.dumps(EXAMPLE_CONTROLLER))["policy"] == "constant"
    assert controller_schema_document()["instance"]["example"] == EXAMPLE_CONTROLLER


def test_example_is_not_the_tuned_demonstration_policy() -> None:
    assert EXAMPLE_CONTROLLER["policy"] != "guidance"
    assert EXAMPLE_CONTROLLER != demonstration_guidance_controller()
    assert "not a recommended, tuned, or good controller" in controller_schema_document()["instance"]["example_note"]


@pytest.mark.parametrize("condition", CONDITIONS)
def test_prompt_distinguishes_schema_from_instance_and_shows_the_example(condition: FeedbackCondition) -> None:
    system_text, user_text = render_messages(_request(condition))
    compact_example = json.dumps(EXAMPLE_CONTROLLER, sort_keys=True, separators=(",", ":"))
    assert compact_example in user_text
    assert "is the SCHEMA" in user_text and "is not a controller" in user_text
    assert "controller instance" in system_text and "never the schema itself" in system_text
    assert f'"schema" must be exactly "{SCHEMA_ID}"' in user_text
    for field in ('"schema"', '"policy"', '"parameters"', '"thrust"', '"rotation"', '"seed"'):
        assert field in user_text
    for policy in POLICIES:
        assert f'"{policy}"' in user_text
    # The example lives in its own section; it is not printed a second time inside the schema JSON.
    schema_json = user_text[user_text.index("Controller schema:"):user_text.index("Controller format:")]
    assert '"instance"' not in schema_json and compact_example not in schema_json


def test_all_three_arms_share_identical_controller_format_instructions() -> None:
    blocks = {c: _format_block(render_messages(_request(c))[1]) for c in CONDITIONS}
    systems = {render_messages(_request(c))[0] for c in CONDITIONS}
    assert len(set(blocks.values())) == 1
    assert systems == {SYSTEM_PROMPT}
    # Same with history present: only the history section may differ.
    with_history = {c: _format_block(render_messages(_request(c, history=True))[1]) for c in CONDITIONS}
    assert len(set(with_history.values())) == 1 and set(with_history.values()) == set(blocks.values())


def test_feedback_isolation_is_unchanged() -> None:
    none_text = render_messages(_request(FeedbackCondition.NO_FEEDBACK, history=True))[1]
    only_text = render_messages(_request(FeedbackCondition.REWARD_ONLY, history=True))[1]
    full_text = render_messages(_request(FeedbackCondition.NUMERICAL_REWARD, history=True))[1]
    assert not any(token in none_text for token in ("reward=", "-41.5", "success=", "steps=", "metrics="))
    assert "reward=-41.5" in only_text
    assert not any(token in only_text for token in ("success=", "steps=", "metrics=", "crashed=", "fuel_used"))
    assert "reward=-41.5" in full_text and "success=false" in full_text and "steps=123" in full_text
    # The controller-format instructions carry no reward values in any condition.
    assert "reward=" not in _format_block(full_text) and "-41.5" not in _format_block(full_text)


def test_missing_policy_error_lists_allowed_policies() -> None:
    status = validate_controller({"schema": SCHEMA_ID, "parameters": {}})
    assert not status.valid
    assert "missing the required 'policy' field" in status.reason
    assert "allowed policies: guidance, constant, random" in status.reason


def test_unknown_policy_error_lists_allowed_policies() -> None:
    status = validate_controller({"schema": SCHEMA_ID, "policy": "pid"})
    assert "unknown controller policy 'pid'" in status.reason
    assert "allowed policies: guidance, constant, random" in status.reason


def test_echoing_the_schema_document_is_rejected_with_a_helpful_message() -> None:
    echoed = {key: value for key, value in controller_schema_document().items() if key != "note"}
    with pytest.raises(ControllerRejected) as caught:
        normalize_controller(echoed)
    assert "schema document, not a controller instance" in caught.value.reason
    assert "allowed policies: guidance, constant, random" in caught.value.reason


# ---------------------------------------------------------------- experiment identity


def test_prompt_template_is_a_new_version_recorded_in_every_study_config() -> None:
    assert PROMPT_TEMPLATE_ID == "rewardbench.prompts.v3"
    for condition in study.CONDITIONS:
        config = study.build_study_config("pilot", condition)
        assert config["metadata"]["prompt_template"] == PROMPT_TEMPLATE_ID
        assert study.PROMPT_TAG in config["experiment_name"]
        assert f"pilot-{study.PROMPT_TAG}" in config["database_path"]


def test_new_experiment_identity_differs_from_the_failed_original() -> None:
    old = {c: load_config(ARCHIVE / f"pilot_{c}.yaml") for c in study.CONDITIONS}
    new = {c: load_config(study.config_path("pilot", c)) for c in study.CONDITIONS}
    # The archived v2 configs still hash to the Mission 006 experiment, so its database stays attributable.
    assert experiment_id(old["no_feedback"]) == MISSION_006_EXPERIMENT_ID
    assert old["no_feedback"].metadata.get("prompt_template") is None
    for condition in study.CONDITIONS:
        assert experiment_id(new[condition]) != experiment_id(old[condition])
        assert new[condition].database_path != old[condition].database_path
        assert new[condition].experiment_name != old[condition].experiment_name
    assert len({experiment_id(c) for c in new.values()}) == 3


def test_prompt_template_changes_the_config_hash() -> None:
    config = study.build_study_config("pilot", "no_feedback")
    other = json.loads(json.dumps(config))
    other["metadata"]["prompt_template"] = "rewardbench.prompts.vNEXT"
    assert experiment_id(study.config_from_dict(config)) != experiment_id(study.config_from_dict(other))


def test_rendered_prompt_text_is_pinned_to_the_template_id() -> None:
    """If this fails you changed prompt wording: bump PROMPT_TEMPLATE_ID, regenerate configs, then update the pin."""
    digest = hashlib.sha256("\n".join(render_messages(_request(FeedbackCondition.NO_FEEDBACK))).encode()).hexdigest()
    assert digest == PINNED_NO_FEEDBACK_PROMPT_SHA256, PROMPT_TEMPLATE_ID


PINNED_NO_FEEDBACK_PROMPT_SHA256 = "4c9e60a2fe329255cce4613e842ae42aaf68e0b2af317a2ac7a2e790db0ee318"


@pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")
def test_live_preflight_refuses_a_config_made_for_another_prompt_template(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    config = prepare_config(study.config_path("pilot", "no_feedback"))
    env = build_environment(config)
    try:
        preflight_live(config, env)  # matching template: accepted offline, no network
        stale = json.loads(json.dumps(study.build_study_config("pilot", "no_feedback")))
        stale["metadata"]["prompt_template"] = "rewardbench.prompts.v2"
        stale_config = study.config_from_dict(stale)
        with pytest.raises(ConfigError, match="prompt template"):
            preflight_live(stale_config, env)
    finally:
        env.close()
