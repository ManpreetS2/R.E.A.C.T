"""Analysis of RewardBench experiment logs.

Statistics are descriptive. This package does not rank language models and
does not invent scores when a log is empty. Synthetic records are accepted
only so tests can render figures; reports label them as fixtures.
"""

from rewardbench.analysis.diagnostics import fairness_notes, resume_notes, seed_leakage
from rewardbench.analysis.environments import environment_family, family_display
from rewardbench.analysis.export import export_jsonl
from rewardbench.analysis.load import load_logs
from rewardbench.analysis.report import write_report
from rewardbench.analysis.sessions import session_summaries, summarize_groups
from rewardbench.analysis.stats import student_t_interval, wilson_interval

__all__ = [
    "environment_family",
    "export_jsonl",
    "fairness_notes",
    "load_logs",
    "resume_notes",
    "seed_leakage",
    "session_summaries",
    "student_t_interval",
    "summarize_groups",
    "wilson_interval",
    "write_report",
]
