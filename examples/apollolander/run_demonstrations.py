"""Record hand-specified ApolloLander flights and compare them with Gymnasium.

The controllers in this script are written by hand. They are not language-model
revisions and they are not evidence of autonomous learning.
"""

from __future__ import annotations

import json
from pathlib import Path

from rewardbench.environments.apollolander import (
    ApolloLanderAdapter,
    constant_controller,
    demonstration_guidance_controller,
)

OUTPUT = Path(__file__).resolve().parent / "output"
GYM_REPORT = Path(__file__).resolve().parents[1] / "lunarlander" / "output" / "development_validation.json"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    adapter = ApolloLanderAdapter()
    guidance = adapter.evaluate(
        demonstration_guidance_controller(),
        [0],
        revision=1,
        origin="hand_specified_demonstration",
        model="hand-specified-guidance",
        record_dir=OUTPUT,
        record_video=True,
    )
    crash = adapter.evaluate(
        constant_controller(0, -90),
        [0],
        revision=1,
        origin="hand_specified_demonstration",
        model="constant-coast",
        record_dir=OUTPUT,
        record_video=True,
    )
    climb = adapter.evaluate(
        constant_controller(1, 0),
        [0],
        revision=2,
        origin="hand_specified_demonstration",
        model="constant-climb",
        record_dir=OUTPUT,
        record_video=True,
        max_steps=900,
    )
    higher = adapter.evaluate(
        demonstration_guidance_controller(),
        [1],
        revision=1,
        origin="hand_specified_demonstration",
        model="hand-specified-guidance",
        start={"x": 6963.2, "y": 80, "vx": 0.1, "vy": 0, "rotation": -90, "fuel": 1000, "scale": 0.25},
        max_steps=8000,
    )
    gym = json.loads(GYM_REPORT.read_text()) if GYM_REPORT.exists() else None
    report = {
        "note": "Apollo flights below are hand-specified demonstrations. autonomous_learning is false.",
        "apollo": {
            "guidance_landing": _brief(guidance),
            "constant_coast_crash": _brief(crash),
            "constant_climb": _brief(climb),
            "alternate_higher_start": _brief(higher),
        },
        "gymnasium_development_validation": _gym_brief(gym),
    }
    destination = OUTPUT / "apollo_comparison.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(destination)


def _brief(report: dict) -> dict:
    episode = report["episodes"][0]
    return {
        "origin": report["origin"],
        "autonomous_learning": report["autonomous_learning"],
        "status": episode["status"],
        "landed": episode["landed"],
        "crashed": episode["crashed"],
        "in_landing_zone": episode["in_landing_zone"],
        "reward": episode["reward"],
        "steps": episode["steps"],
        "fuel_used": episode["fuel_used"],
        "verified": episode["verified"],
        "video_path": episode["video_path"],
    }


def _gym_brief(report: dict | None) -> dict | None:
    if report is None:
        return None
    baselines = {item["name"]: item["evaluation"] for item in report["baselines"]}
    reference = baselines["reference"]
    random = baselines["random"]
    return {
        "environment": "LunarLander-v3",
        "seeds": "8-37 development",
        "reference_landing_rate": reference["landing_rate"],
        "reference_mean_reward": reference["mean_reward"],
        "reference_reward_std": reference["reward_std"],
        "reference_outside_zone": reference["category_counts"]["landed_outside_zone"],
        "random_landing_rate": random["landing_rate"],
        "random_mean_reward": random["mean_reward"],
        "random_reward_std": random["reward_std"],
        "random_physical_crashes": random["category_counts"]["physical_crash"],
        "random_viewport_exits": random["category_counts"]["viewport_exit"],
    }


if __name__ == "__main__":
    main()
