r"""Operating-system isolation for the blind player: a Windows AppContainer inside a Job Object, or the
macOS Seatbelt sandbox (``seatbelt.py``, same interface; this module dispatches to it on macOS).

TRUSTED HOST SIDE. This module starts the player process; the player never runs any of it.

What the kernel enforces for a process started by ``launch`` (verified by probes, see
``tests/blindplay/test_isolation.py`` and docs/ISOLATED_PLAYER_RUNTIME.md):

* **AppContainer token, no capabilities.** Every securable object (file, directory, registry key, pipe,
  process) is checked against the container's package SID in addition to the user. Objects grant the
  container nothing unless their DACL names its SID, a capability it holds, or ALL APPLICATION PACKAGES.
  The repository, ``runs/``, the user profile, credentials and the browser are not readable. Windows
  itself grants ALL APPLICATION PACKAGES read access to system locations (``C:\Windows``,
  ``C:\Program Files``); those stay readable (less-privileged AppContainers could not start Python).
* **No persistent storage.** The container's only writable folder is its own profile
  (``%LOCALAPPDATA%\Packages\<name>\AC``); ``reset_profile`` deletes and recreates it, so nothing written
  in one session survives into the next.
* **No network.** No ``internetClient``/``privateNetworkClientServer`` capability is granted, and
  AppContainers cannot reach loopback, so every socket connect and name lookup fails.
* **No child processes.** ``PROCESS_CREATION_CHILD_PROCESS_RESTRICTED`` plus a Job Object with an active
  process limit of 1: the player cannot start a shell or any other program.
* **Job Object.** Kill-on-close (the player dies with the host), a memory cap, UI restrictions (no
  clipboard, desktop, global atoms or system settings).
* **Only three handles are inherited** (``PROC_THREAD_ATTRIBUTE_HANDLE_LIST``): the stdin/stdout/stderr
  pipes owned by the host. ``DETACHED_PROCESS``: no console, so the host terminal cannot be read through
  ``CONIN$``/``CONOUT$``. The environment block is built from scratch: ``SYSTEMROOT`` and ``LOCALAPPDATA``
  only (Windows requires the latter and rewrites it, ``TEMP`` and ``TMP`` to the container's own folder).

Only Windows (here) and macOS (``seatbelt.py``) are supported. Elsewhere ``launch`` refuses
(``IsolationUnavailable``); it never falls back to an unisolated process.
"""

from __future__ import annotations

import ctypes
import io
import os
import platform
import re
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rewardbench.blindplay import seatbelt
from rewardbench.blindplay.seatbelt import IsolationUnavailable

CONTAINER_NAME = "REACT.BlindPlay.Player"
DEFAULT_MEMORY_LIMIT = 1024 * 1024 * 1024


def supported() -> str | None:
    """``None`` when OS isolation is available, else the reason it is not."""
    if sys.platform == "darwin":
        return seatbelt.supported()
    if sys.platform != "win32":
        return f"OS isolation requires Windows (AppContainer) or macOS (Seatbelt); this is {sys.platform}"
    if sys.getwindowsversion().build < 15063:   # Windows 10 1703: child-process creation policy
        return "Windows 10 1703 or later is required"
    return None


