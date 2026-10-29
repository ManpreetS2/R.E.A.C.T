"""The read-only runtime image an isolated player executes from.

TRUSTED HOST SIDE. The sandbox can read nothing it is not explicitly granted, including the
installed Python and this repository. The host therefore assembles a minimal, standalone directory.

Windows (AppContainer):

    <image>/python/        python.exe + its DLLs + the standard library (no site-packages, no tests, no tk)
    <image>/python/python3XX._pth   fixes sys.path to the image; ``import site`` is absent

macOS (Seatbelt):

    <image>/python/bin/python3        the interpreter (a framework build's inner ``Python.app`` binary)
    <image>/python/bin/python3._pth   fixes sys.path to the image (honoured by getpath on macOS too)
    <image>/python/lib/python3.X/     the standard library; extension modules only if they link nothing
                                      but system libraries

both:

    <image>/player/        the player-side code (``player_runtime/*.py``, standard library only)
    <image>/MANIFEST.json  SHA-256 of every file, plus ``external``: non-system libraries the interpreter
                           links (e.g. a framework's ``Python`` dylib) by absolute path and SHA-256

On Windows the container SID is granted read+execute on the image, nothing else (no write, no other
directory); on macOS the per-launch Seatbelt profile allows reading exactly the image and ``external``.
The image directory name is the hash of its manifest, and ``verify`` re-hashes every file (including
``external``) before each session, so an altered image is never used.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from rewardbench.blindplay import isolation

PLAYER_SOURCE = Path(__file__).with_name("player_runtime")
SCHEMA = "react.blindplay.runtime-image.v1"
_LIB_EXCLUDE = {"site-packages", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3",
                "__pycache__", "venv", "pydoc_data"}
_DLL_EXCLUDE = ("_tkinter", "tcl", "tk")


def default_root() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "REACT-blindplay" / "runtime-images"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "REACT-blindplay" / "runtime-images"


def _python_files(base: Path) -> list[tuple[Path, str]]:
    major_minor = f"{sys.version_info.major}{sys.version_info.minor}"
    files: list[tuple[Path, str]] = []
    for name in ("python.exe", "python3.dll", f"python{major_minor}.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
        if (base / name).is_file():
            files.append((base / name, f"python/{name}"))
    for p in sorted((base / "DLLs").iterdir()):
        if p.is_file() and not p.name.lower().startswith(_DLL_EXCLUDE) and p.suffix.lower() in (".pyd", ".dll"):
            files.append((p, f"python/DLLs/{p.name}"))
    lib = base / "Lib"
    for root, dirs, names in os.walk(lib):
        dirs[:] = sorted(d for d in dirs if d not in _LIB_EXCLUDE)
        for n in sorted(names):
            if n.endswith(".py"):
                src = Path(root) / n
                files.append((src, "python/Lib/" + src.relative_to(lib).as_posix()))
    return files


_SYSTEM_LIBRARY_PREFIXES = ("/usr/lib/", "/System/")


def _linked_libraries(path: Path) -> list[str]:
    """Libraries a Mach-O file loads (``otool -L``), excluding its own install name."""
    out = subprocess.run(["/usr/bin/otool", "-L", str(path)], capture_output=True, text=True, check=True).stdout
    names = [line.strip().split(" (compatibility")[0] for line in out.splitlines() if line.startswith("\t")]
    own = subprocess.run(["/usr/bin/otool", "-D", str(path)], capture_output=True, text=True).stdout.splitlines()[1:]
    return sorted(set(names) - {o.strip() for o in own})


def _macos_interpreter() -> Path:
    base = Path(sys.base_prefix)
    inner = base / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"   # framework builds re-exec this
    if inner.is_file():
        return inner
    return Path(os.path.realpath(getattr(sys, "_base_executable", sys.executable)))


def _macos_python_files() -> tuple[list[tuple[Path, str]], list[Path]]:
    """Interpreter + stdlib for the image, and the non-system libraries the interpreter needs in place."""
    interpreter = _macos_interpreter()
    external = []
    for lib in _linked_libraries(interpreter):
        if lib.startswith(_SYSTEM_LIBRARY_PREFIXES):
            continue
        if not lib.startswith("/"):
            raise isolation.IsolationUnavailable(f"interpreter links a relative library ({lib}); use another Python build")
        external.append(Path(os.path.realpath(lib)))
    allowed = {str(p) for p in external}
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    files: list[tuple[Path, str]] = [(interpreter, "python/bin/python3")]
    lib = Path(sysconfig.get_paths()["stdlib"])
    for root, dirs, names in os.walk(lib):
        dirs[:] = sorted(d for d in dirs if d not in _LIB_EXCLUDE and not d.startswith("config-"))
        for n in sorted(names):
            src = Path(root) / n
            if n.endswith(".py") or (n.endswith(".so") and all(
                    d.startswith(_SYSTEM_LIBRARY_PREFIXES) or os.path.realpath(d) in allowed
                    for d in _linked_libraries(src))):
                files.append((src, f"python/lib/{version}/" + src.relative_to(lib).as_posix()))
    return files, sorted(set(external))


def _sources() -> tuple[list[tuple[Path, str]], list[Path]]:
    if sys.platform == "darwin":
        files, external = _macos_python_files()
    else:
        files, external = _python_files(Path(sys.base_prefix)), []
    for p in sorted(PLAYER_SOURCE.glob("*.py")):
        files.append((p, f"player/{p.name}"))
    return files, external


def _pth_name() -> str:
    if sys.platform == "darwin":
        return "python/bin/python3._pth"
    return f"python/python{sys.version_info.major}{sys.version_info.minor}._pth"


def _pth() -> bytes:
    if sys.platform == "darwin":
        version = f"python{sys.version_info.major}.{sys.version_info.minor}"
        return f"../lib/{version}\n../lib/{version}/lib-dynload\n../../player\n".encode()
    return b"Lib\r\nDLLs\r\n../player\r\n"


def _digest(entries: dict[str, str], external: dict[str, str] | None = None) -> str:
    combined = dict(entries, **{f"external:{k}": v for k, v in (external or {}).items()})
    return hashlib.sha256(json.dumps(combined, sort_keys=True).encode()).hexdigest()


def build(root: Path | None = None) -> Path:
    """Build (or reuse) the image for this Python and player code; returns its directory."""
    reason = isolation.supported()
    if reason:
        raise isolation.IsolationUnavailable(reason)
    root = Path(root or default_root())
    sources, external_paths = _sources()
    entries = {rel: hashlib.sha256(src.read_bytes()).hexdigest() for src, rel in sources}
    entries[_pth_name()] = hashlib.sha256(_pth()).hexdigest()
    external = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in external_paths}
    image = root / _digest(entries, external)[:24]
    if (image / "MANIFEST.json").is_file():
        verify(image)
        return image
    staging = root / (image.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    for src, rel in sources:
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    (staging / _pth_name()).write_bytes(_pth())
    if sys.platform == "darwin":
        os.chmod(staging / "python" / "bin" / "python3", 0o755)
    manifest = {"schema": SCHEMA, "python": sys.version.split()[0], "files": entries, "external": external,
                "digest": _digest(entries, external)}
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if sys.platform == "win32":
        isolation.grant_read_execute(staging, isolation.container_sid())
    staging.rename(image)
    verify(image)
    return image


def verify(image: Path) -> dict:
    """Re-hash every file; raise if anything was added, removed or changed. Returns the manifest."""
    manifest = json.loads((image / "MANIFEST.json").read_text(encoding="utf-8"))
    present = {p.relative_to(image).as_posix() for p in image.rglob("*")
               if p.is_file() and p.name != "MANIFEST.json" and "__pycache__" not in p.parts}
    if present != set(manifest["files"]):
        raise RuntimeError(f"runtime image {image} has unexpected or missing files: {sorted(present ^ set(manifest['files']))[:5]}")
    for rel, digest in manifest["files"].items():
        if hashlib.sha256((image / rel).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"runtime image file changed: {rel}")
    external = manifest.get("external", {})
    for path, digest in external.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"runtime image external library changed: {path}")
    if _digest(manifest["files"], external) != manifest["digest"] or not image.name == manifest["digest"][:24]:
        raise RuntimeError("runtime image manifest does not match its directory")
    return manifest


def python_executable(image: Path) -> Path:
    if sys.platform == "darwin":
        return image / "python" / "bin" / "python3"
    return image / "python" / "python.exe"


def external_libraries(image: Path) -> tuple[Path, ...]:
    """Non-system libraries the sandbox must let the interpreter read where they are installed."""
    manifest = json.loads((image / "MANIFEST.json").read_text(encoding="utf-8"))
    return tuple(Path(p) for p in sorted(manifest.get("external", {})))
