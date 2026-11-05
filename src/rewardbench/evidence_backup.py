"""Read-only evidence tools for the gitignored ``runs/`` directory. Nothing here writes into, moves or deletes evidence.

    python -m rewardbench.evidence_backup verify  --root <repo-root> [--manifest docs/assets/research-results/MANIFEST.json]
    python -m rewardbench.evidence_backup prepare --root <repo-root> --out <inventory.json>      # hashes every file under runs/
    python -m rewardbench.evidence_backup check-copy --inventory <inventory.json> --copy <extracted-dir>

``verify`` checks the committed manifest. ``prepare`` writes an inventory (paths, sizes, SHA-256) of everything under ``runs/``,
including sessions the manifest does not list. ``check-copy`` compares an extracted off-machine copy against an inventory.
The output file must not be inside ``runs/``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterator

DEFAULT_MANIFEST = "docs/assets/research-results/MANIFEST.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _artifacts(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        if "path" in node and "sha256" in node:
            yield node
        for value in node.values():
            yield from _artifacts(value)
    elif isinstance(node, list):
        for value in node:
            yield from _artifacts(value)


def verify_manifest(root: Path, manifest: Path) -> dict[str, Any]:
    """Compare every artifact listed in ``manifest`` against ``root``. Read-only."""
    data = json.loads(manifest.read_text(encoding="utf-8"))
    ok, missing, mismatched = 0, [], []
    for artifact in _artifacts(data):
        path = root / artifact["path"]
        if not path.is_file():
            missing.append(artifact["path"])
        elif sha256_file(path) != artifact["sha256"]:
            mismatched.append(artifact["path"])
        else:
            ok += 1
    return {"ok": ok, "missing": missing, "mismatched": mismatched, "complete": not missing and not mismatched}


def inventory(root: Path) -> dict[str, Any]:
    """Hash every regular file under ``root/runs`` (links are listed, never followed)."""
    runs = root / "runs"
    files, skipped = [], []
    for path in sorted(runs.rglob("*")):
        if path.is_symlink():
            skipped.append(path.relative_to(root).as_posix())
        elif path.is_file():
            files.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return {"root_directory": "runs", "file_count": len(files), "total_bytes": sum(f["bytes"] for f in files),
            "files": files, "skipped_links": skipped}


def check_copy(inv: dict[str, Any], copy_root: Path) -> dict[str, Any]:
    """Compare an extracted copy (a directory that contains ``runs/``) against an inventory. Read-only."""
    missing, mismatched = [], []
    for entry in inv["files"]:
        path = copy_root / entry["path"]
        if not path.is_file():
            missing.append(entry["path"])
        elif path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            mismatched.append(entry["path"])
    extra = sorted({p.relative_to(copy_root).as_posix() for p in (copy_root / "runs").rglob("*") if p.is_file()}
                   - {e["path"] for e in inv["files"]}) if (copy_root / "runs").is_dir() else []
    return {"missing": missing, "mismatched": mismatched, "extra": extra,
            "complete": not missing and not mismatched, "checked": len(inv["files"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.evidence_backup", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify")
    v.add_argument("--root", type=Path, required=True)
    v.add_argument("--manifest", type=Path, default=None)
    p = sub.add_parser("prepare")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check-copy")
    c.add_argument("--inventory", type=Path, required=True)
    c.add_argument("--copy", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "verify":
        manifest = args.manifest or Path(__file__).resolve().parents[2] / DEFAULT_MANIFEST
        result = verify_manifest(args.root, manifest)
    elif args.command == "prepare":
        out = args.out.resolve()
        if out.is_relative_to((args.root / "runs").resolve()):
            parser.error("--out must not be inside runs/")
        if out.exists():
            parser.error("--out already exists; this tool never overwrites")
        result = inventory(args.root)
        out.write_text(json.dumps(result, indent=1), encoding="utf-8")
        result = {k: result[k] for k in ("file_count", "total_bytes")} | {"written": str(out)}
    else:
        result = check_copy(json.loads(args.inventory.read_text(encoding="utf-8")), args.copy)
    print(json.dumps(result, indent=1))
    return 0 if result.get("complete", True) else 1


if __name__ == "__main__":
    sys.exit(main())
