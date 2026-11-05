"""Protocol §7 baseline plan (idle, key-sweep, seeded-random seeds 0-4) through the isolated host.

``plan`` only prints. ``run`` executes the plan sequentially, and only when the caller supplies
``--i-have-owner-approval-reference <text>``. That text is recorded verbatim; this tool never verifies or claims
approval itself. It never overwrites: the out root must not exist, and it must not sit inside an existing
official-looking directory that already holds files. ``--dry-label`` writes under a ``NON-STUDY-<label>``
directory stamped ``NON_STUDY_FIXTURE.txt`` and needs no approval reference (tests and development only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from rewardbench.blindplay import contract, session

PLAN_SCHEMA = "react.blindplay.baseline-plan.v1"
SEEDED_RANDOM_SEEDS = (0, 1, 2, 3, 4)
OFFICIAL_DIR_NAMES = ("runs", "blind-visual")
FIXTURE_FILE = "NON_STUDY_FIXTURE.txt"


class PlanRefused(RuntimeError):
    pass


def _run_spec(name: str, script: str, script_seed: int, keyset: str, episodes: int, frame_budget: int) -> dict[str, Any]:
    args = ["--mode", "scripted", "--script", script, "--script-seed", str(script_seed), "--keyset", keyset,
            "--seed", "0", "--episodes", str(episodes), "--episode-frame-budget", str(frame_budget)]
    return {"name": name, "script": script, "script_seed": script_seed, "subdir": name, "host_args": args}


def official_plan(keyset: str, episodes: int = 10, frame_budget: int = session.DEFAULT_EPISODE_FRAME_BUDGET) -> list[dict[str, Any]]:
    contract.version_for(keyset)   # raises on an unknown keyset
    if episodes < 1 or frame_budget < 1:
        raise ValueError("episodes and frame_budget must be positive")
    runs = [_run_spec("01_idle", "idle", 0, keyset, episodes, frame_budget),
            _run_spec("02_key-sweep", "key-sweep", 0, keyset, episodes, frame_budget)]
    runs += [_run_spec(f"{3 + n:02d}_seeded-random_seed{seed}", "seeded-random", seed, keyset, episodes, frame_budget)
             for n, seed in enumerate(SEEDED_RANDOM_SEEDS)]
    return runs


def plan_hash(runs: list[dict[str, Any]]) -> str:
    """Path-independent: covers names, scripts, seeds, keyset and budgets, not where the output lands."""
    body = json.dumps({"schema": PLAN_SCHEMA, "runs": runs}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def command_for(run: dict[str, Any], out_root: Path, python: str = "python") -> list[str]:
    return [python, "-m", "rewardbench.blindplay.host", "--out", str(Path(out_root) / run["subdir"]), *run["host_args"]]


def _looks_official(path: Path) -> bool:
    return path.name.lower() in OFFICIAL_DIR_NAMES or "blind-visual" in path.name.lower()


def resolve_out_root(out_root: Path, dry_label: str | None) -> Path:
    root = Path(out_root)
    if dry_label:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in dry_label)
        root = root / f"NON-STUDY-{safe}"
    return root


def check_out_root(root: Path) -> None:
    root = Path(root).resolve()
    if root.exists():
        raise PlanRefused(f"out root already exists, never overwriting: {root}")
    for parent in root.parents:
        if parent.is_dir() and _looks_official(parent) and any(f.is_file() for f in parent.rglob("*")):
            raise PlanRefused(f"out root is inside an existing official-looking directory with files: {parent}")


def run_plan(keyset: str, out_root: Path, *, approval_reference: str | None, dry_label: str | None = None,
             episodes: int = 10, frame_budget: int = session.DEFAULT_EPISODE_FRAME_BUDGET) -> dict[str, Any]:
    if dry_label is None and not (approval_reference and approval_reference.strip()):
        raise PlanRefused("refusing to run without --i-have-owner-approval-reference <text> (this tool does not grant approval)")
    runs = official_plan(keyset, episodes, frame_budget)
    root = resolve_out_root(out_root, dry_label)
    check_out_root(root)
    root.mkdir(parents=True, exist_ok=False)
    digest = plan_hash(runs)
    if dry_label:
        (root / FIXTURE_FILE).write_text(
            f"NON-STUDY fixture (label {dry_label!r}). Not study evidence. Plan sha256 {digest}.\n", encoding="utf-8")
    else:
        (root / "OWNER_APPROVAL_REFERENCE.txt").write_text(
            f"Reference supplied by the operator, recorded verbatim and not verified by this tool:\n"
            f"{approval_reference.strip()}\nPlan sha256 {digest}\n", encoding="utf-8")
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    log: list[dict[str, Any]] = []
    for run in runs:
        cmd = command_for(run, root, sys.executable)
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        log.append({"name": run["name"], "exit_code": proc.returncode, "stdout": proc.stdout.strip()[-2000:],
                    "stderr": proc.stderr.strip()[-2000:]})
        if proc.returncode != 0:
            break
    result = {"schema": PLAN_SCHEMA, "plan_sha256": digest, "out_root": str(root), "dry_label": dry_label,
              "planned_runs": len(runs), "executed_runs": len(log), "complete": len(log) == len(runs) and all(r["exit_code"] == 0 for r in log),
              "runs": log}
    (root / "baseline_run_log.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.baselines", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--keyset", choices=sorted(contract.CONTRACTS), required=True)
        p.add_argument("--out-root", type=Path, required=True)
        p.add_argument("--episodes", type=int, default=10)
        p.add_argument("--frame-budget", type=int, default=session.DEFAULT_EPISODE_FRAME_BUDGET)
        p.add_argument("--dry-label", default=None, help="write under NON-STUDY-<label> (tests/dev only)")
        if name == "run":
            p.add_argument("--i-have-owner-approval-reference", dest="approval", default=None)
    args = parser.parse_args(argv)
    runs = official_plan(args.keyset, args.episodes, args.frame_budget)
    root = resolve_out_root(args.out_root, args.dry_label)
    if args.cmd == "plan":
        for run in runs:
            print(" ".join(command_for(run, root)))
        print(f"plan_sha256 {plan_hash(runs)}")
        return 0
    try:
        result = run_plan(args.keyset, args.out_root, approval_reference=args.approval, dry_label=args.dry_label,
                          episodes=args.episodes, frame_budget=args.frame_budget)
    except PlanRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=2))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
