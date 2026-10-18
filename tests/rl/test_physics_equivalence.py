"""Prove the Python physics port matches the original Node session.

Replays random-action trajectories across many seeds. Per-step state and
reward must match within the repo replay tolerance (1e-9); terminal outcomes
must be identical. If this test fails, training must use the Node path.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import pytest

from rewardbench.environments.apollolander.flight_record import (
    REPLAY_REWARD_ABS_TOL,
    REPLAY_STATE_ABS_TOL,
)
from rewardbench.environments.apollolander.starts import derive_start
from rewardbench.rl.physics_python import ApolloPhysicsPython, decode_action, load_landscape

ROOT = Path(__file__).resolve().parents[2]
SESSION = ROOT / "frontend" / "apollolander" / "experiment" / "session.js"
STATE_KEYS = ("x", "y", "vx", "vy", "rotation", "fuel", "altitude", "dx", "dy", "thrust")


class _NodeSession:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            ["node", str(SESSION)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ROOT),
        )

    def request(self, message: dict) -> dict:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            err = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"Node physics ended: {err}")
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


def _assert_close(a: float, b: float, tol: float, label: str) -> None:
    if not math.isfinite(a) or not math.isfinite(b) or abs(a - b) > tol:
        raise AssertionError(f"{label}: python={a!r} node={b!r} tol={tol}")


@pytest.mark.parametrize("seed", [0, 1, 7, 42, 99, 123, 999, 12345, 500_000, 999_999])
def test_python_matches_node_random_trajectory(seed: int) -> None:
    landscape = load_landscape()
    py = ApolloPhysicsPython(landscape)
    node = _NodeSession()
    try:
        start = derive_start(seed).as_dict()
        cfg = {"maxSteps": 8000, "lockedCamera": True, "bonuses": False, "start": start}
        py_obs = py.reset(cfg)
        node_opened = node.request({"cmd": "reset", "config": cfg})
        node_obs = node_opened["observation"]
        for key in STATE_KEYS:
            _assert_close(float(py_obs[key]), float(node_obs[key]), REPLAY_STATE_ABS_TOL, f"reset.{key}")

        # Deterministic pseudo-random actions from the seed (not a learned policy).
        rng_state = seed * 1_000_003 + 17
        for step_i in range(8000):
            rng_state = (1103515245 * rng_state + 12345) & 0x7FFFFFFF
            action = decode_action(rng_state % 95)
            py_step = py.step(action)
            node_stepped = node.request({"cmd": "step", "action": action})
            node_step = node_stepped["step"]
            node_obs = node_stepped["observation"]
            node_result = node_stepped["result"]
            py_obs = py.observe()
            py_result = py.get_result()

            _assert_close(
                float(py_step["reward"]),
                float(node_step["reward"]),
                REPLAY_REWARD_ABS_TOL,
                f"step{step_i}.reward",
            )
            for key in STATE_KEYS:
                _assert_close(
                    float(py_obs[key]),
                    float(node_obs[key]),
                    REPLAY_STATE_ABS_TOL,
                    f"step{step_i}.{key}",
                )
            assert py_result["status"] == node_result["status"]
            assert bool(py_result["landed"]) == bool(node_result["landed"])
            assert bool(py_result["crashed"]) == bool(node_result["crashed"])
            assert bool(py_result["timedOut"]) == bool(node_result["timedOut"])
            assert int(py_result["steps"]) == int(node_result["steps"])
            if node_result["done"]:
                _assert_close(
                    float(py_result["reward"]),
                    float(node_result["reward"]),
                    REPLAY_REWARD_ABS_TOL,
                    "terminal.reward",
                )
                break
        else:
            pytest.fail("trajectory ran to max_steps without terminating")
    finally:
        node.close()


def test_landscape_zone_matches_documented_pad() -> None:
    landscape = load_landscape()
    zone = landscape["zone"]
    assert abs(zone["x1"] - 6873.6) < 1e-9
    assert abs(zone["x2"] - 7052.8) < 1e-9
    assert zone["index"] >= 0
    designated = [line for line in landscape["lines"] if line.designated]
    assert len(designated) == 1
