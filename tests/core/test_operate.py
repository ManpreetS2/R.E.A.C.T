"""The operator command orchestrates existing CLIs and keeps mock/live honest."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from rewardbench.operate import main

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
NOFEEDBACK = CONFIGS / "apollolander_offline_development_nofeedback.yaml"
REWARD_ONLY = CONFIGS / "apollolander_offline_development_rewardonly.yaml"
PILOT = CONFIGS / "apollolander_pilot_openai_gpt54mini.yaml"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")


@needs_node
def test_mock_run_executes_every_stage_and_is_resumable(tmp_path: Path, capsys) -> None:
    out = tmp_path / "out"
    args = ["run", "--config", str(NOFEEDBACK), "--config", str(REWARD_ONLY),
            "--heldout", "--out", str(out)]
    assert main(args) == 0
    text = capsys.readouterr().out
    assert "MOCK MODE" in text and "NOT an LLM result" in text
    for name in ("nofeedback", "rewardonly"):
        stem = f"apollolander-offline-development-{name}"
        assert (out / f"{stem}.sqlite").exists()
        assert (out / "reports" / stem / "report.md").exists()
        assert len(list((out / "prompts" / stem).glob("revision_*.txt"))) == 2
        assert list((out / "flights").rglob("*.flight.json"))
        assert list((out / "heldout-flights" / stem).rglob("*.flight.json"))
    with sqlite3.connect(out / "apollolander-offline-development-rewardonly.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM heldout_episodes").fetchone()[0] == 8
        before = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]

    # Same --out again: resumes without new model calls or a held-out rerun.
    assert main(args) == 0
    assert "not re-running" in capsys.readouterr().out
    with sqlite3.connect(out / "apollolander-offline-development-rewardonly.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == before

    assert main(["status", "--out", str(out)]) == 0
    assert "[MOCK]" in capsys.readouterr().out


def test_real_provider_config_is_refused_in_mock_mode(tmp_path: Path, capsys) -> None:
    assert main(["run", "--config", str(PILOT), "--out", str(tmp_path)]) == 2
    assert "use --mode live" in capsys.readouterr().err


def test_live_mode_without_authorization_makes_no_call(tmp_path: Path, capsys, monkeypatch) -> None:
    for key in ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert main(["run", "--config", str(PILOT), "--mode", "live", "--out", str(tmp_path)]) != 0
    out = capsys.readouterr().out
    assert "LIVE MODE" in out
    with sqlite3.connect(next(tmp_path.glob("*.sqlite"))) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_paid_flags_rejected_in_mock_mode(tmp_path: Path, capsys) -> None:
    code = main(["run", "--config", str(NOFEEDBACK), "--i-authorize-paid-api-calls", "--out", str(tmp_path)])
    assert code == 2


def test_reserved_final_seeds_are_never_evaluated(tmp_path: Path, capsys) -> None:
    import yaml

    config = yaml.safe_load(NOFEEDBACK.read_text())
    config["held_out_seeds"] = [2000000, 2000001]
    path = tmp_path / "reserved.yaml"
    path.write_text(yaml.safe_dump(config))
    if shutil.which("node") is None:
        pytest.skip("needs node")
    assert main(["run", "--config", str(path), "--heldout", "--no-report", "--out", str(tmp_path / "o")]) == 2
    assert "reserved" in capsys.readouterr().err


def test_progress_display_failure_cannot_fail_a_run() -> None:
    from rewardbench.operate import _announcer

    class Closed:
        def write(self, _text: str) -> int:
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self) -> None:
            raise BrokenPipeError(32, "Broken pipe")

    _announcer(Closed())("revision 0: anything")  # must not raise
