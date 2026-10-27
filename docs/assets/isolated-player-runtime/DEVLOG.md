# Mission 014 development log (chronological, 2026-10-27)

Building and attacking the isolated player runtime, including our own mistakes. No model was called and no API
was used; every player was a scripted NON-AI stand-in (or a scripted gateway that is not a model).

1. **Choosing the isolation technology.** This PC: Windows 11 Pro build 26300, standard user (no admin), no Docker,
   WSL2 Ubuntu installed. Ruled out: separate OS user / Windows Sandbox (need admin), Docker (absent), WSL2 (mounts
   the whole C: drive into the distro by default, so it is not a boundary without root changes). Chosen: a Windows
   **AppContainer** with no capabilities (the sandbox used by Edge/Chromium renderers and UWP apps) inside a **Job
   Object**, launched from Python with `ctypes`; no admin rights needed.
2. **Python could not run from its install directory inside the container.** `C:\Python313` grants `Users` but not
   `ALL APPLICATION PACKAGES`. Solution: the host builds a minimal standalone image (python.exe, DLLs, stdlib without
   site-packages/tests/tk, a `._pth` file, the player code) and grants only the container SID read+execute; every file
   is hashed and re-verified before each session.
3. **`CreateProcessW` failed with ERROR_FILE_NOT_FOUND** using only a derived container SID. Windows requires the
   AppContainer profile to be registered (`CreateAppContainerProfile`). Added `reset_profile`.
4. **Then ERROR_ENVVAR_NOT_FOUND (203).** With a hand-built environment block Windows needs `LOCALAPPDATA` (it rewrites
   it, `TEMP` and `TMP` to the container's own folder). The environment is now exactly `SYSTEMROOT` + `LOCALAPPDATA`.
5. **Then every process (even `whoami.exe`) died with STATUS_DLL_INIT_FAILED (0xC0000142).** Bisected: caused by
   `CREATE_NO_WINDOW`, not by the Job UI limits. Simply dropping it would have attached the player to the host's
   console (a channel to read the host terminal via `CONOUT$`), so `DETACHED_PROCESS` is used: no console at all
   (probe confirms `CONOUT$` is invalid).
6. **Less-privileged AppContainer (LPAC)** would also hide `C:\Windows`/`Program Files`; Python fails to start under it
   (STATUS_ACCESS_DENIED loading system DLLs). Not pursued; documented as a limitation.
7. **Probe bugs (ours, not the sandbox's):** querying invalid handles raised `STATUS_INVALID_HANDLE` as an exception
   (now caught per handle); `GetCurrentProcess()` pseudo-handle truncated by default `ctypes` types (now typed). The
   "3 disk handles" first seen were resolved to paths: the process's own working directory and Windows message files.
8. **UDP `sendto` to 8.8.8.8 returned success.** That proves nothing; the probe now sends a real DNS query and waits
   for an answer: none arrives (the firewall drops AppContainer traffic silently). TCP fails immediately with 10013;
   loopback TCP to a host listener times out and the listener receives nothing; the host cannot connect to a socket
   the player opens.
9. **Real finding: `HKCU\Environment` is readable by every AppContainer.** It holds the user's persistent environment
   variables (`setx`), a common place to store API keys. Currently it holds no secret (7 harmless names). Rather than
   editing the user's registry ACLs, the host now **refuses to start** if any variable there looks like a credential
   (`exposed_user_environment_secrets`, tested). Windows Credential Manager is denied. 45 of 116 `HKCU` keys (depth 2)
   are readable: Windows' own settings, no third-party software keys.
10. **The privileged session files did not exist yet when the first probe ran** (two `FileNotFoundError` instead of
    `PermissionError`). Added a second attack after play, when screenshots and `session.json` exist: denied.
11. **Disk-fill bound.** The first host version recorded up to 64 KB of every player line and all player stderr. Now
    the first 4 KB of each line (plus full SHA-256 and length) and at most 16 MB of stderr are recorded.
12. **Own tooling mistakes (no effect on results):** heredoc-driven text replacements twice failed on backslash
    escaping (switched to direct edits); a scratch helper's regex assumed a JSON key order and never fired (the
    real test parses JSON).
13. **Negative control added:** the same code that is denied inside the container reads `PROJECT.md` and spawns a
    process when run normally, so the denials are caused by the sandbox.
14. **Results.** `tests/blindplay`: 89 collected (88 passed, 1 non-Windows test skipped); full suite 528 passed, 1
    skipped, 0 failed (one pre-existing warning in `tests/core/test_operate.py`). Evidence recorded twice: a pre-commit
    dry run (`runs/blind-visual/mission014-isolation-20261027`) and the final run on commit `34cee63`
    (`runs/blind-visual/mission014-isolation-34cee63`). The referee manifests of the final run say `dirty: true`; the
    only uncommitted file at that moment was the untracked evidence JSON being written (`git status` showed no
    tracked change). Isolated scripted sessions are byte-identical to Mission 013 (23/23, 66/66, 44/44); all six
    referee sessions replay identically; the 1,076 pre-existing files under `runs/` were hashed before and after:
    unchanged.
15. **First CI run: Windows failed, macOS/Ubuntu passed** (Actions run 40555569128). Two test assumptions that only
    held on this PC: (a) the runner has no `~/.gitconfig`, so the sandbox got "not found" instead of "access denied".
    Nothing was read, but a missing file must not count as proof of denial: the test now attacks only paths that exist
    on the host. This also exposed a real, documented limitation: the player can tell whether a guessed path exists.
    (b) one of the player's own disk handles had no DOS path on the runner. The probe now also reports each handle's
    NT path and error code, and the test checks the drive-relative path instead of assuming a DOS name.
