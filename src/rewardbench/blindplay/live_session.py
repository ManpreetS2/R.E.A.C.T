"""Command line for one separately authorized model session. **While the gate is closed, ``run`` always refuses.**

    python -m rewardbench.blindplay.live_session template
    python -m rewardbench.blindplay.live_session run --authorization FILE --credential FILE --ledger FILE --out DIR

``template`` prints the provisional authorization for the owner to review, change and fill in. Printing it approves nothing.
``run`` needs an open gate (see ``live_transport``) and then a person typing an exact sentence at a real terminal, so no
script or automated agent can start spending on its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from rewardbench.blindplay import host as host_mod, live_transport, model_gateway, offline_demo


def template() -> dict[str, Any]:
    settings = dict(live_transport.PILOT_CANDIDATE)
    return {"schema": live_transport.AUTHORIZATION_SCHEMA, "approved_by": "OWNER_NAME", "approved_utc": "OWNER_ISO_TIME_UTC",
            "expires_utc": "OWNER_ISO_TIME_UTC", "pricing_verified_utc": "OWNER_ISO_TIME_UTC", "git_commit": "OWNER_COMMIT",
            "config_sha256": live_transport.build_config(settings).sha256(), **settings}


def confirmation_sentence(auth: live_transport.LiveAuthorization) -> str:
    return f"SPEND UP TO {auth.session_cap_usd} USD ON {auth.model_id}"


def require_human(auth: live_transport.LiveAuthorization, *, stdin: TextIO, stdout: TextIO) -> None:
    if not stdin.isatty():
        raise live_transport.LiveGateRefused("a person must confirm at a real terminal; input is not a terminal")
    sentence = confirmation_sentence(auth)
    stdout.write(f"This calls a real, paid API. Model {auth.model_id}, at most {auth.max_model_calls} calls, session cap "
                 f"${auth.session_cap_usd}, cumulative cap ${auth.cumulative_cap_usd}.\nType exactly: {sentence}\n> ")
    stdout.flush()
    if stdin.readline().rstrip("\r\n") != sentence:
        raise live_transport.LiveGateRefused("not confirmed")


def run_session(session: live_transport.LiveSession, *, out: Path, ledger_path: Path, player_label: str) -> dict[str, Any]:
    """One model session through the isolated host. Every session is reported, whatever happens."""
    config = session.config
    gateway = model_gateway.VisionGateway(config, session.adapter, session.transport, session.ledger, session_id=Path(out).name)
    manifest = host_mod.Host(host_mod.HostConfig(
        out=Path(out), mode="model", keyset=config.keyset, max_episodes=config.max_episodes,
        episode_frame_budget=config.episode_frame_budget, max_wall_seconds=config.max_wall_seconds,
        max_requests=config.max_game_requests, player_label=player_label), gateway=gateway).run()
    return {"host_status": manifest["status"], "gateway": manifest["gateway_session"], "player_is_ai": manifest["player_is_ai"],
            "audit": offline_demo.audit_session(Path(out), Path(ledger_path))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.live_session", description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("template", help="print the provisional authorization; this approves nothing")
    run = commands.add_parser("run", help="refuses while the live gate is closed")
    run.add_argument("--authorization", type=Path, required=True)
    run.add_argument("--credential", type=Path, required=True)
    run.add_argument("--ledger", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True, help="new, empty directory")
    args = parser.parse_args(argv)
    if args.command == "template":
        print(json.dumps(template(), indent=2))
        return 0
    try:
        session = live_transport.open_gate(authorization_path=args.authorization, credential_path=args.credential, ledger_path=args.ledger)
        require_human(session.authorization, stdin=sys.stdin, stdout=sys.stdout)
    except (model_gateway.LiveCallsDisabled, live_transport.LiveGateRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    report = run_session(session, out=args.out, ledger_path=args.ledger,
                         player_label=f"{session.authorization.model_id} (AI, authorized by {session.authorization.approved_by})")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
