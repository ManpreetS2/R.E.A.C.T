"""Offline end-to-end demonstration of the model gateway, with a mocked provider. $0, no network, NOT A MODEL.

The real isolated player, real referee, real upstream game and real screenshots run; only the "model" is a fixed script
that ignores the screen. It presses no landing sequence, and the outcome (crashes) means nothing about AI. It exercises
what a real session would hit: normal actions, a hallucinated tool, bad arguments, the speed key, an oversized batch, a
reply with no tool call, a rate limit and a server error. Then it audits the records and replays the referee session.

    python -m rewardbench.blindplay.offline_demo --out runs/blind-visual/<new-id>
"""

from __future__ import annotations

import argparse
import json
import platform
import re
from pathlib import Path
from typing import Any

from rewardbench.blindplay import contract, host as host_mod, model_gateway, model_providers as providers, replay, spend_ledger

MOCK_MODEL_ID = "mock-vision-0"
MOCK_PRICING = model_gateway.ModelPricing("0.10", "0.50", source="MOCK prices for the offline demo; no money exists here")
# Words for what only the referee may know. They must never appear in anything sent to a model.
PRIVILEGED_WORDS = re.compile(r"\b(gameState|fuel|altitude|velocity|vx|vy|rotation|referee|lander|landed|crashed|score|"
                              r"terminal_tick_state|native_message|keysDown)\b", re.I)


def _act(call_id: str, keys: list[str], frames: int) -> dict[str, Any]:
    return {"id": call_id, "name": "act", "arguments": {"keys": keys, "frames": frames}}


def demo_script() -> list[Any]:
    """A fixed list. No item reads the request; the later idle default just runs the two episodes out."""
    return [
        {"text": "Let me look.", "tool_calls": [{"id": "c1", "name": "observe", "arguments": {}}]},
        {"text": "Trying a key.", "tool_calls": [_act("c2", ["ArrowUp"], 30)]},
        {"text": "Reading the source.", "tool_calls": [{"id": "c3", "name": "read_file", "arguments": {"path": "game.js"}}]},
        {"text": "Bad frames.", "tool_calls": [_act("c4", ["ArrowUp"], 9999)]},
        {"text": "Speed key.", "tool_calls": [_act("c5", ["KeyS"], 10)]},
        {"text": "No tool this time.", "tool_calls": []},
        providers.TransportResponse(429, {"error": "slow down, key sk-demo-not-a-real-key"}, {"retry-after": "1"}),
        providers.TransportResponse(500, {"error": "upstream failed"}),
        {"text": "Too many at once.", "tool_calls": [_act(f"b{i}", [], 10) for i in range(10)]},
    ]


def default_reply() -> Any:
    counter = iter(range(1, 100000))

    def reply(_wire: dict[str, Any]) -> dict[str, Any]:
        return {"text": "", "tool_calls": [_act(f"idle{next(counter)}", [], contract.MAX_FRAMES_PER_ACT)]}
    return reply


def audit_session(session: Path, ledger_path: Path) -> dict[str, Any]:
    """Cross-check a finished session's records against the ledger. Read-only; usable after a crash too."""
    records = [json.loads(x) for x in (session / "gateway_transcript.jsonl").read_text(encoding="utf-8").splitlines() if x]
    chain = model_gateway.verify_transcript(records)
    state = spend_ledger.SpendLedger(ledger_path, mode=json.loads(ledger_path.read_text(encoding="utf-8").splitlines()[0])["mode"]).state()
    calls = [r for r in records if r.get("event") == "model_call"]
    max_images, leaks = 0, []
    for r in calls:
        shown = json.dumps(r["messages"])
        max_images = max(max_images, shown.count('"type": "image"'))
        leaks += PRIVILEGED_WORDS.findall(shown)
    return {"transcript": chain, "model_call_records": len(calls), "max_images_in_a_call": max_images,
            "privileged_words_sent": sorted(set(leaks)), "ledger_spent_usd": str(state.spent),
            "ledger_open_reservations": sorted(state.open_reservations),
            "ledger_matches_transcript": chain.get("charged_usd") is not None
            and spend_ledger.usd(chain["charged_usd"]) == state.spent}


def run_demo(base: Path, *, max_episodes: int = 2, episode_frame_budget: int = 2000) -> dict[str, Any]:
    base = Path(base)
    if base.exists() and any(base.iterdir()):
        raise FileExistsError(f"{base} is not empty; records are never overwritten")
    base.mkdir(parents=True, exist_ok=True)
    ledger = spend_ledger.SpendLedger(base / "mock_ledger.jsonl", mode=spend_ledger.MODE_OFFLINE_MOCK)
    config = model_gateway.GatewayConfig(provider_id="offline-mock", model_id=MOCK_MODEL_ID, pricing=MOCK_PRICING,
                                         session_cap_usd="0.05", cumulative_cap_usd="0.05", max_episodes=max_episodes,
                                         episode_frame_budget=episode_frame_budget, max_model_calls=80,
                                         max_wall_seconds=900.0)
    provider = providers.MockVisionProvider(demo_script(), model=MOCK_MODEL_ID, default=default_reply())
    gateway = model_gateway.VisionGateway(config, providers.MockAdapter(), providers.OfflineTransport(provider), ledger,
                                          session_id=base.name, sleep=lambda _seconds: None)
    host_config = host_mod.HostConfig(out=base / "session", mode="model", keyset=config.keyset, max_episodes=max_episodes,
                                      episode_frame_budget=episode_frame_budget, max_wall_seconds=config.max_wall_seconds,
                                      max_requests=1000, player_label="offline demo: mock provider (NOT A MODEL, NOT AI)")
    manifest = host_mod.Host(host_config, gateway=gateway).run()
    audit = audit_session(base / "session", base / "mock_ledger.jsonl")
    receipt = replay.replay(base / "session" / "referee")
    referee = json.loads((base / "session" / "referee" / "session.json").read_text(encoding="utf-8"))
    report = {
        "disclaimer": providers.MOCK_DISCLAIMER, "paid_api_calls": 0, "network_transport_exists": False,
        "platform": platform.platform(), "isolation": (manifest["isolation"] or {}).get("technology"),
        "git": referee["software"]["git"], "browser": referee["software"]["browser"],
        "runtime_image_digest": manifest["runtime_image"]["digest"], "host_status": manifest["status"],
        "player_exit_code": manifest["player_exit_code"], "player_is_ai": manifest["player_is_ai"],
        "contract": referee["player_contract"]["protocol"], "keyset": referee["player_contract"]["keyset"],
        "allowed_keys": referee["player_contract"]["allowed_keys"], "episode_outcomes": referee["episode_outcomes"],
        "host_counts": manifest["counts"], "gateway": {k: manifest["gateway_session"][k] for k in
                                                       ("stop_reason", "counts", "charged_usd", "config_sha256", "transcript_records", "transcript_tip_sha256")},
        "mock_requests_received": len(provider.requests),
        "images_per_request": sorted({len(x) for x in provider.images_received}), "audit": audit,
        "replay": {k: receipt[k] for k in ("requests", "screenshots_compared", "screenshots_identical", "reproduced")},
    }
    (base / "demo_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.offline_demo", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="new, empty directory")
    args = parser.parse_args(argv)
    report = run_demo(args.out)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["replay"]["reproduced"] and report["audit"]["transcript"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
