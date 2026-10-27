# Isolated blind-player runtime (Mission 014)

**Status (2026-10-27): built and verified on this Windows 11 PC with scripted, NON-AI stand-ins only. No model has
played; no API call was made; no model provider is wired in.** This is the boundary PROJECT.md section 20.5
requires before an AI may play: the player is confined by the operating system, not by instructions.

Builds on the Mission 013 foundation (`docs/BLIND_VISUAL_FOUNDATION.md`), unchanged: same referee, same
authentic upstream game, same player contract (`react.blindplay.player.v1`, keyset `keyset.v1`, at most 120
frames per act).

## Architecture

```
 TRUSTED HOST (normal user process)                          ISOLATED PLAYER (AppContainer + Job Object)
 ┌──────────────────────────────────────────────┐  stdin    ┌──────────────────────────────────────┐
 │ host.py                                      │ ───────>  │ runtime image (read+execute only):   │
 │  - builds the referee command itself          │  stdout   │   python.exe + stdlib (no pip pkgs)  │
 │  - launches the sandbox (isolation.py)        │ <───────  │   player/runtime.py  (stdlib only)   │
 │  - re-validates every line (contract.py)      │  stderr   │                                      │
 │  - forwards ONLY canonical requests ──┐       │ <───────  │ modes: scripted | probe | agent      │
 │  - model gateway (disabled by default)│       │           │ sees: "Land the rocket.", 2 tools,   │
 │  - writes all records                 │       │           │   12 key names, PNG screenshots      │
 └───────────────────────────────────────┼───────┘           └──────────────────────────────────────┘
                                         v
               serve.py -> Session -> referee.py (Chromium, upstream game)   [Mission 013, unchanged]
```

| Module | Side | Role |
| --- | --- | --- |
| `isolation.py` | host | Starts a process in a Windows AppContainer (no capabilities) inside a Job Object; resets the container profile; credential preflight. Fails closed on other platforms. |
| `runtime_image.py` | host | Builds a minimal Python (exe, DLLs, stdlib) plus `player_runtime/` into `%LOCALAPPDATA%\REACT-blindplay\runtime-images\<digest>`, grants only the container SID read+execute, and re-hashes every file before each session. |
| `host.py` | host | Owns the referee command, the sandbox, the broker and the records. CLI starts only scripted NON-AI stand-ins. |
| `player_runtime/runtime.py` | player | The only code that runs in the sandbox. Talks to the host over its own stdio. Modes: `scripted`, `probe`, `agent`. |
| `player_runtime/probes.py` | player | NON-AI security stand-in that tries to break out. |

### What a future model would see

The `agent` mode is the loop a vision model would run in. It asks the host for `{"tool": "model", "messages": [...]}`;
messages refer to screenshots by `seq`. The **host** replaces each reference with the exact PNG bytes (base64) it
returned to this player earlier, adds the fixed system text `"Land the rocket."` and the two contract tools, and
calls the gateway. The player never handles a file path, and no image file is readable by it (verified). The
gateway reply is reduced to `text` and up to 8 `tool_calls`; tool calls are executed only through the host, which
re-validates them. Everything sent to a model is logged in `gateway_transcript.jsonl` (images by sha256).

Only two gateways exist: `DisabledGateway` (default; every model request is refused) and `ScriptedGateway`
(**not a model**: replays fixed tool calls, used to prove the plumbing). There is no provider adapter, so this code
cannot call any paid API.

## Guarantees (verified on this PC, 2026-10-27)

Each line is backed by a probe in `tests/blindplay/test_isolation.py` and recorded evidence in
`docs/assets/isolated-player-runtime/evidence-2026-10-27.json`. The probes are told the exact paths, PIDs and ports
to attack.

