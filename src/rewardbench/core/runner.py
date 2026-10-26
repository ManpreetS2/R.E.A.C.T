"""Session lifecycle for in-context reward adaptation.

Each loop iteration asks the model for one controller revision, then simulates
that controller. Those steps are stored separately. ``run`` returns a summary
for completed work, budget stops, and recorded failures. ``KeyboardInterrupt``
is saved as ``interrupted`` and raised again.
"""

from __future__ import annotations

import json
import logging
import math
import platform
import time
import traceback
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rewardbench.contracts import (
    CONTRACT_VERSION,
    BudgetExceeded,
    BudgetSnapshot,
    Checkpoint,
    ConfigError,
    EnvironmentAdapter,
    EnvironmentAdapterError,
    EnvironmentSpec,
    EpisodeResult,
    ErrorPhase,
    ExperimentAborted,
    ExperimentConfig,
    ExperimentRecord,
    ExperimentStatus,
    ExperimentStore,
    ExperimentSummary,
    FailurePolicy,
    ModelClient,
    ModelClientError,
    ModelRequest,
    ModelResponse,
    ResumeError,
    SessionRecord,
    Split,
    StoredAttempt,
    StoredEpisode,
    StoredError,
)
from rewardbench.core.budget import BudgetLimiter, _SpendHold
from rewardbench.core.evaluation import SplitGuard
from rewardbench.core.history import HistoryBuilder, RevisionHistoryEntry
from rewardbench.core.ids import canonical_config, config_hash, experiment_id, new_session_id, reject_legacy_restart
from rewardbench.core.isolation import model_history
from rewardbench.core.locking import ExperimentRunLock
from rewardbench.core.seeds import build_seed_schedule

logger = logging.getLogger("rewardbench.runner")