if sys.platform == "win32":
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _uenv = ctypes.WinDLL("userenv", use_last_error=True)

    PSID = ctypes.c_void_p

    class SECURITY_CAPABILITIES(ctypes.Structure):
        _fields_ = [("AppContainerSid", PSID), ("Capabilities", ctypes.c_void_p),
                    ("CapabilityCount", wintypes.DWORD), ("Reserved", wintypes.DWORD)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
                    ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
                    ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD), ("lpReserved2", ctypes.c_void_p),
                    ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE)]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                    ("bInheritHandle", wintypes.BOOL)]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                   "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    for fn, res, args in (
        (_uenv.DeriveAppContainerSidFromAppContainerName, ctypes.c_long, [wintypes.LPCWSTR, ctypes.POINTER(PSID)]),
        (_uenv.CreateAppContainerProfile, ctypes.c_long, [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(PSID)]),
        (_uenv.DeleteAppContainerProfile, ctypes.c_long, [wintypes.LPCWSTR]),
        (_adv.ConvertSidToStringSidW, wintypes.BOOL, [PSID, ctypes.POINTER(wintypes.LPWSTR)]),
        (_adv.FreeSid, ctypes.c_void_p, [PSID]),
        (_k32.LocalFree, ctypes.c_void_p, [ctypes.c_void_p]),
        (_k32.InitializeProcThreadAttributeList, wintypes.BOOL,
         [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]),
        (_k32.UpdateProcThreadAttribute, wintypes.BOOL,
         [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]),
        (_k32.DeleteProcThreadAttributeList, None, [ctypes.c_void_p]),
        (_k32.CreateProcessW, wintypes.BOOL,
         [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
          ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(PROCESS_INFORMATION)]),
        (_k32.CreatePipe, wintypes.BOOL,
         [ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD]),
        (_k32.SetHandleInformation, wintypes.BOOL, [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]),
        (_k32.CreateJobObjectW, wintypes.HANDLE, [ctypes.c_void_p, wintypes.LPCWSTR]),
        (_k32.SetInformationJobObject, wintypes.BOOL, [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]),
        (_k32.AssignProcessToJobObject, wintypes.BOOL, [wintypes.HANDLE, wintypes.HANDLE]),
        (_k32.ResumeThread, wintypes.DWORD, [wintypes.HANDLE]),
        (_k32.TerminateProcess, wintypes.BOOL, [wintypes.HANDLE, wintypes.UINT]),
        (_k32.WaitForSingleObject, wintypes.DWORD, [wintypes.HANDLE, wintypes.DWORD]),
        (_k32.GetExitCodeProcess, wintypes.BOOL, [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]),
        (_k32.CloseHandle, wintypes.BOOL, [wintypes.HANDLE]),
    ):
        fn.restype, fn.argtypes = res, args

    PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
    PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
    PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY = 0x0002000E
    PROCESS_CREATION_CHILD_PROCESS_RESTRICTED = 0x01
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    CREATE_SUSPENDED = 0x00000004
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    DETACHED_PROCESS = 0x00000008   # not CREATE_NO_WINDOW: that makes AppContainer DLL init fail (0xC0000142)
    STARTF_USESTDHANDLES = 0x00000100
    HANDLE_FLAG_INHERIT = 0x00000001
    JobObjectBasicUIRestrictions, JobObjectExtendedLimitInformation = 4, 9
    JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
    JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
    JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JOB_OBJECT_UILIMIT_ALL = 0x000000FF


def _check(ok: Any, what: str) -> None:
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error(), what)


def container_sid(name: str = CONTAINER_NAME) -> str:
    """The AppContainer package SID (``S-1-15-2-...``) derived from ``name``. No profile is created."""
    reason = supported()
    if reason:
        raise IsolationUnavailable(reason)
    sid = PSID()
    hr = _uenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    if hr != 0:
        raise OSError(f"DeriveAppContainerSidFromAppContainerName failed: 0x{hr & 0xFFFFFFFF:08x}")
    text = wintypes.LPWSTR()
    try:
        _check(_adv.ConvertSidToStringSidW(sid, ctypes.byref(text)), "ConvertSidToStringSidW")
        return text.value
    finally:
        if text:
            _k32.LocalFree(text)
        _adv.FreeSid(sid)


_HR_ALREADY_EXISTS = 0x800700B7


