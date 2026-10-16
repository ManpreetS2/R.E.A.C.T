#!/usr/bin/env python3
"""Keyless dry-run for the first authorized OpenAI pilot.

No API key. No network. Prints the shared prompt, local reservation quote,
Apollo schema validation of a mocked controller, and the owner checklist.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from rewardbench.config import load_config
from rewardbench.contracts import (
    EnvironmentSpec,
    FeedbackCondition,
    ModelRequest,
    Split,
)
from rewardbench.environments.apollolander.schema import (
    constant_controller,
    controller_schema_document,
    validate_controller,
)
from rewardbench.prompts import render_messages
from rewardbench.providers import build_model_client, preflight_first_call, require_preflight_ok
from rewardbench.providers.backends import ScriptedReply


def _request(config) -> ModelRequest:
    adapter_schema = controller_schema_document()
    return ModelRequest(
        contract_version="1.0.0",
        experiment_id="dry-run",
        session_id="dry-run",
        revision_index=0,
        feedback_condition=config.feedback_condition,
        split=config.split,
        environment=EnvironmentSpec(
            environment_id=config.environment_id,
            display_name="ApolloLander",
            task_description=(
                "Land the Apollo lander upright on the single designated pad of one "
                "fixed lunar map. Submit a controller object, not JavaScript."
            ),
            controller_schema=adapter_schema,
            action_space_summary="thrust from 0 to 1 and rotation in 10 degree steps from -90 to 90",
            observation_space_summary=(
                "x, y, vx, vy, rotation, fuel, altitude, and horizontal offset from the pad center"
            ),
        ),
        history=(),
        model_settings=dict(config.model_settings),
    )


def main() -> int:
    config_path = ROOT / "configs" / "apollolander_pilot_openai_gpt54mini.yaml"
    config = load_config(config_path)
    request = _request(config)
    system, user = render_messages(request)

    print("=== Agent 3 dry-run first call (offline) ===")
    print(f"config: {config_path}")
    print(f"provider/model: {config.provider}/{config.model_id}")
    print(f"feedback_condition: {config.feedback_condition.value}")
    print(f"model_settings: {json.dumps(dict(config.model_settings), sort_keys=True)}")
    print()

    preflight = require_preflight_ok(
        preflight_first_call(
            provider=config.provider,
            model_id=config.model_id,
            request=request,
            max_spend_usd=float(config.budget.max_cost_usd or 0.05),
            http_attempts=config.max_model_retries + 1,
        )
    )
    print("preflight: OK (local catalog only)")
    print(f"  catalog: {preflight.catalog_version}")
    print(f"  reserved_usd: {preflight.quote.usd:.6f}")
    print(f"  prompt_token_ceiling: {preflight.quote.prompt_tokens}")
    print(f"  max_output_tokens: {preflight.max_output_tokens}")
    print(f"  reasoning_effort: {preflight.reasoning_effort!r}")
    print(f"  system_chars/user_chars: {preflight.system_chars}/{preflight.user_chars}")
    for note in preflight.notes:
        print(f"  note: {note}")
    print()

    mocked = constant_controller(0.4, -20)
    client = build_model_client(
        "mock",
        "offline-dry-run",
        mock_script=[ScriptedReply(text=json.dumps(mocked, sort_keys=True))],
    )
    response = client.propose(request)
    status = validate_controller(dict(response.parameters or {}))
    print("mocked propose + Apollo schema validation:")
    print(f"  parse_error: {response.parse_error}")
    print(f"  controller_valid: {status.valid} policy={status.policy}")
    print(f"  parameters: {json.dumps(dict(response.parameters or {}), sort_keys=True)}")
    print()

    print("prompt excerpts (feedback isolation check):")
    print(f"  system starts: {system.splitlines()[0]!r}")
    assert "reward=" not in user
    print("  first-revision user prompt contains no reward= lines: OK")
    print(f"  schema id present: {adapter_schema_id_ok(user)}")
    print()

    print("owner checklist before any real spend:")
    for item in (
        "Explicit written approval to spend real money",
        "OpenAI account billing hard limit / alert configured outside this repo",
        "export OPENAI_API_KEY in a local shell (never commit or paste into chat)",
        "build_model_client(..., max_spend_usd=0.05, max_retries=0)",
        "keep reasoning_effort=none and max_output_tokens=800 for the first call",
        "run one revision only; inspect SQLite usage before any second call",
        "remember: in-process locks cannot stop concurrent processes or invoice discrepancies",
    ):
        print(f"  [ ] {item}")
    print()
    print("No network sockets were opened. No API key was read.")
    return 0 if status.valid and response.parse_error is None else 1


def adapter_schema_id_ok(user: str) -> str:
    needle = "rewardbench.apollolander.controller.v1"
    return "OK" if needle in user else "MISSING"


if __name__ == "__main__":
    raise SystemExit(main())
