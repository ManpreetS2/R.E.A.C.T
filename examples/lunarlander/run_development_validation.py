"""Score reference and random baselines on additional development seeds.

Seeds 0-7 were used for the first recorded baseline. This script uses the next
30 development seeds and does not touch the held-out range.

It also records three demonstration videos. The weak and thrust-biased
controllers are hand-specified. They are not language-model revisions.

    PYTHONPATH=src python examples/lunarlander/run_development_validation.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.lunarlander import (  # noqa: E402
    HELD_OUT_SEED_START,
    LunarLanderAdapter,
    controller_schema_document,
    development_seeds,
    evaluate_revision,
    imperfect_heuristic_controller,
    random_controller,
    reference_controller,
    thrust_biased_controller,
)

ADDITIONAL_START = 8
ADDITIONAL_COUNT = 30


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "output")
    parser.add_argument("--video", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()

    seeds = development_seeds(ADDITIONAL_COUNT, start=ADDITIONAL_START)
    if any(seed >= HELD_OUT_SEED_START or seed < ADDITIONAL_START for seed in seeds):
        raise RuntimeError("validation seeds left the additional development range")

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    adapter = LunarLanderAdapter()
    study = []
    for name, controller, origin in (
        ("reference", reference_controller(), "benchmark"),
        ("random", random_controller(0), "random_baseline"),
    ):
        result = evaluate_revision(
            adapter,
            controller,
            seeds,
            revision=1,
            origin=origin,
            split="development",
        )
        study.append({"name": name, **result.to_dict()})
        _print_study(name, result)

    demonstrations = []
    demo_specs = (
        ("random_crash", random_controller(0), [0], 1, "random_baseline"),
        ("weak_failure", imperfect_heuristic_controller(), [ADDITIONAL_START], 1, "hand_specified_demonstration"),
        ("revised_behavior", thrust_biased_controller(), [ADDITIONAL_START], 2, "hand_specified_demonstration"),
    )
    for name, controller, demo_seeds, revision, origin in demo_specs:
        result = evaluate_revision(
            adapter,
            controller,
            demo_seeds,
            revision=revision,
            origin=origin,
            split="development",
            record_dir=output / "demonstrations" / name,
            record_video=bool(args.video),
            video_seeds=demo_seeds,
        )
        demonstrations.append({"name": name, **result.to_dict()})
        _print_study(name, result)

    document = {
        "development_seeds": seeds,
        "held_out_seeds_used": False,
        "note": (
            "Reference and random rows are baselines. "
            "weak_failure and revised_behavior are hand-specified controller payloads "
            "used to exercise revisions. They are not autonomous LLM learning."
        ),
        "controller_schema": controller_schema_document(),
        "baselines": study,
        "demonstrations": demonstrations,
    }
    path = output / "development_validation.json"
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def _print_study(name: str, result) -> None:
    evaluation = result.evaluation
    print(
        f"{name}: origin={result.origin} revision={result.revision} "
        f"mean_reward={_fmt(evaluation.mean_reward)} "
        f"reward_std={_fmt(evaluation.reward_std)} "
        f"landing_rate={_fmt(evaluation.landing_rate)} "
        f"categories={evaluation.category_counts}"
    )
    for error in evaluation.video_errors:
        print(f"  video error: {error}")
    for video in evaluation.video_paths:
        print(f"  video: {video}")


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


if __name__ == "__main__":
    main()
