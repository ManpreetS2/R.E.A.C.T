from pathlib import Path

import pytest

from rewardbench.contracts import (
    CONTRACT_VERSION,
    BudgetSnapshot,
    Checkpoint,
    ExperimentRecord,
    ExperimentStatus,
    FeedbackCondition,
    ResumeError,
    SessionRecord,
    Split,
    StoredAttempt,
    StoredEpisode,
    StoredError,
)
from rewardbench.storage import SqliteStore


def _experiment() -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id="exp_test",
        experiment_name="unit",
        environment_id="lunarlander-v3",
        provider="fake",
        model_id="fake-1",
        feedback_condition=FeedbackCondition.NUMERICAL_REWARD,
        split=Split.DEVELOPMENT,
        seed=1,
        contract_version=CONTRACT_VERSION,
        config_json="{}",
        config_hash="abc",
        status=ExperimentStatus.PENDING,
        created_at="2026-10-15T00:00:00+00:00",
        updated_at="2026-10-15T00:00:00+00:00",
    )


def _session() -> SessionRecord:
    return SessionRecord(
        session_id="ses_test",
        experiment_id="exp_test",
        status=ExperimentStatus.RUNNING,
        started_at="2026-10-15T00:00:00+00:00",
        ended_at=None,
        python_version="3.12.1",
        platform="test",
    )


def test_store_round_trip_and_scores_view(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "rewardbench.sqlite")
    store.initialize()
    store.initialize()
    store.create_experiment(_experiment())
    store.start_session(_session())
    attempt_id = store.insert_attempt(
        StoredAttempt(
            experiment_id="exp_test",
            session_id="ses_test",
            revision_index=0,
            call_index=0,
            selected=True,
            parameters={"gain": 1},
            raw_response='{"gain": 1}',
            valid=True,
            validation_error=None,
            prompt_tokens=3,
            completion_tokens=2,
            reasoning_tokens=1,
            total_tokens=5,
            latency_seconds=0.4,
            estimated_cost_usd=0.02,
            model_id="fake-1",
            provider="fake",
            error=None,
            created_at="2026-10-15T00:00:01+00:00",
        )
    )
    store.insert_episode(
        StoredEpisode(
            experiment_id="exp_test",
            session_id="ses_test",
            revision_index=0,
            episode_index=0,
            seed=1,
            total_reward=-12.5,
            success=False,
            crashed=True,
            steps=30,
            terminated=True,
            truncated=False,
            elapsed_seconds=1.2,
            metrics={"fuel_used": 8.0},
            error=None,
            created_at="2026-10-15T00:00:02+00:00",
        )
    )
    store.insert_error(
        StoredError(
            experiment_id="exp_test",
            session_id="ses_test",
            phase="validation",
            message="ignored example",
            revision_index=0,
            created_at="2026-10-15T00:00:03+00:00",
        )
    )
    store.save_checkpoint(
        Checkpoint(
            experiment_id="exp_test",
            next_revision_index=1,
            budget=BudgetSnapshot(0.02, 5, 1, 1, 1, 3.0),
            seed_schedule=((1, 2), (3,)),
            updated_at="2026-10-15T00:00:04+00:00",
        )
    )
    attempt = store.fetch_attempts("exp_test")[0]
    episode = store.fetch_episodes("exp_test")[0]
    assert attempt.attempt_id == attempt_id
    assert attempt.reasoning_tokens == 1
    assert attempt.estimated_cost_usd == pytest.approx(0.02)
    assert episode.total_reward == pytest.approx(-12.5)
    assert episode.crashed is True
    assert episode.metrics["fuel_used"] == pytest.approx(8.0)
    scores = store.fetch_scores("exp_test")
    assert scores[0]["score"] == pytest.approx(-12.5)
    checkpoint = store.load_checkpoint("exp_test")
    assert checkpoint is not None
    assert checkpoint.seed_schedule == ((1, 2), (3,))
    assert checkpoint.budget.elapsed_seconds == pytest.approx(3.0)
    store.update_experiment(
        "exp_test",
        status=ExperimentStatus.COMPLETED,
        error=None,
        completed_revisions=1,
    )
    store.end_session("ses_test", status=ExperimentStatus.COMPLETED)
    loaded = store.get_experiment("exp_test")
    assert loaded is not None
    assert loaded.status is ExperimentStatus.COMPLETED
    assert store.fetch_sessions("exp_test")[0].ended_at is not None
    store.close()


def test_duplicate_episode_is_rejected(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "rewardbench.sqlite")
    store.initialize()
    store.create_experiment(_experiment())
    store.start_session(_session())
    episode = StoredEpisode(
        experiment_id="exp_test",
        session_id="ses_test",
        revision_index=0,
        episode_index=0,
        seed=1,
        total_reward=1.0,
        success=True,
        crashed=False,
        steps=1,
        terminated=True,
        truncated=False,
        elapsed_seconds=0.1,
        metrics={},
        error=None,
        created_at="2026-10-15T00:00:02+00:00",
    )
    store.insert_episode(episode)
    with pytest.raises(ResumeError):
        store.insert_episode(episode)
    store.close()
