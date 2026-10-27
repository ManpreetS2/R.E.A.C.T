"""The authentic upstream ApolloLander files, pinned by SHA-256.

The referee serves the game only from these files. Hashes are of the files at
https://github.com/sebleedelisle/apollolander commit ``UPSTREAM_COMMIT`` as
downloaded on 2026-10-27 (Mission 013) and match the blobs committed under
``frontend/apollolander/upstream``. A Windows checkout with ``core.autocrlf``
has CRLF line endings; text files are normalised back to LF before hashing,
which reproduces the upstream bytes exactly (no upstream text file contains a
carriage return). Any other difference refuses to start.

Nothing here reads the repository's custom reimplemented simulator (a
different environment, PROJECT.md section 20.3 C).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

UPSTREAM_REPOSITORY = "https://github.com/sebleedelisle/apollolander"
UPSTREAM_COMMIT = "0da09dccbadf0d6ee6efcce1f72e9ae206d341d2"
UPSTREAM_DIR = Path(__file__).resolve().parents[3] / "frontend" / "apollolander" / "upstream"

UPSTREAM_SHA256 = {
    "InfoDisplay.js": "cd966af39ba0e29f34c145924a8f94bb338225204003c75ae4f028f20f7af69a",
    "LICENSE": "b9c117624bc7bb8a96017f1682a20eda1db23add0fe1ec571551803c73c4de71",
    "Lander.js": "67c64fdc7fd47dd1c22bbc67616d338bf09613be8816f233cd7624d705cbed44",
    "Landscape.js": "80b608096ca77ccf6a99fc382676a8f6811ba4ffbb46d0ef3cc56ec062474ccf",
    "Sounds.js": "210df00a2622f843c40db5c7e493ade592e22e8dac128f263de2a7bce6e36f9a",
    "TouchController.js": "5bbab481fc863c2488cfb24aa5f9c0e9a64128bcdb3540611411460ea2d4c4ff",
    "fonts/avhersheysimplexmedium-webfont.woff": "220d02c43b33b49b6418c4435af449558cbf21754b1216d9680ed7e870607031",
    "fonts/avhersheysimplexmedium-webfont.woff2": "36317491af6511486a9d6b572358f984a5a1c3fb6abf9796782d73fb79cd9303",
    "game.js": "b51d73332fa0b1f584c4ef7574d53ccf74431c20a340d61906d082867916dd39",
    "index.html": "a8a02ccedd1567dc5c406751957b89a6a14f9c8fda5a70957149fa8de2eee26b",
    "libs/KeyTracker.js": "c0d02aa5865ba1c5e53c25266cc2b684392920280767ab08266cafeec79974a0",
    "libs/Vector2.js": "ba77e8495749818340a9255f58a5d4fd601202e592cc0295716918c255254e7f",
    "libs/audio.js": "d559c3ddd2c3742f2d6660110d02bd492d69a7a28709f8fa316a41f83070e238",
    "libs/jsfx.js": "20a2b65e453695d23c7f2f7618eff79f4d6a933cb65a5b90df03f9581a09c130",
    "libs/jsfxlib.js": "d9d324469419e2467501f2d804df67a226e673ae11ef66cd2fca49e28e910404",
    "libs/rAF.js": "befdc219193bccc17eeefd308f92ade73ad1e2605c7742d21ee6757f2257fa15",
    "perlin.js": "71e83a16ee13df4eaf5042a1e2e604afe39c71ff0b205a0ab627fe154428f88c",
}

BINARY_SUFFIXES = (".woff", ".woff2")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    "": "text/plain; charset=utf-8",
}


class UpstreamIntegrityError(RuntimeError):
    """A vendored file is missing or differs from the pinned upstream bytes."""


def _normalised(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix in BINARY_SUFFIXES:
        return data
    return data.replace(b"\r\n", b"\n")


def load_upstream(directory: Path = UPSTREAM_DIR) -> dict[str, bytes]:
    """Every pinned file as exact upstream bytes; raises on any mismatch."""
    files: dict[str, bytes] = {}
    for name, expected in UPSTREAM_SHA256.items():
        path = directory / name
        if not path.is_file():
            raise UpstreamIntegrityError(f"missing upstream file {name}")
        data = _normalised(path)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise UpstreamIntegrityError(f"{name}: sha256 {actual} != pinned {expected}")
        files[name] = data
    return files


def content_type(name: str) -> str:
    return CONTENT_TYPES.get(Path(name).suffix, CONTENT_TYPES[""])