_TERMINAL = (
    ExperimentStatus.COMPLETED,
    ExperimentStatus.FAILED,
    ExperimentStatus.BUDGET_EXHAUSTED,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ExperimentRunner:
    """Run or resume one configured experiment."""

    def __init__(
        self,
        config: ExperimentConfig,
        model: ModelClient,
        environment: EnvironmentAdapter,
        store: ExperimentStore,
        *,
        global_budget: BudgetLimiter | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if config.split is not Split.DEVELOPMENT:
            raise ConfigError(
                "controller adaptation requires split=development; use rewardbench.heldout "
                "to score a frozen controller without model calls"
            )
        if (config.provider in {"mock", "openai", "google", "anthropic", "xai"}
                or model.provider == "mock") and (
            config.provider != model.provider or config.model_id != model.model_id
        ):
            raise ConfigError("configured provider/model must match the executing model client")
        self.config = config
        self.model = model
        self.environment = environment
        self.store = store
        self.global_budget = global_budget
        self.clock = clock or time.monotonic
        self.budget = BudgetLimiter(config.budget, clock=self.clock)
        self.split_guard = SplitGuard(
            config.split,
            config.development_seeds,
            config.held_out_seeds,
        )
        self.history = HistoryBuilder(config.history_window, config.feedback_condition)
        self.experiment_id = experiment_id(config)
        self._schedule = build_seed_schedule(
            config.seed,
            self.split_guard.allowed_seeds(),
            config.num_revisions,
            config.episodes_per_revision,
        )
        for row in self._schedule:
            for seed in row:
                self.split_guard.check(seed)
        self._session_id = ""
        self._session_open = False
        self._spec: EnvironmentSpec | None = None

    def run(self) -> ExperimentSummary:
        with ExperimentRunLock(self.experiment_id, self._lock_directory()):
            return self._run_locked()

    def _lock_directory(self) -> Path | None:
        store_path = getattr(self.store, "path", None)
        if store_path is None:
            return None
        return Path(store_path).parent / "locks"

    def _run_locked(self) -> ExperimentSummary:
        self.store.initialize()
        reject_legacy_restart(self.config, self.store)
        self._spec = self.environment.describe()
        self._check_environment()
        existing = self.store.get_experiment(self.experiment_id)
        if existing is not None:
            if existing.config_hash != config_hash(self.config):
                raise ResumeError(
                    "stored config hash does not match this configuration "
                    f"(stored={existing.config_hash}, current={config_hash(self.config)})"
                )
            if existing.status in _TERMINAL:
                return self._summary(
                    existing.status,
                    existing.error,
                    session_id=_latest_session(self.store, self.experiment_id),
                )
        else:
            self._create_experiment()
        self._restore_elapsed()
        self._open_session()
        try:
            start = self._first_incomplete()
            for revision in range(start, self.config.num_revisions):
                self._run_revision(revision)
                if (revision + 1) % self.config.checkpoint_every == 0:
                    self._save_checkpoint()
            return self._finish(ExperimentStatus.COMPLETED, None)
        except BudgetExceeded as exc:
            self._record_error(ErrorPhase.BUDGET, str(exc), exc=exc)
            # A live CLI session call gate pauses the experiment without sealing
            # it as terminal budget_exhausted, so an approved continuation can resume.
            if getattr(exc, "resource", None) in ("live_session_model_calls", "aggregate_usd_ceiling"):
                return self._finish(ExperimentStatus.INTERRUPTED, str(exc))
            return self._finish(ExperimentStatus.BUDGET_EXHAUSTED, str(exc))
        except ExperimentAborted as exc:
            return exc.summary
        except KeyboardInterrupt:
            self._finish(ExperimentStatus.INTERRUPTED, "interrupted")
            raise
        except Exception as exc:
            self._record_error(ErrorPhase.CONFIG, str(exc), exc=exc)
            summary = self._finish(ExperimentStatus.FAILED, str(exc))
            raise ExperimentAborted(str(exc), summary) from exc

    def _check_environment(self) -> None:
        spec = self._environment_spec()
        if spec.environment_id != self.config.environment_id:
            raise ConfigError(
                f"environment id {spec.environment_id!r} does not match "
                f"config environment_id {self.config.environment_id!r}"
            )

    def _create_experiment(self) -> None:
        now = _utc_now()
        payload = canonical_config(self.config)
        payload["database_path"] = self.config.database_path
        payload["notes"] = self.config.notes
        self.store.create_experiment(
            ExperimentRecord(
                experiment_id=self.experiment_id,
                experiment_name=self.config.experiment_name,
                environment_id=self.config.environment_id,
                provider=self.config.provider,
                model_id=self.config.model_id,
                feedback_condition=self.config.feedback_condition,
                split=self.config.split,
                seed=self.config.seed,
                contract_version=CONTRACT_VERSION,
                config_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
                config_hash=config_hash(self.config),
                status=ExperimentStatus.PENDING,
                created_at=now,
                updated_at=now,
            )
        )

    def _restore_elapsed(self) -> None:
        checkpoint = self.store.load_checkpoint(self.experiment_id)
        if checkpoint is None:
            return
        if checkpoint.seed_schedule != self._schedule:
            raise ResumeError("stored seed schedule does not match this configuration")
        self.budget.restore(
            BudgetSnapshot(
                cost_usd=0.0,
                tokens=0,
                episodes=0,
                revisions=0,
                model_calls=0,
                elapsed_seconds=checkpoint.budget.elapsed_seconds,
            )
        )

    def _open_session(self) -> None:
        self._session_id = new_session_id()
        self.store.start_session(
            SessionRecord(
                session_id=self._session_id,
                experiment_id=self.experiment_id,
                status=ExperimentStatus.RUNNING,
                started_at=_utc_now(),
                ended_at=None,
                python_version=platform.python_version(),
                platform=platform.platform(),
            )
        )
        self._session_open = True
        self.store.update_experiment(
            self.experiment_id,
            status=ExperimentStatus.RUNNING,
            error=None,
        )

    def _run_revision(self, revision: int) -> None:
        logger.info("experiment %s revision %s", self.experiment_id, revision)
        attempt = self._propose(revision)
        if attempt.valid:
            self._run_episodes(attempt, revision)

    def _propose(self, revision: int) -> StoredAttempt:
        selected = [item for item in self._attempts_for(revision) if item.selected]
        if selected:
            return selected[-1]
        max_calls = self.config.max_model_retries + 1
        last_message = "model did not return a controller"
        while True:
            existing = self._attempts_for(revision)
            chosen = [item for item in existing if item.selected]
            if chosen:
                return chosen[-1]
            if len(existing) >= max_calls:
                return self._give_up_model(revision, last_message)
            call_index = len(existing)
            new_revision = call_index == 0
            self._block_if_needed(model_call=True, revision=new_revision)
            request = self._request(revision)
            hold = self._begin_global(
                key=f"{self.experiment_id}:attempt:{revision}:{call_index}",
                model_call=True,
                revision=new_revision,
            )
            if hold is None and self._shared_budget() is not None:
                chosen = [item for item in self._attempts_for(revision) if item.selected]
                if chosen:
                    return chosen[-1]
                if len(self._attempts_for(revision)) == len(existing):
                    return self._give_up_model(revision, "stored spend could not be resumed")
                continue
            settled = False
            try:
                try:
                    response = self.model.propose(request)
                except BudgetExceeded as exc:
                    # A pre-call refusal (including SessionPaidCallGate) has no
                    # response and must not create an attempt or spend a call.
                    if exc.response is not None:
                        response = exc.response
                        self._insert_attempt(
                            revision=revision, call_index=call_index, selected=False,
                            parameters={}, raw_response=response.raw_text, valid=False,
                            validation_error=str(exc), response=response, error=str(exc),
                        )
                        self._settle_global(
                            hold, cost_usd=response.estimated_cost_usd,
                            tokens=response.charged_tokens, model_calls=1,
                            revisions=1 if new_revision else 0,
                        )
                        settled = True
                    raise
                except ModelClientError as exc:
                    response = exc.response
                    last_message = str(exc)
                    give_up = (not exc.retryable) or (call_index + 1 >= max_calls)
                    self._insert_attempt(
                        revision=revision,
                        call_index=call_index,
                        selected=give_up,
                        parameters={},
                        raw_response="" if response is None else response.raw_text,
                        valid=False,
                        validation_error=str(exc),
                        response=response,
                        error=str(exc),
                    )
                    self._settle_global(
                        hold,
                        cost_usd=0.0 if response is None else response.estimated_cost_usd,
                        tokens=0 if response is None else response.charged_tokens,
                        model_calls=1,
                        revisions=1 if new_revision else 0,
                    )
                    settled = True
                    self._stop_if_over_budget()
                    if give_up:
                        return self._give_up_model(revision, str(exc))
                    self._record_error(ErrorPhase.MODEL, str(exc), revision=revision, exc=exc)
                    continue
                parameters, valid, error = self._interpret(response)
                is_last = call_index + 1 >= max_calls
                self._insert_attempt(
                    revision=revision,
                    call_index=call_index,
                    selected=valid or is_last,
                    parameters=parameters,
                    raw_response=response.raw_text,
                    valid=valid,
                    validation_error=error,
                    response=response,
                    error=None if valid else error,
                )
                self._settle_global(
                    hold,
                    cost_usd=response.estimated_cost_usd,
                    tokens=response.charged_tokens,
                    model_calls=1,
                    revisions=1 if new_revision else 0,
                )
                settled = True
                self._stop_if_over_budget()
                if valid:
                    return [item for item in self._attempts_for(revision) if item.selected][-1]
                message = error or "invalid controller"
                if is_last:
                    if self.config.on_invalid_policy is FailurePolicy.SKIP:
                        self._record_error(ErrorPhase.VALIDATION, message, revision=revision)
                    return self._give_up_policy(revision, message)
                self._record_error(ErrorPhase.VALIDATION, message, revision=revision)
            finally:
                if not settled:
                    self._cancel_global(hold)

    def _give_up_model(self, revision: int, message: str) -> StoredAttempt:
        if self.config.on_model_failure is FailurePolicy.ABORT:
            raise self._fail(ErrorPhase.MODEL, message, revision=revision)
        selected = [item for item in self._attempts_for(revision) if item.selected]
        if not selected:
            raise self._fail(ErrorPhase.MODEL, message, revision=revision)
        return selected[-1]

    def _give_up_policy(self, revision: int, message: str) -> StoredAttempt:
        if self.config.on_invalid_policy is FailurePolicy.ABORT:
            raise self._fail(ErrorPhase.VALIDATION, message, revision=revision)
        return [item for item in self._attempts_for(revision) if item.selected][-1]

    def _run_episodes(self, attempt: StoredAttempt, revision: int) -> None:
        policy = attempt.as_policy()
        if not policy.valid:
            return
        done = {
            episode.episode_index
            for episode in self.store.fetch_episodes(self.experiment_id)
            if episode.revision_index == revision
        }
        for episode_index, seed in enumerate(self._schedule[revision]):
            if episode_index in done:
                continue
            self.split_guard.check(seed)
            self._block_if_needed(episode=True)
            hold = self._begin_global(
                key=f"{self.experiment_id}:episode:{revision}:{episode_index}",
                episode=True,
            )
            if hold is None and self._shared_budget() is not None:
                continue
            try:
                try:
                    result = self.environment.run_episode(
                        policy,
                        seed=seed,
                        episode_index=episode_index,
                        revision_index=revision,
                        max_steps=self.config.max_episode_steps,
                    )
                    checked = self._checked_episode(result, seed, episode_index, revision)
                except Exception as exc:
                    self._insert_failed_episode(revision, episode_index, seed, exc)
                    self._settle_global(hold, episodes=1)
                    self._stop_if_over_budget()
                    if self.config.on_episode_failure is FailurePolicy.ABORT:
                        raise self._fail(
                            ErrorPhase.EPISODE,
                            str(exc),
                            revision=revision,
                            episode=episode_index,
                            exc=exc,
                        ) from exc
                    self._record_error(
                        ErrorPhase.EPISODE,
                        str(exc),
                        revision=revision,
                        episode=episode_index,
                        exc=exc,
                    )
                    continue
                self._insert_episode(checked)
                self._settle_global(hold, episodes=1)
                self._stop_if_over_budget()
            except BudgetExceeded:
                raise
            except ExperimentAborted:
                raise
            except BaseException:
                self._cancel_global(hold)
                raise

    def _interpret(self, response: ModelResponse) -> tuple[dict[str, Any], bool, str | None]:
        if response.parse_error:
            return {}, False, response.parse_error
        if response.parameters is None:
            return {}, False, "model returned no controller parameters"
        if isinstance(response.parameters, (str, bytes)) or not isinstance(response.parameters, Mapping):
            return {}, False, "controller parameters must be a mapping"
        parameters = dict(response.parameters)
        try:
            validation = self.environment.validate_policy(parameters)
        except EnvironmentAdapterError as exc:
            return parameters, False, str(exc)
        if not validation.valid:
            return parameters, False, validation.error
        return parameters, True, None

    def _checked_episode(
        self,
        result: EpisodeResult,
        seed: int,
        episode_index: int,
        revision: int,
    ) -> EpisodeResult:
        if result.revision_index != revision or result.episode_index != episode_index:
            raise EnvironmentAdapterError(
                "episode result indexes do not match the requested revision and episode"
            )
        if result.seed != seed:
            raise EnvironmentAdapterError("episode result seed does not match the scheduled seed")
        if isinstance(result.total_reward, bool) or not isinstance(result.total_reward, (int, float)):
            raise EnvironmentAdapterError("total_reward must be a real number")
        if not math.isfinite(float(result.total_reward)):
            raise EnvironmentAdapterError("total_reward must be finite")
        return EpisodeResult(
            revision_index=revision,
            episode_index=episode_index,
            seed=seed,
            total_reward=float(result.total_reward),
            success=bool(result.success),
            crashed=None if result.crashed is None else bool(result.crashed),
            steps=result.steps,
            terminated=bool(result.terminated),
            truncated=bool(result.truncated),
            elapsed_seconds=float(result.elapsed_seconds),
            metrics=_finite_metrics(result.metrics),
            error=result.error,
        )

    def _request(self, revision: int) -> ModelRequest:
        attempts = self.store.fetch_attempts(self.experiment_id)
        episodes = self.store.fetch_episodes(self.experiment_id)
        entries: list[RevisionHistoryEntry] = []
        for index in range(revision):
            selected = [
                item for item in attempts if item.revision_index == index and item.selected
            ]
            if not selected:
                continue
            attempt = selected[-1]
            played = [
                episode.as_result()
                for episode in episodes
                if episode.revision_index == index
                and episode.error is None
                and episode.total_reward is not None
                and episode.success is not None
            ]
            entries.append(
                RevisionHistoryEntry(
                    revision_index=index,
                    parameters=dict(attempt.parameters),
                    valid=attempt.valid,
                    validation_error=attempt.validation_error,
                    episodes=tuple(played),
                )
            )
        return ModelRequest(
            contract_version=CONTRACT_VERSION,
            experiment_id=self.experiment_id,
            session_id=self._session_id,
            revision_index=revision,
            feedback_condition=self.config.feedback_condition,
            split=self.config.split,
            environment=self._environment_spec(),
            history=model_history(self.history, entries, self.split_guard.allowed_seeds()),
            model_settings=dict(self.config.model_settings),
        )

    def _insert_attempt(
        self,
        *,
        revision: int,
        call_index: int,
        selected: bool,
        parameters: Mapping[str, Any],
        raw_response: str,
        valid: bool,
        validation_error: str | None,
        response: ModelResponse | None,
        error: str | None,
    ) -> None:
        self.store.insert_attempt(
            StoredAttempt(
                experiment_id=self.experiment_id,
                session_id=self._session_id,
                revision_index=revision,
                call_index=call_index,
                selected=selected,
                parameters=dict(parameters),
                raw_response=raw_response,
                valid=valid,
                validation_error=validation_error,
                prompt_tokens=0 if response is None else response.prompt_tokens,
                completion_tokens=0 if response is None else response.completion_tokens,
                reasoning_tokens=0 if response is None else response.reasoning_tokens,
                total_tokens=0 if response is None else response.charged_tokens,
                latency_seconds=0.0 if response is None else response.latency_seconds,
                estimated_cost_usd=0.0 if response is None else response.estimated_cost_usd,
                model_id=self.model.model_id if response is None else (response.model_id or self.model.model_id),
                provider=self.model.provider if response is None else (response.provider or self.model.provider),
                error=error,
                created_at=_utc_now(),
                usage={} if response is None else dict(response.usage),
            )
        )

    def _insert_episode(self, result: EpisodeResult) -> None:
        self.store.insert_episode(
            StoredEpisode(
                experiment_id=self.experiment_id,
                session_id=self._session_id,
                revision_index=result.revision_index,
                episode_index=result.episode_index,
                seed=result.seed,
                total_reward=result.total_reward,
                success=result.success,
                crashed=result.crashed,
                steps=result.steps,
                terminated=result.terminated,
                truncated=result.truncated,
                elapsed_seconds=result.elapsed_seconds,
                metrics=dict(result.metrics),
                error=result.error,
                created_at=_utc_now(),
            )
        )

    def _insert_failed_episode(
        self,
        revision: int,
        episode_index: int,
        seed: int,
        exc: BaseException,
    ) -> None:
        self.store.insert_episode(
            StoredEpisode(
                experiment_id=self.experiment_id,
                session_id=self._session_id,
                revision_index=revision,
                episode_index=episode_index,
                seed=seed,
                total_reward=None,
                success=None,
                crashed=None,
                steps=0,
                terminated=False,
                truncated=False,
                elapsed_seconds=0.0,
                metrics={},
                error=str(exc),
                created_at=_utc_now(),
            )
        )

    def _environment_spec(self) -> EnvironmentSpec:
        if self._spec is None:
            self._spec = self.environment.describe()
        return self._spec

    def _block_if_needed(
        self,
        *,
        model_call: bool = False,
        episode: bool = False,
        revision: bool = False,
    ) -> None:
        self._sync_experiment_budget()
        self.budget.ensure_can_start(model_call=model_call, episode=episode, revision=revision)

    def _stop_if_over_budget(self) -> None:
        self._sync_experiment_budget()
        self.budget.ensure_within_limits()

    def _shared_budget(self) -> BudgetLimiter | None:
        if self.global_budget is None or self.global_budget is self.budget:
            return None
        return self.global_budget

    def _account_global(self) -> None:
        limiter = self._shared_budget()
        if limiter is None:
            return
        seen_revisions: set[int] = set()
        for attempt in self.store.fetch_attempts(self.experiment_id):
            revision_charge = 0
            if attempt.revision_index not in seen_revisions:
                seen_revisions.add(attempt.revision_index)
                revision_charge = 1
            limiter.commit_once(
                f"{self.experiment_id}:attempt:{attempt.revision_index}:{attempt.call_index}",
                cost_usd=attempt.estimated_cost_usd,
                tokens=attempt.total_tokens,
                model_calls=1,
                revisions=revision_charge,
            )
        for episode in self.store.fetch_episodes(self.experiment_id):
            limiter.commit_once(
                f"{self.experiment_id}:episode:{episode.revision_index}:{episode.episode_index}",
                episodes=1,
            )

    def _begin_global(
        self,
        *,
        key: str,
        model_call: bool = False,
        episode: bool = False,
        revision: bool = False,
    ) -> _SpendHold | None:
        if self._shared_budget() is None:
            return None
        self._account_global()
        assert self.global_budget is not None
        return self.global_budget.begin(
            key=key,
            model_call=model_call,
            episode=episode,
            revision=revision,
        )

    def _settle_global(self, hold: _SpendHold | None, **kwargs: float) -> None:
        if hold is None or self._shared_budget() is None:
            return
        assert self.global_budget is not None
        self.global_budget.settle(hold, **kwargs)

    def _cancel_global(self, hold: _SpendHold | None) -> None:
        if hold is None or self._shared_budget() is None:
            return
        assert self.global_budget is not None
        self.global_budget.cancel(hold)

    def _sync_experiment_budget(self) -> None:
        attempts = self.store.fetch_attempts(self.experiment_id)
        episodes = self.store.fetch_episodes(self.experiment_id)
        self.budget.restore(
            BudgetSnapshot(
                cost_usd=sum(item.estimated_cost_usd for item in attempts),
                tokens=sum(item.total_tokens for item in attempts),
                episodes=len(episodes),
                revisions=len({item.revision_index for item in attempts}),
                model_calls=len(attempts),
                elapsed_seconds=self.budget.elapsed(),
            )
        )

    def _attempts_for(self, revision: int) -> list[StoredAttempt]:
        return [
            item
            for item in self.store.fetch_attempts(self.experiment_id)
            if item.revision_index == revision
        ]

    def _first_incomplete(self) -> int:
        for revision in range(self.config.num_revisions):
            if not self._revision_complete(revision):
                return revision
        return self.config.num_revisions

    def _revision_complete(self, revision: int) -> bool:
        selected = [item for item in self._attempts_for(revision) if item.selected]
        if not selected:
            return False
        if not selected[-1].valid:
            return True
        have = {
            episode.episode_index
            for episode in self.store.fetch_episodes(self.experiment_id)
            if episode.revision_index == revision
        }
        return all(index in have for index in range(self.config.episodes_per_revision))

    def _record_error(
        self,
        phase: ErrorPhase,
        message: str,
        *,
        revision: int | None = None,
        episode: int | None = None,
        exc: BaseException | None = None,
    ) -> None:
        if not self._session_id:
            return
        formatted = None
        if exc is not None:
            formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.store.insert_error(
            StoredError(
                experiment_id=self.experiment_id,
                session_id=self._session_id,
                phase=phase.value,
                message=message,
                revision_index=revision,
                episode_index=episode,
                traceback=formatted,
                created_at=_utc_now(),
            )
        )

    def _fail(
        self,
        phase: ErrorPhase,
        message: str,
        *,
        revision: int | None = None,
        episode: int | None = None,
        exc: BaseException | None = None,
    ) -> ExperimentAborted:
        self._record_error(phase, message, revision=revision, episode=episode, exc=exc)
        summary = self._finish(ExperimentStatus.FAILED, message)
        return ExperimentAborted(message, summary)

    def _save_checkpoint(self) -> None:
        self._sync_experiment_budget()
        self.store.save_checkpoint(
            Checkpoint(
                experiment_id=self.experiment_id,
                next_revision_index=self._first_incomplete(),
                budget=self.budget.snapshot(),
                seed_schedule=self._schedule,
                updated_at=_utc_now(),
            )
        )

    def _finish(self, status: ExperimentStatus, error: str | None) -> ExperimentSummary:
        self._save_checkpoint()
        summary = self._summary(status, error, session_id=self._session_id)
        self.store.update_experiment(
            self.experiment_id,
            status=status,
            error=error,
            completed_revisions=summary.revisions_completed,
        )
        if self._session_open:
            self.store.end_session(self._session_id, status=status, error=error)
            self._session_open = False
        return summary

    def _summary(
        self,
        status: ExperimentStatus,
        error: str | None,
        *,
        session_id: str,
    ) -> ExperimentSummary:
        attempts = self.store.fetch_attempts(self.experiment_id)
        episodes = self.store.fetch_episodes(self.experiment_id)
        selected = [item for item in attempts if item.selected]
        rewards = [
            episode.total_reward
            for episode in episodes
            if episode.error is None and episode.total_reward is not None
        ]
        completed = sum(
            1 for revision in range(self.config.num_revisions) if self._revision_complete(revision)
        )
        return ExperimentSummary(
            experiment_id=self.experiment_id,
            session_id=session_id,
            status=status,
            revisions_completed=completed,
            episodes_recorded=len(episodes),
            invalid_revisions=sum(1 for item in selected if not item.valid),
            model_calls=len(attempts),
            total_tokens=sum(item.total_tokens for item in attempts),
            total_cost_usd=sum(item.estimated_cost_usd for item in attempts),
            mean_reward=(sum(rewards) / len(rewards)) if rewards else None,
            best_reward=max(rewards) if rewards else None,
            error=error,
        )


def _latest_session(store: ExperimentStore, experiment_id: str) -> str:
    sessions = store.fetch_sessions(experiment_id)
    if not sessions:
        return ""
    return sessions[-1].session_id


def _finite_metrics(metrics: Mapping[str, Any]) -> dict[str, float]:
    clean: dict[str, float] = {}
    for key, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EnvironmentAdapterError(f"metric {key!r} must be a finite number")
        if not math.isfinite(float(value)):
            raise EnvironmentAdapterError(f"metric {key!r} must be a finite number")
        clean[str(key)] = float(value)
    return clean
