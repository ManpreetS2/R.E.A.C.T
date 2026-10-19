"""Gymnasium env driving real Seb Lee-Delisle ApolloLander via Playwright."""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .host import ensure_static_server, make_browser_page, release_browser_page

THRUST_LEVELS = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float64)
STEER_DELTAS = np.array([-10.0, 0.0, 10.0], dtype=np.float64)


def _potential(obs: np.ndarray) -> float:
    dx, alt, vx, vy, ang = obs[0], obs[1], obs[2], obs[3], obs[4]
    return float(
        -1.0 * abs(dx)
        - 1.2 * max(alt, 0.0)
        - 0.8 * abs(vx)
        - 1.0 * max(vy, 0.0)
        - 1.5 * abs(ang)
    )


class ApolloLanderGym(gym.Env):
    """Numerical RL interface over the upstream ApolloOriginal bridge."""

    metadata = {"render_modes": ["rgb_array"], "render_fps": 50}

    def __init__(
        self,
        *,
        action_repeat: int = 4,
        max_physics_frames: int = 8000,
        start_mode: str = "fixed",
        start_override: dict[str, float] | None = None,
        reward_mode: str = "progress_a",
        headless: bool = True,
        port: int = 18770,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        self.action_repeat = int(action_repeat)
        self.max_physics_frames = int(max_physics_frames)
        self.start_mode = start_mode
        self.start_override = dict(start_override or {})
        self.reward_mode = reward_mode
        self.headless = headless
        self.port = port
        self.render_mode = render_mode

        self.observation_space = spaces.Box(low=-5.0, high=5.0, shape=(10,), dtype=np.float32)
        self.action_space = spaces.MultiDiscrete([len(THRUST_LEVELS), len(STEER_DELTAS)])

        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._cmd_angle = -90.0
        self._prev_phi: float | None = None
        self._physics_frames = 0
        self._seed_used = 0

    def _ensure_page(self) -> None:
        if self._page is not None:
            return
        url = ensure_static_server(self.port)
        self._pw, self._browser, self._context, self._page = make_browser_page(
            url, headless=self.headless
        )

    def close(self) -> None:
        try:
            release_browser_page(self._context)
        finally:
            self._page = self._context = self._browser = self._pw = None

    def _raw_to_obs(self, raw: dict[str, Any], cmd_angle: float) -> np.ndarray:
        obs = np.array(
            [
                float(raw.get("dx", 0.0)) / 200.0,
                float(raw.get("altitude", 0.0)) / 300.0,
                float(raw.get("vx", 0.0)) / 2.0,
                float(raw.get("vy", 0.0)) / 2.0,
                float(raw.get("rotation", 0.0)) / 90.0,
                float(cmd_angle) / 90.0,
                float(raw.get("fuel", 0.0)) / 1000.0,
                float(raw.get("thrust", 0.0)) / 3.0,
                float(raw.get("pad_width", 0.0)) / 200.0,
                float(raw.get("dy", 0.0)) / 300.0,
            ],
            dtype=np.float32,
        )
        return np.clip(obs, -5.0, 5.0)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self._ensure_page()
        assert self._page is not None
        options = options or {}
        self._seed_used = int(seed if seed is not None else 0)
        self._physics_frames = 0
        self._cmd_angle = float(self.start_override.get("rotation", -90.0))

        cfg: dict[str, Any] = {
            "seed": self._seed_used,
            "start_mode": options.get("start_mode", self.start_mode),
        }
        override = options.get("start_override", self.start_override)
        if cfg["start_mode"] == "research":
            cfg.update(override)
            cfg["start_mode"] = "research"
        elif override:
            cfg.update(override)

        boot = self._page.evaluate("(cfg) => window.ApolloOriginal.reset(cfg)", cfg)
        raw = boot["observation"]
        if "rotation" in (override or {}):
            self._cmd_angle = float(override["rotation"])
        elif boot.get("start"):
            self._cmd_angle = float(boot["start"].get("rotation", self._cmd_angle))

        obs = self._raw_to_obs(raw, self._cmd_angle)
        self._prev_phi = _potential(obs)
        info = {
            "engine": "upstream-original",
            "start": boot.get("start"),
            "zone": boot.get("zone"),
            "start_mode": boot.get("start_mode"),
            "native_score": raw.get("native_score"),
            "raw": raw,
        }
        return obs, info

    @property
    def cmd_angle(self) -> float:
        return float(self._cmd_angle)

    def _train_reward(
        self,
        obs: np.ndarray,
        result: dict[str, Any],
        truncated: bool,
        raw: dict[str, Any],
    ) -> float:
        mode = self.reward_mode.lower()
        if mode in ("sparse_d", "d"):
            if result.get("landed"):
                return 1.0
            if result.get("crashed") or truncated:
                return -1.0
            return 0.0

        if mode in ("zero_e", "e"):
            return 0.0

        # Shared terminal signals for A/B/C
        if result.get("perfect"):
            terminal = 100.0
        elif result.get("landed"):
            terminal = 40.0
        elif result.get("crashed"):
            terminal = -100.0
        elif truncated:
            # Same severity as crash so delaying forever is not preferred to attempting landing.
            terminal = -100.0
        else:
            terminal = None

        if terminal is not None and mode in ("progress_a", "a", "progress_b", "b", "progress_c", "c"):
            # Still update potential bookkeeping on terminal for clean resets
            self._prev_phi = _potential(obs)
            if mode in ("progress_b", "b") and terminal > 0:
                return terminal  # same landing bonus; hover bias is nonterminal only
            return float(terminal)

        phi = _potential(obs)
        delta = 0.0 if self._prev_phi is None else (phi - self._prev_phi)
        self._prev_phi = phi

        if mode in ("progress_b", "b"):
            # Intentionally problematic: pay for occupying upright+slow each step
            ang = abs(float(raw.get("rotation", 0.0)))
            speed = float(np.hypot(raw.get("vx", 0.0), raw.get("vy", 0.0)))
            hover_bonus = 1.0 if (ang < 10.0 and speed < 0.2) else 0.0
            return float(delta - 0.05 + hover_bonus)

        if mode in ("progress_c", "c"):
            # Explicit time cost retained (stronger than early A) without occupancy bonus
            return float(delta - 0.05)

        # progress_a: potential delta + mild per-step time cost
        return float(delta - 0.05)

    def _finish_step(self, last: dict[str, Any]):
        raw = last["observation"]
        result = last["result"]
        obs = self._raw_to_obs(raw, self._cmd_angle)
        terminated = bool(result.get("done"))
        truncated = (not terminated) and (self._physics_frames >= self.max_physics_frames)
        if truncated and not terminated:
            result = dict(result)
            result["status"] = "timeout"
            result["timeout"] = True
        reward = self._train_reward(obs, result, truncated, raw)
        info = {
            "engine": "upstream-original",
            "native_score": result.get("native_score"),
            "status": result.get("status"),
            "landed": bool(result.get("landed")),
            "crashed": bool(result.get("crashed")),
            "perfect": bool(result.get("perfect")),
            "hard_landing": bool(result.get("hard_landing")),
            "fuel_remaining": result.get("fuelRemaining"),
            "physics_frames": self._physics_frames,
            "cmd_angle": self._cmd_angle,
            "train_reward": reward,
            "applied": last.get("applied"),
            "raw": raw,
            "result": result,
        }
        return obs, reward, terminated, truncated, info

    def step(self, action):
        self._ensure_page()
        assert self._page is not None
        thrust_i = int(action[0])
        steer_i = int(action[1])
        thrust = float(THRUST_LEVELS[thrust_i])
        self._cmd_angle = float(
            np.clip(self._cmd_angle + float(STEER_DELTAS[steer_i]), -90.0, 90.0)
        )

        last = None
        for _ in range(self.action_repeat):
            if self._physics_frames >= self.max_physics_frames:
                break
            last = self._page.evaluate(
                "(a) => window.ApolloOriginal.step(a)",
                {"thrust": thrust, "rotation": self._cmd_angle},
            )
            self._physics_frames += 1
            if last["result"].get("done"):
                break

        assert last is not None
        return self._finish_step(last)

    def step_absolute(self, thrust: float, rotation: float, *, repeats: int | None = None):
        """Drive original controls with absolute thrust/angle (feasibility / video only)."""
        self._ensure_page()
        assert self._page is not None
        self._cmd_angle = float(np.clip(rotation, -90.0, 90.0))
        thrust = float(np.clip(thrust, 0.0, 1.0))
        n = self.action_repeat if repeats is None else int(repeats)
        last = None
        for _ in range(n):
            if self._physics_frames >= self.max_physics_frames:
                break
            last = self._page.evaluate(
                "(a) => window.ApolloOriginal.step(a)",
                {"thrust": thrust, "rotation": self._cmd_angle},
            )
            self._physics_frames += 1
            if last["result"].get("done"):
                break
        assert last is not None
        return self._finish_step(last)

    def render(self):
        if self.render_mode != "rgb_array":
            return None
        self._ensure_page()
        assert self._page is not None
        png = self._page.evaluate("() => window.ApolloOriginal.snapshotPNG()")
        import base64
        from io import BytesIO

        from PIL import Image

        raw = base64.b64decode(png.split(",", 1)[1])
        img = Image.open(BytesIO(raw)).convert("RGB")
        return np.asarray(img)
