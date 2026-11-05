"""The only code that could reach a real model, and the gate in front of it. **THE GATE IS CLOSED.**

TRUSTED HOST SIDE; never in the runtime image, never imported by ``host`` or ``model_gateway``. No real request has ever been
made with this code. Everything about it is tested against a local mock HTTP server.

Opening the gate takes all of the following, checked in this order, and each failure refuses without side effects:

1. ``model_gateway.LIVE_CALLS_PERMITTED`` set to True in a reviewed commit (nothing else is even looked at until then),
2. no provider credential in the environment (such a variable would also switch Claude Code to API billing),
3. an owner-written authorization file: exact fields, no placeholders, not expired, recent price check, bound to the exact
   configuration hash and the exact clean git commit, thinking setting supported,
4. an owner-supplied credential file outside the repository, private to the user, in the documented key format,
5. a live ledger whose opening balance includes the spending already recorded elsewhere.

``live_session.py`` adds a human confirmation at a real terminal on top.

Why the standard library's ``http.client`` and not a provider SDK: it is the smallest thing that can make this one request. It
reads no ambient credentials, ignores proxy variables, never retries (the gateway counts and pays for every attempt) and never
follows a redirect (which could carry the key to another host). It needs no new dependency.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from rewardbench.blindplay import contract, model_gateway, model_providers as providers, spend_ledger

AUTHORIZATION_SCHEMA = "react.blindplay.live-authorization.v1"
ANTHROPIC_HOST = "api.anthropic.com"
MESSAGES_PATH = "/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_AUTHORIZATION_DAYS = 7
MAX_PRICE_CHECK_AGE_DAYS = 7
# Adaptive thinking is refused for now. The documentation requires thinking blocks to be echoed during tool use, while the
# last-four-screenshots policy edits history in a way that invalidates them. See docs/LIVE_TRANSPORT_PREPARATION.md.
SUPPORTED_THINKING = ("disabled",)
_ALLOWED_WIRE_FIELDS = frozenset({"model", "max_tokens", "system", "tools", "tool_choice", "messages", "output_config", "thinking"})
_AMBIENT_CREDENTIALS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
_KEY_FORMAT = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,250}")
_PLACEHOLDER = "OWNER_"
REPOSITORY = Path(__file__).resolve().parents[3]
DISABLED_MESSAGE = ("live model calls are disabled (model_gateway.LIVE_CALLS_PERMITTED is False). Enabling them needs owner "
                    "authorization, pre-registration and a reviewed commit; see docs/LIVE_TRANSPORT_PREPARATION.md")

# PROVISIONAL engineering proposal from the Mission 015B brief. Not an approval, not permission to spend, not the final study.
PILOT_CANDIDATE: dict[str, Any] = {
    "provider": "anthropic", "model_id": "claude-haiku-5-5", "effort": "low", "thinking": "disabled",
    "keyset": contract.V2.keyset, "max_episodes": 1, "max_model_calls": 30,
    "session_cap_usd": "0.50", "cumulative_cap_usd": "1.00", "opening_balance_usd": "0.106019",
    "input_per_mtok": "0.10", "output_per_mtok": "0.50", "threshold_input_tokens": 100000,
    "over_threshold_input_per_mtok": "0.50", "over_threshold_output_per_mtok": "2.50",
    "pricing_source": "https://platform.claude.com/docs/en/about-claude/pricing",
}


class LiveGateRefused(RuntimeError):
    """The gate stays closed. Messages name what is wrong and never contain a credential."""


@dataclass(frozen=True)
class LiveAuthorization:
    schema: str
    approved_by: str
    approved_utc: str
    expires_utc: str
    pricing_verified_utc: str
    git_commit: str
    config_sha256: str
    provider: str
    model_id: str
    effort: str
    thinking: str
    keyset: str
    max_episodes: int
    max_model_calls: int
    session_cap_usd: str
    cumulative_cap_usd: str
    opening_balance_usd: str
    input_per_mtok: str
    output_per_mtok: str
    threshold_input_tokens: int
    over_threshold_input_per_mtok: str
    over_threshold_output_per_mtok: str
    pricing_source: str


def build_config(settings: Mapping[str, Any]) -> model_gateway.GatewayConfig:
    """The one place a live configuration is assembled. Everything not named here keeps the P1 default."""
    pricing = model_gateway.ModelPricing(
        settings["input_per_mtok"], settings["output_per_mtok"], source=settings["pricing_source"],
        threshold_input_tokens=settings["threshold_input_tokens"],
        over_threshold_input_per_mtok=settings["over_threshold_input_per_mtok"],
        over_threshold_output_per_mtok=settings["over_threshold_output_per_mtok"])
    return model_gateway.GatewayConfig(
        provider_id=settings["provider"], model_id=settings["model_id"], pricing=pricing, keyset=settings["keyset"],
        session_cap_usd=settings["session_cap_usd"], cumulative_cap_usd=settings["cumulative_cap_usd"],
        max_episodes=settings["max_episodes"], max_model_calls=settings["max_model_calls"],
        adapter_settings=(("effort", settings["effort"]), ("thinking", settings["thinking"])))


def git_state() -> dict[str, Any]:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPOSITORY, capture_output=True, text=True, timeout=10)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=REPOSITORY, capture_output=True, text=True, timeout=10)
        if head.returncode != 0 or status.returncode != 0:   # a failed status prints nothing, which must not read as "clean"
            return {"commit": None, "dirty": None}
        return {"commit": head.stdout.strip() or None, "dirty": bool(status.stdout.strip())}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def _utc(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise LiveGateRefused(f"authorization field {name} is not an ISO 8601 time") from None
    if parsed.tzinfo is None:
        raise LiveGateRefused(f"authorization field {name} needs a time zone")
    return parsed


def load_authorization(path: Path) -> LiveAuthorization:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise LiveGateRefused(f"cannot read the authorization file: {type(exc).__name__}") from None
    except ValueError:
        raise LiveGateRefused("the authorization file is not valid JSON") from None
    expected = {f.name for f in fields(LiveAuthorization)}
    if not isinstance(raw, dict) or set(raw) != expected:
        raise LiveGateRefused("the authorization file must have exactly the template's fields")
    if raw["schema"] != AUTHORIZATION_SCHEMA:
        raise LiveGateRefused("unknown authorization schema")
    for name, kinds in ((f.name, f.type) for f in fields(LiveAuthorization)):
        wanted = int if kinds == "int" else str
        if type(raw[name]) is not wanted:
            raise LiveGateRefused(f"authorization field {name} has the wrong type")
        if wanted is str and (_PLACEHOLDER in raw[name] or not raw[name].strip()):
            raise LiveGateRefused(f"authorization field {name} has not been filled in by the owner")
    return LiveAuthorization(**raw)


def _check_authorization(auth: LiveAuthorization, config: model_gateway.GatewayConfig, *, now: datetime, state: Mapping[str, Any]) -> None:
    if auth.provider != "anthropic":
        raise LiveGateRefused("only the anthropic adapter has a live transport")
    if auth.thinking not in SUPPORTED_THINKING:
        raise LiveGateRefused(f"thinking {auth.thinking!r} is not supported by the live gate: {SUPPORTED_THINKING}")
    if auth.config_sha256 != config.sha256():
        raise LiveGateRefused("the authorization's config_sha256 does not match its own settings")
    approved, expires = _utc(auth.approved_utc, "approved_utc"), _utc(auth.expires_utc, "expires_utc")
    if approved > now:
        raise LiveGateRefused("the authorization is dated in the future")
    if now >= expires:
        raise LiveGateRefused("the authorization has expired")
    if expires - approved > timedelta(days=MAX_AUTHORIZATION_DAYS):
        raise LiveGateRefused(f"an authorization may last at most {MAX_AUTHORIZATION_DAYS} days")
    verified = _utc(auth.pricing_verified_utc, "pricing_verified_utc")
    if verified > now:
        raise LiveGateRefused("prices cannot have been checked in the future")
    if now - verified > timedelta(days=MAX_PRICE_CHECK_AGE_DAYS):
        raise LiveGateRefused(f"prices must have been checked within the last {MAX_PRICE_CHECK_AGE_DAYS} days")
    if state["dirty"] is not False or state["commit"] != auth.git_commit:
        raise LiveGateRefused("the checkout must be clean and at the exact authorized commit")


def _refuse_ambient_credentials(environ: Mapping[str, str]) -> None:
    found = [name for name in _AMBIENT_CREDENTIALS if name in environ]
    if found:
        raise LiveGateRefused(f"remove {found} from the environment first: the key belongs only in its file, and these "
                              "variables would also switch Claude Code away from the subscription")


# Trustees whose access an AppContainer or another user could use: SDDL aliases and numeric SIDs, so the check does not
# depend on the language of Windows. Everyone, Users, Authenticated Users, Interactive, Network, All Application Packages
# (AC), anonymous, guests, domain users/guests, restricted code, power users and every individual AppContainer package SID
# (S-1-15-2-...) or capability SID (S-1-15-3-...). A specific other user's SID cannot be told from the owner's here.
_BROAD_TRUSTEES = {"WD", "BU", "AU", "IU", "NU", "AC", "AN", "BG", "DU", "DG", "RC", "WR", "PU", "LG", "DD", "DC", "RU", "CG",
                   "S-1-1-0", "S-1-5-32-545", "S-1-5-11", "S-1-5-4", "S-1-5-2", "S-1-5-7", "S-1-5-32-546", "S-1-5-32-547",
                   "S-1-5-32-554", "S-1-5-12", "S-1-5-33"}
_BROAD_RIDS = {"513", "514", "515"}      # Domain Users, Domain Guests, Domain Computers
_ALLOW_ACE = re.compile(r"\((A|OA|XA|ZA);[^;]*;[^;]*;[^;]*;[^;]*;([^;)]+)(?:;[^)]*)?\)")
_DACL_HEADER = re.compile(r"D:(NO_ACCESS_CONTROL|[PAIR]{0,6})(?=\(|S:|\s|$)")


def _is_broad(trustee: str) -> bool:
    t = trustee.strip().upper()
    return (t in _BROAD_TRUSTEES or t.startswith(("S-1-15-2-", "S-1-15-3-"))
            or (t.startswith("S-1-5-21-") and t.rsplit("-", 1)[-1] in _BROAD_RIDS))


def _sddl_is_private(sddl: str) -> bool:
    """False for a broad allow in any ACE shape, and also when the text has no DACL or has a NULL DACL: both mean that nobody
    is restricted. The last ``D:`` header wins, since a file name printed before the SDDL may contain one."""
    headers = list(_DACL_HEADER.finditer(sddl))
    if not headers or headers[-1].group(1) == "NO_ACCESS_CONTROL":
        return False
    for _kind, trustee in _ALLOW_ACE.findall(sddl[headers[-1].end():]):
        if _is_broad(trustee):
            return False
    return True


def _windows_acl_is_private(path: Path) -> bool:
    """False when the file grants access to a broad group or an AppContainer. Read as SDDL (``icacls /save``), which
    names trustees by SID alias, so the result does not depend on the Windows display language."""
    with tempfile.TemporaryDirectory() as scratch:
        saved = Path(scratch) / "acl.txt"
        done = subprocess.run(["icacls", str(path), "/save", str(saved), "/Q"], capture_output=True, timeout=15)
        if done.returncode != 0 or not saved.exists():
            return False   # cannot read the ACL: refuse
        text = saved.read_bytes().decode("utf-16", errors="replace")
    return _sddl_is_private(text)


def read_credential(path: Path) -> "_Secret":
    candidate = Path(path)
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise LiveGateRefused(f"cannot read the credential file: {type(exc).__name__}") from None
    if not stat.S_ISREG(info.st_mode):
        raise LiveGateRefused("the credential must be a regular file, not a link")
    resolved = candidate.resolve()
    if resolved.is_relative_to(REPOSITORY):
        raise LiveGateRefused("the credential file must be outside the repository")
    if info.st_size > 1024:
        raise LiveGateRefused("the credential file is too large to be a key")
    if sys.platform == "win32":
        if not _windows_acl_is_private(resolved):
            raise LiveGateRefused("the credential file is readable by other accounts; see the icacls step in the instructions")
    elif info.st_mode & 0o077:
        raise LiveGateRefused("the credential file must be private to your user (chmod 600)")
    try:
        text = resolved.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise LiveGateRefused(f"cannot read the credential file: {type(exc).__name__}") from None
    if not _KEY_FORMAT.fullmatch(text):
        raise LiveGateRefused("the credential file does not hold a key in the documented sk-ant- format")
    return _Secret(text)


class _Secret:
    """Holds the key. Printing, logging or formatting it shows nothing."""
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def header(self) -> str:
        return f"Bearer {self._value}"

    def __repr__(self) -> str:
        return "<credential hidden>"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("a credential cannot be pickled")


def _https_connection(timeout: float) -> http.client.HTTPConnection:
    return http.client.HTTPSConnection(ANTHROPIC_HOST, timeout=timeout, context=ssl.create_default_context())


class AnthropicLiveTransport:
    """POST /v1/messages, one attempt per call. Construct only through ``open_gate``."""
    is_offline = False

    def __init__(self, authorization: LiveAuthorization, secret: _Secret,
                 connection_factory: Callable[[float], http.client.HTTPConnection]) -> None:
        self.authorization = authorization
        self.authorized_config_sha256 = authorization.config_sha256
        self._secret = secret
        self._connect = connection_factory
        self.requests_sent = 0

    def __repr__(self) -> str:
        return f"<AnthropicLiveTransport model={self.authorization.model_id} requests_sent={self.requests_sent}>"

    def send(self, wire_request: dict[str, Any], timeout: float) -> providers.TransportResponse:
        if model_gateway.LIVE_CALLS_PERMITTED is not True:
            raise model_gateway.LiveCallsDisabled(DISABLED_MESSAGE)
        extra = set(wire_request) - _ALLOWED_WIRE_FIELDS
        if extra:
            raise model_gateway.LiveCallsDisabled(f"refusing to send unexpected request fields: {sorted(extra)}")
        if wire_request.get("model") != self.authorization.model_id:
            raise model_gateway.LiveCallsDisabled("refusing to send a request for a model that was not authorized")
        if self.requests_sent >= self.authorization.max_model_calls:
            raise model_gateway.LiveCallsDisabled("the authorized number of model calls has been used")
        self.requests_sent += 1
        body = json.dumps(wire_request).encode("utf-8")
        headers = {"Authorization": self._secret.header(), "anthropic-version": ANTHROPIC_VERSION, "content-type": "application/json"}
        connection = self._connect(timeout)
        try:
            connection.request("POST", MESSAGES_PATH, body=body, headers=headers)
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            received = {k.lower(): v for k, v in response.getheaders()}
            status = response.status
        except (socket.timeout, TimeoutError):
            raise providers.TransportTimeout("provider did not answer in time") from None
        finally:
            connection.close()
        if len(raw) > MAX_RESPONSE_BYTES:
            return providers.TransportResponse(status, None, received)
        try:
            parsed: Any = json.loads(raw)
        except ValueError:
            parsed = raw[:2000].decode("utf-8", errors="replace")
        return providers.TransportResponse(status, parsed, received)


@dataclass(frozen=True)
class LiveSession:
    """Everything needed to run one authorized session."""
    authorization: LiveAuthorization
    config: model_gateway.GatewayConfig
    adapter: providers.AnthropicMessagesAdapter
    transport: AnthropicLiveTransport
    ledger: spend_ledger.SpendLedger


def _open_ledger(path: Path, opening: Decimal) -> spend_ledger.SpendLedger:
    """Cumulative caps include what was spent before this ledger existed, so a new ledger starts with that balance."""
    new = not Path(path).exists()
    ledger = spend_ledger.SpendLedger(path, mode=spend_ledger.MODE_LIVE)
    if new:
        ledger.record_opening_balance(opening, "spending recorded in earlier missions, from the owner's authorization")
    state = ledger.state()
    if state.opening < opening:   # the recorded balance itself, not later charges that merely add up to as much
        raise LiveGateRefused("this ledger does not include the authorized opening balance")
    return ledger


def open_gate(*, authorization_path: Path, credential_path: Path, ledger_path: Path,
              connection_factory: Callable[[float], http.client.HTTPConnection] = _https_connection,
              state: Callable[[], Mapping[str, Any]] = git_state, now: Callable[[], datetime] | None = None) -> LiveSession:
    if model_gateway.LIVE_CALLS_PERMITTED is not True:
        raise model_gateway.LiveCallsDisabled(DISABLED_MESSAGE)
    _refuse_ambient_credentials(os.environ)
    auth = load_authorization(authorization_path)
    try:
        config = build_config({f.name: getattr(auth, f.name) for f in fields(LiveAuthorization)})
        adapter = providers.AnthropicMessagesAdapter(effort=auth.effort, thinking=auth.thinking)
        opening = spend_ledger.usd(auth.opening_balance_usd)
    except (ValueError, ArithmeticError) as exc:
        raise LiveGateRefused(f"the authorization's settings are not valid: {exc}") from None
    _check_authorization(auth, config, now=(now or (lambda: datetime.now(timezone.utc)))(), state=state())
    secret = read_credential(credential_path)
    ledger = _open_ledger(ledger_path, opening)
    return LiveSession(auth, config, adapter, AnthropicLiveTransport(auth, secret, connection_factory), ledger)
