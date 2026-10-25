"""Authorized live-provider wiring for the experiment CLI.

This module does not reimplement providers. It validates controls, builds a
client through ``rewardbench.providers.build_model_client``, and gates how many
new paid ``propose`` calls a single CLI invocation may make.

A one-call pilot that stops with remaining revisions is **paused**, not a
completed learning experiment.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rewardbench import CONTRACT_VERSION
from rewardbench.contracts import (
    BudgetExceeded,
    ConfigError,
    EnvironmentAdapter,
    ExperimentConfig,
    FeedbackCondition,
    ModelClient,
    ModelClientError,
    ModelRequest,
    Split,
)
from rewardbench.prompts import render_messages
from rewardbench.providers.backends import resolve_api_key
from rewardbench.providers.client import build_model_client
from rewardbench.providers.pricing import PriceQuote, load_catalog, quote_call

# Mirrors rewardbench.providers.client live providers without importing private tables.
LIVE_PROVIDERS = ("openai", "google", "anthropic", "xai")
_CREDENTIAL_ENV = {
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY or GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "xai": "XAI_API_KEY",
}
ACK_PAID_FLAG = "--i-authorize-paid-api-calls"
ACK_CONTINUATION_FLAG = "--authorize-continuation"
SESSION_CALL_RESOURCE = "live_session_model_calls"


@dataclass(frozen=True)
class LivePreflight:
    """Checks that must pass before the first paid ``propose`` in a session."""

    provider: str
    model_id: str
    catalog_version: str
    quote: PriceQuote
    credential_env: str
    max_new_paid_calls: int
    max_model_retries: int
    max_cost_usd: float
    controller_schema_id: str | None


class SessionPaidCallGate:
    """Allow a fixed number of new ``propose`` calls in one CLI process.

    Further calls raise ``BudgetExceeded`` with ``resource=live_session_model_calls``
    so the runner stops without marking a multi-revision pilot as completed.
    """

    def __init__(self, inner: ModelClient, *, max_new_calls: int) -> None:
        if isinstance(max_new_calls, bool) or not isinstance(max_new_calls, int) or max_new_calls < 1:
            raise ConfigError("max_new_paid_calls must be an integer >= 1")
        self._inner = inner
        self.max_new_calls = max_new_calls
        self.calls_started = 0

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    def propose(self, request: ModelRequest):
        if self.calls_started >= self.max_new_calls:
            raise BudgetExceeded(
                (
                    "live session paid-call limit reached "
                    f"({self.calls_started}/{self.max_new_calls}). "
                    f"Re-run with {ACK_CONTINUATION_FLAG} after reviewing SQLite "
                    "to authorize another paid model request. "
                    "This pause is not a completed learning experiment."
                ),
                resource=SESSION_CALL_RESOURCE,
                spent=float(self.calls_started),
                limit=float(self.max_new_calls),
            )
        self.calls_started += 1
        return self._inner.propose(request)


def validate_live_authorization(
    *,
    authorize_paid: bool,
    authorize_continuation: bool,
    resume_selected_attempts: int,
) -> None:
    """Fail closed unless the operator explicitly opts into paid calls."""

    if not authorize_paid:
        raise ConfigError(
            "live mode refuses to run without explicit paid-call acknowledgment. "
            f"Pass {ACK_PAID_FLAG}. Default mode remains mock and spends nothing."
        )
    if resume_selected_attempts > 0 and not authorize_continuation:
        raise ConfigError(
            "this experiment already has stored controller attempts. "
            f"A second (or later) paid revision requires {ACK_CONTINUATION_FLAG} "
            f"together with {ACK_PAID_FLAG}. Resume will not repeat completed calls."
        )


def preflight_live(
    config: ExperimentConfig,
    environment: EnvironmentAdapter,
    *,
    max_new_paid_calls: int = 1,
    api_key: str | None = None,
) -> LivePreflight:
    """Validate provider, pricing, credentials, budget, retries, and schema.

    Does not open a provider socket and does not call ``propose``.
    """

    if config.split is not Split.DEVELOPMENT:
        raise ConfigError("live adaptation requires split=development; use rewardbench.heldout")
    if config.provider == "mock":
        raise ConfigError("live mode requires a real provider; use --mode mock for the scripted model")
    if config.provider not in LIVE_PROVIDERS:
        raise ConfigError(
            f"unsupported live provider {config.provider!r}; expected one of {LIVE_PROVIDERS}"
        )
    if not isinstance(config.model_id, str) or not config.model_id.strip():
        raise ConfigError("model_id must be a non-empty string for live mode")
    if config.max_model_retries != 0:
        raise ConfigError(
            "live pilot requires max_model_retries=0 so a failed propose cannot "
            "silently purchase retries"
        )
    if config.budget.max_cost_usd is None:
        raise ConfigError("live mode requires budget.max_cost_usd as a hard cost ceiling")
    if config.budget.max_model_calls is None:
        raise ConfigError("live mode requires budget.max_model_calls")
    if config.budget.max_model_calls < 1:
        raise ConfigError("budget.max_model_calls must be >= 1")
    if max_new_paid_calls < 1:
        raise ConfigError("max_new_paid_calls must be >= 1")
    if max_new_paid_calls > 1:
        raise ConfigError(
            "first live pilot invocations allow at most one new paid model request; "
            "use a separately authorized continuation for the next revision"
        )

    settings = dict(config.model_settings)
    if "max_output_tokens" not in settings:
        raise ConfigError(
            "live mode requires model_settings.max_output_tokens so pricing can bound output"
        )

    catalog = load_catalog()
    rate = catalog.rate_for(config.provider, config.model_id)
    if rate is None:
        raise ConfigError(
            f"model {config.provider}:{config.model_id} is unpriced in catalog "
            f"{catalog.version}; refusing live mode"
        )

    try:
        key = resolve_api_key(config.provider, api_key)
    except LookupError as exc:
        raise ConfigError(
            f"{config.provider} API key is not set; expected {exc}. "
            "Live mode will not construct a client without credentials."
        ) from exc
    if not key.strip():
        raise ConfigError(f"{config.provider} API key is empty")

    spec = environment.describe()
    if spec.environment_id != config.environment_id:
        raise ConfigError(
            f"environment id {spec.environment_id!r} does not match config "
            f"{config.environment_id!r}"
        )
    if not isinstance(spec.controller_schema, Mapping) or not spec.controller_schema:
        raise ConfigError("environment controller_schema is missing; refusing live mode")
    schema_id = spec.controller_schema.get("schema")
    if schema_id is not None and not isinstance(schema_id, str):
        raise ConfigError("controller_schema.schema must be a string when present")

    probe = ModelRequest(
        contract_version=CONTRACT_VERSION,
        experiment_id="preflight",
        session_id="preflight",
        revision_index=0,
        feedback_condition=config.feedback_condition,
        split=config.split,
        environment=spec,
        history=(),
        model_settings=settings,
    )
    if probe.feedback_condition not in (
        FeedbackCondition.NO_FEEDBACK,
        FeedbackCondition.NUMERICAL_REWARD,
        FeedbackCondition.REWARD_ONLY,
    ):
        raise ConfigError(f"unsupported feedback_condition {probe.feedback_condition!r}")
    if probe.split not in (Split.DEVELOPMENT, Split.HELD_OUT):
        raise ConfigError(f"unsupported split {probe.split!r}")

    system_text, user_text = render_messages(probe)
    quote = quote_call(
        catalog,
        config.provider,
        config.model_id,
        system_text=system_text,
        user_text=user_text,
        settings=settings,
        attempts=config.max_model_retries + 1,
    )
    if not quote.available:
        raise ConfigError(
            f"live pricing cannot bound this call ({quote.status}: {quote.note}); refusing"
        )
    if quote.usd > float(config.budget.max_cost_usd):
        raise ConfigError(
            f"worst-case quote ${quote.usd:.6f} exceeds budget.max_cost_usd "
            f"${float(config.budget.max_cost_usd):.6f}; refusing"
        )

    return LivePreflight(
        provider=config.provider,
        model_id=config.model_id,
        catalog_version=catalog.version,
        quote=quote,
        credential_env=_CREDENTIAL_ENV.get(config.provider, "API_KEY"),
        max_new_paid_calls=max_new_paid_calls,
        max_model_retries=config.max_model_retries,
        max_cost_usd=float(config.budget.max_cost_usd),
        controller_schema_id=schema_id if isinstance(schema_id, str) else None,
    )


def build_live_model(
    config: ExperimentConfig,
    *,
    max_new_paid_calls: int = 1,
    api_key: str | None = None,
    transport: Any | None = None,
    sleeper: Any | None = None,
) -> SessionPaidCallGate:
    """Construct a gated live client via the shared provider factory."""

    try:
        inner = build_model_client(
            config.provider,
            config.model_id,
            api_key=api_key,
            transport=transport,
            max_spend_usd=config.budget.max_cost_usd,
            max_retries=config.max_model_retries,
            sleeper=sleeper,
        )
    except ModelClientError as exc:
        raise ConfigError(str(exc)) from exc
    return SessionPaidCallGate(inner, max_new_calls=max_new_paid_calls)


def is_session_pause(summary_error: str | None, *, status_value: str) -> bool:
    """True when the runner stopped because this CLI session's paid-call gate closed."""

    if status_value not in {"interrupted", "budget_exhausted"}:
        return False
    text = summary_error or ""
    return SESSION_CALL_RESOURCE in text or "live session paid-call limit" in text
