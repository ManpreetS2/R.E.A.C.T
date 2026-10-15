import math

import pytest

from rewardbench.analysis.stats import median, student_t_interval, wilson_interval


def test_student_t_interval_matches_known_value() -> None:
    # Critical value is the published two-sided 95% Student-t quantile for df=4.
    interval = student_t_interval([1.0, 2.0, 3.0, 4.0, 5.0], 0.95)
    standard_deviation = math.sqrt(2.5)
    standard_error = standard_deviation / math.sqrt(5)
    half = 2.7764451051977987 * standard_error
    assert interval.point == pytest.approx(3.0)
    assert interval.low == pytest.approx(3.0 - half)
    assert interval.high == pytest.approx(3.0 + half)
    assert interval.n == 5
    assert interval.defined


def test_student_t_interval_is_undefined_for_one_observation() -> None:
    interval = student_t_interval([4.0], 0.95)
    assert interval.point == pytest.approx(4.0)
    assert interval.low is None
    assert interval.high is None
    assert interval.note == "n<2"


def test_student_t_interval_rejects_empty_and_non_finite() -> None:
    with pytest.raises(ValueError):
        student_t_interval([], 0.95)
    with pytest.raises(ValueError):
        student_t_interval([1.0, math.nan], 0.95)


def test_wilson_interval_matches_formula() -> None:
    z = 1.959963984540054
    n = 10
    probability = 0.8
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (probability + z2 / (2.0 * n)) / denominator
    margin = z * math.sqrt(probability * (1.0 - probability) / n + z2 / (4.0 * n * n))
    margin /= denominator
    interval = wilson_interval(8, 10, 0.95)
    assert interval.point == pytest.approx(0.8)
    assert interval.low == pytest.approx(center - margin)
    assert interval.high == pytest.approx(center + margin)


def test_wilson_bounds_stay_inside_unit_interval() -> None:
    none = wilson_interval(0, 10)
    all_success = wilson_interval(10, 10)
    assert none.low is not None and none.low >= 0.0
    assert all_success.high is not None and all_success.high <= 1.0


def test_wilson_empty_sample_is_undefined() -> None:
    interval = wilson_interval(0, 0)
    assert interval.point is None
    assert interval.note == "n=0"


def test_wilson_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError):
        wilson_interval(3, 2)


def test_median_even_and_odd() -> None:
    assert median([1.0, 3.0, 2.0]) == pytest.approx(2.0)
    assert median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)
    assert median([]) is None
