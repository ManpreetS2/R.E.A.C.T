"""Draw genuine ApolloLander frames at 1920×1080 and encode 60 FPS video."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def write_flight_video(
    path: Path,
    terrain: list[dict[str, float]],
    frames: list[dict],
    *,
    hud: dict[str, str],
) -> None:
    if not frames:
        raise ValueError("cannot record a flight with no frames")
    path.parent.mkdir(parents=True, exist_ok=True)
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    process = subprocess.Popen(
        [
            ffmpeg,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            "1920x1080",
            "-r",
            "60",
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            str(path),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    background = None
    background_key = None
    try:
        for frame in frames:
            key = tuple(frame["camera"][name] for name in ("left", "top", "width", "height"))
            if background is None or key != background_key:
                background = _background(terrain, frame)
                background_key = key
            image = background.copy()
            _draw_ship(image, frame, hud)
            process.stdin.write(np.asarray(image, dtype=np.uint8).tobytes())
    finally:
        process.stdin.close()
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        code = process.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed while writing {path}: {stderr[-500:]}")


def _background(terrain: list[dict[str, float]], frame: dict) -> Image.Image:
    image = Image.new("RGB", (1920, 1080), (0, 0, 6))
    draw = ImageDraw.Draw(image)
    camera = frame["camera"]
    visible = _visible_terrain(terrain, camera)
    if len(visible) >= 2:
        draw.line(visible, fill=(240, 246, 255), width=2)
    zone = frame["zone"]
    draw.line(
        [
            _project(zone["x1"], zone["y"], camera),
            _project(zone["x2"], zone["y"], camera),
        ],
        fill=(214, 222, 122),
        width=5,
    )
    return image


def _draw_ship(image: Image.Image, frame: dict, hud: dict[str, str]) -> None:
    draw = ImageDraw.Draw(image)
    camera = frame["camera"]
    for polyline in frame["lander"]:
        points = [_project(point["x"], point["y"], camera) for point in polyline]
        if len(points) >= 2:
            draw.line(points, fill=(240, 246, 255), width=2)
    thrust = frame.get("thrust")
    if thrust:
        draw.line([_project(point["x"], point["y"], camera) for point in thrust], fill=(240, 246, 255), width=2)
    observation = frame["observation"]
    result = frame["result"]
    speed = (observation["vx"] ** 2 + observation["vy"] ** 2) ** 0.5
    mode = hud.get("mode", "FIXED MAP")
    lines = [
        f"APOLLO LANDER  {mode}",
        f"MODEL {hud.get('model', 'unspecified')}   REV {hud.get('revision', '-')}",
        f"ORIGIN {hud.get('origin', 'unspecified')}   SEED {hud.get('seed', '-')}",
        f"REWARD {result['reward']:.1f}   STATUS {result['status']}",
        f"SPEED {speed:.3f}   FUEL {observation['fuel']:.1f}",
    ]
    y = 36
    for line in lines:
        draw.text((48, y), line, fill=(240, 246, 255))
        y += 28


def _visible_terrain(terrain: list[dict[str, float]], camera: dict) -> list[tuple[float, float]]:
    left = camera["left"]
    right = camera["left"] + camera["width"]
    points: list[tuple[float, float]] = []
    for index, point in enumerate(terrain):
        previous = terrain[index - 1] if index else None
        next_point = terrain[index + 1] if index + 1 < len(terrain) else None
        near = left - 20 <= point["x"] <= right + 20
        if previous and previous["x"] < right and point["x"] > left:
            near = True
        if next_point and point["x"] < right and next_point["x"] > left:
            near = True
        if near:
            points.append(_project(point["x"], point["y"], camera))
    return points


def _project(x: float, y: float, camera: dict) -> tuple[float, float]:
    return (
        (x - camera["left"]) / camera["width"] * camera["screenWidth"],
        (y - camera["top"]) / camera["height"] * camera["screenHeight"],
    )
