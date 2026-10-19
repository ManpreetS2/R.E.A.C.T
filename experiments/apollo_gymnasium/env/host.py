"""Static server + Playwright host for the upstream ApolloOriginal bridge."""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APOLLO_ROOT = ROOT / "frontend" / "apollolander"
DEFAULT_PORT = 18770

_server_proc: subprocess.Popen | None = None
_pw = None
_browser = None
_lock = threading.Lock()
_page_refs = 0


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_static_server(port: int = DEFAULT_PORT) -> str:
    global _server_proc
    if _port_open(port):
        return f"http://127.0.0.1:{port}/original/index.html"
    _server_proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(APOLLO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def _cleanup() -> None:
        if _server_proc and _server_proc.poll() is None:
            _server_proc.terminate()

    atexit.register(_cleanup)
    for _ in range(100):
        if _port_open(port):
            return f"http://127.0.0.1:{port}/original/index.html"
        time.sleep(0.05)
    raise RuntimeError(f"static server failed on port {port}")


def _chromium_executable() -> str | None:
    """Prefer an installed Chromium binary when Playwright's default path is missing."""
    cache = Path(
        os.environ.get(
            "PLAYWRIGHT_BROWSERS_PATH",
            Path.home() / "Library" / "Caches" / "ms-playwright",
        )
    )
    candidates = [
        cache
        / "chromium-1248"
        / "chrome-mac-arm64"
        / "Google Chrome for Testing.app"
        / "Contents"
        / "MacOS"
        / "Google Chrome for Testing",
        cache
        / "chromium-1248"
        / "chrome-mac-x64"
        / "Google Chrome for Testing.app"
        / "Contents"
        / "MacOS"
        / "Google Chrome for Testing",
        cache
        / "chromium_headless_shell-1248"
        / "chrome-headless-shell-mac-arm64"
        / "chrome-headless-shell",
        cache
        / "chromium_headless_shell-1248"
        / "chrome-headless-shell-mac-x64"
        / "chrome-headless-shell",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def _ensure_browser(*, headless: bool = True):
    """One shared Playwright + Chromium for all Gym envs (avoids sync-API loop conflicts)."""
    global _pw, _browser
    with _lock:
        if _browser is not None:
            return _pw, _browser
        from playwright.sync_api import sync_playwright

        _pw = sync_playwright().start()
        launch_kwargs: dict = {"headless": headless}
        exe = _chromium_executable()
        if exe is not None:
            launch_kwargs["executable_path"] = exe
        _browser = _pw.chromium.launch(**launch_kwargs)

        def _shutdown() -> None:
            global _pw, _browser, _page_refs
            try:
                if _browser is not None:
                    _browser.close()
            except Exception:
                pass
            try:
                if _pw is not None:
                    _pw.stop()
            except Exception:
                pass
            _browser = None
            _pw = None
            _page_refs = 0

        atexit.register(_shutdown)
        return _pw, _browser


def make_browser_page(url: str, *, headless: bool = True):
    """Return (pw, browser, context, page). Context/page are per-env; browser is shared."""
    global _page_refs
    pw, browser = _ensure_browser(headless=headless)
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(f"console:{msg.type}:{msg.text}")
        if msg.type == "error"
        else None,
    )
    page.goto(url, wait_until="load", timeout=60_000)
    try:
        page.wait_for_function("() => window.__originalBridgeReady === true", timeout=60_000)
    except Exception as exc:
        context.close()
        raise RuntimeError(
            f"ApolloOriginal bridge failed to become ready at {url}. page_errors={errors[:8]}"
        ) from exc
    with _lock:
        _page_refs += 1
    return pw, browser, context, page


def release_browser_page(context) -> None:
    """Close one env's context; leave shared browser alive for siblings."""
    global _page_refs
    try:
        if context is not None:
            context.close()
    finally:
        with _lock:
            _page_refs = max(0, _page_refs - 1)
