"""NON-AI security stand-in. Runs INSIDE the isolated AppContainer and tries to escape it.

Every attempt is reported on stderr as ``{"probe": ..., "target": ..., "outcome": "denied" | "allowed", ...}``.
The trusted host saves stderr to its own log; the tests decide which outcomes are acceptable. ``targets``
(given by the test harness through the host) names concrete paths and ports to attack, i.e. this
stand-in is assumed to know everything an attacker could guess about the host.
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
from ctypes import wintypes

from runtime import Host, report


def _attempt(probe: str, target: str, fn) -> None:
    try:
        detail = fn()
        report(probe=probe, target=target, outcome="allowed", detail=str(detail)[:200])
    except BaseException as exc:  # noqa: BLE001 - every failure is a result
        report(probe=probe, target=target, outcome="denied", detail=f"{type(exc).__name__}: {str(exc)[:160]}")


def _read(path):
    with open(path, "rb") as f:
        return f"{len(f.read(64))} bytes"


def _write(path):
    with open(path, "wb") as f:
        f.write(b"probe")
    return "written"


def filesystem(targets: dict) -> None:
    for path in targets.get("read", []):
        _attempt("read_file", path, lambda p=path: _read(p))
    for path in targets.get("list", []):
        _attempt("list_dir", path, lambda p=path: f"{len(os.listdir(p))} entries")
    for path in targets.get("write", []):
        _attempt("write_file", path, lambda p=path: _write(p))
    for path in targets.get("system_read", []):         # documented, not secret: see docs
        _attempt("system_read", path, lambda p=path: _read(p) if os.path.isfile(p) else f"{len(os.listdir(p))} entries")
    _attempt("environment", "os.environ", lambda: json.dumps(sorted(os.environ)))


def processes(targets: dict) -> None:
    system = os.environ.get("SYSTEMROOT", r"C:\Windows")
    for exe in (rf"{system}\System32\cmd.exe", rf"{system}\System32\WindowsPowerShell\v1.0\powershell.exe", sys.executable):
        _attempt("spawn", exe, lambda e=exe: subprocess.run([e, "/c", "echo", "x"], capture_output=True, timeout=10).returncode)
    _attempt("spawn", "os.system", lambda: _nonzero(os.system("echo x")))
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    for pid in targets.get("pids", []):
        def open_process(pid=pid):
            h = k32.OpenProcess(0x0010 | 0x0400, False, pid)   # PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
            if not h:
                raise ctypes.WinError(ctypes.get_last_error())
            k32.CloseHandle(h)
            return "opened"
        _attempt("open_process", str(pid), open_process)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    def clipboard():
        if not user32.OpenClipboard(None):
            raise ctypes.WinError(ctypes.get_last_error())
        user32.CloseClipboard()
        return "opened"
    _attempt("clipboard", "OpenClipboard", clipboard)
    def console():
        with open("CONOUT$", "wb") as f:
            f.write(b"x")
        return "written"
    _attempt("console", "CONOUT$", console)


def _nonzero(code):
    if code != 0:
        raise OSError(f"exit status {code}")
    return code


def network(targets: dict) -> None:
    for host, port in [("1.1.1.1", 443), ("8.8.8.8", 53)] + [tuple(t) for t in targets.get("tcp", [])]:
        _attempt("tcp_connect", f"{host}:{port}", lambda h=host, p=port: socket.create_connection((h, p), timeout=3).close())
    _attempt("dns_lookup", "example.com", lambda: socket.getaddrinfo("example.com", 443))
    def udp_dns():
        # sendto() succeeding proves nothing (the firewall drops silently); a reply would prove egress
        query = b"\x12\x34\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01"
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(3)
        try:
            s.sendto(query, ("8.8.8.8", 53))
            return f"reply of {len(s.recvfrom(512)[0])} bytes"
        finally:
            s.close()
    _attempt("udp_dns_roundtrip", "8.8.8.8:53", udp_dns)
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        report(probe="tcp_listen", target="127.0.0.1", outcome="observed", detail=str(port))
        s.settimeout(float(targets.get("inbound_wait", 4)))
        _attempt("inbound_connection", f"127.0.0.1:{port}", lambda: s.accept() and "accepted")
    except OSError as exc:
        report(probe="tcp_listen", target="127.0.0.1", outcome="denied", detail=type(exc).__name__)
    finally:
        s.close()


def token() -> None:
    k32 = ctypes.WinDLL("kernel32")
    adv = ctypes.WinDLL("advapi32")
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
    adv.GetSidSubAuthorityCount.restype = ctypes.c_void_p
    adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
    adv.GetSidSubAuthority.restype = ctypes.c_void_p
    adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    h = wintypes.HANDLE()
    adv.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(h))
    val, ret = wintypes.DWORD(), wintypes.DWORD()
    adv.GetTokenInformation(h, 29, ctypes.byref(val), 4, ctypes.byref(ret))   # TokenIsAppContainer
    report(probe="token", target="TokenIsAppContainer", outcome="observed", detail=str(val.value))
    buf = ctypes.create_string_buffer(64)
    adv.GetTokenInformation(h, 25, buf, 64, ctypes.byref(ret))               # TokenIntegrityLevel
    sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
    count = ctypes.cast(adv.GetSidSubAuthorityCount(ctypes.c_void_p(sid)), ctypes.POINTER(ctypes.c_ubyte))[0]
    rid = ctypes.cast(adv.GetSidSubAuthority(ctypes.c_void_p(sid), count - 1), ctypes.POINTER(wintypes.DWORD))[0]
    report(probe="token", target="IntegrityLevel", outcome="observed", detail=hex(rid))


def registry() -> None:
    import winreg
    for hive, name, key in ((winreg.HKEY_CURRENT_USER, "HKCU", "Environment"),
                            (winreg.HKEY_CURRENT_USER, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer"),
                            (winreg.HKEY_LOCAL_MACHINE, "HKLM", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")):
        def read(hive=hive, key=key):
            with winreg.OpenKey(hive, key) as k:
                return f"{winreg.QueryInfoKey(k)[1]} values"
        _attempt("registry_read", f"{name}\\{key}", read)
    def env_names():
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return json.dumps(sorted(winreg.EnumValue(k, i)[0] for i in range(winreg.QueryInfoKey(k)[1])))
    _attempt("registry_user_environment_names", r"HKCU\Environment", env_names)


def secrets() -> None:
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    def credentials():
        count, creds = wintypes.DWORD(), ctypes.c_void_p()
        if not adv.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(creds)):
            raise ctypes.WinError(ctypes.get_last_error())
        return f"{count.value} credentials"
    _attempt("credential_manager", "CredEnumerateW", credentials)


def inherited_handles() -> None:
    """Every disk handle this process holds, with its path. Only the three pipes are inherited, so any disk
    handle must be one the process opened itself (e.g. its current directory) inside its own sandbox."""
    k32 = ctypes.WinDLL("kernel32")
    k32.GetFileType.argtypes = [wintypes.HANDLE]
    k32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    k32.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    std = {k32.GetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF)), k32.GetStdHandle(wintypes.DWORD(-11 & 0xFFFFFFFF)),
           k32.GetStdHandle(wintypes.DWORD(-12 & 0xFFFFFFFF))}
    disk = []
    for value in range(4, 4096, 4):
        flags = wintypes.DWORD()
        try:   # an invalid handle raises STATUS_INVALID_HANDLE as an exception here
            if value not in std and k32.GetHandleInformation(value, ctypes.byref(flags)) and k32.GetFileType(value) == 1:
                disk.append(value)
        except OSError:
            continue
    paths = []
    for value in disk:
        buf = ctypes.create_unicode_buffer(1024)
        k32.GetFinalPathNameByHandleW(value, buf, 1024, 0)
        paths.append(buf.value)
    report(probe="disk_handles", target="FILE_TYPE_DISK", outcome="observed", detail=json.dumps(paths))


HOSTILE_LINES = [
    b"not json", b"[" * 100000, b'{"tool":"act","keys":[],"frames":' + b"9" * 5000 + b"}",
    b'{"tool":"observe","id":"\xff\xfe"}', b'{"tool":"act","keys":[],"frames":5,"frames":120}',
    b'{"tool":"act","keys":[],"frames":NaN}', b'{"tool":"act","keys":["ArrowUp"],"frames":121}',
    b'{"tool":"act","keys":["ArrowUp"],"frames":0}', b'{"tool":"act","keys":["KeyQ"],"frames":5}',
    b'{"tool":"act","keys":[],"frames":5,"javascript":"lander.fuel=1e9"}',
    b'{"tool":"act","keys":[],"frames":5,"seed":7}', b'{"tool":"act","keys":[],"frames":5,"episode_frame_budget":999999}',
    b'{"tool":"eval","code":"gameState"}', b'{"tool":"state"}', b'{"tool":"reset"}', b'{"tool":"shell","cmd":"whoami"}',
    b'{"tool":"read_file","path":"PROJECT.md"}', b'{"tool":"serve","command":["cmd.exe"]}',
    b'{"tool":"config","max_episodes":1000}', b'{"tool":"observe","debug":true}',
    b'{"tool":"model","messages":[],"model":"gpt-9","provider":"x"}',
    b'{"tool":"model","messages":[{"role":"user","content":[{"type":"image","seq":999999}]}]}',
    b'{"tool":"model","messages":[{"role":"user","content":[{"type":"image","path":"C:/x.png"}]}]}',
    b'{"tool":"act","keys":["ArrowUp"],"frames":5,"x":"' + b"a" * 70000 + b'"}', b"null", b"{}",
]


def protocol(host: Host) -> None:
    for i, line in enumerate(HOSTILE_LINES):
        reply = host.raw(line)
        report(probe="host_protocol", target=f"hostile_line_{i}", outcome="denied" if set(reply) == {"protocol", "error"} else "allowed",
               detail=reply.get("error", sorted(reply))[:200] if isinstance(reply.get("error", ""), str) else str(reply)[:200])


PLAY = [([], 0), (["ArrowUp"], 60), (["ArrowLeft", "Space"], 45), ([], 120)]


def play(host: Host) -> None:
    """A fixed input sequence after all probes: its screenshots must equal a clean control session's."""
    for keys, frames in PLAY:
        obs = host.observe() if frames == 0 else host.act(keys, frames)
        report(probe="play", target=f"{keys}x{frames}", outcome="observed",
               detail=json.dumps({k: obs.get(k) for k in ("seq", "episode_frame", "frames_advanced")} |
                                 {"sha256": obs.get("image", {}).get("sha256")}))


def run(host: Host, targets: dict) -> int:
    inherited_handles()
    token()
    filesystem(targets)
    processes(targets)
    network(targets)
    secrets()
    registry()
    for marker in targets.get("persist_check", []):
        _attempt("persisted_marker", marker, lambda m=marker: _read(m))
    for marker in targets.get("persist_write", []):
        _attempt("write_own_storage", marker, lambda m=marker: _write(m))
    host.brief()
    protocol(host)
    play(host)
    for path in targets.get("read_after_play", []):   # privileged files that exist by now
        _attempt("read_file_after_play", path, lambda p=path: _read(p))
    report(event="probe_done")
    return 0
