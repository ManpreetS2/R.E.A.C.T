"""Score controller revision 1, 2, 3, ... without choosing the controller.

The reference heuristic is a benchmark the caller may pass in. This function
does not replace another payload with that benchmark. Provider clients and the
central experiment runner belong to other components.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rewardbench.environments.lunarlander.feedback import numerical_feedback
from rewardbench.environments.lunarlander.types import FlightEvaluation

REVISION_ORIGINS: tuple[str, ...] = (
    "benchmark",
    "random_baseline",
    "hand_specified_demonstration",
    "model_proposal",
)


@dataclass(frozen=True)
class ControllerRevisionResult:
    """One submitted controller and the flights scored for that revision."""

    revision: int
    origin: str
    controller: dict[str, Any]
    evaluation: FlightEvaluation
    feedback: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision": self.revision,
            "origin": self.origin,
            "autonomous_learning": False,
            "controller": self.controller,
            "feedback": self.feedback,
            "evaluation": self.evaluation.to_dict(),
        }


def evaluate_revision(
    adapter: Any,
    controller: Mapping[str, Any] | str,
    seeds: Sequence[int],
    *,
    revision: int,
    origin: str,
    split: str = "development",
    record_dir: str | Path | None = None,
    record_video: bool = False,
    video_seeds: Sequence[int] | None = None,
    max_steps: int | None = None,
) -> ControllerRevisionResult:
    """Evaluate exactly ``controller`` on ``seeds``.

    ``revision`` starts at 1. ``origin`` records who supplied the payload.
    ``autonomous_learning`` stays false here; a model client has to set that
    only after a real model produced the controller.
    """
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError("controller revision must be an integer starting at 1")
    if origin not in REVISION_ORIGINS:
        raise ValueError(
            f"revision origin {origin!r} is unknown; expected one of {', '.join(REVISION_ORIGINS)}"
        )
    if isinstance(controller, str):
        stored: dict[str, Any] = {"json": controller}
    else:
        stored = dict(controller)

    evaluation = adapter.evaluate(
        controller,
        seeds,
        revision=revision,
        split=split,
        record_dir=record_dir,
        record_video=record_video,
        video_seeds=video_seeds,
        max_steps=max_steps,
    )
    return ControllerRevisionResult(
        revision=revision,
        origin=origin,
        controller=stored,
        evaluation=evaluation,
        feedback=numerical_feedback(evaluation),
    )
