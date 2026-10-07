"""Sample-size and power calculations for two-arm tests (normal approximation)."""

from __future__ import annotations

import math

from scipy import stats


def _z(alpha: float, power: float) -> tuple[float, float]:
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must be in (0, 1)")
    return float(stats.norm.ppf(1 - alpha / 2)), float(stats.norm.ppf(power))


def sample_size_proportions(
    baseline: float, mde: float, alpha: float = 0.05, power: float = 0.8, ratio: float = 1.0
) -> tuple[int, int]:
    """Units per arm (control, treatment) to detect an absolute lift ``mde`` over
    ``baseline`` with a two-sided test. ``ratio`` is treatment/control size."""
    p1, p2 = baseline, baseline + mde
    if not (0 < p1 < 1 and 0 < p2 < 1) or mde == 0:
        raise ValueError("baseline and baseline + mde must be in (0, 1), mde non-zero")
    z_a, z_b = _z(alpha, power)
    p_bar = (p1 + ratio * p2) / (1 + ratio)
    numerator = z_a * math.sqrt(p_bar * (1 - p_bar) * (1 + 1 / ratio)) + z_b * math.sqrt(
        p1 * (1 - p1) + p2 * (1 - p2) / ratio
    )
    n_control = math.ceil((numerator / mde) ** 2)
    return n_control, math.ceil(n_control * ratio)


def sample_size_means(
    sd: float,
    mde: float,
    alpha: float = 0.05,
    power: float = 0.8,
    ratio: float = 1.0,
    variance_reduction: float = 0.0,
) -> tuple[int, int]:
    """Units per arm for a difference in means. ``variance_reduction`` is the share of
    variance removed by CUPED or regression adjustment (e.g. 0.3)."""
    if sd <= 0 or mde == 0 or not 0 <= variance_reduction < 1:
        raise ValueError("sd must be positive, mde non-zero, variance_reduction in [0, 1)")
    z_a, z_b = _z(alpha, power)
    variance = sd**2 * (1 - variance_reduction)
    n_control = math.ceil((z_a + z_b) ** 2 * variance * (1 + 1 / ratio) / mde**2)
    return n_control, math.ceil(n_control * ratio)


def power_proportions(
    baseline: float, mde: float, n_control: int, n_treatment: int, alpha: float = 0.05
) -> float:
    """Approximate power of the two-sided unpooled z-test at the given arm sizes."""
    p1, p2 = baseline, baseline + mde
    se = math.sqrt(p1 * (1 - p1) / n_control + p2 * (1 - p2) / n_treatment)
    z_a = float(stats.norm.ppf(1 - alpha / 2))
    shift = abs(mde) / se
    return float(stats.norm.cdf(shift - z_a) + stats.norm.cdf(-shift - z_a))


def minimum_detectable_effect(
    baseline: float, n_per_arm: int, alpha: float = 0.05, power: float = 0.8
) -> float:
    """Smallest absolute lift detectable at ``power`` with ``n_per_arm`` units each."""
    lo, hi = 1e-6, 1 - baseline - 1e-6
    for _ in range(100):
        mid = (lo + hi) / 2
        if power_proportions(baseline, mid, n_per_arm, n_per_arm, alpha) < power:
            lo = mid
        else:
            hi = mid
    return hi
