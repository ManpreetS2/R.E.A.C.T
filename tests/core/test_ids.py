from rewardbench import experiment_id
from rewardbench.contracts import BudgetLimits, ConfigError, ExperimentConfig
from rewardbench.core.ids import canonical_config, config_hash

from fakes import make_config


def test_experiment_id_is_stable_and_ignores_notes_and_database_path() -> None:
    first = make_config(notes="one", database_path="runs/a.sqlite")
    second = make_config(notes="two", database_path="runs/b.sqlite")
    assert experiment_id(first) == experiment_id(second)
    assert config_hash(first) == config_hash(second)
    assert experiment_id(first).startswith("exp_")
    assert len(config_hash(first)) == 64


def test_experiment_id_changes_with_feedback_split_and_budget() -> None:
    base = make_config()
    from rewardbench.contracts import FeedbackCondition, Split

    other_feedback = make_config(feedback_condition=FeedbackCondition.NO_FEEDBACK)
    other_split = make_config(split=Split.HELD_OUT)
    other_budget = make_config(budget=BudgetLimits(max_cost_usd=1.0))
    assert experiment_id(base) != experiment_id(other_feedback)
    assert experiment_id(base) != experiment_id(other_split)
    assert experiment_id(base) != experiment_id(other_budget)


def test_canonical_config_rejects_non_json_metadata() -> None:
    config = make_config(metadata={"when": object()})
    try:
        canonical_config(config)
    except ConfigError as exc:
        assert "JSON-serializable" in str(exc)
    else:
        raise AssertionError("expected ConfigError")


def test_overlapping_seeds_are_rejected() -> None:
    try:
        ExperimentConfig(
            experiment_name="bad",
            environment_id="lunarlander-v3",
            provider="fake",
            model_id="fake-1",
            feedback_condition=make_config().feedback_condition,
            split=make_config().split,
            seed=1,
            num_revisions=1,
            episodes_per_revision=1,
            history_window=0,
            development_seeds=(1, 2),
            held_out_seeds=(2, 3),
        )
    except ConfigError as exc:
        assert "disjoint" in str(exc)
    else:
        raise AssertionError("expected ConfigError")
