"""Run the LunarLander reference heuristic and the random-policy baseline.

Scores use Gymnasium's returned reward. A landing is reported only when the
physics snapshot says the craft settled inside the viewport without hull contact.

From the repository root, with the project virtualenv activated:

    PYTHONPATH=src python examples/lunarlander/run_baselines.py --episodes 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.lunarlander import (  # noqa: E402
    LunarLanderAdapter,
    controller_schema_document,
    development_seeds,
    random_controller,
    reference_controller,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=8, help="development flights per controller")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="directory for scores, replays, and one reference video",
    )
    parser.add_argument("--video", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    seeds = development_seeds(args.episodes)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / "controller_schema.json").write_text(
        json.dumps(controller_schema_document(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    adapter = LunarLanderAdapter()
    controllers = (
        ("reference", reference_controller(), 0),
        ("random", random_controller(0), 1),
    )
    summaries = []
    for name, controller, revision in controllers:
        record_video = bool(args.video and name == "reference")
        evaluation = adapter.evaluate(
            controller,
            seeds,
            revision=revision,
            split="development",
            record_dir=output / name,
            record_video=record_video,
            video_seeds=[seeds[0]] if record_video else None,
        )
        payload = {"name": name, **evaluation.to_dict()}
        summaries.append(payload)
        _print_summary(name, evaluation)

    results_path = output / "baseline_results.json"
    results_path.write_text(json.dumps(summaries, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {results_path}")


def _print_summary(name: str, evaluation) -> None:
    print(
        f"{name}: valid={evaluation.controller_valid} "
        f"mean_reward={_fmt(evaluation.mean_reward)} "
        f"landings={evaluation.landing_count}/{len(evaluation.executed_episodes)} "
        f"crashes={evaluation.crash_count} "
        f"mean_fuel={_fmt(evaluation.mean_fuel_penalty)} "
        f"mean_duration_s={_fmt(evaluation.mean_duration_seconds)}"
    )
    for episode in evaluation.episodes:
        print(
            f"  seed={episode.seed} reward={_fmt(episode.reward)} "
            f"outcome={episode.outcome} steps={episode.steps} "
            f"fuel={episode.fuel_penalty:.2f} "
            f"landed={episode.landed} crashed={episode.crashed}"
        )
    for error in evaluation.video_errors:
        print(f"  video error: {error}")
    for path in evaluation.video_paths:
        print(f"  video: {path}")


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


if __name__ == "__main__":
    main()
