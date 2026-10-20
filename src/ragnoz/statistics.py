"""Deterministic statistical comparison helpers for the RAGnoz CLI.

The public functions return plain tuples or floats so their results can be
serialized without a custom encoder.  No third-party dependencies are used.
"""

from __future__ import annotations

import math
import operator
import random
import statistics
from collections.abc import Iterable, Sequence

_DEFAULT_CONFIDENCE = 0.95
_DEFAULT_Z = statistics.NormalDist().inv_cdf(1.0 - (1.0 - _DEFAULT_CONFIDENCE) / 2.0)


def _as_nonnegative_int(value: int, name: str) -> int:
    """Return an integer argument, rejecting booleans and negative values."""

    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer, not bool")
    try:
        integer = operator.index(value)
    except TypeError as exc:
        raise TypeError(f"{name} must be an integer") from exc
    if integer < 0:
        raise ValueError(f"{name} must be non-negative")
    return integer


def _validate_confidence(confidence: float) -> float:
    """Validate and normalize a confidence level in the open interval (0, 1)."""

    confidence = float(confidence)
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be a finite number between 0 and 1")
    return confidence


def wilson_ci(
    successes: int,
    n: int,
    confidence: float = _DEFAULT_CONFIDENCE,
) -> tuple[float, float]:
    """Return a Wilson score interval for a binomial proportion.

    The default interval is 95%.  With no trials there is no observed
    proportion; this function returns the conservative uninformative interval
    ``(0.0, 1.0)`` rather than attempting a division by zero.  ``successes``
    must be between zero and ``n`` inclusive.
    """

    successes = _as_nonnegative_int(successes, "successes")
    n = _as_nonnegative_int(n, "n")
    confidence = _validate_confidence(confidence)

    if successes > n:
        raise ValueError("successes must not exceed n")
    if n == 0:
        return 0.0, 1.0

    z = statistics.NormalDist().inv_cdf(1.0 - (1.0 - confidence) / 2.0)
    p = successes / n
    z_squared = z * z
    denominator = 1.0 + z_squared / n
    center = (p + z_squared / (2.0 * n)) / denominator
    half_width = (
        z
        * math.sqrt(p * (1.0 - p) / n + z_squared / (4.0 * n * n))
        / denominator
    )

    # The endpoint values are exact mathematically; handle them explicitly so
    # floating-point cancellation cannot produce a tiny value outside them.
    lower = 0.0 if successes == 0 else max(0.0, center - half_width)
    upper = 1.0 if successes == n else min(1.0, center + half_width)
    return lower, upper


def wilson_interval(
    successes: int,
    n: int,
    confidence: float = _DEFAULT_CONFIDENCE,
) -> tuple[float, float]:
    """Alias for :func:`wilson_ci` with a descriptive name."""

    return wilson_ci(successes, n, confidence)


def mcnemar_exact_p_value(b: int, c: int) -> float:
    """Return the exact two-sided McNemar p-value for discordant counts.

    Conditional on ``b + c`` discordant pairs, the null distribution is
    Binomial(``b + c``, 0.5).  The two-sided p-value is twice the probability
    of the tail at ``min(b, c)``, capped at one.  With no discordant pairs
    (``b == c == 0``), the p-value is exactly 1.0.
    """

    b = _as_nonnegative_int(b, "b")
    c = _as_nonnegative_int(c, "c")
    discordant = b + c
    if discordant == 0:
        return 1.0

    lower_count = min(b, c)
    # b == c means the observed split is at the center of the symmetric null
    # distribution, so the doubled tail is at least one and clips to one.
    if b == c:
        return 1.0

    # Compute the exact binomial tail as an integer ratio.  Taking logarithms
    # of the integers avoids converting very large 2**discordant values to a
    # float, while retaining deterministic results for large count inputs.
    numerator = sum(
        math.comb(discordant, successes) for successes in range(lower_count + 1)
    )
    log_tail = math.log(numerator) - discordant * math.log(2.0)
    tail = math.exp(log_tail) if log_tail > -745.0 else 0.0
    return min(1.0, 2.0 * tail)


def exact_mcnemar_pvalue(b: int, c: int) -> float:
    """Alias for :func:`mcnemar_exact_p_value`."""

    return mcnemar_exact_p_value(b, c)


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated percentile from a non-empty sorted list."""

    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = probability * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(sorted_values[lower])
    fraction = position - lower
    return float(
        sorted_values[lower]
        + fraction * (sorted_values[upper] - sorted_values[lower])
    )


def paired_bootstrap_ci(
    differences: Iterable[float],
    reps: int = 10_000,
    seed: int = 0,
    confidence: float = _DEFAULT_CONFIDENCE,
) -> tuple[float, float]:
    """Return a percentile bootstrap interval for the mean paired difference.

    ``differences`` contains one already-paired difference per observation.
    Each replicate samples those differences with replacement and computes its
    mean.  A local ``random.Random`` instance makes the result reproducible
    for a given ``seed`` without changing process-global random state.  The
    default interval is 95% and uses linear interpolation between sorted
    replicate values.
    """

    confidence = _validate_confidence(confidence)
    reps = _as_nonnegative_int(reps, "reps")
    if reps == 0:
        raise ValueError("reps must be greater than zero")

    values = [float(value) for value in differences]
    if not values:
        raise ValueError("differences must contain at least one observation")
    if not all(math.isfinite(value) for value in values):
        raise ValueError("differences must contain only finite numbers")

    rng = random.Random(seed)
    sample_size = len(values)
    bootstrap_means: list[float] = []
    for _ in range(reps):
        total = sum(values[rng.randrange(sample_size)] for _ in range(sample_size))
        bootstrap_means.append(total / sample_size)

    bootstrap_means.sort()
    alpha = (1.0 - confidence) / 2.0
    return (
        _percentile(bootstrap_means, alpha),
        _percentile(bootstrap_means, 1.0 - alpha),
    )


def paired_bootstrap_mean_difference_ci(
    left: Sequence[float],
    right: Sequence[float],
    reps: int = 10_000,
    seed: int = 0,
    confidence: float = _DEFAULT_CONFIDENCE,
) -> tuple[float, float]:
    """Compute paired differences from two sequences and bootstrap their mean."""

    if len(left) != len(right):
        raise ValueError("left and right must have the same length")
    return paired_bootstrap_ci(
        (float(after) - float(before) for before, after in zip(left, right)),
        reps=reps,
        seed=seed,
        confidence=confidence,
    )


__all__ = [
    "exact_mcnemar_pvalue",
    "mcnemar_exact_p_value",
    "paired_bootstrap_ci",
    "paired_bootstrap_mean_difference_ci",
    "wilson_ci",
    "wilson_interval",
]
