import json

import pytest

from rewardbench.config import config_from_mapping, load_config
from rewardbench.contracts import ConfigError, FeedbackCondition, Split


def test_yaml_examples_load_and_keep_splits_apart(tmp_path) -> None:
    development = load_config("configs/lunarlander_development_numerical.yaml")
    withheld = load_config("configs/lunarlander_development_nofeedback.yaml")
    held_out = load_config("configs/lunarlander_heldout_numerical.yaml")
    assert development.feedback_condition is FeedbackCondition.NUMERICAL_REWARD
    assert withheld.feedback_condition is FeedbackCondition.NO_FEEDBACK
    assert held_out.split is Split.HELD_OUT
    assert set(development.development_seeds).isdisjoint(development.held_out_seeds)
    from rewardbench import experiment_id

    assert len({experiment_id(development), experiment_id(withheld), experiment_id(held_out)}) == 3


def test_json_round_trip(tmp_path) -> None:
    source = load_config("configs/lunarlander_development_numerical.yaml")
    payload = {
        "experiment_name": source.experiment_name,
        "environment_id": source.environment_id,
        "provider": source.provider,
        "model_id": source.model_id,
        "feedback_condition": source.feedback_condition.value,
        "split": source.split.value,
        "seed": source.seed,
        "num_revisions": source.num_revisions,
        "episodes_per_revision": source.episodes_per_revision,
        "history_window": source.history_window,
        "development_seeds": list(source.development_seeds),
        "held_out_seeds": list(source.held_out_seeds),
        "budget": {"max_cost_usd": source.budget.max_cost_usd},
        "model_settings": dict(source.model_settings),
    }
    path = tmp_path / "experiment.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_config(path)
    assert loaded.model_id == source.model_id
    assert loaded.budget.max_cost_usd == source.budget.max_cost_usd


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ConfigError, match="unknown config fields"):
        config_from_mapping(
            {
                "experiment_name": "x",
                "environment_id": "lunarlander-v3",
                "provider": "fake",
                "model_id": "fake-1",
                "feedback_condition": "numerical_reward",
                "split": "development",
                "seed": 1,
                "num_revisions": 1,
                "episodes_per_revision": 1,
                "history_window": 0,
                "development_seeds": [1],
                "held_out_seeds": [2],
                "temperature": 0,
            }
        )
