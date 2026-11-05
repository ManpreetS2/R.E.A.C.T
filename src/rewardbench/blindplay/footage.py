"""Authentic demonstration footage: a video made by DETERMINISTIC REPLAY of a recorded session.

Nothing is synthesised. The recorded ``act`` requests are re-driven into a fresh ``Session`` (exactly as
``replay`` does) whose referee is a thin subclass that also captures the page image after every Nth
simulated frame. Rendering is refused unless

1. the standard ``replay.replay`` check on a temporary COPY of the session reports ``reproduced=True``, and
2. this module's own capture pass returns, for every observation, a screenshot whose SHA-256 equals the
   recorded one, and its referee ticks / episode outcomes equal the recorded ones.

Every frame carries a burned-in label (below the game image, never over it) built from the recorded
manifest and the trusted referee record (``session.json`` / ``episodes.jsonl``), never from pixels.

    python -m rewardbench.blindplay.footage <session_dir> --out <new_dir> [--every N] [--episode K]

The input session directory is only read. Output goes to the new ``--out`` directory (never overwritten).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from rewardbench.blindplay import referee as referee_mod, replay as replay_mod, serve, session as session_mod

SCHEMA = "react.blindplay.footage.v1"
BANNER = "REPLAY OF RECORDED SESSION"
FOOTER_HEIGHT = 80
FRAME_W, FRAME_H = referee_mod.VIEWPORT["width"], referee_mod.VIEWPORT["height"]


class FootageRefused(RuntimeError):
    """The footage could not be proven to show the recorded game; nothing was rendered."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------- capturing referee
class CapturingReferee(referee_mod.Referee):
    """Referee that records the page image every ``every`` ticks of an act (and of the post-terminal settle).

    ``run`` re-implements the base loop with identical key handling and the same per-tick JS, but runs the
    ticks in chunks and takes a screenshot between chunks. Screenshots never advance the virtual clock, so the
    simulation is unchanged; the verification pass proves this against the recorded hashes.
    """

    def __post_init__(self) -> None:
        super().__post_init__()
        self.every = 1
        self.captured: list[dict[str, Any]] = []
        self._capturing = True

    def reset(self) -> dict[str, Any]:
        self._capturing = False            # the pre-start title/attract frames are never part of the game record
        try:
            start = super().reset()
        finally:
            self._capturing = True
        self.captured.append({"kind": "episode_start", "png": self.screenshot(), "tick": start["tick"]})
        return start

    def run(self, keys, n, *, stop_on_terminal=True):  # type: ignore[no-untyped-def]
        if self.page is None:
            raise referee_mod.RefereeError("no episode")
        if not self._capturing:
            return super().run(keys, n, stop_on_terminal=stop_on_terminal)
        pressed: list[str] = []
        ticks: list[dict[str, Any]] = []
        try:
            for key in keys:
                self.page.keyboard.down(referee_mod.PLAYWRIGHT_KEYS[key])
                pressed.append(key)
            remaining = int(n)
            while remaining > 0:
                chunk = min(self.every, remaining)
                out = self.page.evaluate(referee_mod._RUN_JS, {"n": chunk, "stop": bool(stop_on_terminal)})
                ticks.extend(out)
                remaining -= len(out)
                self.captured.append({"kind": "tick", "png": self.screenshot(), "tick": out[-1]["tick"]})
                if len(out) < chunk:       # stopped on a terminal tick
                    break
            self.page_errors.extend(self.page.evaluate("() => window.__reactClock.takeErrors()"))
            return ticks
        finally:
            for key in reversed(pressed):
                self.page.keyboard.up(referee_mod.PLAYWRIGHT_KEYS[key])


