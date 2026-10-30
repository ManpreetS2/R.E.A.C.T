"""The unprivileged player contract: everything a blind player may send or receive.

This module is the whole observation/action boundary (PROJECT.md section 20.4). A player gets the
objective, a neutral description of two tools, and screenshots. It never gets source files, game
variables, rewards, trajectories or controllers. Tests pin every field that crosses this boundary.

Deliberately imports nothing from the rest of ``rewardbench``.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

OBJECTIVE = "Land the rocket."
MAX_FRAMES_PER_ACT = 120
FRAMES_PER_SECOND = 60


def _tools(keys: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
    return (
        {
            "name": "observe",
            "description": "Return the current game screen as an image. Does not advance the game.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "act",
            "description": (
                "Press and hold the listed keys (none, one or several) for the given number of game frames, "
                "then release them, and return the game screen. The game is paused between calls; "
                f"it runs at {FRAMES_PER_SECOND} frames per second of game time."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string", "enum": list(keys)}, "uniqueItems": True},
                    "frames": {"type": "integer", "minimum": 1, "maximum": MAX_FRAMES_PER_ACT},
                },
                "required": ["keys", "frames"],
                "additionalProperties": False,
            },
        },
    )


@dataclass(frozen=True)
class ContractVersion:
    """One immutable version of the boundary. Changing a key, a tool or a field means adding a new version."""
    protocol: str
    keyset: str
    keys: tuple[str, ...]
    tools: tuple[dict[str, Any], ...]


# Standard KeyboardEvent.code names, alphabetical. The enumeration is generic keyboard keys; nothing
# says what any key does in this game.
_KEYS_V1: tuple[str, ...] = (
    "ArrowDown", "ArrowLeft", "ArrowRight", "ArrowUp", "Enter", "Escape",
    "KeyA", "KeyD", "KeyS", "KeyW", "ShiftLeft", "Space",
)
# Frozen: every Mission 013/014 session used it and replays against it.
V1 = ContractVersion("react.blindplay.player.v1", "keyset.v1", _KEYS_V1, _tools(_KEYS_V1))
# PROPOSED for P1, pending owner approval: the same 11 keys without KeyS, which holds upstream's undocumented
# developer speed mode (4 physics updates per frame). Message fields and frame limits are unchanged.
_KEYS_V2: tuple[str, ...] = tuple(k for k in _KEYS_V1 if k != "KeyS")
V2 = ContractVersion("react.blindplay.player.v2", "keyset.v2", _KEYS_V2, _tools(_KEYS_V2))
CONTRACTS: dict[str, ContractVersion] = {V1.keyset: V1, V2.keyset: V2}


def version_for(keyset: str) -> ContractVersion:
    try:
        return CONTRACTS[keyset]
    except KeyError:
        raise ValueError(f"unknown keyset {keyset!r}; known: {sorted(CONTRACTS)}") from None


# The historical names remain the frozen v1 contract.
PROTOCOL = V1.protocol
KEYSET_VERSION = V1.keyset
ALLOWED_KEYS = V1.keys
TOOLS = V1.tools

# Exact key sets of every message that crosses the boundary toward the player.
OBSERVATION_FIELDS = frozenset({
    "protocol", "seq", "episode", "episode_frame", "episode_frame_budget", "max_episodes",
    "frames_advanced", "episode_ended", "session_over", "image",
})
IMAGE_FIELDS = frozenset({"media_type", "width", "height", "sha256", "base64"})
ERROR_FIELDS = frozenset({"protocol", "error"})
BRIEF_FIELDS = frozenset({"protocol", "objective", "tools", "max_frames_per_act",
                          "episode_frame_budget", "max_episodes", "keyset"})


class ActionRejected(ValueError):
    """A player request outside the contract. Nothing was sent to the game."""


@dataclass(frozen=True)
class Act:
    keys: tuple[str, ...]
    frames: int


def parse_request(message: Any, version: ContractVersion = V1) -> tuple[str, Act | None]:
    """Validate one player request. Returns ``("observe", None)``, ``("brief", None)`` or ``("act", Act)``."""
    if not isinstance(message, Mapping):
        raise ActionRejected("request must be a JSON object")
    tool = message.get("tool")
    if tool in ("observe", "brief"):
        extra = set(message) - {"tool", "id"}
        if extra:
            raise ActionRejected(f"unexpected fields for {tool}: {sorted(extra)}")
        return tool, None
    if tool != "act":
        raise ActionRejected("tool must be 'observe', 'act' or 'brief'")
    extra = set(message) - {"tool", "id", "keys", "frames"}
    if extra:
        raise ActionRejected(f"unexpected fields for act: {sorted(extra)}")
    keys, frames = message.get("keys"), message.get("frames")
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise ActionRejected("keys must be a list of key names")
    unknown = [k for k in keys if k not in version.keys]
    if unknown:
        raise ActionRejected(f"keys not allowed: {unknown}; allowed: {list(version.keys)}")
    if len(set(keys)) != len(keys):
        raise ActionRejected("keys must not repeat")
    if isinstance(frames, bool) or not isinstance(frames, int):
        raise ActionRejected("frames must be an integer")
    if not 1 <= frames <= MAX_FRAMES_PER_ACT:
        raise ActionRejected(f"frames must be between 1 and {MAX_FRAMES_PER_ACT}")
    return "act", Act(keys=tuple(keys), frames=frames)


def brief(*, episode_frame_budget: int, max_episodes: int, version: ContractVersion = V1) -> dict[str, Any]:
    """The only description of the task a player receives."""
    return {
        "protocol": version.protocol,
        "objective": OBJECTIVE,
        "tools": [dict(t) for t in version.tools],
        "keyset": {"version": version.keyset, "keys": list(version.keys)},
        "max_frames_per_act": MAX_FRAMES_PER_ACT,
        "episode_frame_budget": episode_frame_budget,
        "max_episodes": max_episodes,
    }


def image_payload(png: bytes, width: int, height: int) -> dict[str, Any]:
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("not a PNG")
    return {"media_type": "image/png", "width": width, "height": height,
            "sha256": hashlib.sha256(png).hexdigest(), "base64": base64.b64encode(png).decode("ascii")}


def observation(*, seq: int, episode: int, episode_frame: int, episode_frame_budget: int, max_episodes: int,
                frames_advanced: int, episode_ended: bool, session_over: bool, image: dict[str, Any],
                version: ContractVersion = V1) -> dict[str, Any]:
    """The only game information a player receives: the screenshot plus procedural counters."""
    return {
        "protocol": version.protocol, "seq": seq, "episode": episode, "episode_frame": episode_frame,
        "episode_frame_budget": episode_frame_budget, "max_episodes": max_episodes,
        "frames_advanced": frames_advanced, "episode_ended": episode_ended, "session_over": session_over,
        "image": image,
    }


def error(message: str, version: ContractVersion = V1) -> dict[str, Any]:
    return {"protocol": version.protocol, "error": message}
