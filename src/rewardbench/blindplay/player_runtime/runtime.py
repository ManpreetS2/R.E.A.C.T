"""Player-side runtime. Runs INSIDE the isolated AppContainer, from the read-only runtime image.

Standard library only; imports nothing from the repository (the sandbox could not read it anyway).
It talks to the trusted host over its own stdin/stdout, one JSON object per line:

    {"tool": "brief"} | {"tool": "observe"} | {"tool": "act", "keys": [...], "frames": n}
    {"tool": "model", "messages": [...]}      (host-side model gateway; disabled unless the host enables it)

Modes (chosen by the host, which builds this command line; the player cannot choose):

* ``scripted``  NON-AI stand-in input scripts (idle, key-sweep, seeded-random) that never look at the screen.
* ``probe``     NON-AI security stand-in: tries to break out of the sandbox and to misuse the host
                protocol, reports every result as JSON lines on stderr, then plays a fixed scripted input.
* ``agent``     the loop a future vision model would run in: screenshots go to the model only through
                the host gateway (as references the host resolves), tool calls come back and are executed
                through the host. The model never gets any other tool.
"""

from __future__ import annotations

import argparse
import json
import random
import sys

PROTOCOL = "react.blindplay.runtime.v1"


class HostError(RuntimeError):
    pass


class Host:
    """The only channel out of the sandbox: our stdin/stdout pipes, owned by the trusted host."""

    def __init__(self, stdin=None, stdout=None) -> None:
        self._in = stdin or sys.stdin.buffer
        self._out = stdout or sys.stdout.buffer

    def raw(self, line: bytes) -> dict:
        self._out.write(line.rstrip(b"\n") + b"\n")
        self._out.flush()
        reply = self._in.readline()
        if not reply:
            raise HostError("host closed the connection")
        return json.loads(reply)

    def call(self, request: dict) -> dict:
        return self.raw(json.dumps(request).encode("utf-8"))

    def brief(self) -> dict:
        return self.call({"tool": "brief"})

    def observe(self) -> dict:
        return self.call({"tool": "observe"})

    def act(self, keys, frames: int) -> dict:
        return self.call({"tool": "act", "keys": list(keys), "frames": frames})


def report(**fields) -> None:
    sys.stderr.write(json.dumps(fields, sort_keys=True) + "\n")
    sys.stderr.flush()


# ------------------------------------------------------------------ scripted (NON-AI) stand-ins
def run_scripted(host: Host, script: str, script_seed: int) -> int:
    brief = host.brief()
    keys, max_frames = brief["keyset"]["keys"], brief["max_frames_per_act"]
    rng = random.Random(script_seed)
    cycle = list(keys) + [None]
    obs, step = host.observe(), 0
    while not obs.get("session_over"):
        if "error" in obs:
            raise HostError(obs["error"])
        if script == "idle":
            pressed, frames = [], max_frames
        elif script == "key-sweep":
            key = cycle[step % len(cycle)]
            pressed, frames = ([key] if key else []), 20
        elif script == "seeded-random":
            pressed, frames = rng.sample(keys, rng.randint(0, 2)), rng.randint(1, max_frames)
        else:
            raise SystemExit(f"unknown script {script}")
        obs = host.act(pressed, frames)
        step += 1
    report(event="scripted_done", script=script, act_calls=step)
    return 0


# ------------------------------------------------------------------ agent loop (for a future model)
SYSTEM_NOTE = "Land the rocket."


def _tool_result(call_id: str, obs: dict) -> dict:
    counters = {k: obs[k] for k in ("episode", "episode_frame", "episode_frame_budget", "max_episodes",
                                    "frames_advanced", "episode_ended", "session_over") if k in obs}
    content = [{"type": "text", "text": json.dumps(counters if "image" in obs else {"error": obs.get("error")})}]
    if "image" in obs:
        content.append({"type": "image", "seq": obs["seq"]})
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def run_agent(host: Host, image_window: int, max_model_calls: int) -> int:
    """Conversation loop. Memory = the whole text history of this session; only the last ``image_window``
    screenshots are sent again (older ones are replaced by a note). Nothing persists after the session."""
    host.brief()
    first = host.observe()
    messages = [{"role": "user", "content": [{"type": "text", "text": SYSTEM_NOTE}, {"type": "image", "seq": first["seq"]}]}]
    calls = 0
    session_over = False
    while not session_over and calls < max_model_calls:
        reply = host.call({"tool": "model", "messages": _window(messages, image_window)})
        calls += 1
        if "error" in reply:
            report(event="model_unavailable", error=reply["error"])
            return 0
        messages.append({"role": "assistant", "content": [{"type": "text", "text": reply.get("text", "")}],
                         "tool_calls": reply.get("tool_calls", [])})
        if not reply.get("tool_calls"):
            messages.append({"role": "user", "content": [{"type": "text", "text": "Use a tool to continue."}]})
            continue
        for call in reply["tool_calls"]:
            args = call.get("arguments", {})
            if call.get("name") == "observe":
                obs = host.observe()
            elif call.get("name") == "act":
                obs = host.call({"tool": "act", "keys": args.get("keys"), "frames": args.get("frames")})
            else:
                obs = {"error": "unknown tool"}
            messages.append(_tool_result(call.get("id", ""), obs))
            session_over = bool(obs.get("session_over"))
            if session_over:
                break
    report(event="agent_done", model_calls=calls, session_over=session_over)
    return 0


def _window(messages: list, image_window: int) -> list:
    seen = 0
    out = []
    for m in reversed(messages):
        content = []
        for part in m["content"]:
            if part.get("type") == "image":
                seen += 1
                if seen > image_window:
                    part = {"type": "text", "text": "[earlier screenshot omitted]"}
            content.append(part)
        out.append(dict(m, content=content))
    return list(reversed(out))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="player_runtime")
    parser.add_argument("--mode", choices=("scripted", "probe", "agent"), required=True)
    parser.add_argument("--script", default="idle")
    parser.add_argument("--script-seed", type=int, default=0)
    parser.add_argument("--probe-targets", default="{}", help="JSON; probe mode only (security tests)")
    parser.add_argument("--image-window", type=int, default=4)
    parser.add_argument("--max-model-calls", type=int, default=0)
    args = parser.parse_args(argv)
    host = Host()
    if args.mode == "scripted":
        return run_scripted(host, args.script, args.script_seed)
    if args.mode == "agent":
        return run_agent(host, args.image_window, args.max_model_calls)
    import probes
    return probes.run(host, json.loads(args.probe_targets))


if __name__ == "__main__":
    raise SystemExit(main())
