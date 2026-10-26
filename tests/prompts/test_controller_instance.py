"""Prompt v4: a guidance controller instance, real flight mechanics, and nothing the model can copy.

History: v2 got the schema echoed back (Mission 006); v3 got its numeric example copied verbatim
(Mission 008). v4 removes every complete controller from the prompt and restricts the model to the
closed-loop guidance policy. See docs/STUDY_V2_PROTOCOL.md.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from rewardbench import study
from rewardbench.config import load_config
from rewardbench.contracts import (
    ConfigError,
    FeedbackCondition,
    ModelRequest,
    PriorAttempt,
    RewardFeedback,
    Split,
)
from rewardbench.core.ids import experiment_id
from rewardbench.environments.apollolander import ApolloLanderAdapter
from rewardbench.environments.apollolander.schema import (
    DEMONSTRATION_GUIDANCE,
    GUIDANCE_BOUNDS,
    GUIDANCE_PARAMETER_GUIDE,
    MECHANICS_CONSTANTS,
    POLICIES,
    SCHEMA_ID,
    ControllerRejected,
    constant_controller,
    controller_schema_document,
    demonstration_guidance_controller,
    normalize_controller,
    random_controller,
    validate_controller,
)
from rewardbench.prompts import PROMPT_TEMPLATE_ID, SYSTEM_PROMPT, render_messages
from rewardbench.run.factory import build_environment, prepare_config
from rewardbench.run.live import preflight_live

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "configs" / "study" / "archive"
PHYSICS_JS = ROOT / "frontend" / "apollolander" / "experiment" / "physics.js"
MISSION_006_EXPERIMENT_ID = "exp_26eb2593d31e4a72c041"  # prompt v2: schema echoed back
MISSION_008_EXPERIMENT_ID = "exp_bcc1e26372179700a53d"  # prompt v3: example controller copied verbatim
CONDITIONS = tuple(FeedbackCondition)
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")

# A study-shaped spec without Node: the same document the guidance-only research adapter describes.
SPEC = ApolloLanderAdapter(research_mode=True, allowed_policies=study.MODEL_POLICIES).describe()
_FEEDBACK = (
    RewardFeedback(revision_index=0, episode_index=0, total_reward=-41.5, success=False, crashed=True,
                   steps=123, metrics={"fuel_used": 12.5}),
)


def _midpoint_guidance() -> dict:
    return {"schema": SCHEMA_ID, "policy": "guidance",
            "parameters": {k: (lo + hi) / 2 for k, (lo, hi) in GUIDANCE_BOUNDS.items()}}


def _request(condition: FeedbackCondition, *, history: bool = False, spec=SPEC) -> ModelRequest:
    attempts = ()
    if history:
        attempts = (PriorAttempt(
            revision_index=0, parameters=_midpoint_guidance(), valid=True, validation_error=None,
            feedback=None if condition is FeedbackCondition.NO_FEEDBACK else _FEEDBACK,
        ),)
    return ModelRequest(
        contract_version="1.0.0", experiment_id="exp_test", session_id="ses_test", revision_index=len(attempts),
        feedback_condition=condition, split=Split.DEVELOPMENT, environment=spec, history=attempts,
        model_settings={},
    )


def _instructions(user_text: str) -> str:
    """Everything except the revision number and history: task, mechanics, schema, format, output rule."""
    return user_text[:user_text.index("Revision:")] + user_text[user_text.index("Reply with one compact JSON object"):]


def _json_objects(text: str) -> list[dict]:
    decoder, found = json.JSONDecoder(), []
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


# ---------------------------------------------------------------- nothing copyable


@pytest.mark.parametrize("condition", CONDITIONS)
def test_revision_zero_prompt_contains_no_complete_valid_controller(condition: FeedbackCondition) -> None:
    system_text, user_text = render_messages(_request(condition))
    for text in (system_text, user_text):
        for candidate in _json_objects(text):
            # Not valid under the study's restriction, nor under the unrestricted validator.
            assert not validate_controller(candidate).valid, candidate
            assert not validate_controller(candidate, study.MODEL_POLICIES).valid, candidate
    assert '"example"' not in user_text and "Example of a complete valid controller" not in user_text


def test_prompt_has_no_smallest_controller_rule_and_no_tuned_values() -> None:
    _system, user_text = render_messages(_request(FeedbackCondition.NO_FEEDBACK))
    assert "smallest valid controller" not in user_text
    for name, value in DEMONSTRATION_GUIDANCE.items():
        assert f'"{name}":{json.dumps(value)}' not in user_text
        assert f"{name} = {value}" not in user_text and f"{name}={value}" not in user_text
    # The shape lists every parameter with a placeholder, so it is not JSON and cannot be pasted back.
    shape = controller_schema_document(study.MODEL_POLICIES)["instance"]["shape"]
    assert shape in user_text and shape.count("<number>") == len(GUIDANCE_BOUNDS)
    with pytest.raises(json.JSONDecodeError):
        json.loads(shape)


def test_scripted_mock_guidance_pair_is_not_the_demonstration_controller() -> None:
    from rewardbench.run.mock_model import apollo_guidance_pair

    for controller in apollo_guidance_pair():
        assert validate_controller(controller, study.MODEL_POLICIES).valid
        assert controller["parameters"] != DEMONSTRATION_GUIDANCE


# ---------------------------------------------------------------- flight mechanics


def test_mechanics_constants_match_the_physics_source() -> None:
    source = PHYSICS_JS.read_text(encoding="utf-8")

    def js(name: str) -> float:
        return float(re.search(rf"\b{name}:\s*([0-9.]+)", source).group(1))

    for name in ("gravity", "thrustAcceleration", "drag", "rotationLerp", "safeVerticalSpeed", "perfectVerticalSpeed"):
        assert MECHANICS_CONSTANTS[name] == js(name), name
    assert "state.thrustBuild += (state.thrust - state.thrustBuild) * 0.2" in source
    assert MECHANICS_CONSTANTS["thrustLerp"] == 0.2
    assert "fuelUsed = 0.2 * state.thrustBuild" in source and MECHANICS_CONSTANTS["fuelPerStep"] == 0.2
    assert "dx: mid - state.x" in source  # "dx > 0: the pad is to the right"
    assert "state.vy += PHYSICS.gravity" in source  # "y grows downward"
    # Hover: thrust that cancels gravity upright is gravity / thrustAcceleration, the "about 1/3" in the prompt.
    assert MECHANICS_CONSTANTS["gravity"] / MECHANICS_CONSTANTS["thrustAcceleration"] == pytest.approx(1 / 3)


def test_prompt_explains_every_guidance_parameter_and_the_control_law() -> None:
    _system, user_text = render_messages(_request(FeedbackCondition.NO_FEEDBACK))
    assert set(GUIDANCE_PARAMETER_GUIDE) == set(GUIDANCE_BOUNDS)
    for name in GUIDANCE_BOUNDS:
        assert f"- {name}: " in user_text
    for token in ("Objective:", "Flight mechanics:", "y grows DOWNWARD", "Positive rotation tilts the thrust",
                  "rotation exactly 0", "below 0.15", "below 0.075", "timeout",
                  "desired_vx = clamp(dx * vx_gain", "thrust = hover_thrust + (vy - target_vy) * vy_gain"):
        assert token in user_text, token
    # Research starts are described from the real schedule.
    assert "80 to 240 units to the right" in user_text and "rotation -90 to -30 degrees" in user_text


def test_the_described_control_law_is_the_one_the_simulator_runs() -> None:
    from rewardbench.environments.apollolander.schema import guidance_action

    params = dict(DEMONSTRATION_GUIDANCE)
    observation = {"dx": 120.0, "vx": 0.4, "vy": 0.1, "altitude": 150.0}
    desired_vx = min(max(120.0 * params["vx_gain"], -params["vx_limit"]), params["vx_limit"])
    vx_error = 0.4 - desired_vx
    rotation = min(max(-vx_error * params["rotation_gain"], -params["cruise_rotation_limit"]), params["cruise_rotation_limit"])
    thrust = params["hover_thrust"] + (0.1 - params["descent_cruise"]) * params["vy_gain"] + abs(vx_error) * params["brake_thrust"]
    action = guidance_action(observation, params)
    assert action == {"thrust": min(max(thrust, 0.0), 1.0), "rotation": int(round(rotation / 10) * 10)}


# ---------------------------------------------------------------- one search space, no repair


def test_guidance_only_schema_offers_only_guidance() -> None:
    document = controller_schema_document(study.MODEL_POLICIES)
    assert list(document["policies"]) == ["guidance"]
    assert list(document["instance"]["policy_fields"]) == ["guidance"]
    _system, user_text = render_messages(_request(FeedbackCondition.NO_FEEDBACK))
    assert '"policy" must be one of: "guidance".' in user_text
    assert '"constant"' not in user_text and '"random"' not in user_text


@pytest.mark.parametrize("controller", [constant_controller(0.5, 0), random_controller(7)])
def test_guidance_only_experiments_reject_scripted_baseline_policies(controller) -> None:
    status = validate_controller(controller, study.MODEL_POLICIES)
    assert not status.valid
    assert "is not allowed in this experiment; allowed policies: guidance" in status.reason
    adapter = ApolloLanderAdapter(research_mode=True, allowed_policies=["guidance"])
    assert not adapter.validate_policy(controller).valid
    # The same baselines stay available to a default adapter for scripted comparisons.
    assert ApolloLanderAdapter(research_mode=True).validate_policy(controller).valid


def test_missing_out_of_range_or_extra_parameters_are_rejected_never_repaired() -> None:
    complete = _midpoint_guidance()
    assert normalize_controller(complete, study.MODEL_POLICIES)["parameters"] == complete["parameters"]
    missing = json.loads(json.dumps(complete))
    del missing["parameters"]["vy_gain"]
    with pytest.raises(ControllerRejected, match="missing guidance parameter 'vy_gain'"):
        normalize_controller(missing, study.MODEL_POLICIES)
    high = json.loads(json.dumps(complete))
    high["parameters"]["descent_low"] = 0.25
    with pytest.raises(ControllerRejected, match="descent_low must be between"):
        normalize_controller(high, study.MODEL_POLICIES)
    extra = json.loads(json.dumps(complete))
    extra["parameters"]["gain"] = 1.0
    with pytest.raises(ControllerRejected, match="unknown guidance parameter"):
        normalize_controller(extra, study.MODEL_POLICIES)
    for bad in (None, "0.1", True, float("nan")):
        broken = json.loads(json.dumps(complete))
        broken["parameters"]["hover_thrust"] = bad
        assert not validate_controller(broken, study.MODEL_POLICIES).valid, bad


def test_missing_and_unknown_policy_errors_list_the_allowed_policies() -> None:
    assert "allowed policies: guidance, constant, random" in validate_controller({"schema": SCHEMA_ID}).reason
    status = validate_controller({"schema": SCHEMA_ID, "policy": "pid"}, study.MODEL_POLICIES)
    assert "unknown controller policy 'pid'; allowed policies: guidance" in status.reason


def test_echoing_the_schema_document_is_rejected_with_a_helpful_message() -> None:
    echoed = {k: v for k, v in controller_schema_document(study.MODEL_POLICIES).items() if k != "note"}
    with pytest.raises(ControllerRejected, match="schema document, not a controller instance"):
        normalize_controller(echoed, study.MODEL_POLICIES)


def test_invalid_allowed_policies_are_refused() -> None:
    for bad in ([], ["pid"], ["guidance", "guidance"], "guidance"):
        with pytest.raises(ValueError):
            ApolloLanderAdapter(allowed_policies=bad)
    assert ApolloLanderAdapter(allowed_policies=["random", "guidance"]).allowed_policies == ("guidance", "random")
    assert ApolloLanderAdapter().allowed_policies == POLICIES


# ---------------------------------------------------------------- matched arms and feedback isolation


def test_all_three_arms_receive_identical_task_mechanics_and_controller_instructions() -> None:
    blocks = {_instructions(render_messages(_request(c))[1]) for c in CONDITIONS}
    with_history = {_instructions(render_messages(_request(c, history=True))[1]) for c in CONDITIONS}
    assert len(blocks) == 1 and with_history == blocks
    assert {render_messages(_request(c))[0] for c in CONDITIONS} == {SYSTEM_PROMPT}


def test_feedback_isolation_is_unchanged() -> None:
    none_text = render_messages(_request(FeedbackCondition.NO_FEEDBACK, history=True))[1]
    only_text = render_messages(_request(FeedbackCondition.REWARD_ONLY, history=True))[1]
    full_text = render_messages(_request(FeedbackCondition.NUMERICAL_REWARD, history=True))[1]
    assert not any(t in none_text for t in ("reward=", "-41.5", "success=", "steps=", "metrics="))
    assert "reward=-41.5" in only_text
    assert not any(t in only_text for t in ("success=", "steps=", "metrics=", "crashed=", "fuel_used"))
    assert "reward=-41.5" in full_text and "success=false" in full_text and "steps=123" in full_text
    # The shared instructions carry no simulator values in any condition.
    assert "reward=" not in _instructions(full_text) and "-41.5" not in _instructions(full_text)


# ---------------------------------------------------------------- versioned identity


def test_prompt_template_and_protocol_are_versioned_in_every_study_config() -> None:
    assert PROMPT_TEMPLATE_ID == "rewardbench.prompts.v4" and study.PROMPT_TAG == "p4"
    assert study.STUDY_ID == "first_llm_study.v2" and (ROOT / study.PROTOCOL_DOC).is_file()
    for condition in study.CONDITIONS:
        config = study.build_study_config("pilot", condition)
        meta = config["metadata"]
        assert meta["prompt_template"] == PROMPT_TEMPLATE_ID and meta["study"] == study.STUDY_ID
        assert meta["protocol"] == study.PROTOCOL_DOC
        assert meta["adapter_kwargs"]["allowed_policies"] == ["guidance"]
        assert "-p4-" in config["experiment_name"] and "/pilot-p4/" in config["database_path"]


def test_archived_configs_still_identify_missions_006_and_008() -> None:
    v2 = load_config(ARCHIVE / "prompt_v2" / "pilot_no_feedback.yaml")
    v3 = load_config(ARCHIVE / "prompt_v3" / "pilot_no_feedback.yaml")
    assert experiment_id(v2) == MISSION_006_EXPERIMENT_ID
    assert experiment_id(v3) == MISSION_008_EXPERIMENT_ID
    assert v3.metadata["prompt_template"] == "rewardbench.prompts.v3"
    old = {experiment_id(load_config(ARCHIVE / v / f"pilot_{c}.yaml"))
           for v in ("prompt_v2", "prompt_v3") for c in study.CONDITIONS}
    new = {c: load_config(study.config_path("pilot", c)) for c in study.CONDITIONS}
    assert len({experiment_id(c) for c in new.values()}) == 3
    assert not {experiment_id(c) for c in new.values()} & old
    paths = {c.database_path for c in new.values()}
    assert all("pilot-p4" in p for p in paths) and not any("pilot-p3" in p or "/pilot/" in p for p in paths)


def test_search_space_and_prompt_template_change_the_config_hash() -> None:
    base = study.build_study_config("pilot", "no_feedback")
    widened = json.loads(json.dumps(base))
    widened["metadata"]["adapter_kwargs"]["allowed_policies"] = list(POLICIES)
    retemplated = json.loads(json.dumps(base))
    retemplated["metadata"]["prompt_template"] = "rewardbench.prompts.vNEXT"
    ids = {experiment_id(study.config_from_dict(c)) for c in (base, widened, retemplated)}
    assert len(ids) == 3


def test_rendered_prompt_text_is_pinned_to_the_template_id() -> None:
    """If this fails you changed prompt wording: bump PROMPT_TEMPLATE_ID, regenerate configs, then update the pin."""
    digest = hashlib.sha256("\n".join(render_messages(_request(FeedbackCondition.NO_FEEDBACK))).encode()).hexdigest()
    assert digest == PINNED_NO_FEEDBACK_PROMPT_SHA256, PROMPT_TEMPLATE_ID


PINNED_NO_FEEDBACK_PROMPT_SHA256 = "c347b6a695ab3506bd9342bdf858d73303a80ddfe41213b65f70e39b11c3fe9d"


@needs_node
def test_study_environment_describes_the_guidance_only_space(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    config = prepare_config(study.config_path("pilot", "no_feedback"))
    env = build_environment(config)
    try:
        assert env.describe().controller_schema == SPEC.controller_schema
        preflight_live(config, env)  # matching template: accepted offline, no network
        stale = json.loads(json.dumps(study.build_study_config("pilot", "no_feedback")))
        stale["metadata"]["prompt_template"] = "rewardbench.prompts.v3"
        with pytest.raises(ConfigError, match="prompt template"):
            preflight_live(study.config_from_dict(stale), env)
    finally:
        env.close()


# ---------------------------------------------------------------- research reproducibility


@needs_node
def test_same_controller_and_seed_reproduce_the_same_flight_and_restriction_changes_no_physics() -> None:
    controller = demonstration_guidance_controller()
    restricted = ApolloLanderAdapter(research_mode=True, max_steps=600, allowed_policies=["guidance"])
    unrestricted = ApolloLanderAdapter(research_mode=True, max_steps=600)
    runs = [adapter.evaluate(controller, [3], origin="hand_specified") for adapter in (restricted, restricted, unrestricted)]
    hashes = {run["episodes"][0]["trace_hash"] for run in runs}
    rewards = {run["episodes"][0]["reward"] for run in runs}
    assert len(hashes) == 1 and len(rewards) == 1
    assert restricted.start_for_seed(3) == unrestricted.start_for_seed(3)
    assert restricted.evaluate(constant_controller(0.5, 0), [3])["controller_valid"] is False
