"""Gymnasium env driving real Seb Lee-Delisle ApolloLander via Playwright."""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .host import ensure_static_server, make_browser_page, release_browser_page
from .seeds import TRAIN_SEED_BASE
from .starts import derive_short_horizon_start

THRUST_LEVELS = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float64)
STEER_DELTAS = np.array([-10.0, 0.0, 10.0], dtype=np.float64)

# A′ defaults (explicit; also overridable via constructor).
A_PRIME_ALPHA = 10.0
A_PRIME_TIME_COST = 0.005
A_PRIME_MODES = frozenset({"progress_a_prime", "a_prime"})


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
        start_template: str | None = None,
        auto_seed_base: int = TRAIN_SEED_BASE,
        reward_mode: str = "progress_a",
        headless: bool = True,
        port: int = 18770,
        render_mode: str | None = None,
        timeout_as_terminated: bool = False,
        potential_scale: float = 1.0,
        time_cost: float | None = None,
    ) -> None:
        super().__init__()
        self.action_repeat = int(action_repeat)
        self.max_physics_frames = int(max_physics_frames)
        self.start_mode = start_mode
        self.start_override = dict(start_override or {})
        self.start_template = start_template
        self.auto_seed_base = int(auto_seed_base)
        self.reward_mode = reward_mode
        self.headless = headless
        self.port = port
        self.render_mode = render_mode
        self.timeout_as_terminated = bool(timeout_as_terminated)
        self.potential_scale = float(potential_scale)
        self.time_cost = time_cost
        # A′ defaults: α=10, c=0.005 unless explicitly overridden.
        if self.reward_mode.lower() in A_PRIME_MODES:
            if self.potential_scale == 1.0:
                self.potential_scale = A_PRIME_ALPHA
            if self.time_cost is None:
                self.time_cost = A_PRIME_TIME_COST
            # V3 experimental task: frame budget is a terminal failure (not SB3 bootstrap).
            if not timeout_as_terminated:
                self.timeout_as_terminated = True

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
        self._auto_episode_idx = 0
        self._last_start: dict[str, float] | None = None

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

    def _resolve_episode_seed(self, seed: int | None) -> int:
        """Explicit seed → reproducible start; bare reset() → new auto seed.

        When ``start_template`` is set, small SB3 init seeds (< auto_seed_base) are
        mapped into the training pool so train starts are not diagnostic seeds.
        Eval/held-out seeds (≥ auto_seed_base) pass through unchanged.
        """
        if seed is not None:
            s = int(seed)
            if self.start_template is not None and s < self.auto_seed_base:
                return int(self.auto_seed_base + s)
            return s
        self._auto_episode_idx += 1
        return int(self.auto_seed_base + self._auto_episode_idx)

    def _resolve_start_override(self, episode_seed: int, options: dict) -> dict[str, float]:
        if "start_override" in options:
            return dict(options["start_override"])
        if self.start_template is not None:
            return derive_short_horizon_start(self.start_template, episode_seed)
        return dict(self.start_override)

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self._ensure_page()
        assert self._page is not None
        options = options or {}
        self._seed_used = self._resolve_episode_seed(seed)
        self._physics_frames = 0

        override = self._resolve_start_override(self._seed_used, options)
        self._cmd_angle = float(override.get("rotation", -90.0))
        self._last_start = dict(override)

        cfg: dict[str, Any] = {
            "seed": self._seed_used,
            "start_mode": options.get("start_mode", self.start_mode),
            **override,
        }
        if cfg["start_mode"] != "research" and override:
            cfg["start_mode"] = options.get("start_mode", self.start_mode)
        if self.start_template is not None or override:
            cfg["start_mode"] = "research"

        boot = self._page.evaluate("(cfg) => window.ApolloOriginal.reset(cfg)", cfg)
        raw = boot["observation"]
        if "rotation" in override:
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
            "episode_seed": self._seed_used,
            "start_template": self.start_template,
            "native_score": raw.get("native_score"),
            "raw": raw,
        }
        return obs, info

    @property
    def cmd_angle(self) -> float:
        return float(self._cmd_angle)

    def _terminal_reward(self, result: dict[str, Any], timed_out: bool) -> float | None:
        """Native outcomes only — never invent land/crash labels."""
        if result.get("perfect"):
            return 100.0
        if result.get("landed"):
            return 40.0  # hard landing (landed and not perfect)
        if result.get("crashed"):
            return -100.0
        if timed_out or result.get("timeout"):
            return -100.0
        return None

    def _train_reward(
        self,
        obs: np.ndarray,
        result: dict[str, Any],
        timed_out: bool,
        raw: dict[str, Any],
    ) -> float:
        mode = self.reward_mode.lower()
        if mode in ("sparse_d", "d"):
            if result.get("landed"):
                return 1.0
            if result.get("crashed") or timed_out:
                return -1.0
            return 0.0

        if mode in ("zero_e", "e"):
            return 0.0

        terminal = self._terminal_reward(result, timed_out)

        # A′ and A/B/C all use the same native terminal constants.
        shaped_modes = (
            "progress_a",
            "a",
            "progress_b",
            "b",
            "progress_c",
            "c",
            "progress_a_prime",
            "a_prime",
        )
        if terminal is not None and mode in shaped_modes:
            self._prev_phi = _potential(obs)
            return float(terminal)

        phi = _potential(obs)
        delta = 0.0 if self._prev_phi is None else (phi - self._prev_phi)
        self._prev_phi = phi

        if mode in A_PRIME_MODES:
            return float(self.potential_scale * delta - float(self.time_cost))

        c_time = 0.05 if self.time_cost is None else float(self.time_cost)
        alpha = self.potential_scale

        if mode in ("progress_b", "b"):
            ang = abs(float(raw.get("rotation", 0.0)))
            speed = float(np.hypot(raw.get("vx", 0.0), raw.get("vy", 0.0)))
            hover_bonus = 1.0 if (ang < 10.0 and speed < 0.2) else 0.0
            return float(alpha * delta - c_time + hover_bonus)

        if mode in ("progress_c", "c"):
            return float(3.0 * delta - 0.02)

        return float(alpha * delta - c_time)

    def _finish_step(self, last: dict[str, Any]):
        raw = last["observation"]
        result = dict(last["result"])
        obs = self._raw_to_obs(raw, self._cmd_angle)

        native_done = bool(result.get("done"))
        timed_out = (not native_done) and (self._physics_frames >= self.max_physics_frames)

        # Experimental-task timeout: treat as terminal failure (no SB3 bootstrap).
        # Native land/crash never relabeled.
        if timed_out:
            result["status"] = "timeout"
            result["timeout"] = True
            if self.timeout_as_terminated:
                terminated, truncated = True, False
            else:
                terminated, truncated = False, True
        else:
            terminated, truncated = native_done, False

        reward = self._train_reward(obs, result, timed_out, raw)
        info = {
            "engine": "upstream-original",
            "native_score": result.get("native_score"),
            "status": result.get("status"),
            "landed": bool(result.get("landed")),
            "crashed": bool(result.get("crashed")),
            "perfect": bool(result.get("perfect")),
            "hard_landing": bool(result.get("hard_landing")),
            "timeout": bool(result.get("timeout")),
            "fuel_remaining": result.get("fuelRemaining"),
            "physics_frames": self._physics_frames,
            "physics_frames_delta": self._physics_frames,  # overwritten in step loops
            "cmd_angle": self._cmd_angle,
            "train_reward": reward,
            "episode_seed": self._seed_used,
            "start": self._last_start,
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

        frames_before = self._physics_frames
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
        obs, reward, terminated, truncated, info = self._finish_step(last)
        info["physics_frames_delta"] = int(self._physics_frames - frames_before)
        return obs, reward, terminated, truncated, info

    def step_absolute(self, thrust: float, rotation: float, *, repeats: int | None = None):
        """Drive original controls with absolute thrust/angle (feasibility / video only)."""
        self._ensure_page()
        assert self._page is not None
        self._cmd_angle = float(np.clip(rotation, -90.0, 90.0))
        thrust = float(np.clip(thrust, 0.0, 1.0))
        n = self.action_repeat if repeats is None else int(repeats)
        frames_before = self._physics_frames
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
        obs, reward, terminated, truncated, info = self._finish_step(last)
        info["physics_frames_delta"] = int(self._physics_frames - frames_before)
        return obs, reward, terminated, truncated, info

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