def reset_profile(name: str = CONTAINER_NAME) -> None:
    """Delete and recreate the container profile: wipes the only folder the player can write to.

    Windows refuses to start an AppContainer process whose profile is not registered (ERROR_FILE_NOT_FOUND).
    On macOS there is nothing to wipe: the Seatbelt profile allows no writes at all.
    """
    reason = supported()
    if reason:
        raise IsolationUnavailable(reason)
    if sys.platform == "darwin":
        return
    _uenv.DeleteAppContainerProfile(name)   # absent is fine
    sid = PSID()
    hr = _uenv.CreateAppContainerProfile(name, name, "R.E.A.C.T. isolated blind player (no capabilities)",
                                         None, 0, ctypes.byref(sid)) & 0xFFFFFFFF
    if hr == 0:
        _adv.FreeSid(sid)
    elif hr != _HR_ALREADY_EXISTS:
        raise OSError(f"CreateAppContainerProfile failed: 0x{hr:08x}")


def delete_profile(name: str = CONTAINER_NAME) -> None:
    if sys.platform == "win32" and supported() is None:
        _uenv.DeleteAppContainerProfile(name)


_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|BEARER|COOKIE|SESSION", re.I)
_SECRET_VALUE = re.compile(r"^(sk-|sk_|ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|AKIA|ASIA|AIza|xox[abposr]-|hf_|r8_|"
                           r"eyJ[A-Za-z0-9_-]{10,}\.)")


def looks_like_credential(name: str, value: Any) -> bool:
    return bool(_SECRET_NAME.search(name) or (isinstance(value, str) and _SECRET_VALUE.match(value.strip())))


def exposed_user_environment_secrets() -> list[str]:
    """Names (never values) of persistent user environment variables that look like credentials.

    Windows grants every AppContainer read access to ``HKCU\\Environment`` (where ``setx`` stores user
    variables), and the sandbox cannot remove that grant without editing the user's registry ACLs. The host
    therefore refuses to start while anything credential-like is stored there. macOS has no such shared
    store: the player's environment is empty and the Seatbelt profile denies the home folder and keychain.
    """
    if sys.platform != "win32" or supported() is not None:
        return []
    import winreg
    found = []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        for i in range(winreg.QueryInfoKey(key)[1]):
            name, value, _ = winreg.EnumValue(key, i)
            if looks_like_credential(name, value):
                found.append(name)
    return sorted(found)


def grant_read_execute(directory: Path, sid: str) -> None:
    """Allow ``sid`` to read and execute ``directory`` (inherited by everything below it). Nothing else."""
    subprocess.run(["icacls", str(directory), "/grant", f"*{sid}:(OI)(CI)(RX)", "/Q"], check=True,
                   capture_output=True, text=True)


def _pipe() -> tuple[int, int]:
    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
    r, w = wintypes.HANDLE(), wintypes.HANDLE()
    _check(_k32.CreatePipe(ctypes.byref(r), ctypes.byref(w), ctypes.byref(sa), 1 << 20), "CreatePipe")
    return r.value, w.value


def default_environment() -> dict[str, str]:
    return {"SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "LOCALAPPDATA": os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")}


def _environment_block(env: dict[str, str]) -> ctypes.Array:
    text = "".join(f"{k}={v}\0" for k, v in sorted(env.items())) + "\0"
    return ctypes.create_unicode_buffer(text, len(text))


@dataclass
class IsolatedProcess:
    """A running isolated player. ``stdin``/``stdout``/``stderr`` are binary streams owned by the host."""
    pid: int
    sid: str
    stdin: io.BufferedWriter
    stdout: io.BufferedReader
    stderr: io.BufferedReader
    _process: int
    _job: int
    _closed: bool = False

    def poll(self) -> int | None:
        if _k32.WaitForSingleObject(self._process, 0) != 0:
            return None
        code = wintypes.DWORD()
        _k32.GetExitCodeProcess(self._process, ctypes.byref(code))
        return code.value

    def wait(self, timeout: float | None = None) -> int | None:
        ms = 0xFFFFFFFF if timeout is None else int(timeout * 1000)
        _k32.WaitForSingleObject(self._process, ms)
        return self.poll()

    def kill(self) -> None:
        if self.poll() is None:
            _k32.TerminateProcess(self._process, 1)
            _k32.WaitForSingleObject(self._process, 5000)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for stream in (self.stdin, self.stdout, self.stderr):
            try:
                stream.close()
            except OSError:
                pass
        self.kill()
        _k32.CloseHandle(self._process)
        _k32.CloseHandle(self._job)   # kill-on-close also ends anything left in the job


