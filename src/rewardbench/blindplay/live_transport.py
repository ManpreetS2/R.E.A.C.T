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


# FAIL-CLOSED ALLOWLIST (Mission 018, owner amendment replacing the earlier deny-list). A credential file is private only
# if every allow-type ACE of its DACL names one of these trustees, and its owner is one of them as well:
#   * the SID of the user running this process (read from the process token, never from a display name);
#   * OWNER RIGHTS (OW, S-1-3-4): means "the file's owner", who must already be on this list (Python and pytest create private
#     files with exactly this ACE), so it adds no principal;
#   * SYSTEM (SY, S-1-5-18) and built-in Administrators (BA, S-1-5-32-544): both can read any file or take ownership of it
#     anyway, and the owner's setup instructions already tolerate them. No other principal is allowed, so every other user
#     SID, group, alias, AppContainer or capability SID, unknown token, Everyone, Users and Authenticated Users is refused.
# CREATOR OWNER (CO) is deliberately not allowed: it is not needed on a plain file.
_PRIVILEGED_TRUSTEES = frozenset({"SY", "S-1-5-18", "BA", "S-1-5-32-544", "OW", "S-1-3-4"})
_DACL_HEADER = re.compile(r"D:(NO_ACCESS_CONTROL|[PAIR]{0,6})(?=\(|S:|\s|$)")
_OWNER = re.compile(r"(?mi)^O:(S-1-[0-9-]+|[A-Za-z]{2})(?=G:|D:|S:|\s|$)")
_SACL_START = re.compile(r"(?:(?<=\))|^)S:")
_DACL_BODY = re.compile(r'(?:\([^()"]*\))*')


def _sddl_is_private(sddl: str, current_sid: "str | None" = None) -> bool:
    """True only when the owner and every allow ACE are in the allowlist above (current user SID, SY, BA). Anything else
    is refused: a NULL, missing or unparseable DACL, an unknown or conditional ACE, an unknown ACE type, a missing owner,
    or no current-user SID. Deny ACEs grant nothing. The last ``D:`` header wins, since a file name printed before the
    SDDL may contain one."""
    if current_sid is None:
        current_sid = _current_user_sid()
    if not current_sid or not re.fullmatch(r"S-1-[0-9-]+", current_sid.strip(), re.IGNORECASE):
        return False
    allowed = _PRIVILEGED_TRUSTEES | {current_sid.strip().upper()}
    owners = list(_OWNER.finditer(sddl))
    if not owners or owners[-1].group(1).upper() not in allowed:
        return False
    headers = list(_DACL_HEADER.finditer(sddl))
    if not headers or headers[-1].group(1) == "NO_ACCESS_CONTROL":
        return False
    rest = sddl[headers[-1].end():].rstrip()
    sacl = _SACL_START.search(rest)
    body = rest[:sacl.start()] if sacl else rest
    if not _DACL_BODY.fullmatch(body):
        return False
    for ace in re.findall(r"\(([^()]*)\)", body):
        fields = ace.split(";")
        kind = fields[0].strip().upper()
        if kind in ("D", "OD"):
            continue
        if kind not in ("A", "OA") or len(fields) != 6 or fields[5].strip().upper() not in allowed:
            return False
    return True


def _current_user_sid() -> "str | None":
    """SID string of the process token's user (locale independent), or None if it cannot be determined."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        advapi, kernel = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
        advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                               ctypes.POINTER(wintypes.DWORD)]
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        token = wintypes.HANDLE()
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x8, ctypes.byref(token)):   # TOKEN_QUERY
            return None
        try:
            size = wintypes.DWORD(0)
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))   # TokenUser
            buf = ctypes.create_string_buffer(size.value)
            if not size.value or not advapi.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
                return None
            sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            text = ctypes.c_void_p()
            if not sid_ptr or not advapi.ConvertSidToStringSidW(sid_ptr, ctypes.byref(text)):
                return None
            try:
                return ctypes.wstring_at(text.value)
            finally:
                kernel.LocalFree(text)
        finally:
            kernel.CloseHandle(token)
    except Exception:   # noqa: BLE001 - any failure means "unknown": the caller refuses
        return None


def _file_owner_and_dacl_sddl(path: Path) -> "str | None":
    """``O:...D:...`` SDDL of the file's owner and DACL from the Win32 API, or None on any failure. A NULL DACL yields
    text without ``D:``."""
    try:
        import ctypes
        from ctypes import wintypes
        advapi, kernel = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        advapi.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                                 ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        advapi.GetNamedSecurityInfoW.restype = wintypes.DWORD
        advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        descriptor = ctypes.c_void_p()
        # SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION
        if advapi.GetNamedSecurityInfoW(str(path), 1, 0x1 | 0x4, None, None, None, None, ctypes.byref(descriptor)) != 0:
            return None
        try:
            text = ctypes.c_void_p()
            if not advapi.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor, 1, 0x1 | 0x4, ctypes.byref(text), None):
                return None
            try:
                return ctypes.wstring_at(text.value)
            finally:
                kernel.LocalFree(text)
        finally:
            kernel.LocalFree(descriptor)
    except Exception:   # noqa: BLE001
        return None


def _windows_acl_is_private(path: Path) -> bool:
    """True only when the owner and every allow ACE of the file are the current user, SYSTEM or Administrators. The
    descriptor is read as SDDL, which names trustees by SID or alias, so the result does not depend on the display language.
    Any failure to read the ACL or the current SID refuses."""
    sid = _current_user_sid()
    sddl = _file_owner_and_dacl_sddl(path) if sid else None
    return bool(sddl) and _sddl_is_private(sddl, sid)


def _identity(info: os.stat_result) -> tuple:
    """Device, file index (st_ino is the NTFS file index on Windows), size and mtime."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _check_private(resolved: Path, info: os.stat_result) -> None:
    if sys.platform == "win32":
        if not _windows_acl_is_private(resolved):
            raise LiveGateRefused("the credential file is readable by other accounts; see the icacls step in the instructions")
    elif info.st_mode & 0o077:
        raise LiveGateRefused("the credential file must be private to your user (chmod 600)")


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
    _check_private(resolved, info)
    try:
        text = _read_text(resolved).strip()
        after = candidate.lstat()
    except (OSError, UnicodeError) as exc:
        raise LiveGateRefused(f"cannot read the credential file: {type(exc).__name__}") from None
    # TOCTOU: the file must be the very one that was checked, and still private after the read.
    if not stat.S_ISREG(after.st_mode) or _identity(after) != _identity(info):
        raise LiveGateRefused("the credential file changed while it was being read")
    _check_private(resolved, after)
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
