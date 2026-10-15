"""Session-level confidence intervals.

The independent unit for a published interval is the session, not the episode.
Intervals are undefined when fewer than two sessions contribute.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from scipy.stats import norm, t

from rewardbench.analysis.schema import Interval


def student_t_interval(values: Sequence[float], confidence: float = 0.95) -> Interval:
    """Two-sided Student-t interval for the mean of ``values``.

    ``n < 2`` returns the mean with undefined bounds. The sample standard
    deviation uses ``n - 1``.
    """

    _check_confidence(confidence)
    sample = [float(value) for value in values]
    n = len(sample)
    if n == 0:
        raise ValueError("student_t_interval requires at least one value")
    for value in sample:
        if not math.isfinite(value):
            raise ValueError("student_t_interval requires finite values")
    mean = sum(sample) / n
    if n < 2:
        return Interval(mean, None, None, n, "n<2")
    variance = sum((value - mean) ** 2 for value in sample) / (n - 1)
    scale = math.sqrt(variance / n)
    critical = float(t.ppf((1.0 + confidence) / 2.0, n - 1))
    half = critical * scale
    return Interval(mean, mean - half, mean + half, n, None)


def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> Interval:
    """Wilson score interval for a binomial proportion.

    ``n == 0`` returns an undefined interval. Counts must be non-negative and
    ``successes`` cannot exceed ``n``.
    """

    _check_confidence(confidence)
    if isinstance(successes, bool) or isinstance(n, bool):
        raise ValueError("wilson_interval counts must be integers")
    if not isinstance(successes, int) or not isinstance(n, int):
        raise ValueError("wilson_interval counts must be integers")
    if successes < 0 or n < 0 or successes > n:
        raise ValueError("wilson_interval requires 0 <= successes <= n")
    if n == 0:
        return Interval(None, None, None, 0, "n=0")
    probability = successes / n
    z = float(norm.ppf((1.0 + confidence) / 2.0))
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (probability + z2 / (2.0 * n)) / denominator
    margin = z * math.sqrt(probability * (1.0 - probability) / n + z2 / (4.0 * n * n))
    margin /= denominator
    return Interval(probability, center - margin, center + margin, n, None)


def mean_interval(values: Sequence[float | None], confidence: float = 0.95) -> Interval:
    """Mean interval after dropping missing values."""

    observed = [float(value) for value in values if value is not None]
    if not observed:
        return Interval(None, None, None, 0, "no observations")
    return student_t_interval(observed, confidence)


def median(values: Sequence[float]) -> float | None:
    """Sample median. Even counts use the average of the two central values."""

    sample = sorted(float(value) for value in values)
    n = len(sample)
    if n == 0:
        return None
    middle = n // 2
    if n % 2:
        return sample[middle]
    return (sample[middle - 1] + sample[middle]) / 2.0


def _check_confidence(confidence: float) -> None:
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a real number between 0 and 1")
    if not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be between 0 and 1")