def identity() -> str:
    """What the sandbox is keyed on: the AppContainer SID (Windows) or ``seatbelt`` (the profile is per launch)."""
    return container_sid() if sys.platform == "win32" else "seatbelt"


def describe() -> dict[str, Any]:
    """Isolation facts recorded in every host session manifest."""
    if sys.platform == "darwin":
        return {"technology": "macOS Seatbelt sandbox (sandbox-exec, deny-by-default profile)",
                "read": "runtime image + interpreter's own non-system libraries only",
                "write": "none", "child_processes": "blocked (process-fork denied; exec of the interpreter only)",
                "network": "none (inet and Unix sockets denied)", "mach_services": "none",
                "inherited_handles": "stdin/stdout/stderr pipes only", "console": "none (new session, no tty)",
                "environment": [], "limits": {"cpu_seconds": seatbelt.DEFAULT_CPU_SECONDS,
                                              "open_files": seatbelt.MAX_OPEN_FILES, "file_size": 0,
                                              "memory_bytes_watchdog": seatbelt.DEFAULT_MEMORY_LIMIT},
                "macos": platform.mac_ver()[0], "machine": platform.machine()}
    return {"technology": "Windows AppContainer (no capabilities) + Job Object",
            "container": CONTAINER_NAME, "container_sid": container_sid(),
            "child_processes": "blocked (child-process policy + job active-process limit 1)",
            "network": "none (no capabilities)", "inherited_handles": "stdin/stdout/stderr pipes only",
            "console": "none (DETACHED_PROCESS)", "profile_reset": "before and after the session",
            "environment": sorted(default_environment()), "windows_build": sys.getwindowsversion().build}


