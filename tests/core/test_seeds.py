import pytest

from rewardbench.contracts import Split, SplitViolation
from rewardbench.core.evaluation import SplitGuard
from rewardbench.core.seeds import build_seed_schedule


def test_seed_schedule_is_deterministic_and_cycles() -> None:
    first = build_seed_schedule(11, (4, 1, 9), 2, 2)
    second = build_seed_schedule(11, (9, 4, 1), 2, 2)
    assert first == second
    assert len(first) == 2
    assert len(first[0]) == 2
    flat = [seed for row in first for seed in row]
    assert set(flat) <= {1, 4, 9}
    longer = build_seed_schedule(11, (1, 4, 9), 2, 3)
    assert len([seed for row in longer for seed in row]) == 6


def test_development_guard_rejects_held_out_seeds() -> None:
    guard = SplitGuard(Split.DEVELOPMENT, (1, 2), (101, 102))
    guard.check(1)
    with pytest.raises(SplitViolation):
        guard.check(101)
    with pytest.raises(SplitViolation):
        guard.check(999)


def test_held_out_guard_rejects_development_seeds() -> None:
    guard = SplitGuard(Split.HELD_OUT, (1, 2), (101, 102))
    assert guard.allowed_seeds() == (101, 102)
    guard.check(102)
    with pytest.raises(SplitViolation):
        guard.check(1)
