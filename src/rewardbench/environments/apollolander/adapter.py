"""ApolloLander adapter.

Drives the vendored game's deterministic physics through Node. It does not
replace the Gymnasium LunarLander adapter and it does not execute model JavaScript.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rewardbench.environments.apollolander.recording import write_flight_video
from rewardbench.environments.apollolander.schema import (
    constant_action,
    controller_schema_document,
    guidance_action,
    normalize_controller,
    validate_controller,
)
from rewardbench.environments.lunarlander.seeds import validate_seed_split
from rewardbench.environments.protocol import adapter_error, load_contracts

ENVIRONMENT_ID = "ApolloLander"
CONTRACT_ENVIRONMENT_ID = "apollolander"
SESSION = Path(__file__).resolve().parents[4] / "frontend" / "apollolander" / "experiment" / "session.js"


class ApolloLanderAdapter:
    """One fixed map, explicit starts, and numerical rewards from the JS physics."""

    environment_id = ENVIRONMENT_ID

    def __init__(
        self,
        *,
        max_steps: int = 8000,
        locked_camera: bool = True,
        record_dir: str | Path | None = None,
        record_video: bool = False,
    ) -> None:
        self.max_steps = max_steps
        self.locked_camera = locked_camera
        self.record_dir = Path(record_dir) if record_dir is not None else None
        self.record_video = record_video

    def validate_controller(self, controller: Mapping[str, Any] | str):
        return validate_controller(controller)

    def close(self) -> None:
        return None

    def describe(self):
        """Runner-facing description. The id matches an experiment config exactly."""
        contracts = _contracts()
        return contracts.EnvironmentSpec(
            environment_id=CONTRACT_ENVIRONMENT_ID,
            display_name="ApolloLander",
            task_description=(
                "Land the Apollo lander upright on the single designated pad of one "
                "fixed lunar map. Every controlled trial starts at the same position, "
                "velocity, rotation, and fuel. Episode seeds name the trial and do not "
                "move the terrain, the pad, or the ship. Submit a controller object, "
                "not JavaScript."
            ),
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

        The seed is stored on the result. It does not resample the landscape
        or the landing zone.
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
        )
        elapsed = time.perf_counter() - started
        verified = episode.get("verified") or {}
        vertical_speed = verified.get("vy")
        metrics = {
            "fuel_used": float(episode["fuel_used"]),
            "fuel_remaining": float(episode["fuel_remaining"]),
            "in_landing_zone": 1.0 if episode["in_landing_zone"] else 0.0,
            "physics_seconds": episode["steps"] / 60.0,
            "seed_affects_physics": 0.0,
        }
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
        checked_start = _checked_start(start)
        status = validate_controller(controller)
        if not status.valid:
            return {
                "environment_id": self.environment_id,
                "revision": revision,
                "origin": origin,
                "autonomous_learning": False,
                "controller_valid": False,
                "invalid_reason": status.reason,
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
        for seed in seeds:
            episode = self._run_episode(
                normalized,
                seed=seed,
                revision=revision,
                max_steps=max_steps or self.max_steps,
                start=checked_start,
                record=seed in selected,
                output=output,
                model=model,
            )
            if episode.get("video_path"):
                video_paths.append(episode["video_path"])
            episodes.append(episode)
        rewards = [episode["reward"] for episode in episodes]
        return {
            "environment_id": self.environment_id,
            "revision": revision,
            "origin": origin,
            "autonomous_learning": False,
            "controller_valid": True,
            "invalid_reason": None,
            "policy": normalized["policy"],
            "split": split,
            "mean_reward": sum(rewards) / len(rewards),
            "landing_count": sum(1 for episode in episodes if episode["landed"]),
            "crash_count": sum(1 for episode in episodes if episode["crashed"]),
        "video_paths": video_paths,
        "seed_affects_physics": False,
        "episodes": episodes,
    }

    def replay(self, trace: Sequence[Mapping[str, Any]], *, max_steps: int | None = None) -> dict[str, Any]:
        """Replay an explicit action trace through the same physics process."""
        session = _Session(SESSION)
        try:
            return session.request(
                {
                    "cmd": "replay",
                    "trace": list(trace),
                    "config": {
                        "maxSteps": max_steps or self.max_steps,
                        "lockedCamera": self.locked_camera,
                        "bonuses": False,
                    },
                }
            )["replay"]
        finally:
            session.close()

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
    ) -> dict[str, Any]:
        if shutil.which("node") is None:
            raise RuntimeError("ApolloLander requires Node.js to run the vendored physics")
        session = _Session(SESSION)
        try:
            opened = session.request(
                {
                    "cmd": "reset",
                    "config": {
                        "maxSteps": max_steps,
                        "lockedCamera": self.locked_camera,
                        "bonuses": False,
                        **({} if start is None else {"start": dict(start)}),
                    },
                }
            )
            terrain = opened["map"]["points"]
            zone = opened["map"]["zone"]
            frames: list[dict] = []
            fuel_penalty = 0.0
            terminal = 0.0
            observation = opened["observation"]
            result = None
            if record:
                frames.append(_frame(session, observation, session.request({"cmd": "result"})["result"]))
            for _ in range(max_steps):
                action = _action(controller, observation)
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
        if record and output is not None:
            video_path = output / f"apollo-{_slug(model)}-revision-{revision}-seed-{seed}.mp4"
            write_flight_video(
                video_path,
                terrain,
                frames,
                hud={"model": model, "revision": "-" if revision is None else str(revision)},
            )
            video_path = str(video_path)
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
            "identical_start": True,
        }


def _contracts():
    return load_contracts()


def _contracts():
    return load_contracts()


def _checked_start(start: Mapping[str, float] | None) -> dict[str, float] | None:
    if start is None:
        return None
    allowed = {"x", "y", "vx", "vy", "rotation", "fuel", "scale"}
    extra = sorted(set(start) - allowed)
    if extra:
        raise ValueError(f"unknown start field {extra[0]!r}")
    missing = sorted(allowed - set(start))
    if missing:
        raise ValueError(f"missing start field {missing[0]!r}")
    parsed: dict[str, float] = {}
    for key in allowed:
        value = start[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"start.{key} must be a finite number")
        number = float(value)
        if number != number or number in {float("inf"), float("-inf")}:
            raise ValueError(f"start.{key} must be a finite number")
        parsed[key] = number
    return parsed


def _frame(session: _Session, observation: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    geometry = session.request({"cmd": "geometry"})
    return {
        "camera": geometry["frame"]["camera"],
        "lander": geometry["frame"]["lander"],
        "thrust": geometry["frame"]["thrust"],
        "zone": geometry["frame"]["zone"],
        "observation": dict(observation),
        "result": dict(result),
    }


def _slug(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_" else "-" for character in value)
    return cleaned or "flight"


def _action(controller: dict[str, Any], observation: Mapping[str, float]) -> dict[str, float | int]:
    if controller["policy"] == "guidance":
        return guidance_action(observation, controller["parameters"])
    return constant_action(controller)
    if controller["policy"] == "guidance":
        return guidance_action(observation, controller["parameters"])
    return constant_action(controller)
    if controller["policy"] == "guidance":
        return guidance_action(observation, controller["parameters"])
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
