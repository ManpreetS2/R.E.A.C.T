"""Trusted host for an isolated blind-play session.

TRUSTED HOST SIDE. The host owns, and the player can neither see nor change:

* the referee command (built here from ``HostConfig``; ``rewardbench.blindplay.serve`` with fixed budgets),
* the referee's records, stderr and browser (in ``<out>/referee``, outside the sandbox),
* the sandbox itself (``isolation.launch`` from the verified ``runtime_image``),
* the model gateway (credentials, provider, model id and limits, if one is ever configured).

The isolated player reaches the host only through its stdin/stdout. Each line is size-capped and
strictly decoded; game requests are re-validated with ``contract.parse_request`` and only the canonical
form is forwarded to the referee, so a rejected line never reaches the game. ``{"tool": "model"}`` goes to
the gateway: the player refers to screenshots by ``seq`` and the host attaches the exact PNG bytes it
returned earlier, so images reach a model without the player touching any file.

Session layout (``out``, never inside the sandbox's reach):

    host_session.json        configuration, isolation facts, runtime image digest, counts, status
    host_transcript.jsonl    every player line (sha256, length, first 4 KB verbatim) and the host's decision
    player_stderr.jsonl      the player's own stderr lines (scripted/probe reports)
    gateway_transcript.jsonl exactly what a model was sent (images as sha256) and what it returned
    referee/                 the referee's session (Mission 013 layout; replayable with ``replay.py``)

    python -m rewardbench.blindplay.host --out runs/blind-visual/<id> --mode scripted --script idle --episodes 2
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from rewardbench.blindplay import contract, isolation, runtime_image, serve, session

HOST_SCHEMA = "react.blindplay.host-session.v1"
MAX_GAME_LINE = serve.MAX_LINE_BYTES
MAX_MODEL_LINE = 2 * 1024 * 1024
MAX_PLAYER_STDERR = 16 * 1024 * 1024    # bytes of player stderr the host records (disk-fill bound)
RECORDED_RAW_BYTES = 4096              # head of each player line kept verbatim (full sha256 and length always)
MODEL_REPLY_FIELDS = frozenset({"protocol", "text", "tool_calls"})
_MESSAGE_ROLES = {"user", "assistant", "tool"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ModelGateway(Protocol):
    """Host-side model access. Holds any credentials; the player never sees them."""
    name: str
    is_model: bool

    def complete(self, request: dict[str, Any]) -> dict[str, Any]: ...


class DisabledGateway:
    """The default: there is no model. Every model request is refused."""
    name, is_model = "disabled", False

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:   # pragma: no cover - never called
        raise RuntimeError("disabled")


class ScriptedGateway:
    """NOT A MODEL. Replays fixed tool calls, ignoring what it is shown, and records the images it received.

    Used only to prove the plumbing (screenshots arrive as genuine PNG bytes; tool calls are executed
    through the host) without calling any provider.
    """
    name, is_model = "scripted-not-a-model", False

    def __init__(self, actions: list[tuple[list[str], int]]) -> None:
        self.actions = list(actions)
        self.received_images: list[str] = []

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        for m in request["messages"]:
            for part in m["content"]:
                if part["type"] == "image":
                    png = base64.b64decode(part["base64"])
                    assert png.startswith(b"\x89PNG") and hashlib.sha256(png).hexdigest() == part["sha256"]
                    self.received_images.append(part["sha256"])
        if not self.actions:
            return {"text": "done", "tool_calls": []}
        keys, frames = self.actions.pop(0)
        return {"text": "scripted", "tool_calls": [{"id": f"c{len(self.received_images)}", "name": "act",
                                                    "arguments": {"keys": keys, "frames": frames}}]}


@dataclass
class HostConfig:
    out: Path
    mode: str                                    # scripted | probe | agent
    player_label: str
    script: str = "idle"
    script_seed: int = 0
    seed: int = 0
    episode_frame_budget: int = session.DEFAULT_EPISODE_FRAME_BUDGET
    max_episodes: int = session.DEFAULT_MAX_EPISODES
    max_requests: int = session.DEFAULT_MAX_REQUESTS
    max_wall_seconds: float = 3600.0
    max_model_calls: int = 0
    max_images_per_model_call: int = 4
    image_window: int = 4
    probe_targets: dict[str, Any] = field(default_factory=dict)   # security tests only
    image_root: Path | None = None

    def player_args(self, image: Path) -> list[str]:
        args = ["-I", "-S", "-B", str(image / "player" / "runtime.py"), "--mode", self.mode]
        if self.mode == "scripted":
            args += ["--script", self.script, "--script-seed", str(self.script_seed)]
        elif self.mode == "agent":
            args += ["--image-window", str(self.image_window), "--max-model-calls", str(self.max_model_calls)]
        elif self.mode == "probe":
            args += ["--probe-targets", json.dumps(self.probe_targets)]
        else:
            raise ValueError(f"unknown mode {self.mode}")
        return args


class Host:
    def __init__(self, config: HostConfig, gateway: ModelGateway | None = None) -> None:
        reason = isolation.supported()
        if reason:
            raise isolation.IsolationUnavailable(reason)
        exposed = isolation.exposed_user_environment_secrets()
        if exposed:
            raise isolation.IsolationUnavailable(
                f"refusing to start: user environment variables readable by any AppContainer look like credentials: "
                f"{exposed}. Move them to host-only storage (see docs/ISOLATED_PLAYER_RUNTIME.md).")
        self.config = config
        self.gateway = gateway or DisabledGateway()
        if config.mode == "agent" and self.gateway.is_model and config.max_model_calls < 1:
            raise ValueError("a model gateway needs a positive max_model_calls")
        self.out = Path(config.out)
        if self.out.exists() and any(self.out.iterdir()):
            raise FileExistsError(f"{self.out} is not empty; records are never overwritten")
        self.out.mkdir(parents=True, exist_ok=True)
        self.images: dict[int, dict[str, str]] = {}      # seq -> image the player was shown
        self.counts = {"player_lines": 0, "forwarded_to_referee": 0, "rejected_by_host": 0, "model_calls": 0,
                       "model_rejected": 0}
        self.status = "starting"
        self.failure: str | None = None
        self._files = {n: open(self.out / n, "a", encoding="utf-8")
                       for n in ("host_transcript.jsonl", "player_stderr.jsonl", "gateway_transcript.jsonl")}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ records
    def _append(self, name: str, record: dict[str, Any]) -> None:
        with self._lock:
            f = self._files[name]
            f.write(json.dumps(record, sort_keys=True) + "\n")
            f.flush()

    def _manifest(self) -> dict[str, Any]:
        c = self.config
        return {
            "schema": HOST_SCHEMA, "status": self.status, "failure": self.failure,
            "started_utc": self.started, "ended_utc": None if self.status in ("starting", "running") else _now(),
            "config": {k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(c).items()},
            "player_is_ai": bool(self.gateway.is_model), "gateway": self.gateway.name,
            "isolation": {"technology": "Windows AppContainer (no capabilities) + Job Object",
                          "container": isolation.CONTAINER_NAME, "container_sid": getattr(self, "sid", None),
                          "child_processes": "blocked (child-process policy + job active-process limit 1)",
                          "network": "none (no capabilities)", "inherited_handles": "stdin/stdout/stderr pipes only",
                          "console": "none (DETACHED_PROCESS)", "profile_reset": "before and after the session",
                          "environment": sorted(isolation.default_environment()),
                          "windows_build": sys.getwindowsversion().build},
            "runtime_image": getattr(self, "image_info", None),
            "referee_command": getattr(self, "referee_command", None),
            "player_command": getattr(self, "player_command", None),
            "counts": dict(self.counts),
        }

    def _write_manifest(self) -> None:
        tmp = self.out / "host_session.json.tmp"
        tmp.write_text(json.dumps(self._manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.out / "host_session.json")

    # ------------------------------------------------------------------ processes
    def _start_referee(self) -> subprocess.Popen:
        c = self.config
        self.referee_command = [sys.executable, "-m", "rewardbench.blindplay.serve", "--out", str(self.out / "referee"),
                                "--player-label", c.player_label, "--player-is-ai", str(bool(self.gateway.is_model)).lower(),
                                "--seed", str(c.seed), "--episode-frame-budget", str(c.episode_frame_budget),
                                "--max-episodes", str(c.max_episodes), "--max-requests", str(c.max_requests),
                                "--max-wall-seconds", str(c.max_wall_seconds)]
        env = dict(os.environ)
        src = str(Path(__file__).resolve().parents[2])
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        return subprocess.Popen(self.referee_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=env)

    def _referee_call(self, request: dict[str, Any]) -> bytes:
        self._referee.stdin.write(json.dumps(request).encode("utf-8") + b"\n")
        self._referee.stdin.flush()
        line = self._referee.stdout.readline()
        if not line:
            raise RuntimeError("referee closed its output")
        return line

    def _drain_stderr(self, stream) -> None:
        logged = 0
        for raw in iter(lambda: stream.readline(65536), b""):
            logged += len(raw)
            if logged > MAX_PLAYER_STDERR:   # keep draining (the player must not block) but stop recording
                if logged - len(raw) <= MAX_PLAYER_STDERR:
                    self._append("player_stderr.jsonl", {"utc": _now(), "line": {"event": "stderr_truncated_by_host"}})
                continue
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            try:
                record: Any = json.loads(text)
            except ValueError:
                record = {"text": text}
            self._append("player_stderr.jsonl", {"utc": _now(), "line": record})

    # ------------------------------------------------------------------ broker
    def _reject(self, message: str) -> bytes:
        self.counts["rejected_by_host"] += 1
        return json.dumps(contract.error(message)).encode("utf-8") + b"\n"

    def _handle_game(self, request: Any) -> tuple[bytes, str]:
        try:
            tool, act = contract.parse_request(request)
        except contract.ActionRejected as exc:
            return self._reject(str(exc)), "rejected"
        canonical: dict[str, Any] = {"tool": tool}
        if act is not None:
            canonical.update(keys=list(act.keys), frames=act.frames)
        line = self._referee_call(canonical)
        self.counts["forwarded_to_referee"] += 1
        reply = json.loads(line)
        if "image" in reply:
            self.images[reply["seq"]] = {"sha256": reply["image"]["sha256"], "base64": reply["image"]["base64"]}
        return line, "forwarded"

    def _resolve_messages(self, messages: Any) -> list[dict[str, Any]]:
        if not isinstance(messages, list) or not 1 <= len(messages) <= 4000:
            raise contract.ActionRejected("messages must be a non-empty list")
        images = 0
        resolved = []
        for m in messages:
            if not isinstance(m, dict) or m.get("role") not in _MESSAGE_ROLES or not isinstance(m.get("content"), list):
                raise contract.ActionRejected("each message needs a role and a content list")
            if set(m) - {"role", "content", "tool_calls", "tool_call_id"}:
                raise contract.ActionRejected("unexpected message fields")
            parts = []
            for part in m["content"]:
                if not isinstance(part, dict):
                    raise contract.ActionRejected("content parts must be objects")
                if part.get("type") == "text" and set(part) == {"type", "text"} and isinstance(part["text"], str) \
                        and len(part["text"]) <= 20000:
                    parts.append(dict(part))
                elif part.get("type") == "image" and set(part) == {"type", "seq"} and type(part["seq"]) is int:
                    shown = self.images.get(part["seq"])
                    if shown is None:
                        raise contract.ActionRejected("image must be a screenshot this session returned")
                    images += 1
                    parts.append({"type": "image", "media_type": "image/png", "seq": part["seq"], **shown})
                else:
                    raise contract.ActionRejected("content parts must be text or a screenshot reference")
            resolved.append(dict(m, content=parts))
        if images > self.config.max_images_per_model_call:
            raise contract.ActionRejected(f"at most {self.config.max_images_per_model_call} screenshots per model call")
        return resolved

    def _handle_model(self, request: Any) -> tuple[bytes, str]:
        if set(request) != {"tool", "messages"}:
            self.counts["model_rejected"] += 1
            return self._reject("model requests contain only messages"), "rejected"
        if isinstance(self.gateway, DisabledGateway):
            self.counts["model_rejected"] += 1
            return self._reject("no model gateway is enabled for this session"), "rejected"
        if self.counts["model_calls"] >= self.config.max_model_calls:
            self.counts["model_rejected"] += 1
            return self._reject("model call budget exhausted"), "rejected"
        try:
            messages = self._resolve_messages(request["messages"])
        except contract.ActionRejected as exc:
            self.counts["model_rejected"] += 1
            return self._reject(str(exc)), "rejected"
        self.counts["model_calls"] += 1
        gateway_request = {"system": contract.OBJECTIVE, "tools": [dict(t) for t in contract.TOOLS], "messages": messages}
        result = self.gateway.complete(gateway_request)
        reply = {"protocol": contract.PROTOCOL, "text": str(result.get("text", ""))[:20000],
                 "tool_calls": [{"id": str(c.get("id", "")), "name": str(c.get("name", "")),
                                 "arguments": c.get("arguments", {})} for c in result.get("tool_calls", [])][:8]}
        shown = [{"role": m["role"], "content": [{k: v for k, v in p.items() if k != "base64"} for p in m["content"]]}
                 for m in messages]
        self._append("gateway_transcript.jsonl", {"call": self.counts["model_calls"], "utc": _now(),
                                                  "gateway": self.gateway.name, "system": gateway_request["system"],
                                                  "tools": [t["name"] for t in contract.TOOLS], "messages": shown,
                                                  "reply": reply})
        return json.dumps(reply).encode("utf-8") + b"\n", "model"

    def _handle_line(self, raw: bytes, overlong: bool) -> tuple[bytes, str]:
        if overlong:
            return self._reject(f"request longer than {MAX_GAME_LINE} bytes"), "rejected"
        request, rejection = serve.decode_line(raw) if len(raw) <= MAX_GAME_LINE else self._decode_model(raw)
        if rejection:
            return self._reject(rejection), "rejected"
        if isinstance(request, dict) and request.get("tool") == "model":
            return self._handle_model(request)
        return self._handle_game(request)

    @staticmethod
    def _decode_model(raw: bytes) -> tuple[Any, str | None]:
        """Only model requests may exceed the game line limit (they carry text history, never image bytes)."""
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None, "request is not valid UTF-8"
        try:
            request = json.loads(text, object_pairs_hook=serve._no_duplicates, parse_constant=serve._no_constant)
        except RecursionError:
            return None, "request is nested too deeply"
        except ValueError as exc:
            return None, f"request is not acceptable JSON: {type(exc).__name__}"
        if not (isinstance(request, dict) and request.get("tool") == "model"):
            return None, f"request longer than {MAX_GAME_LINE} bytes"
        return request, None

    def _read_player_line(self, stream) -> tuple[bytes, bool] | None:
        line = stream.readline(MAX_MODEL_LINE + 1)
        if not line:
            return None
        overlong = len(line) > MAX_MODEL_LINE and not line.endswith(b"\n")
        if overlong:
            while True:
                rest = stream.readline(MAX_MODEL_LINE)
                if not rest or rest.endswith(b"\n"):
                    break
        return line.rstrip(b"\r\n"), overlong

    # ------------------------------------------------------------------ session
    def run(self) -> dict[str, Any]:
        self.started = _now()
        c = self.config
        image = runtime_image.build(c.image_root)
        manifest = runtime_image.verify(image)
        self.image_info = {"path": str(image), "digest": manifest["digest"], "python": manifest["python"],
                           "files": len(manifest["files"])}
        self.sid = isolation.container_sid()
        self._write_manifest()
        self._referee = self._start_referee()
        player = drain = None
        deadline = time.monotonic() + c.max_wall_seconds + 60
        try:
            isolation.reset_profile()
            args = c.player_args(image)
            self.player_command = [str(runtime_image.python_executable(image)), *args]
            player = isolation.launch(runtime_image.python_executable(image), args, cwd=image)
            self.status = "running"
            self._write_manifest()
            drain = threading.Thread(target=self._drain_stderr, args=(player.stderr,), daemon=True)
            drain.start()
            while time.monotonic() < deadline and self.counts["player_lines"] < c.max_requests + 1000:
                item = self._read_player_line(player.stdout)
                if item is None:
                    break
                raw, overlong = item
                if not raw.strip():
                    continue
                self.counts["player_lines"] += 1
                received, t0 = _now(), time.monotonic()
                response, decision = self._handle_line(raw, overlong)
                try:
                    player.stdin.write(response)
                    player.stdin.flush()
                except OSError:
                    decision += "+player_gone"
                summary = json.loads(response)
                if "image" in summary:
                    summary["image"] = {"sha256": summary["image"]["sha256"]}
                self._append("host_transcript.jsonl", {
                    "index": self.counts["player_lines"], "received_utc": received, "seconds": round(time.monotonic() - t0, 6),
                    "raw_bytes": len(raw), "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "raw_head_base64": base64.b64encode(raw[:RECORDED_RAW_BYTES]).decode("ascii"), "overlong": overlong,
                    "decision": decision, "response": summary})
            self.status = "closed"
        except BaseException as exc:
            self.status = "aborted_host_failure"
            self.failure = f"{type(exc).__name__}: {str(exc)[:2000]}"
            raise
        finally:
            if player is not None:
                try:
                    player.stdin.close()
                except OSError:
                    pass
                player.wait(10)
                if drain is not None:
                    drain.join(10)
                player.close()
            self._referee.stdin.close()
            try:
                self._referee.wait(120)
            except subprocess.TimeoutExpired:
                self._referee.kill()
            isolation.reset_profile()   # wipe anything the player wrote to its own storage
            self._write_manifest()
            for f in self._files.values():
                f.close()
        return self._manifest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.host", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("scripted",), default="scripted",
                        help="only scripted NON-AI stand-ins can be started from the command line")
    parser.add_argument("--script", choices=("idle", "key-sweep", "seeded-random"), default="idle")
    parser.add_argument("--script-seed", type=int, default=0)
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--episode-frame-budget", type=int, default=session.DEFAULT_EPISODE_FRAME_BUDGET)
    args = parser.parse_args(argv)
    config = HostConfig(out=args.out, mode="scripted", script=args.script, script_seed=args.script_seed,
                        player_label=f"isolated scripted:{args.script} script_seed={args.script_seed} (NOT AI)",
                        max_episodes=args.episodes, episode_frame_budget=args.episode_frame_budget)
    print(json.dumps(Host(config).run()["counts"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
