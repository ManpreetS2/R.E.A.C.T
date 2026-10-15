from pathlib import Path

from rewardbench.analysis.__main__ import main
from rewardbench.analysis.load import load_logs
from rewardbench.analysis.report import write_report
from rewardbench.analysis.schema import SYNTHETIC_BANNER
from fixtures import build_synthetic_plot_log, connect_memory, write_database


def test_empty_log_report_does_not_rank_models(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite"
    connection = connect_memory()
    write_database(database, connection)
    connection.close()
    result = write_report(load_logs(database), tmp_path / "report")
    text = result.markdown_path.read_text(encoding="utf-8")
    assert "No experiment logs were loaded" in text
    assert "No independently validated results are present" in text
    lowered = text.lower()
    assert "winner" not in lowered
    assert "best model" not in lowered
    assert "outperforms" not in lowered


def test_synthetic_report_is_labeled_and_not_a_ranking(tmp_path: Path) -> None:
    database = tmp_path / "synthetic.sqlite"
    build_synthetic_plot_log(database)
    result = write_report(load_logs(database), tmp_path / "report", reward_targets=(0.0, 200.0))
    text = result.markdown_path.read_text(encoding="utf-8")
    assert SYNTHETIC_BANNER in text
    assert "does not rank models" in text
    assert "model-a" in text
    assert "model-b" in text
    assert text.index("model-a") < text.index("model-b")
    for plot in result.plot_paths:
        assert plot.read_bytes().startswith(b"\x89PNG")
    assert (tmp_path / "report" / "preliminary" / "time_to_target.png").is_file()


def test_cli_report_and_export(tmp_path: Path) -> None:
    database = tmp_path / "synthetic.sqlite"
    build_synthetic_plot_log(database)
    report_dir = tmp_path / "out"
    assert main(["report", "--logs", str(database), "--out", str(report_dir)]) == 0
    assert (report_dir / "report.md").is_file()
    export_path = tmp_path / "copy.jsonl"
    assert main(["export", "--logs", str(database), "--out", str(export_path)]) == 0
    assert export_path.read_text(encoding="utf-8").startswith('{"')
    assert main(["report", "--logs", str(tmp_path / "missing.sqlite"), "--out", str(report_dir)]) == 2
