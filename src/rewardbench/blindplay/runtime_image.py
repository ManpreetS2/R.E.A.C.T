"""The read-only runtime image an isolated player executes from.

TRUSTED HOST SIDE. The AppContainer can read nothing it is not explicitly granted, including the
installed Python and this repository. The host therefore assembles a minimal, standalone directory:

    <image>/python/        python.exe + its DLLs + the standard library (no site-packages, no tests, no tk)
    <image>/python/python3XX._pth   fixes sys.path to the image; ``import site`` is absent
    <image>/player/        the player-side code (``player_runtime/*.py``, standard library only)
    <image>/MANIFEST.json  SHA-256 of every file

and grants the container SID read+execute on it, nothing else (no write, no other directory). The
image directory name is the hash of its manifest, and ``verify`` re-hashes every file before each
session, so an altered image is never used.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from rewardbench.blindplay import isolation

PLAYER_SOURCE = Path(__file__).with_name("player_runtime")
SCHEMA = "react.blindplay.runtime-image.v1"
_LIB_EXCLUDE = {"site-packages", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3",
                "__pycache__", "venv", "pydoc_data"}
_DLL_EXCLUDE = ("_tkinter", "tcl", "tk")


def default_root() -> Path:
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


def _sources() -> list[tuple[Path, str]]:
    files = _python_files(Path(sys.base_prefix))
    for p in sorted(PLAYER_SOURCE.glob("*.py")):
        files.append((p, f"player/{p.name}"))
    return files


def _pth_name() -> str:
    return f"python/python{sys.version_info.major}{sys.version_info.minor}._pth"


_PTH = b"Lib\r\nDLLs\r\n../player\r\n"


def _digest(entries: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


def build(root: Path | None = None) -> Path:
    """Build (or reuse) the image for this Python and player code; returns its directory."""
    reason = isolation.supported()
    if reason:
        raise isolation.IsolationUnavailable(reason)
    root = Path(root or default_root())
    sources = _sources()
    entries = {rel: hashlib.sha256(src.read_bytes()).hexdigest() for src, rel in sources}
    entries[_pth_name()] = hashlib.sha256(_PTH).hexdigest()
    image = root / _digest(entries)[:24]
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
    (staging / _pth_name()).write_bytes(_PTH)
    manifest = {"schema": SCHEMA, "python": sys.version.split()[0], "files": entries, "digest": _digest(entries)}
    (staging / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
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
    if _digest(manifest["files"]) != manifest["digest"] or not image.name == manifest["digest"][:24]:
        raise RuntimeError("runtime image manifest does not match its directory")
    return manifest


def python_executable(image: Path) -> Path:
    return image / "python" / "python.exe"
