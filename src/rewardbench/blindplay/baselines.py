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
from typing import Any, Mapping, Sequence

from rewardbench.blindplay import contract, session

PLAN_SCHEMA = "react.blindplay.baseline-plan.v2"
SEEDED_RANDOM_SEEDS = (0, 1, 2, 3, 4)
OFFICIAL_DIR_NAMES = ("runs", "blind-visual")
FIXTURE_FILE = "NON_STUDY_FIXTURE.txt"


class PlanRefused(RuntimeError):
    pass


# Owner amendment (Mission 018): two separately labelled conditions, never substituted for one another.
CONDITIONS: dict[str, int] = {"matched-1000": 1000, "diagnostic-20000": 20000}
CONDITION_ROLES: dict[str, str] = {
    "matched-1000": "budget-matched control",
    "diagnostic-20000": "extended scripted diagnostic (NOT budget-matched)",
}
CONDITION_FILE = "baseline_condition.json"
PLAN_FILE = "baseline_plan.json"


def condition_role(label: str, max_requests: int) -> str:
    if label in CONDITION_ROLES:
        return CONDITION_ROLES[label]
    return f"custom-{max_requests} (NOT budget-matched, NOT an official condition)"


def _run_spec(name: str, script: str, script_seed: int, keyset: str, episodes: int, frame_budget: int,
              condition: str, max_requests: int) -> dict[str, Any]:
    args = ["--mode", "scripted", "--script", script, "--script-seed", str(script_seed), "--keyset", keyset,
            "--seed", "0", "--episodes", str(episodes), "--episode-frame-budget", str(frame_budget),
            "--max-requests", str(max_requests)]
    return {"name": name, "script": script, "script_seed": script_seed, "condition": condition,
            "condition_role": condition_role(condition, max_requests), "max_requests": max_requests,
            "subdir": f"{condition}_{name}", "host_args": args}


def _resolve_conditions(conditions: Mapping[str, int] | Sequence[str] | None, dry_label: str | None = None) -> dict[str, int]:
    if conditions is None:
        return dict(CONDITIONS)
    if isinstance(conditions, Mapping):
        chosen = dict(conditions)
    else:
        unknown = [c for c in conditions if c not in CONDITIONS]
        if unknown:
            raise ValueError(f"unknown condition(s) {unknown}; known: {sorted(CONDITIONS)}")
        chosen = {c: CONDITIONS[c] for c in conditions}
    if not chosen or any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in chosen.values()):
        raise ValueError("conditions must be a non-empty set with positive integer max_requests")
    for label, limit in chosen.items():
        if label in CONDITIONS:
            if limit != CONDITIONS[label]:
                raise ValueError(f"condition {label!r} is canonically max_requests={CONDITIONS[label]}, refusing {limit}")
        elif not dry_label:
            raise PlanRefused(f"non-canonical condition label {label!r} is allowed only with dry_label (test-only)")
    return chosen


def official_plan(keyset: str, episodes: int = 10, frame_budget: int = session.DEFAULT_EPISODE_FRAME_BUDGET,
                  conditions: Mapping[str, int] | Sequence[str] | None = None,
                  only_scripts: Sequence[str] | None = None, dry_label: str | None = None) -> list[dict[str, Any]]:
    """The 7 protocol runs per condition (default: both conditions, 14 runs). ``conditions`` may name known
    conditions or map label -> max_requests (tests only); ``only_scripts`` restricts scripts (tests/dev only)."""
    contract.version_for(keyset)   # raises on an unknown keyset
    if only_scripts is not None and not dry_label:
        raise PlanRefused("only_scripts is allowed only with dry_label (test-only); an approved run covers all scripts")
    if episodes < 1 or frame_budget < 1:
        raise ValueError("episodes and frame_budget must be positive")
    runs: list[dict[str, Any]] = []
    for cond, limit in _resolve_conditions(conditions, dry_label).items():
        sub = [_run_spec("01_idle", "idle", 0, keyset, episodes, frame_budget, cond, limit),
               _run_spec("02_key-sweep", "key-sweep", 0, keyset, episodes, frame_budget, cond, limit)]
        sub += [_run_spec(f"{3 + n:02d}_seeded-random_seed{seed}", "seeded-random", seed, keyset, episodes, frame_budget, cond, limit)
                for n, seed in enumerate(SEEDED_RANDOM_SEEDS)]
        runs += [r for r in sub if only_scripts is None or r["script"] in only_scripts]
    return runs


