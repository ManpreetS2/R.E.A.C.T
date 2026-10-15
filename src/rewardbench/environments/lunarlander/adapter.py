"""Gymnasium LunarLander-v3 adapter.

Scored flights use the discrete environment with wind disabled. The reward
stored on each episode is the sum of the rewards Gymnasium returned. Landing
and crash flags come from the physics snapshot in ``outcomes.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from rewardbench.environments.lunarlander.actions import (
    IDLE,
    LEFT_ENGINE,
    MAIN_ENGINE,
    MAIN_ENGINE_FUEL_COST,
    PHYSICS_FPS,
    RIGHT_ENGINE,
    SIDE_ENGINE_FUEL_COST,
    action_name,
)
from rewardbench.environments.lunarlander.controller import (
    CompiledController,
    compile_controller,
    episode_rng,
)
from rewardbench.environments.lunarlander.outcomes import (
    PhysicsSnapshot,
    classify_outcome,
)
from rewardbench.environments.lunarlander.recording import (
    replay_document,
    write_replay,
    write_video,
)
from rewardbench.environments.lunarlander.schema import (
    ControllerStatus,
    controller_schema_document,
    validate_controller,
)
from rewardbench.environments.lunarlander.seeds import validate_seed_split
from rewardbench.environments.lunarlander.types import FlightEpisode, FlightEvaluation
from rewardbench.environments.protocol import adapter_error, load_contracts

ENVIRONMENT_ID = "LunarLander-v3"
CONTRACT_ENVIRONMENT_ID = "lunarlander-v3"
ABSOLUTE_STEP_CAP = 5_000


class LunarLanderAdapter:
    """Safe, seeded evaluator for one discrete LunarLander-v3 revision."""

    environment_id = ENVIRONMENT_ID

    def __init__(
        self,
        *,
        gravity: float = -10.0,
        enable_wind: bool = False,
        wind_power: float = 15.0,
        turbulence_power: float = 1.5,
    ) -> None:
        if not -12.0 < gravity < 0.0:
            raise ValueError("gravity must be between -12 and 0, matching Gymnasium")
        self.gravity = gravity
        self.enable_wind = enable_wind
        self.wind_power = wind_power
        self.turbulence_power = turbulence_power

    def validate_controller(self, controller: Mapping[str, Any] | str) -> ControllerStatus:
        return validate_controller(controller)

    def close(self) -> None:
        """Episodes open and close their own environment. Nothing is retained."""

    def describe(self):
        """Runner-facing description. The id matches the published experiment configs."""
        contracts = load_contracts()
        return contracts.EnvironmentSpec(
            environment_id=CONTRACT_ENVIRONMENT_ID,
            display_name="LunarLander-v3",
            task_description=(
                "Land the Gymnasium LunarLander-v3 craft between the flag poles. "
                "Wind is off. The score is the sum of Gymnasium rewards. A landing "
                "counts only when the body settles between the flags. Submit a "
                "controller object, not Python code."
            ),
            controller_schema=controller_schema_document(),
            action_space_summary="discrete idle, left engine, main engine, or right engine",
            observation_space_summary="x, y, vx, vy, angle, angular velocity, and two leg contacts",
        )

    def validate_policy(self, parameters: Mapping[str, Any]):
        contracts = load_contracts()
        if isinstance(parameters, (str, bytes)) or not isinstance(parameters, Mapping):
            return contracts.ValidationResult(False, "controller parameters must be a mapping")
        status = validate_controller(dict(parameters))
        if not status.valid:
            return contracts.ValidationResult(False, status.reason or "invalid controller")
        return contracts.ValidationResult(True, None)

    def run_episode(
        self,
        policy,
        *,
        seed: int,
        episode_index: int,
        revision_index: int,
        max_steps: int | None = None,
    ):
        """Simulate one Gymnasium episode and return the shared episode record."""
        import time

        contracts = load_contracts()
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise adapter_error("episode seed must be a non-negative integer")
        if isinstance(episode_index, bool) or not isinstance(episode_index, int) or episode_index < 0:
            raise adapter_error("episode_index must be a non-negative integer")
        if isinstance(revision_index, bool) or not isinstance(revision_index, int) or revision_index < 0:
            raise adapter_error("revision_index must be a non-negative integer")
        validation = self.validate_policy(policy.parameters)
        if not validation.valid:
            raise adapter_error(validation.error or "invalid controller")
        started = time.perf_counter()
        try:
            evaluation = self.evaluate(
                dict(policy.parameters),
                [seed],
                revision=revision_index,
                split="unrestricted",
                max_steps=max_steps,
            )
        except ValueError as exc:
            raise adapter_error(str(exc)) from exc
        elapsed = time.perf_counter() - started
        episode = evaluation.episodes[0]
        if episode.reward is None:
            raise adapter_error(episode.invalid_reason or "episode produced no reward")
        metrics = {
            "fuel_used": float(episode.fuel_penalty),
            "in_landing_zone": 1.0 if episode.in_landing_zone else 0.0,
            "viewport_exit": 1.0 if episode.viewport_exit else 0.0,
            "hull_contact": 1.0 if episode.hull_contact else 0.0,
        }
        if episode.lander_x is not None:
            metrics["lander_x"] = float(episode.lander_x)
        return contracts.EpisodeResult(
            revision_index=revision_index,
            episode_index=episode_index,
            seed=seed,
            total_reward=float(episode.reward),
            success=bool(episode.landed),
            crashed=bool(episode.crashed),
            steps=int(episode.steps),
            terminated=bool(episode.terminated),
            truncated=bool(episode.truncated),
            elapsed_seconds=elapsed,
            metrics=metrics,
            error=None,
        )

    def evaluate(
        self,
        controller: Mapping[str, Any] | str,
        seeds: Sequence[int],
        *,
        revision: int | None = None,
        split: str = "unrestricted",
        record_dir: str | Path | None = None,
        record_video: bool = False,
        video_seeds: Sequence[int] | None = None,
        max_steps: int | None = None,
    ) -> FlightEvaluation:
        validate_seed_split(seeds, split)
        if max_steps is not None and (isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1):
            raise ValueError("max_steps must be a positive integer")
        if max_steps is not None and max_steps > ABSOLUTE_STEP_CAP:
            raise ValueError(f"max_steps cannot exceed {ABSOLUTE_STEP_CAP}")

        status = validate_controller(controller)
        if not status.valid:
            episodes = tuple(
                _invalid_episode(
                    seed=seed,
                    revision=revision,
                    reason=status.reason or "invalid controller",
                )
                for seed in seeds
            )
            return FlightEvaluation(
                environment_id=self.environment_id,
                revision=revision,
                controller_valid=False,
                invalid_reason=status.reason,
                policy=None,
                split=split,
                episodes=episodes,
            )

        compiled = compile_controller(controller)
        output_dir = Path(record_dir) if record_dir is not None else None
        selected_video_seeds = _video_seed_selection(seeds, record_video, video_seeds)

        gymnasium_version, box2d_version = _dependency_versions()
        episodes: list[FlightEpisode] = []
        replays: list[dict[str, Any]] = []
        env = self._make_env(render=False, max_steps=max_steps)
        try:
            for seed in seeds:
                episode, replay, _frames = self._run_episode(
                    env,
                    compiled,
                    seed=seed,
                    revision=revision,
                    max_steps=max_steps,
                )
                episodes.append(episode)
                replays.append(replay)
        finally:
            env.close()

        replay_paths: list[str] = []
        if output_dir is not None:
            for replay in replays:
                path = output_dir / f"replay-revision-{_revision_label(revision)}-seed-{replay['seed']}.json"
                write_replay(path, replay)
                replay_paths.append(str(path))

        video_paths: list[str] = []
        video_errors: list[str] = []
        if selected_video_seeds:
            video_paths, video_errors = self._record_videos(
                compiled,
                selected_video_seeds,
                revision=revision,
                output_dir=output_dir,
                max_steps=max_steps,
            )

        return FlightEvaluation(
            environment_id=self.environment_id,
            revision=revision,
            controller_valid=True,
            invalid_reason=None,
            policy=compiled.policy,
            split=split,
            episodes=tuple(episodes),
            replay_paths=tuple(replay_paths),
            video_paths=tuple(video_paths),
            video_errors=tuple(video_errors),
            gymnasium_version=gymnasium_version,
            box2d_version=box2d_version,
        )

    def _make_env(self, *, render: bool, max_steps: int | None) -> Any:
        try:
            import gymnasium as gym
        except ImportError as exc:
            raise RuntimeError(
                "LunarLander-v3 requires gymnasium and Box2D. "
                "Install swig, then pip install 'gymnasium[box2d]'."
            ) from exc

        kwargs: dict[str, Any] = {
            "continuous": False,
            "gravity": self.gravity,
            "enable_wind": self.enable_wind,
            "wind_power": self.wind_power,
            "turbulence_power": self.turbulence_power,
            "render_mode": "rgb_array" if render else None,
        }
        if max_steps is not None:
            kwargs["max_episode_steps"] = max_steps
        try:
            return gym.make(ENVIRONMENT_ID, **kwargs)
        except Exception as exc:
            message = str(exc)
            if "Box2D" in message or "box2d" in message:
                raise RuntimeError(
                    "LunarLander-v3 requires Box2D. Install swig, then pip install 'gymnasium[box2d]'."
                ) from exc
            raise

    def _run_episode(
        self,
        env: Any,
        controller: CompiledController,
        *,
        seed: int,
        revision: int | None,
        max_steps: int | None,
        collect_frames: bool = False,
    ) -> tuple[FlightEpisode, dict[str, Any], list[np.ndarray]]:
        observation, _info = env.reset(seed=seed)
        rng = episode_rng(controller.normalized.seed or 0, seed)
        actions: list[int] = []
        steps: list[dict[str, Any]] = []
        frames: list[np.ndarray] = []
        total_reward = 0.0
        last_step_reward: float | None = None
        terminated = False
        truncated = False
        main_steps = 0
        side_steps = 0
        idle_steps = 0
        step_limit = max_steps if max_steps is not None else ABSOLUTE_STEP_CAP

        if collect_frames:
            frames.extend(_capture_frame(env))

        for time_index in range(step_limit):
            action = controller.act(observation, rng)
            if action not in (IDLE, LEFT_ENGINE, MAIN_ENGINE, RIGHT_ENGINE):
                raise RuntimeError(f"controller returned an illegal action {action}")
            next_observation, reward, terminated, truncated, _info = env.step(action)
            reward = float(reward)
            total_reward += reward
            last_step_reward = reward
            actions.append(action)
            if action == MAIN_ENGINE:
                main_steps += 1
            elif action in (LEFT_ENGINE, RIGHT_ENGINE):
                side_steps += 1
            else:
                idle_steps += 1
            steps.append(
                {
                    "t": time_index,
                    "observation": [float(value) for value in observation],
                    "action": action,
                    "action_name": action_name(action),
                    "reward": reward,
                    "terminated": bool(terminated),
                    "truncated": bool(truncated),
                }
            )
            observation = next_observation
            if collect_frames:
                frames.extend(_capture_frame(env))
            if terminated or truncated:
                break
        else:
            truncated = True

        snapshot = _physics_snapshot(env, observation, terminated=bool(terminated), truncated=bool(truncated))
        outcome = classify_outcome(snapshot)
        episode = FlightEpisode(
            environment_id=self.environment_id,
            seed=seed,
            revision=revision,
            controller_valid=True,
            invalid_reason=None,
            executed=True,
            policy=controller.policy,
            reward=total_reward,
            steps=len(actions),
            duration_seconds=len(actions) / PHYSICS_FPS,
            terminated=bool(terminated),
            truncated=bool(truncated),
            landed=outcome.landed,
            crashed=outcome.crashed,
            outcome=outcome.label,
            crash_cause=outcome.crash_cause,
            hull_contact=snapshot.game_over,
            out_of_bounds=snapshot.out_of_bounds,
            lander_awake=snapshot.lander_awake,
            main_engine_steps=main_steps,
            side_engine_steps=side_steps,
            idle_steps=idle_steps,
            fuel_penalty=round(
                main_steps * MAIN_ENGINE_FUEL_COST + side_steps * SIDE_ENGINE_FUEL_COST,
                2,
            ),
            action_checksum=_checksum(actions),
            last_step_reward=last_step_reward,
            viewport_exit=outcome.viewport_exit,
            timed_out=outcome.timed_out,
            in_landing_zone=snapshot.in_landing_zone,
            lander_x=snapshot.lander_x,
            helipad_x1=snapshot.helipad_x1,
            helipad_x2=snapshot.helipad_x2,
        )
        replay = replay_document(
            environment_id=self.environment_id,
            seed=seed,
            revision=revision,
            policy=controller.policy,
            steps=steps,
            result=episode.to_dict(),
        )
        return episode, replay, frames

    def _record_videos(
        self,
        controller: CompiledController,
        seeds: Sequence[int],
        *,
        revision: int | None,
        output_dir: Path | None,
        max_steps: int | None,
    ) -> tuple[list[str], list[str]]:
        if output_dir is None:
            return [], ["record_video requires record_dir"]
        paths: list[str] = []
        errors: list[str] = []
        env = self._make_env(render=True, max_steps=max_steps)
        try:
            for seed in seeds:
                path = output_dir / f"video-revision-{_revision_label(revision)}-seed-{seed}.mp4"
                try:
                    _episode, _replay, frames = self._run_episode(
                        env,
                        controller,
                        seed=seed,
                        revision=revision,
                        max_steps=max_steps,
                        collect_frames=True,
                    )
                    write_video(path, frames, fps=PHYSICS_FPS)
                except Exception as exc:
                    errors.append(f"seed {seed}: {exc}")
                    continue
                paths.append(str(path))
        finally:
            env.close()
        return paths, errors


def _invalid_episode(*, seed: int, revision: int | None, reason: str) -> FlightEpisode:
    return FlightEpisode(
        environment_id=ENVIRONMENT_ID,
        seed=seed,
        revision=revision,
        controller_valid=False,
        invalid_reason=reason,
        executed=False,
        policy=None,
        reward=None,
        steps=0,
        duration_seconds=0.0,
        terminated=False,
        truncated=False,
        landed=False,
        crashed=False,
        outcome="invalid",
        crash_cause=None,
        hull_contact=False,
        out_of_bounds=False,
        lander_awake=None,
        main_engine_steps=0,
        side_engine_steps=0,
        idle_steps=0,
        fuel_penalty=0.0,
        action_checksum=None,
        last_step_reward=None,
        viewport_exit=False,
        timed_out=False,
        in_landing_zone=None,
        lander_x=None,
        helipad_x1=None,
        helipad_x2=None,
    )


def _physics_snapshot(env: Any, observation: Any, *, terminated: bool, truncated: bool) -> PhysicsSnapshot:
    lander_env = env.unwrapped
    x_position = float(observation[0])
    lander = getattr(lander_env, "lander", None)
    awake = None if lander is None else bool(lander.awake)
    helipad_x1 = getattr(lander_env, "helipad_x1", None)
    helipad_x2 = getattr(lander_env, "helipad_x2", None)
    lander_x = None if lander is None else float(lander.position.x)
    in_landing_zone = None
    if lander_x is not None and helipad_x1 is not None and helipad_x2 is not None:
        # The flags stand on helipad_x1 and helipad_x2. The body must lie between them.
        in_landing_zone = float(helipad_x1) <= lander_x <= float(helipad_x2)
    return PhysicsSnapshot(
        terminated=terminated,
        truncated=truncated,
        game_over=bool(getattr(lander_env, "game_over", False)),
        out_of_bounds=abs(x_position) >= 1.0,
        lander_awake=awake,
        in_landing_zone=in_landing_zone,
        lander_x=lander_x,
        helipad_x1=None if helipad_x1 is None else float(helipad_x1),
        helipad_x2=None if helipad_x2 is None else float(helipad_x2),
    )


def _capture_frame(env: Any) -> list[np.ndarray]:
    frame = env.render()
    if frame is None:
        return []
    # Copy immediately. pygame's pixel view is reused on the next render.
    return [np.array(frame, copy=True)]


def _checksum(actions: Sequence[int]) -> str:
    return hashlib.sha256(bytes(actions)).hexdigest()


def _revision_label(revision: int | None) -> str:
    return "none" if revision is None else str(revision)


def _video_seed_selection(
    seeds: Sequence[int],
    record_video: bool,
    video_seeds: Sequence[int] | None,
) -> list[int]:
    if not record_video:
        if video_seeds:
            raise ValueError("video_seeds requires record_video=True")
        return []
    if video_seeds is None:
        return list(seeds)
    selected = list(video_seeds)
    unknown = sorted(set(selected) - set(seeds))
    if unknown:
        raise ValueError(f"video seeds {unknown} were not part of this evaluation")
    return selected


def _dependency_versions() -> tuple[str | None, str | None]:
    try:
        import gymnasium
    except ImportError:
        return None, None
    box2d_version = None
    try:
        import Box2D

        box2d_version = str(getattr(Box2D, "__version__", "installed"))
    except ImportError:
        box2d_version = None
    return str(gymnasium.__version__), box2d_version
