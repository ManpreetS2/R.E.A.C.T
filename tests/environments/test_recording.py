"""Replay documents round-trip without starting Box2D."""

from __future__ import annotations

from rewardbench.environments.lunarlander.recording import read_replay, replay_document, write_replay


def test_replay_round_trip(tmp_path) -> None:
    document = replay_document(
        environment_id="LunarLander-v3",
        seed=4,
        revision=2,
        policy="heuristic",
        steps=[
            {
                "t": 0,
                "observation": [0.0] * 8,
                "action": 2,
                "action_name": "main_engine",
                "reward": -0.3,
                "terminated": False,
                "truncated": False,
            }
        ],
        result={"landed": False, "reward": -0.3},
    )
    path = tmp_path / "replay.json"
    write_replay(path, document)
    loaded = read_replay(path)
    assert loaded["seed"] == 4
    assert loaded["steps"][0]["action_name"] == "main_engine"
    assert loaded["result"]["landed"] is False
