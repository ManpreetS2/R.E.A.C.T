"""Command line for RewardBench analysis.

Examples
--------
python -m rewardbench.analysis report --logs runs/rewardbench.sqlite --out reports/run1
python -m rewardbench.analysis export --logs runs/rewardbench.sqlite --out exports/run1.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rewardbench.analysis.export import export_jsonl
from rewardbench.analysis.load import load_logs
from rewardbench.analysis.report import write_report
from rewardbench.analysis.schema import AnalysisError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.analysis")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser("report", help="write a markdown report from a log")
    report.add_argument("--logs", required=True, type=Path)
    report.add_argument("--out", required=True, type=Path)
    report.add_argument("--confidence", type=float, default=0.95)
    report.add_argument(
        "--reward-targets",
        default="200",
        help="comma-separated reward thresholds, for example 0,200",
    )

    export = subparsers.add_parser("export", help="write a JSONL copy of a log")
    export.add_argument("--logs", required=True, type=Path)
    export.add_argument("--out", required=True, type=Path)

    args = parser.parse_args(argv)
    try:
        bundle = load_logs(args.logs)
        if args.command == "export":
            path = export_jsonl(bundle, args.out)
            print(path)
            return 0
        targets = _targets(args.reward_targets)
        result = write_report(
            bundle,
            args.out,
            confidence=args.confidence,
            reward_targets=targets,
        )
        print(result.markdown_path)
        return 0
    except (AnalysisError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _targets(raw: str) -> tuple[float, ...]:
    pieces = [piece.strip() for piece in raw.split(",") if piece.strip()]
    if not pieces:
        raise ValueError("reward targets must not be empty")
    return tuple(float(piece) for piece in pieces)


if __name__ == "__main__":
    raise SystemExit(main())