# ---------------------------------------------------------------------------- verification + capture
def _capture_pass(original: Path, work: Path, every: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest = json.loads((original / "session.json").read_text(encoding="utf-8"))
    transcript = replay_mod._lines(original / "player_transcript.jsonl")
    budgets = manifest["budgets"]
    ref = CapturingReferee(seed=manifest["environment"]["seed"])
    ref.every = every
    frames: list[dict[str, Any]] = []
    mismatches: list[str] = []
    with session_mod.Session(work, seed=manifest["environment"]["seed"],
                             episode_frame_budget=budgets["episode_frame_budget"], max_episodes=budgets["max_episodes"],
                             max_requests=budgets["max_requests"], ref=ref,
                             player_label=f"footage capture of {original.name} (referee verification, not a player)",
                             player_is_ai=False, keyset=manifest["player_contract"]["keyset"]) as s:
        for i, entry in enumerate(transcript):
            if "raw_line_base64" in entry:
                raw = base64.b64decode(entry["raw_line_base64"])
                request, rejection = serve.decode_line(raw)
                if entry.get("raw_line_bytes", len(raw)) > len(raw):
                    rejection = f"request longer than {serve.MAX_LINE_BYTES} bytes"
                response = s.handle(request, raw_line=raw, rejection=rejection)
            else:
                response = s.handle(entry["request"])
            recorded = entry["response"]
            if "image" in recorded:
                got = response.get("image", {}).get("sha256")
                if got != recorded["image"]["sha256"]:
                    mismatches.append(f"request {i}: screenshot {got} != recorded {recorded['image']['sha256']}")
            for cap in ref.captured:
                cap["episode"] = s.episode
                frames.append(cap)
            ref.captured = []
        episodes_replayed = list(s.episodes)
    ref_a = replay_mod._strip(replay_mod._lines(original / "referee.jsonl"))
    ref_b = replay_mod._strip(replay_mod._lines(work / "referee.jsonl"))
    epi_a = replay_mod._strip(replay_mod._lines(original / "episodes.jsonl"))
    epi_b = replay_mod._strip(replay_mod._lines(work / "episodes.jsonl"))
    if ref_a != ref_b:
        mismatches.append("referee ticks differ from the recorded referee.jsonl")
    if epi_a != epi_b:
        mismatches.append("episode receipts differ from the recorded episodes.jsonl")
    n_images = sum(1 for e in transcript if "image" in e["response"])
    return frames, {"capture_pass_mismatches": mismatches, "observations_compared": n_images,
                    "episodes_replayed": len(episodes_replayed)}


# ---------------------------------------------------------------------------- labels and frames
def build_label(manifest: dict[str, Any], session_sha256: str, episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Label facts come from the recorded manifest and referee record only."""
    player = manifest["player"]
    kind = "AI PLAYER (as recorded)" if player["is_ai"] else "SCRIPTED NON-AI PLAYER (as recorded)"
    return {"banner": BANNER, "session_sha256_prefix": session_sha256[:12], "player_label": player["label"],
            "player_is_ai": bool(player["is_ai"]), "player_kind": kind,
            "outcomes": {e["episode"]: e["outcome"] for e in episodes}}


def _font(size: int):  # type: ignore[no-untyped-def]
    from PIL import ImageFont
    return ImageFont.load_default(size)


def _footer_lines(label: dict[str, Any], episode: int | None, kind: str) -> tuple[str, str]:
    outcome = label["outcomes"].get(episode, "n/a (no finished episode)") if episode is not None else "see title card"
    l1 = f"{label['banner']}  |  session {label['session_sha256_prefix']}  |  {label['player_kind']}"
    l2 = f"player: {label['player_label']}  |  episode {episode if episode is not None else '-'}  |  recorded outcome: {outcome}"
    return l1, l2


def compose(png: bytes | None, label: dict[str, Any], episode: int | None, kind: str,
            card_lines: list[str] | None = None):  # type: ignore[no-untyped-def]
    """Game image (or title card) above a burned-in label strip. Returns an RGB PIL image (1280 x 800)."""
    from PIL import Image, ImageDraw
    canvas = Image.new("RGB", (FRAME_W, FRAME_H + FOOTER_HEIGHT), (0, 0, 0))
    d = ImageDraw.Draw(canvas)
    if png is not None:
        canvas.paste(Image.open(io.BytesIO(png)).convert("RGB"), (0, 0))
    else:
        d.rectangle([0, 0, FRAME_W, FRAME_H], fill=(20, 20, 40))
        y = 160
        for i, line in enumerate(card_lines or []):
            f = _font(44 if i == 0 else 26)
            d.text((FRAME_W // 2, y), line, fill=(255, 220, 60) if i == 0 else (235, 235, 235), font=f, anchor="mt")
            y += 80 if i == 0 else 44
    d.rectangle([0, FRAME_H, FRAME_W, FRAME_H + FOOTER_HEIGHT], fill=(150, 20, 20))
    l1, l2 = _footer_lines(label, episode, kind)
    d.text((12, FRAME_H + 8), l1, fill=(255, 255, 255), font=_font(24))
    d.text((12, FRAME_H + 44), l2, fill=(255, 255, 255), font=_font(22))
    return canvas


def _tool_versions(browser: str) -> dict[str, Any]:
    import importlib.metadata as md

    def v(name: str) -> str | None:
        try:
            return md.version(name)
        except md.PackageNotFoundError:
            return None
    out = {"python": sys.version.split()[0], "pillow": v("pillow"), "imageio": v("imageio"),
           "imageio-ffmpeg": v("imageio-ffmpeg"), "numpy": v("numpy"), "playwright": v("playwright"),
           "browser_of_this_replay": browser}
    try:
        import imageio_ffmpeg
        out["ffmpeg"] = imageio_ffmpeg.get_ffmpeg_version()
    except Exception:  # noqa: BLE001
        out["ffmpeg"] = None
    return out


# ---------------------------------------------------------------------------- main entry
def render(session_dir: Path, out: Path, *, every: int = 1, episode: int | None = None, fps: int = 30,
           card_seconds: float = 2.0) -> dict[str, Any]:
    session_dir, out = Path(session_dir), Path(out)
    if every < 1:
        raise ValueError("--every must be >= 1")
    for name in ("session.json", "player_transcript.jsonl", "referee.jsonl", "episodes.jsonl"):
        if not (session_dir / name).is_file():
            raise FootageRefused(f"{session_dir} is not a recorded session (missing {name})")
    if out.exists():
        raise FileExistsError(f"{out} already exists; footage never overwrites")
    out.mkdir(parents=True)
    work = out / "_work"
    try:
        session_sha = _sha256_file(session_dir / "session.json")
        manifest = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
        episodes = replay_mod._lines(session_dir / "episodes.jsonl")
        # (1) standard replay check on a COPY (replay writes into the session it is given)
        copy = work / "copy"
        shutil.copytree(session_dir, copy, ignore=shutil.ignore_patterns("replays"))
        receipt = replay_mod.replay(copy)
        if not receipt["reproduced"]:
            raise FootageRefused(f"replay did not reproduce the recorded session; refusing to render: "
                                 f"{json.dumps({k: v for k, v in receipt.items() if k not in ('original', 'replay')})}")
        # (2) capture pass: per-frame capture; per-act screenshots must equal the recorded hashes
        frames, check = _capture_pass(copy, work / "capture", every)
        if check["capture_pass_mismatches"]:
            raise FootageRefused("capture pass differs from the recording: " + "; ".join(check["capture_pass_mismatches"][:5]))
        label = build_label(manifest, session_sha, episodes)
        episode_numbers = sorted({f["episode"] for f in frames})
        if episode is not None:
            if episode not in episode_numbers:
                raise FootageRefused(f"episode {episode} is not in the recorded session (has {episode_numbers})")
            episode_numbers = [episode]
        cards = max(1, round(fps * card_seconds))
        images: list[Any] = []
        kinds: list[str] = []

        def add(img: Any, kind: str) -> None:
            images.append(img)
            kinds.append(kind)
        intro = [BANNER, f"session {label['session_sha256_prefix']}", label["player_kind"],
                 f"player: {label['player_label']}", f"episodes recorded: {len(episodes)}   "
                 f"outcomes: " + ", ".join(f"{k}={v}" for k, v in label["outcomes"].items())]
        for _ in range(cards):
            add(compose(None, label, None, "card", intro), "title_card")
        for ep in episode_numbers:
            ep_card = [f"{BANNER}  -  EPISODE {ep}", f"recorded outcome: {label['outcomes'].get(ep, 'n/a')}",
                       label["player_kind"]]
            for _ in range(max(1, cards // 2)):
                add(compose(None, label, ep, "card", ep_card), "episode_card")
            for f in (f for f in frames if f["episode"] == ep):
                add(compose(f["png"], label, ep, f["kind"]), "game")
        import numpy as np
        arrays = [np.asarray(im) for im in images]
        frame_hashes = [hashlib.sha256(a.tobytes()).hexdigest() for a in arrays]
        rendered = _write_output(out, arrays, fps)
        sidecar = {
            "schema": SCHEMA, "input_session_dir_name": session_dir.name, "input_session_json_sha256": session_sha,
            "label": {**label, "outcomes": {str(k): v for k, v in label["outcomes"].items()},
                      "label_text_line1_example": _footer_lines(label, episode_numbers[0], "game")[0],
                      "label_text_line2_example": _footer_lines(label, episode_numbers[0], "game")[1]},
            "replay_receipt": {k: v for k, v in receipt.items() if k not in ("original", "replay")},
            "capture_check": check, "every": every, "episode_filter": episode, "fps": fps,
            "frame_count": len(images), "game_frame_count": kinds.count("game"),
            "card_frame_count": len(images) - kinds.count("game"), "acts": _count_acts(session_dir),
            "frames_sha256": hashlib.sha256("".join(frame_hashes).encode()).hexdigest(),
            "frame_size": [images[0].width, images[0].height], "tool_versions": _tool_versions(manifest["software"]["browser"]),
            "output_format": rendered["format"], "output_file": rendered["file"], "output_sha256": rendered["sha256"],
        }
        (out / "footage.json").write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
        sidecar["frame_hashes"] = frame_hashes
        return sidecar
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)    # we created it: leave nothing behind on refusal
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _count_acts(session_dir: Path) -> int:
    return sum(1 for e in replay_mod._lines(session_dir / "player_transcript.jsonl")
               if isinstance(e.get("request"), dict) and e["request"].get("tool") == "act")


def _write_output(out: Path, arrays: list[Any], fps: int) -> dict[str, Any]:
    try:
        import imageio.v2 as imageio
        import imageio_ffmpeg  # noqa: F401
    except ImportError:
        pngs = out / "frames"
        pngs.mkdir()
        from PIL import Image
        names = []
        for i, a in enumerate(arrays):
            name = f"frames/{i:06d}.png"
            Image.fromarray(a).save(out / name)
            names.append(name)
        (out / "frames_manifest.json").write_text(json.dumps({"files": names, "fps": fps}, indent=2), encoding="utf-8")
        return {"format": "png-sequence (imageio/imageio-ffmpeg not installed)", "file": "frames_manifest.json",
                "sha256": _sha256_file(out / "frames_manifest.json")}
    path = out / "footage.mp4"
    with imageio.get_writer(str(path), fps=fps, codec="libx264", pixelformat="yuv420p", macro_block_size=16,
                            quality=7) as w:
        for a in arrays:
            w.append_data(a)
    return {"format": "mp4 (h264)", "file": "footage.mp4", "sha256": _sha256_file(path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.footage", description=__doc__.split("\n\n")[0])
    parser.add_argument("session", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--every", type=int, default=4, help="capture every Nth simulated frame (default 4)")
    parser.add_argument("--episode", type=int, default=None, help="only this episode (the whole session is still verified)")
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args(argv)
    try:
        result = render(args.session, args.out, every=args.every, episode=args.episode, fps=args.fps)
    except (FootageRefused, FileExistsError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    result.pop("frame_hashes", None)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
