"""Serve one blind-play session over stdin/stdout, one JSON object per line.

This process is the referee side. The player side (a tool runner for a future model, or a scripted
test player) holds only the two pipes: it sends ``{"tool": "brief" | "observe" | "act", ...}`` and
receives exactly what ``contract`` defines. End of input closes the session.

* Every input line is recorded before it is interpreted, including lines that are rejected (too long,
  not UTF-8, not JSON, duplicate keys, non-finite numbers, too deeply nested, oversized integers).
* File descriptors 1 and 2 are redirected to ``<out>/referee_stderr.log`` at the OS level, so neither
  this process nor its children (browser, Playwright driver) can write anything to the player except
  protocol lines, which go to a private duplicate of the original stdout.

    python -m rewardbench.blindplay.serve --out runs/blind-visual/<id> --player-label "..." --player-is-ai false
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from rewardbench.blindplay import contract, session

MAX_LINE_BYTES = 64 * 1024


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate keys")
    return dict(pairs)


def _no_constant(name: str) -> Any:
    raise ValueError(f"non-finite number {name}")


def decode_line(raw: bytes) -> tuple[Any, str | None]:
    """Strictly decode one input line. Returns ``(request, None)`` or ``(None, rejection reason)``."""
    if len(raw) > MAX_LINE_BYTES:
        return None, f"request longer than {MAX_LINE_BYTES} bytes"
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None, "request is not valid UTF-8"
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant), None
    except RecursionError:
        return None, "request is nested too deeply"
    except ValueError as exc:   # JSONDecodeError, duplicate keys, NaN/Infinity, int digit limit
        return None, f"request is not acceptable JSON: {type(exc).__name__}"


def read_lines(stream: Any):
    """Yield raw lines (without the newline); an over-long line is yielded truncated past the limit."""
    while True:
        line = stream.readline(MAX_LINE_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
            while True:   # discard the rest of the over-long line
                rest = stream.readline(MAX_LINE_BYTES)
                if not rest or rest.endswith(b"\n"):
                    break
        yield line.rstrip(b"\r\n")


def _bool(text: str) -> bool:
    if text.lower() in ("true", "yes", "1"):
        return True
    if text.lower() in ("false", "no", "0"):
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.serve", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="new, empty session directory")
    parser.add_argument("--player-label", required=True, help="who or what is playing, recorded verbatim")
    parser.add_argument("--player-is-ai", type=_bool, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--episode-frame-budget", type=int, default=session.DEFAULT_EPISODE_FRAME_BUDGET)
    parser.add_argument("--max-episodes", type=int, default=session.DEFAULT_MAX_EPISODES)
    parser.add_argument("--max-requests", type=int, default=session.DEFAULT_MAX_REQUESTS)
    parser.add_argument("--max-wall-seconds", type=float, default=None)
    parser.add_argument("--keyset", choices=sorted(contract.CONTRACTS), default=contract.V1.keyset)
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    if any(p.name != "referee_stderr.log" for p in args.out.iterdir()):
        raise SystemExit(f"{args.out} is not empty; records are never overwritten")
    sys.stdout.flush()
    sys.stderr.flush()
    protocol = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    log_fd = os.open(args.out / "referee_stderr.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)

    with session.Session(args.out, seed=args.seed, episode_frame_budget=args.episode_frame_budget,
                         max_episodes=args.max_episodes, max_requests=args.max_requests,
                         max_wall_seconds=args.max_wall_seconds, player_label=args.player_label,
                         player_is_ai=args.player_is_ai, allow_files={"referee_stderr.log"}, keyset=args.keyset) as s:
        for raw in read_lines(sys.stdin.buffer):
            if not raw.strip():
                continue
            request, rejection = decode_line(raw)
            response = s.handle(request, raw_line=raw, rejection=rejection)
            protocol.write(json.dumps(response) + "\n")
            protocol.flush()
    protocol.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