def launch(executable: Path, args: list[str], *, cwd: Path, env: dict[str, str] | None = None,
           container: str = CONTAINER_NAME, memory_limit: int = DEFAULT_MEMORY_LIMIT,
           extra_readable: tuple[Path, ...] = ()) -> IsolatedProcess | seatbelt.SeatbeltProcess:
    """Start ``executable args`` in the AppContainer + Job Object described in the module docstring, or on
    macOS under the Seatbelt profile (``cwd`` = the runtime image, plus ``extra_readable`` files)."""
    reason = supported()
    if reason:
        raise IsolationUnavailable(reason)
    if sys.platform == "darwin":
        return seatbelt.launch(executable, args, cwd=cwd, env=env, extra_readable=extra_readable,
                               memory_limit=memory_limit)
    sid_text = container_sid(container)
    sid = PSID()
    hr = _uenv.DeriveAppContainerSidFromAppContainerName(container, ctypes.byref(sid))
    if hr != 0:
        raise OSError(f"DeriveAppContainerSidFromAppContainerName failed: 0x{hr & 0xFFFFFFFF:08x}")

    child_in_r, child_in_w = _pipe()
    child_out_r, child_out_w = _pipe()
    child_err_r, child_err_w = _pipe()
    for host_end in (child_in_w, child_out_r, child_err_r):   # the host's ends are never inherited
        _check(_k32.SetHandleInformation(host_end, HANDLE_FLAG_INHERIT, 0), "SetHandleInformation")
    inherited = (wintypes.HANDLE * 3)(child_in_r, child_out_w, child_err_w)

    job = _k32.CreateJobObjectW(None, None)
    _check(job, "CreateJobObjectW")
    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = (JOB_OBJECT_LIMIT_ACTIVE_PROCESS | JOB_OBJECT_LIMIT_PROCESS_MEMORY
                                               | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
    limits.BasicLimitInformation.ActiveProcessLimit = 1
    limits.ProcessMemoryLimit = memory_limit
    _check(_k32.SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(limits),
                                        ctypes.sizeof(limits)), "SetInformationJobObject(limits)")
    ui = wintypes.DWORD(JOB_OBJECT_UILIMIT_ALL)
    _check(_k32.SetInformationJobObject(job, JobObjectBasicUIRestrictions, ctypes.byref(ui), ctypes.sizeof(ui)),
           "SetInformationJobObject(ui)")

    n_attrs = 3
    size = ctypes.c_size_t()
    _k32.InitializeProcThreadAttributeList(None, n_attrs, 0, ctypes.byref(size))
    attr_buf = ctypes.create_string_buffer(size.value)
    _check(_k32.InitializeProcThreadAttributeList(attr_buf, n_attrs, 0, ctypes.byref(size)),
           "InitializeProcThreadAttributeList")
    caps = SECURITY_CAPABILITIES(sid, None, 0, 0)          # no capabilities at all
    child_policy = wintypes.DWORD(PROCESS_CREATION_CHILD_PROCESS_RESTRICTED)
    process = thread = None
    try:
        _check(_k32.UpdateProcThreadAttribute(attr_buf, 0, PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, ctypes.byref(caps),
                                              ctypes.sizeof(caps), None, None), "security capabilities")
        _check(_k32.UpdateProcThreadAttribute(attr_buf, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherited,
                                              ctypes.sizeof(inherited), None, None), "handle list")
        _check(_k32.UpdateProcThreadAttribute(attr_buf, 0, PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY,
                                              ctypes.byref(child_policy), ctypes.sizeof(child_policy), None, None),
               "child process policy")
        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
        si.StartupInfo.hStdInput, si.StartupInfo.hStdOutput, si.StartupInfo.hStdError = child_in_r, child_out_w, child_err_w
        si.lpAttributeList = ctypes.cast(attr_buf, ctypes.c_void_p)
        cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(executable), *args]))
        environment = _environment_block(env if env is not None else default_environment())
        pi = PROCESS_INFORMATION()
        _check(_k32.CreateProcessW(str(executable), cmdline, None, None, True,
                                   EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | DETACHED_PROCESS,
                                   environment, str(cwd), ctypes.byref(si), ctypes.byref(pi)), "CreateProcessW")
        process, thread = pi.hProcess, pi.hThread
        if not _k32.AssignProcessToJobObject(job, process):
            err = ctypes.get_last_error()
            _k32.TerminateProcess(process, 1)
            raise ctypes.WinError(err, "AssignProcessToJobObject")
        _check(_k32.ResumeThread(thread) != 0xFFFFFFFF, "ResumeThread")
    except BaseException:
        for h in (child_in_w, child_out_r, child_err_r):
            _k32.CloseHandle(h)
        if process:
            _k32.CloseHandle(process)
        _k32.CloseHandle(job)
        raise
    finally:
        _k32.DeleteProcThreadAttributeList(attr_buf)
        _adv.FreeSid(sid)
        for h in (child_in_r, child_out_w, child_err_w):   # the child holds its own copies now
            _k32.CloseHandle(h)
        if thread:
            _k32.CloseHandle(thread)

    import msvcrt
    return IsolatedProcess(
        pid=pi.dwProcessId, sid=sid_text,
        stdin=os.fdopen(msvcrt.open_osfhandle(child_in_w, 0), "wb", buffering=0),
        stdout=os.fdopen(msvcrt.open_osfhandle(child_out_r, os.O_RDONLY), "rb"),
        stderr=os.fdopen(msvcrt.open_osfhandle(child_err_r, os.O_RDONLY), "rb"),
        _process=process, _job=job)