| Attempt by the player | Result | Enforced by |
| --- | --- | --- |
| Read the repository (PROJECT.md, referee/host source, upstream `game.js`, custom simulator, `.git`) | Denied (`PermissionError`) | AppContainer DACL check |
| Read or list `runs/` (Mission 010/012 databases, Mission 013 records, this session's referee/host records, screenshots, referee stderr), before and after they exist | Denied | AppContainer |
| Read `~/.gitconfig`, `.git-credentials`, GitHub CLI `hosts.yml`, list `.ssh`, `.claude`, the backups folder, the Playwright browser, the runtime-image root, the installed Python | Denied | AppContainer |
| Windows Credential Manager (`CredEnumerateW`) | Denied | AppContainer |
| Write to the repository, the session, the runtime image, `C:\Users\Public`, `C:\ProgramData` | Denied | AppContainer |
| Start `cmd.exe`, PowerShell, Python, `os.system` | Denied (`ERROR_CHILD_PROCESS_BLOCKED`) | child-process policy + Job active-process limit 1 |
| TCP to the internet, DNS lookup, UDP DNS round trip, TCP to a host loopback listener | Denied / no reply; host listener got 0 connections | no network capabilities; AppContainer loopback isolation |
| Accept a connection from the host (listening socket) | Socket can be opened, but the host's connection attempt times out | loopback isolation |
| Open the host process, the clipboard, the console (`CONOUT$`) | Denied | AppContainer; Job UI limits; `DETACHED_PROCESS` |
| Inherited handles | Only stdin/stdout/stderr pipes; the only disk handles are the process's own (its working directory, system message files) | `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` |
| Environment variables | Exactly `LOCALAPPDATA`, `SYSTEMROOT`, `TEMP`, `TMP` (Windows points the first, third and fourth at the container's own folder) | host builds the block |
| Token | AppContainer = 1, integrity Low (0x1000) | kernel |
| 26 hostile protocol lines (bad JSON/UTF-8, 100k nesting, 5000-digit ints, duplicate keys, NaN, >64 KB, frames 0/121, key `KeyQ`, injected `javascript`/`seed`/`episode_frame_budget`, tools `eval`/`state`/`reset`/`shell`/`read_file`/`serve`/`config`, model requests choosing a model/provider, unknown screenshot `seq`, image by file path) | All rejected by the host with fixed messages; **none reached the referee** (referee saw exactly brief + observe + 3 acts) | `host.py` + `contract.py` |
| Game state after the attacks | Identical, byte for byte, to a clean unsandboxed session with the same inputs (and Mission 013's fixed start frame) | broker forwards only canonical requests |
| Persist data between sessions | The container's own folder is writable during a session and is deleted when the session ends (marker gone) | `reset_profile` before and after |
| Use an altered runtime image | Refused (every file re-hashed; changed or extra files detected) | `runtime_image.verify` |
| Choose the referee command, budgets, seed, model or gateway | Impossible: built by the host from `HostConfig`; the player only writes request lines | design + tests |

**Negative control:** the same read-and-spawn code that is denied inside the container succeeds as a normal process
(`test_negative_control_the_same_attack_succeeds_without_the_sandbox`), so the denials come from the sandbox.

**Fidelity:** the isolated scripted idle, key-sweep and seeded-random sessions are byte-identical to the Mission 013
recordings (23/23, 66/66, 44/44 screenshots); the 120-frame cap and upstream game are unchanged.

## Limitations (what this does not guarantee)

1. **Windows only.** Linux/macOS have no backend; there the host refuses to start (tested in CI). A Linux backend
   (e.g. user namespaces/bubblewrap or a container) would need its own verification.
2. **Readable by every AppContainer by Windows design:** system files (`C:\Windows`, `C:\Program Files`) and parts
   of `HKCU`/`HKLM` (`HKCU\Environment`, `Control Panel`, `Software\Microsoft`, `Software\Classes`,
   `Software\Policies`; 45 of 116 `HKCU` keys to depth 2). None of this contains game state or project data.
   - **`HKCU\Environment` is where `setx` stores user environment variables.** If a provider key were stored there the
     player could read it. The host therefore **refuses to start** when any user variable there looks like a
     credential (name contains KEY/TOKEN/SECRET/PASSWORD/AUTH/... or value starts with a known key prefix). Keep API
     keys in host-only storage (e.g. a file under your user profile, which the sandbox cannot read), never in `setx`.
   - The less-privileged AppContainer mode (LPAC), which would close these, was tried: Python cannot start under it
     without additional system-DLL capability work (`STATUS_ACCESS_DENIED`). Not pursued.
3. **The player can learn non-game facts about the PC:** the Windows user name (from its own folder path), the
   Windows build, installed programs (from `C:\Program Files`), the names of user environment variables, and the
   user SID in its own token (not tested: whether it can resolve that SID to the account name or e-mail, or list
   other processes). None reveals the game, the referee or the repository; it matters for privacy only if
   transcripts are published.
4. **File-existence oracle.** Opening a path the player cannot read fails with "access denied" if it exists and
   "not found" if it does not (seen when CI's runner had no `.gitconfig`). The player can therefore test whether a
   guessed path exists, but never read, list or write it. It does not reveal game state, which lives only in the
   referee's memory and in record files whose names are already documented.
5. **Not a defence against a Windows kernel or AppContainer escape exploit**, or against an administrator. It is
   the same boundary Edge/Chromium renderers and UWP apps rely on, not a virtual machine.
6. **Resource exhaustion is bounded, not eliminated:** 1 GB memory cap, 1 process, size-capped requests (64 KB game,
   2 MB model), 16 MB of recorded stderr, request and wall-clock limits. CPU time and disk writes inside the
   container's own (wiped) folder are not capped.
7. **Timing and the screen are the intended channels.** Everything the player learns about the game comes from
   screenshots and procedural counters (Mission 013 contract); that is the experiment.
8. **The isolation applies to the player runtime.** A model provider's own servers are outside it: whatever the
   host sends to a model leaves the machine by design (screenshots, the objective, the two tool descriptions and
   the conversation). The gateway transcript records exactly that.
9. **The runtime image hash depends on the checkout's line endings** (Windows `autocrlf` checks the player files out
   with CRLF), so the digest differs between checkouts; each session records the digest it actually used.
10. **No model runtime has been exercised.** The agent loop is verified only with a scripted gateway that is not a
   model. Real vision-model behaviour (image consumption, tool-call formats, refusals, cost) is untested.

## Commands

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,blindplay]"
.\.venv\Scripts\python.exe -m playwright install chromium
$env:PYTHONPATH='src'; $env:REACT_REQUIRE_ISOLATION='1'
.\.venv\Scripts\python.exe -m pytest tests/blindplay -q                       # 89 tests (isolation + Mission 013)
.\.venv\Scripts\python.exe -m rewardbench.blindplay.host --out runs/blind-visual/<id> --script idle --episodes 2
.\.venv\Scripts\python.exe docs/assets/isolated-player-runtime/verify/record_evidence.py . runs/blind-visual/<new> runs/blind-visual/mission013-verify-20261027
```

The CLI can start only the scripted NON-AI stand-ins. Starting a model session requires code that does not exist
yet (a provider gateway) and the owner approvals listed in `docs/BLIND_PLAY_PROTOCOL_V1_DRAFT.md`.

Chronology and problems met: `docs/assets/isolated-player-runtime/DEVLOG.md`.
