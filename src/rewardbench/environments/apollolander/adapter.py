"""ApolloLander adapter.

Drives the vendored game's deterministic physics through Node. It does not
replace the Gymnasium LunarLander adapter and it does not execute model JavaScript.

Two modes:

* **Demonstration / fixed-start (default).** Every seed uses the original
  spawn. Episode seeds name matched trials only.
* **Research mode (opt-in).** Initial conditions are derived from the episode
  seed via ``apollolander.starts`` while the terrain, pad, and verifier stay
  fixed. Development and held-out seed pools induce disjoint start schedules.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rewardbench.environments.apollolander.flight_record import (
    ENVIRONMENT_VERSION,
    REPLAY_REWARD_ABS_TOL,
    REPLAY_STATE_ABS_TOL,
    autonomous_learning_claimed,
    build_flight_record,
    compare_observations,
    compare_terminal,
    controller_hash,
    flight_record_stem,
    load_flight_record,
    trace_hash,
    write_flight_record,
)
from rewardbench.environments.apollolander.recording import write_flight_video
from rewardbench.environments.apollolander.schema import (
    constant_action,
    controller_schema_document,
    guidance_action,
    normalize_controller,
    random_action,
    validate_controller,
)
from rewardbench.environments.apollolander.starts import (
    START_SCHEDULE_VERSION,
    checked_start,
    derive_start,
    schedule_document,
    standard_start,
)
from rewardbench.environments.lunarlander.seeds import validate_seed_split
from rewardbench.environments.protocol import adapter_error, load_contracts

ENVIRONMENT_ID = "ApolloLander"
CONTRACT_ENVIRONMENT_ID = "apollolander"
SESSION = Path(__file__).resolve().parents[4] / "frontend" / "apollolander" / "experiment" / "session.js"


class ApolloLanderAdapter:
    """Fixed lunar map with optional seed-derived research starts."""

    environment_id = ENVIRONMENT_ID
    environment_version = ENVIRONMENT_VERSION

    def __init__(
        self,
        *,
        max_steps: int = 8000,
        locked_camera: bool = True,
        record_dir: str | Path | None = None,
        record_video: bool = False,
        research_mode: bool = False,
        start_schedule_version: str = START_SCHEDULE_VERSION,
        vary_fuel: bool = False,
        experiment_id: str | None = None,
        split: str | None = None,
        origin: str = "unspecified",
    ) -> None:
        self.max_steps = max_steps
        self.locked_camera = locked_camera
        self.record_dir = Path(record_dir) if record_dir is not None else None
        self.record_video = record_video
        self.research_mode = bool(research_mode)
        self.start_schedule_version = start_schedule_version
        self.vary_fuel = bool(vary_fuel)
        self.experiment_id = experiment_id
        self.split = split
        self.origin = origin
        # Validate the schedule version at construction time.
        schedule_document(self.start_schedule_version)

    def validate_controller(self, controller: Mapping[str, Any] | str):
        return validate_controller(controller)

    def close(self) -> None:
        return None

    def describe(self):
        """Runner-facing description. The id matches an experiment config exactly."""
        contracts = _contracts()
        if self.research_mode:
            task = (
                "Land the Apollo lander upright on the single designated pad of one "
                "fixed lunar map. Research mode varies starting position, altitude, "
                f"velocities, rotation, and optionally fuel from schedule "
                f"{self.start_schedule_version}. Terrain and pad stay fixed. The same "
                "episode seed always yields the same start so models can be compared "
                "fairly. Submit a controller object, not JavaScript."
            )
        else:
            task = (
                "Land the Apollo lander upright on the single designated pad of one "
                "fixed lunar map. Every controlled trial starts at the same position, "
                "velocity, rotation, and fuel. Episode seeds name the trial and do not "
                "move the terrain, the pad, or the ship. Submit a controller object, "
                "not JavaScript."
            )
        return contracts.EnvironmentSpec(
            environment_id=CONTRACT_ENVIRONMENT_ID,
            display_name="ApolloLander",
            task_description=task,
            controller_schema=controller_schema_document(),
            action_space_summary="thrust from 0 to 1 and rotation in 10 degree steps from -90 to 90",
            observation_space_summary=(
                "x, y, vx, vy, rotation, fuel, altitude, and horizontal offset from the pad center"
            ),
        )

    def validate_policy(self, parameters: Mapping[str, Any]):
        """Reject a bad controller before any physics step."""
        contracts = _contracts()
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
        """Run one fixed-map flight and return the shared episode record.

        In demonstration mode the seed is stored only. In research mode it also
        selects the starting state from the versioned schedule.
        """
        import time

        contracts = _contracts()
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
        episode = self._run_episode(
            normalize_controller(dict(policy.parameters)),
            seed=seed,
            revision=revision_index,
            max_steps=max_steps or self.max_steps,
            start=None,
            record=self.record_video and self.record_dir is not None,
            output=self.record_dir,
            model=getattr(policy, "model_id", None) or "unspecified",
            episode_index=episode_index,
            split=self.split,
            origin=self.origin,
        )
        elapsed = time.perf_counter() - started
        verified = episode.get("verified") or {}
        vertical_speed = verified.get("vy")
        metrics = {
            "fuel_used": float(episode["fuel_used"]),
            "fuel_remaining": float(episode["fuel_remaining"]),
            "in_landing_zone": 1.0 if episode["in_landing_zone"] else 0.0,
            "physics_seconds": episode["steps"] / 60.0,
            "seed_affects_physics": 1.0 if self.research_mode else 0.0,
            "research_mode": 1.0 if self.research_mode else 0.0,
        }
        start = episode.get("start") or {}
        for key in ("x", "y", "vx", "vy", "rotation", "fuel"):
            if isinstance(start.get(key), (int, float)) and not isinstance(start.get(key), bool):
                metrics[f"start_{key}"] = float(start[key])
        if isinstance(vertical_speed, (int, float)) and not isinstance(vertical_speed, bool):
            metrics["vertical_speed"] = float(vertical_speed)
        zone = episode.get("zone") or {}
        for key, metric_name in (("x1", "zone_x1"), ("x2", "zone_x2"), ("y", "zone_y"), ("width", "zone_width")):
            if isinstance(zone.get(key), (int, float)) and not isinstance(zone.get(key), bool):
                metrics[metric_name] = float(zone[key])
        return contracts.EpisodeResult(
            revision_index=revision_index,
            episode_index=episode_index,
            seed=seed,
            total_reward=float(episode["reward"]),
            success=bool(episode["landed"]),
            crashed=bool(episode["crashed"]),
            steps=int(episode["steps"]),
            terminated=not bool(episode["timed_out"]),
            truncated=bool(episode["timed_out"]),
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
        split: str = "development",
        record_dir: str | Path | None = None,
        record_video: bool = False,
        video_seeds: Sequence[int] | None = None,
        max_steps: int | None = None,
        start: Mapping[str, float] | None = None,
        origin: str = "unspecified",
        model: str = "unspecified",
    ) -> dict[str, Any]:
        validate_seed_split(seeds, split)
        if revision is not None and revision < 1:
            raise ValueError("controller revision must start at 1")
        if self.research_mode and start is not None:
            raise ValueError(
                "research mode derives starts from episode seeds; omit the explicit start "
                "override or construct the adapter with research_mode=False"
            )
        checked = checked_start(start)
        learning = autonomous_learning_claimed(origin)
        status = validate_controller(controller)
        if not status.valid:
            return {
                "environment_id": self.environment_id,
                "environment_version": ENVIRONMENT_VERSION,
                "revision": revision,
                "origin": origin,
                "autonomous_learning": learning,
                "controller_valid": False,
                "invalid_reason": status.reason,
                "research_mode": self.research_mode,
                "start_schedule_version": self.start_schedule_version if self.research_mode else None,
                "episodes": [
                    {"seed": seed, "executed": False, "landed": False, "crashed": False, "reward": None}
                    for seed in seeds
                ],
            }
        normalized = normalize_controller(controller)
        output = Path(record_dir) if record_dir is not None else None
        selected = list(seeds if video_seeds is None else video_seeds) if record_video else []
        unknown = sorted(set(selected) - set(seeds))
        if unknown:
            raise ValueError(f"video seeds {unknown} were not part of this evaluation")
        episodes = []
        video_paths: list[str] = []
        flight_record_paths: list[str] = []
        for seed in seeds:
            episode = self._run_episode(
                normalized,
                seed=seed,
                revision=revision,
                max_steps=max_steps or self.max_steps,
                start=checked,
                record=seed in selected,
                output=output,
                model=model,
                origin=origin,
                split=split,
            )
            if episode.get("video_path"):
                video_paths.append(episode["video_path"])
            if episode.get("flight_record_path"):
                flight_record_paths.append(episode["flight_record_path"])
            episodes.append(episode)
        rewards = [episode["reward"] for episode in episodes]
        return {
            "environment_id": self.environment_id,
            "environment_version": ENVIRONMENT_VERSION,
            "revision": revision,
            "origin": origin,
            "autonomous_learning": learning,
            "controller_valid": True,
            "invalid_reason": None,
            "policy": normalized["policy"],
            "split": split,
            "mean_reward": sum(rewards) / len(rewards),
            "landing_count": sum(1 for episode in episodes if episode["landed"]),
            "crash_count": sum(1 for episode in episodes if episode["crashed"]),
            "video_paths": video_paths,
            "flight_record_paths": flight_record_paths,
            "seed_affects_physics": self.research_mode,
            "research_mode": self.research_mode,
            "start_schedule_version": self.start_schedule_version if self.research_mode else None,
            "start_schedule": schedule_document(self.start_schedule_version) if self.research_mode else None,
            "episodes": episodes,
        }

    def replay(
        self,
        trace: Sequence[Mapping[str, Any]],
        *,
        max_steps: int | None = None,
        seed: int | None = None,
        start: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        """Replay an explicit action trace through the same physics process."""
        resolved = self._resolve_start(seed=seed, start=start)
        applied = resolved if resolved is not None else standard_start().as_dict()
        session = _Session(SESSION)
        try:
            replayed = session.request(
                {
                    "cmd": "replay",
                    "trace": list(trace),
                    "config": {
                        "maxSteps": max_steps or self.max_steps,
                        "lockedCamera": self.locked_camera,
                        "bonuses": False,
                        **({} if resolved is None else {"start": resolved}),
                    },
                }
            )["replay"]
        finally:
            session.close()
        replayed["start"] = applied
        replayed["seed"] = seed
        return replayed

    def verify_flight_record(
        self,
        record: Mapping[str, Any] | str | Path,
        *,
        reward_tol: float = REPLAY_REWARD_ABS_TOL,
        state_tol: float = REPLAY_STATE_ABS_TOL,
    ) -> dict[str, Any]:
        """Replay a saved manifest and report whether the outcome matches."""
        if isinstance(record, (str, Path)):
            payload = load_flight_record(record)
        else:
            payload = dict(record)
        if payload.get("environment_version") != self.environment_version:
            raise ValueError("flight record environment version does not match this adapter")
        if payload.get("research_mode") and not self.research_mode:
            raise ValueError("flight record requires research_mode=True on this adapter")
        if (not payload.get("research_mode")) and self.research_mode:
            raise ValueError("flight record is fixed-start; construct adapter with research_mode=False")
        if payload.get("research_mode"):
            if bool(payload.get("vary_fuel")) != self.vary_fuel:
                raise ValueError("flight record vary_fuel does not match this adapter")
            version = payload.get("start_schedule_version")
            if version != self.start_schedule_version:
                raise ValueError(
                    f"start schedule {version!r} does not match adapter {self.start_schedule_version!r}"
                )
        structural = _structural_problems(payload)
        if structural:
            return _rejected(payload, structural, reward_tol, state_tol)
        seed = int(payload["episode_seed"])
        trace = list(payload["trace"])
        # maxSteps must match the original episode so timeouts fire on the same step.
        original_max = int(payload.get("max_steps") or payload["terminal"]["steps"])
        try:
            replayed = self.replay(
                trace,
                seed=seed if payload.get("research_mode") else None,
                start=None if payload.get("research_mode") else payload["initial_state"],
                max_steps=original_max,
            )
        except RuntimeError as exc:  # the physics refused an action in the recorded trace
            return _rejected(payload, [f"physics rejected the recorded trace: {exc}"], reward_tol, state_tol)
        expected_terminal = {
            "status": payload["terminal"]["status"],
            "reward": payload["terminal"]["reward"],
            "landed": payload["terminal"]["landed"],
            "crashed": payload["terminal"]["crashed"],
            "in_landing_zone": payload["terminal"]["in_landing_zone"],
            "timed_out": payload["terminal"]["timed_out"],
            "steps": payload["terminal"]["steps"],
        }
        observed_result = replayed["result"]
        observed_terminal = {
            "status": observed_result["status"],
            "reward": observed_result["reward"],
            "landed": observed_result["landed"],
            "crashed": observed_result["crashed"],
            "in_landing_zone": observed_result["inLandingZone"],
            "timed_out": observed_result["timedOut"],
            "steps": observed_result["steps"],
        }
        mismatches = compare_terminal(expected_terminal, observed_terminal, reward_tol=reward_tol)
        for recorded_key, replayed_key in (("fuel_used", "fuelUsed"), ("fuel_remaining", "fuelRemaining")):
            recorded_value = payload["terminal"].get(recorded_key)
            if recorded_value is not None and not (
                abs(float(recorded_value) - float(observed_result[replayed_key])) <= state_tol
            ):
                mismatches.append(
                    f"terminal.{recorded_key}: recorded {recorded_value}, replay {observed_result[replayed_key]}"
                )
        if payload.get("trace_hash") != trace_hash(trace):
            mismatches.append("trace_hash does not match the recorded actions")
        if payload.get("controller_hash") != controller_hash(payload["controller"]):
            mismatches.append("controller_hash does not match the recorded controller")
        if payload.get("trace_length") != len(trace):
            mismatches.append("trace_length does not match the recorded actions")
        # The declared length and hash only describe the array itself, so a re-sealed
        # edit passes them. Compare with what the physics actually consumed.
        consumed = len(replayed["frames"])
        if len(trace) > consumed and observed_result.get("status") != "flying":
            mismatches.append(
                f"{len(trace) - consumed} trailing action(s) after the simulation terminated at step {consumed}"
            )
        elif consumed == len(trace) and observed_result.get("status") == "flying":
            mismatches.append(
                f"truncated trace: {len(trace)} actions end before the simulation terminates "
                f"(recorded terminal status {payload['terminal']['status']!r})"
            )
        if payload["terminal"].get("steps") != len(trace):
            mismatches.append(
                f"terminal.steps {payload['terminal'].get('steps')} is inconsistent with "
                f"{len(trace)} recorded actions"
            )
        if replayed["frames"]:
            mismatches.extend(
                compare_observations(
                    payload["initial_state"],
                    {"x": replayed["start"]["x"], "y": replayed["start"]["y"], "vx": replayed["start"]["vx"],
                     "vy": replayed["start"]["vy"], "rotation": replayed["start"]["rotation"],
                     "fuel": replayed["start"]["fuel"]},
                    abs_tol=state_tol,
                )
            )
        return {
            "matched": not mismatches,
            "mismatches": mismatches,
            "trace_hash": payload.get("trace_hash"),
            "replay_result": observed_terminal,
            "expected_result": expected_terminal,
            "reward_tol": reward_tol,
            "state_tol": state_tol,
        }

    def start_for_seed(self, seed: int) -> dict[str, float]:
        """Public helper for Agent 1 and tests: the start this adapter would use."""
        if not self.research_mode:
            return standard_start().as_dict()
        return derive_start(
            seed,
            version=self.start_schedule_version,
            vary_fuel=self.vary_fuel,
        ).as_dict()

    def _resolve_start(
        self,
        *,
        seed: int | None,
        start: Mapping[str, float] | None,
    ) -> dict[str, float] | None:
        if start is not None:
            if self.research_mode:
                raise ValueError(
                    "research mode derives starts from episode seeds; omit the explicit start override"
                )
            return checked_start(start)
        if self.research_mode:
            if seed is None:
                raise ValueError("research mode requires an episode seed to derive the start")
            return derive_start(
                seed,
                version=self.start_schedule_version,
                vary_fuel=self.vary_fuel,
            ).as_dict()
        return None

    def _run_episode(
        self,
        controller: dict[str, Any],
        *,
        seed: int,
        revision: int | None,
        max_steps: int,
        start: Mapping[str, float] | None,
        record: bool,
        output: Path | None,
        model: str,
        origin: str = "unspecified",
        split: str | None = None,
        episode_index: int | None = None,
    ) -> dict[str, Any]:
        if shutil.which("node") is None:
            raise RuntimeError("ApolloLander requires Node.js to run the vendored physics")
        resolved = self._resolve_start(seed=seed, start=start)
        applied_start = resolved if resolved is not None else standard_start().as_dict()
        session = _Session(SESSION)
        try:
            opened = session.request(
                {
                    "cmd": "reset",
                    "config": {
                        "maxSteps": max_steps,
                        "lockedCamera": self.locked_camera,
                        "bonuses": False,
                        **({} if resolved is None else {"start": dict(resolved)}),
                    },
                }
            )
            terrain = opened["map"]["points"]
            zone = opened["map"]["zone"]
            frames: list[dict] = []
            trace: list[dict[str, float | int]] = []
            fuel_penalty = 0.0
            terminal = 0.0
            observation = opened["observation"]
            result = None
            if record:
                frames.append(_frame(session, observation, session.request({"cmd": "result"})["result"]))
            for _ in range(max_steps):
                action = _action(controller, observation, episode_seed=seed)
                trace.append({"thrust": float(action["thrust"]), "rotation": int(action["rotation"])})
                stepped = session.request({"cmd": "step", "action": action})
                if not stepped.get("ok", False):
                    raise RuntimeError(stepped.get("error", "physics step failed"))
                fuel_penalty += float(stepped["step"]["breakdown"]["fuelPenalty"])
                terminal += float(stepped["step"]["breakdown"]["terminal"])
                observation = stepped["observation"]
                result = stepped["result"]
                if record:
                    frames.append(_frame(session, observation, result))
                if result["done"]:
                    break
            if result is None:
                raise RuntimeError("episode produced no physics result")
        finally:
            session.close()

        video_path = None
        flight_record_path = None
        stem = flight_record_stem(model, revision, episode_index, seed)
        if record and output is not None:
            video_file = output / f"{stem}.mp4"
            write_flight_video(
                video_file,
                terrain,
                frames,
                hud={
                    "model": model,
                    "revision": "-" if revision is None else str(revision),
                    "origin": origin,
                    "seed": str(seed),
                    "mode": "RESEARCH" if self.research_mode else "FIXED MAP",
                },
            )
            video_path = str(video_file)

        flight = build_flight_record(
            environment_id=self.environment_id,
            environment_version=ENVIRONMENT_VERSION,
            research_mode=self.research_mode,
            start_schedule_version=self.start_schedule_version if self.research_mode else None,
            vary_fuel=self.vary_fuel,
            seed=seed,
            start=applied_start,
            controller=controller,
            revision=revision,
            origin=origin,
            model=model,
            split=split,
            max_steps=max_steps,
            result=result,
            zone=zone,
            trace=trace,
            fuel_penalty=fuel_penalty,
            terminal_reward=terminal,
            video_path=video_path,
            experiment_id=self.experiment_id,
            episode_index=episode_index,
        )
        # Flight manifests are written whenever an output directory is set.
        # Video frames remain opt-in via record_video to avoid long HD captures.
        if output is not None:
            record_file = output / f"{stem}.flight.json"
            write_flight_record(record_file, flight)
            flight_record_path = str(record_file)
            flight = {**flight, "flight_record_path": flight_record_path}

        return {
            "seed": seed,
            "executed": True,
            "reward": result["reward"],
            "status": result["status"],
            "landed": result["landed"],
            "crashed": result["crashed"],
            "in_landing_zone": result["inLandingZone"],
            "timed_out": result["timedOut"],
            "steps": result["steps"],
            "fuel_used": result["fuelUsed"],
            "fuel_remaining": result["fuelRemaining"],
            "verified": result["verified"],
            "zone": zone,
            "fuel_penalty": fuel_penalty,
            "terminal_reward": terminal,
            "video_path": video_path,
            "flight_record_path": flight_record_path,
            "flight_record": flight,
            "trace": trace,
            "trace_hash": flight["trace_hash"],
            "controller_hash": flight["controller_hash"],
            "environment_version": ENVIRONMENT_VERSION,
            "origin": origin,
            "model": model,
            "revision": revision,
            "start": applied_start,
            "identical_start": not self.research_mode and start is None,
            "seed_affects_physics": self.research_mode,
            "autonomous_learning": autonomous_learning_claimed(origin),
        }


def _contracts():
    return load_contracts()


def _frame(session: "_Session", observation: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    geometry = session.request({"cmd": "geometry"})
    return {
        "camera": geometry["frame"]["camera"],
        "lander": geometry["frame"]["lander"],
        "thrust": geometry["frame"]["thrust"],
        "zone": geometry["frame"]["zone"],
        "observation": dict(observation),
        "result": dict(result),
    }


def _action(
    controller: dict[str, Any],
    observation: Mapping[str, float],
    *,
    episode_seed: int = 0,
) -> dict[str, float | int]:
    if controller["policy"] == "guidance":
        return guidance_action(observation, controller["parameters"])
    if controller["policy"] == "random":
        return random_action(
            observation,
            controller_seed=int(controller["seed"]),
            episode_seed=episode_seed,
        )
    return constant_action(controller)


class _Session:
    def __init__(self, script: Path) -> None:
        self.process = subprocess.Popen(
            ["node", str(script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def request(self, message: Mapping[str, Any]) -> dict[str, Any]:
        assert self.process.stdin is not None
        assert self.process.stdout is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            error = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"ApolloLander physics process ended: {error}")
        payload = json.loads(line)
        if not payload.get("ok", False):
            raise RuntimeError(payload.get("error", "physics command failed"))
        return payload

    def close(self) -> None:
        if self.process.poll() is None:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()


_REQUIRED_RECORD_FIELDS = ("trace", "terminal", "initial_state", "episode_seed", "controller")
_REQUIRED_TERMINAL_FIELDS = ("status", "reward", "landed", "crashed", "in_landing_zone", "timed_out", "steps")


def _structural_problems(payload: Mapping[str, Any]) -> list[str]:
    """Reasons a record cannot be replayed at all; reported instead of raised."""
    problems = [f"record is missing {key!r}" for key in _REQUIRED_RECORD_FIELDS if key not in payload]
    if problems:
        return problems
    if not isinstance(payload["trace"], list) or not all(isinstance(a, Mapping) for a in payload["trace"]):
        problems.append("trace must be a list of action objects")
    terminal = payload["terminal"]
    if not isinstance(terminal, Mapping):
        return problems + ["terminal must be an object"]
    problems += [f"terminal is missing {key!r}" for key in _REQUIRED_TERMINAL_FIELDS if key not in terminal]
    return problems


def _rejected(payload: Mapping[str, Any], reasons: list[str], reward_tol: float, state_tol: float) -> dict[str, Any]:
    return {
        "matched": False,
        "mismatches": list(reasons),
        "trace_hash": payload.get("trace_hash"),
        "replay_result": None,
        "expected_result": None,
        "reward_tol": reward_tol,
        "state_tol": state_tol,
    }
