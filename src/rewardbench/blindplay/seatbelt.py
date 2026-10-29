"""Operating-system isolation for the blind player on macOS: the kernel Seatbelt sandbox (``sandbox-exec``).

TRUSTED HOST SIDE. ``isolation`` dispatches here on macOS; the player never runs any of it.

What the kernel enforces for a process started by ``launch`` (verified by probes, see
``tests/blindplay/test_isolation.py`` and docs/ISOLATED_PLAYER_RUNTIME.md):

* **Deny-by-default Seatbelt profile** (``profile``), applied by ``/usr/bin/sandbox-exec`` before the
  interpreter is executed and inherited by everything it could start. The sandbox (Sandbox.kext, the
  mechanism behind the App Sandbox, Safari and Chromium renderers) checks every file, process, network,
  IPC, Mach service and sysctl operation; anything not allowed below fails with ``EPERM``.
* **Reads:** the runtime image directory (``cwd``), the exact non-system libraries the interpreter links
  (e.g. a framework build's ``Python`` dylib), the listing of ``/`` (dyld needs it), metadata of the
  image's ancestor directories (``realpath``), and the Rosetta runtime when an x86_64 interpreter runs
  on Apple silicon. System libraries come from dyld's shared cache, so ``/usr/lib`` and ``/System`` are
  not opened. The repository, ``runs/``, the home folder, credentials and the browser are unreadable,
  and so is their metadata (no ``stat`` of anything outside the list).
* **No writes anywhere** (not even a private folder), so nothing can persist between sessions.
* **Only the interpreter may be executed** (``process-exec`` of one literal path), and ``process-fork``
  is denied: no shell, no child process of any kind.
* **No network** (inet and Unix-domain), **no Mach service lookups** (pasteboard, keychain, launchd,
  DNS resolver, window server), **no signals** or task ports for other processes, no process list or
  process information about other processes (an explicit rule: ``deny default`` leaves ``process-info``
  open), no IOKit, no shared memory. ``sysctl`` reads are limited to the five names ``os.uname()``
  needs.
* **Resources:** a new session (no controlling terminal), only the three stdio pipes are inherited, an
  empty environment, CPU-time / open-file / file-size / core limits (``ulimit``), and a host-side memory
  watchdog (macOS does not enforce address-space rlimits).

Elsewhere ``launch`` refuses (``IsolationUnavailable``); there is no unisolated fallback.
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
DEFAULT_MEMORY_LIMIT = 1024 * 1024 * 1024
DEFAULT_CPU_SECONDS = 4 * 3600
MAX_OPEN_FILES = 64
UNAME_SYSCTLS = ("kern.ostype", "kern.hostname", "kern.osrelease", "kern.version", "hw.machine")
ROSETTA_PATHS = ("/Library/Apple/usr/libexec/oah", "/usr/libexec/rosetta")
_SAFE_PATH = re.compile(r"^/[A-Za-z0-9 ._+@/-]*$")


class IsolationUnavailable(RuntimeError):
    """OS isolation cannot be provided here. Nothing is started; there is no unisolated fallback.

    Defined here and re-exported by ``isolation`` (which imports this module)."""


def supported() -> str | None:
    """``None`` when Seatbelt isolation is available, else the reason it is not."""
    if sys.platform != "darwin":
        return f"Seatbelt isolation requires macOS (this is {sys.platform})"
    if not os.access(SANDBOX_EXEC, os.X_OK):
        return f"{SANDBOX_EXEC} is not available"
    return None


def _quote(path: str | Path) -> str:
    """A profile string literal. Paths that would need escaping are refused rather than escaped."""
    text = str(path)
    if not _SAFE_PATH.match(text):
        raise IsolationUnavailable(f"path not usable in a sandbox profile: {text!r}")
    return f'"{text}"'


def profile(image: Path, executable: Path, extra_readable: tuple[Path, ...] = (), rosetta: bool = False) -> str:
    """The complete Seatbelt profile for one player process. ``image`` and ``executable`` are real paths."""
    image, executable = Path(os.path.realpath(image)), Path(os.path.realpath(executable))
    if not executable.is_relative_to(image):
        raise IsolationUnavailable("the player executable must be inside the runtime image")
    extras = [Path(os.path.realpath(p)) for p in extra_readable]
    metadata = sorted({str(a) for p in [image, *extras] for a in p.parents})
    read = [f"(subpath {_quote(image)})"] + [f"(literal {_quote(p)})" for p in extras]
    if rosetta:
        read += [f"(subpath {_quote(p)})" for p in ROSETTA_PATHS if Path(p).exists()]
    sysctls = " ".join(f'(sysctl-name "{n}")' for n in UNAME_SYSCTLS)
    return "\n".join([
        "(version 1)",
        "(deny default)",
        f"(allow process-exec (literal {_quote(executable)}))",
        f"(allow file-read* {' '.join(read)})",
        '(allow file-read-data (literal "/"))',
        f"(allow file-read-metadata {' '.join(f'(literal {_quote(p)})' for p in metadata)})",
        f"(allow sysctl-read {sysctls})",
        # ``deny default`` does not cover these: without them proc_listallpids/proc_pidpath list every
        # process on the Mac and their executable paths (found by the probe, Mission 014 macOS)
        "(deny process-info*)",
        "(allow process-info* (target self))",
        "",
    ])


def _needs_rosetta(executable: Path) -> bool:
    if platform.machine() != "arm64":
        return False
    head = Path(executable).read_bytes()[:8]
    return head[:4] == b"\xcf\xfa\xed\xfe" and head[4:8] == b"\x07\x00\x00\x01"   # thin x86_64 Mach-O


@dataclass
class SeatbeltProcess:
    """A running isolated player. ``stdin``/``stdout``/``stderr`` are binary streams owned by the host."""
    pid: int
    profile_sha256: str
    stdin: io.BufferedWriter
    stdout: io.BufferedReader
    stderr: io.BufferedReader
    _popen: subprocess.Popen
    memory_limit: int
    killed_for_memory: bool = False
    _stop: threading.Event = field(default_factory=threading.Event)

    def poll(self) -> int | None:
        return self._popen.poll()

    def wait(self, timeout: float | None = None) -> int | None:
        try:
            return self._popen.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def kill(self) -> None:
        if self._popen.poll() is None:
            try:
                os.killpg(self._popen.pid, signal.SIGKILL)   # its own session: nothing else is in the group
            except ProcessLookupError:
                pass
            self._popen.wait(5)

    def close(self) -> None:
        self._stop.set()
        for stream in (self.stdin, self.stdout, self.stderr):
            try:
                stream.close()
            except OSError:
                pass
        self.kill()

    def _watch_memory(self) -> None:
        """macOS ignores RLIMIT_AS/RLIMIT_DATA, so the host samples the resident size and kills on excess."""
        while not self._stop.wait(0.25) and self._popen.poll() is None:
            try:
                rss_kb = int(subprocess.run(["/bin/ps", "-o", "rss=", "-p", str(self.pid)], capture_output=True,
                                            text=True, timeout=5).stdout.strip() or 0)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                continue
            if rss_kb * 1024 > self.memory_limit:
                self.killed_for_memory = True
                self.kill()
                return


def launch(executable: Path, args: list[str], *, cwd: Path, env: dict[str, str] | None = None,
           extra_readable: tuple[Path, ...] = (), memory_limit: int = DEFAULT_MEMORY_LIMIT,
           cpu_seconds: int = DEFAULT_CPU_SECONDS) -> SeatbeltProcess:
    """Start ``executable args`` under the profile in the module docstring. ``cwd`` is the runtime image."""
    reason = supported()
    if reason:
        raise IsolationUnavailable(reason)
    text = profile(Path(cwd), Path(executable), tuple(extra_readable), rosetta=_needs_rosetta(Path(executable)))
    # ``ulimit`` then ``exec``: the shell is replaced by ``env -i`` (drops the shell's PWD/SHLVL), then by
    # sandbox-exec, which applies the profile and is replaced by the interpreter. No argument passes through
    # the shell's parser ("$@"). ``env`` (normally empty) is the interpreter's whole environment.
    limits = f"ulimit -t {int(cpu_seconds)} -n {MAX_OPEN_FILES} -f 0 -c 0 && exec /usr/bin/env -i \"$@\""
    assignments = [f"{k}={v}" for k, v in sorted((env or {}).items())]
    command = ["/bin/sh", "-c", limits, "sh", *assignments, str(SANDBOX_EXEC), "-p", text, str(executable), *args]
    popen = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             cwd=str(cwd), env={}, close_fds=True, start_new_session=True)
    process = SeatbeltProcess(pid=popen.pid, profile_sha256=hashlib.sha256(text.encode()).hexdigest(),
                              stdin=popen.stdin, stdout=popen.stdout, stderr=popen.stderr, _popen=popen,
                              memory_limit=memory_limit)
    threading.Thread(target=process._watch_memory, daemon=True).start()
    return process
