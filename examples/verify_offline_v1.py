"""Repeat the existing offline v1 workflow in fresh databases, without providers.

Run from the repository root after the documented editable install:
    python examples/verify_offline_v1.py --out runs/offline-v1-verification
The output directory must be new; prior evidence is never overwritten.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys

from rewardbench.config import load_config
from rewardbench.core.ids import canonical_config
from rewardbench.environments import make_environment

ROOT = Path(__file__).resolve().parents[1]
ARMS = ("numerical", "nofeedback")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def command(arguments: list[str], log: Path, *, expected: int = 0) -> None:
    result = subprocess.run([sys.executable, *arguments], cwd=ROOT, text=True, capture_output=True)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    require(result.returncode == expected, f"unexpected exit {result.returncode}: see {log}")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observations(database: Path) -> dict:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        def rows(query: str) -> list[dict]:
            return [dict(row) for row in connection.execute(query)]
        return {
            "attempts": rows("SELECT revision_index, call_index, parameters_json, selected, valid, provider, model_id, total_tokens, estimated_cost_usd FROM attempts ORDER BY revision_index, call_index"),
            "development": rows("SELECT revision_index, episode_index, seed, total_reward, success, crashed, steps, terminated, truncated, metrics_json, error FROM episodes ORDER BY revision_index, episode_index"),
            "freeze": rows("SELECT controller_hash, parameters_json, source_revision_index, source_call_index, selection_rule FROM frozen_controllers"),
            "heldout": rows("SELECT episode_index, seed, total_reward, success, crashed, steps, terminated, truncated, initial_state_json, error FROM heldout_episodes ORDER BY episode_index"),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    output = args.out.resolve()
    configs = {arm: ROOT / f"configs/apollolander_offline_development_{arm}.yaml" for arm in ARMS}
    payloads = []
    for path in configs.values():
        config = load_config(path)
        require(config.provider == "mock", "verification accepts mock providers only")
        require(tuple(config.held_out_seeds) == tuple(range(1_000_000, 1_000_008)), "verification accepts engineering/demo holdout only")
        require(all(0 <= seed < 1_000_000 for seed in config.development_seeds), "unexpected development seeds")
        payload = canonical_config(config)
        for key in ("experiment_name", "feedback_condition"):
            payload.pop(key)
        payloads.append(payload)
    require(payloads[0] == payloads[1], "comparison arms differ beyond feedback and identity")
    output.mkdir(parents=True, exist_ok=False)
    adapter = make_environment("ApolloLander", research_mode=True)
    repeats = []
    replay_count = 0
    for repeat in range(2):
        repeat_dir = output / f"repeat-{repeat + 1}"
        repeat_dir.mkdir()
        paired = {}
        for arm in ARMS:
            database = repeat_dir / f"{arm}.sqlite"
            config_path = str(configs[arm])
            development_args = ["-m", "rewardbench.run", "--config", config_path, "--mode", "mock", "--database", str(database)]
            command(development_args, repeat_dir / f"{arm}-development.log")
            before = observations(database)["attempts"]
            command(development_args, repeat_dir / f"{arm}-resume.log")
            require(observations(database)["attempts"] == before, "completed development called a model again")
            heldout_args = ["-m", "rewardbench.heldout", "--database", str(database), "--source-config", config_path, "--record-dir", str(repeat_dir / "heldout-flights")]
            command(heldout_args, repeat_dir / f"{arm}-heldout.log")
            command(heldout_args, repeat_dir / f"{arm}-repeat-refusal.log", expected=2)
            data = observations(database)
            require(data["attempts"] == before, "held-out scoring changed model attempts")
            require(len(data["development"]) == 2 and len(data["heldout"]) == 8, "missing episodes")
            require(all(row["error"] is None for row in data["development"] + data["heldout"]), "episode errors recorded")
            require(all(row["provider"] == "mock" and row["estimated_cost_usd"] == 0 for row in before), "unexpected provider/cost")
            require(data["development"][0]["seed"] == data["development"][1]["seed"], "revision starts are not matched")
            with sqlite3.connect(database) as connection:
                paths = [Path(row[0]) for row in connection.execute("SELECT replay_path FROM heldout_episodes ORDER BY episode_index")]
                experiment_id = connection.execute("SELECT experiment_id FROM experiments").fetchone()[0]
                require(connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", "SQLite integrity failure")
                require(not connection.execute("PRAGMA foreign_key_check").fetchall(), "SQLite foreign key failure")
            paths += sorted((repeat_dir / "flights" / experiment_id).glob("*.flight.json"))
            require(len(paths) == 10, "missing flight records")
            hashes = []
            for path in paths:
                record = json.loads(path.read_text())
                require(record["origin"] == "deterministic_mock", "mock flight provenance missing")
                require(adapter.verify_flight_record(path)["matched"], f"replay mismatch: {path}")
                hashes.append((record["split"], record["episode_seed"], record["trace_hash"], record["controller_hash"]))
                replay_count += 1
            data["flight_hashes"] = hashes
            report_dir = repeat_dir / f"report-{arm}"
            report_args = ["-m", "rewardbench.analysis", "report", "--logs", str(database), "--out", str(report_dir)]
            command(report_args, repeat_dir / f"{arm}-report.log")
            normalize = lambda text: "\n".join(line for line in text.splitlines() if not line.startswith("- Generated (UTC):"))
            report_before = normalize((report_dir / "report.md").read_text())
            plots_before = {str(path.relative_to(report_dir)): file_hash(path) for path in report_dir.rglob("*.png")}
            require(len(plots_before) == 6, "missing report figures")
            command(report_args, repeat_dir / f"{arm}-report-repeat.log")
            require(normalize((report_dir / "report.md").read_text()) == report_before, "report content changed on identical input")
            require({str(path.relative_to(report_dir)): file_hash(path) for path in report_dir.rglob("*.png")} == plots_before, "figure bytes changed on identical input")
            paired[arm] = data
        require([row["seed"] for row in paired["numerical"]["development"]] == [row["seed"] for row in paired["nofeedback"]["development"]], "arms use different development seeds")
        require([row["initial_state_json"] for row in paired["numerical"]["heldout"]] == [row["initial_state_json"] for row in paired["nofeedback"]["heldout"]], "arms use different held-out starts")
        repeats.append(paired)
    require(repeats[0] == repeats[1], "fresh repetitions differ in deterministic outcomes or traces")
    tracked = ROOT / "docs/assets/v1-evidence/flights/offline_mock_development_episode.flight.json"
    require(adapter.verify_flight_record(tracked)["matched"], "tracked sample replay mismatch")
    summary = {
        "status": "verified", "scope": "scripted offline infrastructure; engineering/demo seeds only; no LLM learning claim",
        "repetitions": 2, "flight_replays_verified": replay_count + 1,
        "report_determinism": "identical text excluding generation timestamp; byte-identical PNGs on repeated input",
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "working_tree_diff_sha256": hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=ROOT)).hexdigest(),
        "verifier_sha256": file_hash(Path(__file__).resolve()),
        "python": platform.python_version(), "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "packages": {name: importlib.metadata.version(name) for name in ("PyYAML", "pytest", "numpy", "scipy", "matplotlib", "gymnasium", "imageio")},
        "observations": repeats[0],
    }
    (output / "verification.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"Verified two fresh paired workflows, {replay_count + 1} replays, reports and figures: {output / 'verification.json'}")


if __name__ == "__main__":
    main()
