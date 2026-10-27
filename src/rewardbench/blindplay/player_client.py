"""Player-side client for a blind-play session. Standard library only.

A future model tool runner (or a scripted test player) uses this to reach the referee through the
two pipes of ``rewardbench.blindplay.serve``. It deliberately imports nothing from ``rewardbench``:
the player side needs no repository code, game files or referee state, only this file and a command
that starts the referee elsewhere.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from typing import Any, Sequence


class SessionError(RuntimeError):
    pass


class BlindPlayClient:
    def __init__(self, command: Sequence[str], *, env: dict[str, str] | None = None) -> None:
        # The referee's diagnostics stay on the referee side (serve.py logs them privately); nothing from
        # its stderr is passed to the player process.
        self._proc = subprocess.Popen(list(command), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, encoding="utf-8", env=env, bufsize=1)

    def _call(self, request: dict[str, Any]) -> dict[str, Any]:
        if self._proc.poll() is not None:
            raise SessionError(f"referee exited with code {self._proc.returncode}")
        self._proc.stdin.write(json.dumps(request) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            raise SessionError("referee closed the connection")
        return json.loads(line)

    def brief(self) -> dict[str, Any]:
        return self._call({"tool": "brief"})

    def observe(self) -> dict[str, Any]:
        return self._call({"tool": "observe"})

    def act(self, keys: Sequence[str], frames: int) -> dict[str, Any]:
        return self._call({"tool": "act", "keys": list(keys), "frames": frames})

    def raw(self, request: Any) -> dict[str, Any]:
        """Send any JSON value (used by tests to prove the referee rejects it)."""
        return self._call(request)

    def close(self, timeout: float = 120.0) -> int:
        if self._proc.stdin and not self._proc.stdin.closed:
            self._proc.stdin.close()
        try:
            return self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            return self._proc.wait()

    def __enter__(self) -> "BlindPlayClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def png_bytes(observation: dict[str, Any]) -> bytes:
    """Decode and integrity-check the screenshot in an observation."""
    image = observation["image"]
    data = base64.b64decode(image["base64"])
    if hashlib.sha256(data).hexdigest() != image["sha256"]:
        raise SessionError("screenshot hash mismatch")
    return data
