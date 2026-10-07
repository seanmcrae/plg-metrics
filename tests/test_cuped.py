from __future__ import annotations

import numpy as np
import pytest

from plg.stats.cuped import cuped_adjust, cuped_diff_means


def _correlated(rng: np.random.Generator, n: int, rho: float) -> tuple[np.ndarray, np.ndarray]:
    x = rng.normal(0, 1, n)
    y = rho * x + np.sqrt(1 - rho**2) * rng.normal(0, 1, n)
    return x, y


def test_cuped_variance_reduction_is_about_rho_squared() -> None:
    rng = np.random.default_rng(3)
    x, y = _correlated(rng, 50_000, rho=0.6)
    adjusted, theta = cuped_adjust(y, x)
    assert theta == pytest.approx(0.6, abs=0.01)
    assert 1 - adjusted.var() / y.var() == pytest.approx(0.36, abs=0.01)
    assert adjusted.mean() == pytest.approx(y.mean())


def test_cuped_is_unbiased_and_narrows_ci() -> None:
    rng = np.random.default_rng(4)
    effect, diffs, widths, raw_widths = 0.1, [], [], []
    for _ in range(300):
        xc, yc = _correlated(rng, 1_000, 0.7)
        xt, yt = _correlated(rng, 1_000, 0.7)
        res = cuped_diff_means(yc, xc, yt + effect, xt)
        diffs.append(res.estimate.diff)
        widths.append(res.estimate.ci_high - res.estimate.ci_low)
        raw_widths.append(res.unadjusted.ci_high - res.unadjusted.ci_low)
    assert np.mean(diffs) == pytest.approx(effect, abs=0.005)
    # Width scales with sqrt(1 - rho^2) = 0.714.
    assert np.mean(widths) / np.mean(raw_widths) == pytest.approx(np.sqrt(1 - 0.49), abs=0.02)


def test_cuped_with_useless_covariate_changes_little() -> None:
    rng = np.random.default_rng(5)
    res = cuped_diff_means(
        rng.normal(size=2_000),
        rng.normal(size=2_000),
        rng.normal(size=2_000),
        rng.normal(size=2_000),
    )
    assert abs(res.variance_reduction) < 0.01


def test_cuped_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="same shape"):
        cuped_adjust([1.0, 2.0], [1.0])
