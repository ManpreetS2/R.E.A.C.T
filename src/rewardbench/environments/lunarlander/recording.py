"""JSON flight replays and optional mp4 recordings.

Scored episodes are recorded as JSON from the headless simulation. Video is a
separate rendering of selected seeds. Landing claims stay on the scored
episode record; a video file is not evidence of a landing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np


def write_replay(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_replay(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"replay {path} is not a JSON object")
    return payload


def write_video(path: Path, frames: Sequence[np.ndarray], fps: int) -> None:
    if fps < 1:
        raise ValueError("video fps must be positive")
    if len(frames) == 0:
        raise ValueError("cannot write a video with no frames")
    try:
        import imageio.v2 as imageio
    except ImportError as exc:
        raise RuntimeError(
            "video recording requires imageio and imageio-ffmpeg"
        ) from exc

    stacked = np.stack([np.asarray(frame, dtype=np.uint8) for frame in frames])
    path.parent.mkdir(parents=True, exist_ok=True)
    # 600x400 is not divisible by 16. Keep the simulator's pixels instead of letting
    # ffmpeg resize the frame.
    imageio.mimwrite(
        path,
        stacked,
        fps=fps,
        codec="libx264",
        quality=8,
        macro_block_size=1,
    )


def replay_document(
    *,
    environment_id: str,
    seed: int,
    revision: int | None,
    policy: str,
    steps: list[dict[str, Any]],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "environment_id": environment_id,
        "seed": seed,
        "revision": revision,
        "policy": policy,
        "controller_valid": True,
        "steps": steps,
        "result": dict(result),
    }
