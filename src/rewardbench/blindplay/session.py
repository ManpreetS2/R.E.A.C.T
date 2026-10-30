"""A blind-play session: budgets, automatic episode resets and the chronological record.

``Session.handle(request)`` is the only entry point a player reaches (through ``serve``). Player
responses are built only by ``contract`` from screenshots and procedural counters. Everything the
referee knows (game state per tick, outcomes, native score) goes to separate referee files.

Record layout (``out``):

* ``session.json``           configuration, environment provenance, final status
* ``player_transcript.jsonl`` every request and exactly what was returned to the player
                              (image bytes replaced by sha256 + file name; bytes are in screenshots/)
* ``screenshots/``            every PNG returned to the player, byte for byte
* ``referee.jsonl``           PRIVILEGED: per call, every tick's game state and terminal evidence
* ``episodes.jsonl``          PRIVILEGED: one receipt per finished episode
* ``referee_frames/``         PRIVILEGED: the start frame of every episode (fixed-start evidence)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rewardbench.blindplay import contract, referee as referee_mod, upstream

SESSION_SCHEMA = "react.blindplay.session.v1"
ENVIRONMENT_ID = "apollolander-upstream-fixed-start"   # PROJECT.md 20.3, environment A
DEFAULT_EPISODE_FRAME_BUDGET = 8000
DEFAULT_MAX_EPISODES = 20
DEFAULT_MAX_REQUESTS = 20000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _git_state() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=10).stdout.strip()
        return {"commit": head or None, "dirty": bool(dirty)}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def _recordable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError, RecursionError):
        return {"unserialisable_repr": repr(value)[:2000]}


class Session:
    def __init__(self, out: Path, *, seed: int = 0, episode_frame_budget: int = DEFAULT_EPISODE_FRAME_BUDGET,
                 max_episodes: int = DEFAULT_MAX_EPISODES, max_requests: int = DEFAULT_MAX_REQUESTS,
                 max_wall_seconds: float | None = None, player_label: str, player_is_ai: bool,
                 ref: referee_mod.Referee | None = None, allow_files: set[str] | None = None,
                 keyset: str = contract.V1.keyset) -> None:
        self.contract = contract.version_for(keyset)
        if not player_label:
            raise ValueError("player_label is required (who or what is playing)")
        if episode_frame_budget < 1 or max_episodes < 1 or max_requests < 1:
            raise ValueError("budgets must be positive")
        self.out = Path(out)
        if self.out.exists() and any(p.name not in (allow_files or set()) for p in self.out.iterdir()):
            raise FileExistsError(f"{self.out} is not empty; records are never overwritten")
        (self.out / "screenshots").mkdir(parents=True, exist_ok=True)
        (self.out / "referee_frames").mkdir(exist_ok=True)
        self.referee = ref or referee_mod.Referee(seed=seed)
        served = {name: hashlib.sha256(data).hexdigest() for name, data in self.referee.files.items()}
        if served != upstream.UPSTREAM_SHA256:
            raise referee_mod.RefereeError("referee files differ from the pinned upstream files")
        self.seed = self.referee.seed
        self.episode_frame_budget = episode_frame_budget
        self.max_episodes = max_episodes
        self.max_requests = max_requests
        self.max_wall_seconds = max_wall_seconds
        self.player_label = player_label
        self.player_is_ai = player_is_ai
        self.requests = 0
        self.seq = 0
        self.episode = 0
        self.episode_frame = 0
        self.episode_start_png = ""
        self.failure: str | None = None
        self.needs_reset = True
        self.session_over = False
        self.episodes: list[dict[str, Any]] = []
        self.started = _now()
        self._t0 = time.monotonic()
        self._files = {name: open(self.out / name, "a", encoding="utf-8")
                       for name in ("player_transcript.jsonl", "referee.jsonl", "episodes.jsonl")}
        self.referee.start()
        self._write_manifest(status="running")

    # ------------------------------------------------------------------ records
    def _append(self, name: str, record: dict[str, Any]) -> None:
        f = self._files[name]
        f.write(json.dumps(record, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())

    def _manifest(self, status: str) -> dict[str, Any]:
        try:
            import importlib.metadata as md
            pw_version = md.version("playwright")
        except Exception:  # noqa: BLE001
            pw_version = None
        return {
            "schema": SESSION_SCHEMA, "status": status, "started_utc": self.started,
            "ended_utc": None if status == "running" else _now(),
            "player": {"label": self.player_label, "is_ai": self.player_is_ai},
            "environment": {
                "id": ENVIRONMENT_ID, "upstream_repository": upstream.UPSTREAM_REPOSITORY,
                "upstream_commit": upstream.UPSTREAM_COMMIT, "upstream_sha256": dict(upstream.UPSTREAM_SHA256),
                "clock_js_sha256": self.referee.clock_sha256, "seed": self.seed,
                "viewport": dict(referee_mod.VIEWPORT), "pre_start_ticks": referee_mod.PRE_START_TICKS,
                "start_ticks": referee_mod.START_TICKS, "settle_ticks_after_terminal": referee_mod.SETTLE_TICKS,
                "deviations_from_live_game": [
                    "virtual clock: the game advances only when the referee ticks (no Date.now catch-up)",
                    "Math.random seeded (mulberry32); timers and requestAnimationFrame virtual",
                    "audio muted; one fresh browser context per episode (fresh game: fuel 1000, score 0)",
                    "referee clicks to start; the title screen is never shown to the player",
                    "an episode ends at the first terminal event (upstream would continue with a new life)",
                    "time zone UTC and locale en-US pinned; network limited to the pinned upstream files",
                    "upstream speed mode (KeyS) runs 4 physics updates per frame; frame limits bound frames"
                    if "KeyS" in self.contract.keys else
                    "upstream developer speed mode (KeyS) not offered to the player (keyset.v2)",
                ],
            },
            "player_contract": {"protocol": self.contract.protocol, "objective": contract.OBJECTIVE,
                                "keyset": self.contract.keyset, "allowed_keys": list(self.contract.keys),
                                "max_frames_per_act": contract.MAX_FRAMES_PER_ACT},
            "budgets": {"episode_frame_budget": self.episode_frame_budget, "max_episodes": self.max_episodes,
                        "max_requests": self.max_requests, "max_wall_seconds": self.max_wall_seconds},
            "software": {"python": sys.version.split()[0], "platform": platform.platform(),
                         "playwright": pw_version, "browser": self.referee.browser_version, **{"git": _git_state()}},
            "counts": {"requests": self.requests, "observations": self.seq, "episodes_finished": len(self.episodes),
                       "wall_seconds": round(time.monotonic() - self._t0, 3)},
            "network": {"served": sorted({r["url"] for r in self.referee.requests if r["result"] == "served"}),
                        "blocked": [r["url"] for r in self.referee.requests if r["result"] == "blocked"]},
            "page_errors": list(self.referee.page_errors),
            "episode_outcomes": [e["outcome"] for e in self.episodes],
            "environment_failure": self.failure,
        }

    def _write_manifest(self, status: str) -> None:
        tmp = self.out / "session.json.tmp"
        tmp.write_text(json.dumps(self._manifest(status), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.out / "session.json")

    def close(self, status: str = "closed") -> None:
        if self._files:
            self._write_manifest(status)
            for f in self._files.values():
                f.close()
            self._files = {}
            self.referee.close()

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type: object, *exc: object) -> None:
        self.close("closed" if exc_type is None else "aborted_with_error")

    # ------------------------------------------------------------------ player entry point
    def handle(self, request: Any, *, raw_line: bytes | None = None, rejection: str | None = None) -> dict[str, Any]:
        """Validate and execute one player request; record it and exactly what is returned.

        ``raw_line`` is the exact input line when it arrived over ``serve``; ``rejection`` is set when that
        line could not be decoded (it is then recorded and rejected without being interpreted).
        """
        self.requests += 1
        received, t = _now(), time.monotonic()
        try:
            if rejection is not None:
                raise contract.ActionRejected(rejection)
            if self.requests > self.max_requests:
                raise contract.ActionRejected("request budget exhausted")
            if self.max_wall_seconds is not None and time.monotonic() - self._t0 > self.max_wall_seconds:
                self.session_over = True
            tool, act = contract.parse_request(request, self.contract)
            if tool == "brief":
                response = contract.brief(episode_frame_budget=self.episode_frame_budget, max_episodes=self.max_episodes,
                                          version=self.contract)
            elif self.session_over:
                raise contract.ActionRejected("session is over")
            elif tool == "observe":
                response = self._observe()
            else:
                response = self._act(act)
        except contract.ActionRejected as exc:
            response = contract.error(str(exc), self.contract)
        except Exception as exc:  # noqa: BLE001 - any environment failure ends the session, with a record
            self.failure = f"{type(exc).__name__}: {str(exc)[:2000]}"
            self.session_over = True
            response = contract.error("environment failure; the session has ended", self.contract)
            self._write_manifest("aborted_environment_failure")
        recorded = json.loads(json.dumps(response))
        if "image" in recorded:
            recorded["image"].pop("base64")
            recorded["image"]["file"] = f"screenshots/{recorded['seq']:06d}.png"
        entry: dict[str, Any] = {"request_index": self.requests, "received_utc": received,
                                 "seconds": round(time.monotonic() - t, 6), "request": _recordable(request),
                                 "response": recorded}
        if raw_line is not None:
            entry["raw_line_sha256"] = hashlib.sha256(raw_line).hexdigest()
            entry["raw_line_base64"] = base64.b64encode(raw_line[:65536]).decode("ascii")
            entry["raw_line_bytes"] = len(raw_line)
        if rejection is not None:
            entry["rejected_before_parsing"] = rejection
        self._append("player_transcript.jsonl", entry)
        if self.requests % 50 == 0:
            self._write_manifest("running")
        return response

    # ------------------------------------------------------------------ internals
    def _reset_if_needed(self) -> None:
        if not self.needs_reset:
            return
        self.episode += 1
        self.episode_frame = 0
        start = self.referee.reset()
        self.needs_reset = False
        png = self.referee.screenshot()
        (self.out / "referee_frames" / f"episode_{self.episode:04d}_start.png").write_bytes(png)
        self.episode_start_png = hashlib.sha256(png).hexdigest()
        self._append("referee.jsonl", {"event": "reset", "episode": self.episode, "utc": _now(), "start_state": start,
                                       "start_frame_sha256": self.episode_start_png, "message": self.referee.message()})

    def _screenshot(self, *, frames_advanced: int, episode_ended: bool) -> dict[str, Any]:
        png = self.referee.screenshot()
        self.seq += 1
        (self.out / "screenshots" / f"{self.seq:06d}.png").write_bytes(png)
        image = contract.image_payload(png, referee_mod.VIEWPORT["width"], referee_mod.VIEWPORT["height"])
        return contract.observation(seq=self.seq, episode=self.episode, episode_frame=self.episode_frame,
                                    episode_frame_budget=self.episode_frame_budget, max_episodes=self.max_episodes,
                                    frames_advanced=frames_advanced, episode_ended=episode_ended,
                                    session_over=self.session_over, image=image, version=self.contract)

    def _observe(self) -> dict[str, Any]:
        self._reset_if_needed()
        return self._screenshot(frames_advanced=0, episode_ended=False)

    def _act(self, act: contract.Act) -> dict[str, Any]:
        self._reset_if_needed()
        allowed = min(act.frames, self.episode_frame_budget - self.episode_frame)
        ticks = self.referee.run(act.keys, allowed, stop_on_terminal=True)
        if self.referee.snapshot()["keysDown"]:
            raise referee_mod.RefereeError("keys still held after an act")
        self.episode_frame += len(ticks)
        last = ticks[-1]
        terminal = last["gameState"] in referee_mod.TERMINAL_STATES
        timed_out = not terminal and self.episode_frame >= self.episode_frame_budget
        settle: list[dict[str, Any]] = []
        if terminal:
            settle = self.referee.run([], referee_mod.SETTLE_TICKS, stop_on_terminal=False)
        record: dict[str, Any] = {"event": "act", "episode": self.episode, "utc": _now(), "keys": list(act.keys),
                                  "frames_requested": act.frames, "frames_executed": len(ticks),
                                  "episode_frame_after": self.episode_frame, "ticks": ticks}
        if settle:
            record["settle_ticks"] = settle
        ended = terminal or timed_out
        if ended:
            self.needs_reset = True
            if len(self.episodes) + 1 >= self.max_episodes:
                self.session_over = True
        response = self._screenshot(frames_advanced=len(ticks), episode_ended=ended)
        record["response_seq"] = response["seq"]
        if ended:
            outcome = referee_mod.classify(last, 0) if terminal else "frame_budget_exhausted"
            receipt = {"episode": self.episode, "outcome": outcome, "frames": self.episode_frame,
                       "terminal_tick_state": last, "after_settle_state": settle[-1] if settle else None,
                       "native_message": self.referee.message(), "native_score": last["score"],
                       "start_frame_sha256": self.episode_start_png,
                       "end_seq": response["seq"], "end_screenshot_sha256": response["image"]["sha256"],
                       "utc": _now()}
            record["terminal"] = {"outcome": outcome, "message": receipt["native_message"]}
            self.episodes.append(receipt)
            self._append("referee.jsonl", record)
            self._append("episodes.jsonl", receipt)
            self._write_manifest("running" if not self.session_over else "completed")
        else:
            self._append("referee.jsonl", record)
        return response
