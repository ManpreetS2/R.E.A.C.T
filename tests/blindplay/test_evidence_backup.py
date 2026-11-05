"""The evidence tools on disposable fixtures only. They never touch the real ``runs/``."""

from __future__ import annotations

import json

import pytest

from rewardbench import evidence_backup as eb


def _tree(tmp_path):
    root = tmp_path / "repo"
    (root / "runs" / "a").mkdir(parents=True)
    (root / "runs" / "a" / "one.bin").write_bytes(b"one")
    (root / "runs" / "two.bin").write_bytes(b"two")
    return root


def test_verify_manifest_detects_missing_and_mismatch(tmp_path):
    root = _tree(tmp_path)
    manifest = tmp_path / "m.json"
    good = {"experiments": [{"artifacts": [{"path": "runs/a/one.bin", "sha256": eb.sha256_file(root / "runs/a/one.bin")},
                                           {"path": "runs/two.bin", "sha256": "0" * 64},
                                           {"path": "runs/gone.bin", "sha256": "1" * 64}]}]}
    manifest.write_text(json.dumps(good))
    result = eb.verify_manifest(root, manifest)
    assert result == {"ok": 1, "missing": ["runs/gone.bin"], "mismatched": ["runs/two.bin"], "complete": False}


def test_inventory_and_copy_check_round_trip(tmp_path):
    root = _tree(tmp_path)
    inv = eb.inventory(root)
    assert inv["file_count"] == 2 and inv["total_bytes"] == 6
    copy = tmp_path / "copy"
    (copy / "runs" / "a").mkdir(parents=True)
    (copy / "runs/a/one.bin").write_bytes(b"one")
    (copy / "runs/two.bin").write_bytes(b"two")
    assert eb.check_copy(inv, copy)["complete"] is True
    (copy / "runs/two.bin").write_bytes(b"TWO")
    (copy / "runs/extra.bin").write_bytes(b"x")
    result = eb.check_copy(inv, copy)
    assert result["mismatched"] == ["runs/two.bin"] and result["extra"] == ["runs/extra.bin"] and not result["complete"]


def test_prepare_never_overwrites_and_refuses_output_inside_runs(tmp_path):
    root = _tree(tmp_path)
    out = tmp_path / "inv.json"
    assert eb.main(["prepare", "--root", str(root), "--out", str(out)]) == 0
    before = out.read_bytes()
    with pytest.raises(SystemExit):
        eb.main(["prepare", "--root", str(root), "--out", str(out)])
    with pytest.raises(SystemExit):
        eb.main(["prepare", "--root", str(root), "--out", str(root / "runs" / "inv.json")])
    assert out.read_bytes() == before
    assert sorted(p.name for p in (root / "runs").rglob("*") if p.is_file()) == ["one.bin", "two.bin"]