def plan_hash(runs: list[dict[str, Any]]) -> str:
    """Path-independent: covers condition labels, max_requests, names, scripts, seeds, keyset and budgets."""
    body = json.dumps({"schema": PLAN_SCHEMA, "runs": runs}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def plan_document(runs: list[dict[str, Any]]) -> dict[str, Any]:
    conds: dict[str, int] = {}
    for r in runs:
        conds[r["condition"]] = r["max_requests"]
    return {"schema": PLAN_SCHEMA, "plan_sha256": plan_hash(runs), "conditions": conds,
            "condition_roles": {c: condition_role(c, m) for c, m in conds.items()}, "runs": runs}


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
             episodes: int = 10, frame_budget: int = session.DEFAULT_EPISODE_FRAME_BUDGET,
             conditions: Mapping[str, int] | Sequence[str] | None = None,
             only_scripts: Sequence[str] | None = None) -> dict[str, Any]:
    if dry_label is None and not (approval_reference and approval_reference.strip()):
        raise PlanRefused("refusing to run without --i-have-owner-approval-reference <text> (this tool does not grant approval)")
    runs = official_plan(keyset, episodes, frame_budget, conditions, only_scripts, dry_label)
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
    (root / PLAN_FILE).write_text(json.dumps(plan_document(runs), indent=2) + "\n", encoding="utf-8")
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    log: list[dict[str, Any]] = []
    for run in runs:
        cmd = command_for(run, root, sys.executable)
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
        tag = {k: run[k] for k in ("name", "subdir", "condition", "condition_role", "max_requests")}
        if (root / run["subdir"]).is_dir():
            (root / run["subdir"] / CONDITION_FILE).write_text(json.dumps(tag, indent=2) + "\n", encoding="utf-8")
        log.append({**tag, "exit_code": proc.returncode, "stdout": proc.stdout.strip()[-2000:],
                    "stderr": proc.stderr.strip()[-2000:]})
        if proc.returncode != 0:
            break
    result = {"schema": PLAN_SCHEMA, "plan_sha256": digest, "conditions": plan_document(runs)["conditions"],
              "out_root": str(root), "dry_label": dry_label,
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
        p.add_argument("--condition", choices=sorted(CONDITIONS), action="append", default=None,
                       help="restrict to one condition (repeatable); DEFAULT is both, and the official plan hash covers both")
        p.add_argument("--dry-label", default=None, help="write under NON-STUDY-<label> (tests/dev only)")
        if name == "run":
            p.add_argument("--i-have-owner-approval-reference", dest="approval", default=None)
    args = parser.parse_args(argv)
    runs = official_plan(args.keyset, args.episodes, args.frame_budget, args.condition)
    root = resolve_out_root(args.out_root, args.dry_label)
    if args.cmd == "plan":
        current = None
        for run in runs:
            if run["condition"] != current:
                current = run["condition"]
                print(f"# condition {current}: max_requests={run['max_requests']} -- {run['condition_role']}")
            print(" ".join(command_for(run, root)))
        print("# Both budgets are reported side by side; neither is ever substituted for the other.")
        print(f"plan_sha256 {plan_hash(runs)}")
        return 0
    try:
        result = run_plan(args.keyset, args.out_root, approval_reference=args.approval, dry_label=args.dry_label,
                          episodes=args.episodes, frame_budget=args.frame_budget, conditions=args.condition)
    except PlanRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != "runs"}, indent=2))
    return 0 if result["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
