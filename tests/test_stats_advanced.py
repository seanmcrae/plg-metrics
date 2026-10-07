from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import integrate, stats

from plg.stats.bayes import beta_binomial, prob_b_beats_a
from plg.stats.power import (
    minimum_detectable_effect,
    power_proportions,
    sample_size_means,
    sample_size_proportions,
)
from plg.stats.sequential import always_valid_p_values, msprt_likelihood_ratio, sequential_monitor

# --- sequential --------------------------------------------------------------


def test_msprt_lr_matches_formula() -> None:
    d, v, tau = 0.02, 1e-4, 0.03
    expected = np.sqrt(v / (v + tau**2)) * np.exp(tau**2 * d**2 / (2 * v * (v + tau**2)))
    assert msprt_likelihood_ratio(d, v, tau) == pytest.approx(expected)


def test_always_valid_p_is_monotone() -> None:
    p = always_valid_p_values([0.0, 0.05, 0.0, 0.0], [0.01, 0.001, 0.0005, 0.0002], tau=0.05)
    assert (np.diff(p) <= 0).all()


def _aa_looks(rng: np.random.Generator, n_looks: int, per_look: int, effect: float) -> pd.DataFrame:
    c = rng.binomial(1, 0.3, (n_looks, per_look)).cumsum(axis=0).sum(axis=1)
    t = rng.binomial(1, 0.3 + effect, (n_looks, per_look)).cumsum(axis=0).sum(axis=1)
    n = per_look * np.arange(1, n_looks + 1)
    pc, pt = c / n, t / n
    return pd.DataFrame({"diff": pt - pc, "se": np.sqrt(pc * (1 - pc) / n + pt * (1 - pt) / n)})


def test_peeking_inflates_errors_but_msprt_controls_them() -> None:
    rng = np.random.default_rng(6)
    naive = msprt = 0
    sims = 400
    for _ in range(sims):
        mon = sequential_monitor(_aa_looks(rng, 20, 200, 0.0), tau=0.03)
        naive += bool(mon["naive_reject"].any())
        msprt += bool(mon["msprt_reject"].any())
    assert naive / sims > 0.15  # repeated peeking at alpha=0.05 roughly triples errors
    assert msprt / sims <= 0.05


def test_msprt_detects_real_effect() -> None:
    rng = np.random.default_rng(7)
    detected = sum(
        bool(sequential_monitor(_aa_looks(rng, 20, 500, 0.04), tau=0.03)["msprt_reject"].any())
        for _ in range(100)
    )
    assert detected >= 90


# --- Bayesian ----------------------------------------------------------------


def test_prob_to_beat_matches_numerical_integration() -> None:
    a_a, b_a, a_b, b_b = 121.0, 881.0, 141.0, 861.0
    integrand = lambda p: stats.beta.pdf(p, a_b, b_b) * stats.beta.cdf(p, a_a, b_a)  # noqa: E731
    ref, _ = integrate.quad(integrand, 0, 1, points=[0.12, 0.14], limit=200)
    assert prob_b_beats_a(a_a, b_a, a_b, b_b) == pytest.approx(ref, abs=1e-8)


def test_prob_to_beat_symmetry() -> None:
    assert prob_b_beats_a(50, 950, 50, 950) == pytest.approx(0.5, abs=1e-9)
    p = prob_b_beats_a(40, 960, 60, 940)
    assert prob_b_beats_a(60, 940, 40, 960) == pytest.approx(1 - p, abs=1e-9)


def test_beta_binomial_summary_is_reproducible() -> None:
    a = beta_binomial(300, 1_000, 340, 1_000, seed=1)
    b = beta_binomial(300, 1_000, 340, 1_000, seed=1)
    assert a == b
    assert a.prob_treatment_better > 0.95
    assert a.diff_ci_low < 0.04 < a.diff_ci_high
    assert a.expected_loss_treatment < 0.001


# --- power -------------------------------------------------------------------


def test_sample_size_proportions_textbook_value() -> None:
    assert sample_size_proportions(0.10, 0.02) == (3_841, 3_841)


def test_sample_size_means_hand_computed() -> None:
    assert sample_size_means(1.0, 0.2) == (393, 393)
    # 36% variance removed by CUPED cuts the requirement by 36%.
    assert sample_size_means(1.0, 0.2, variance_reduction=0.36) == (252, 252)


def test_unequal_allocation() -> None:
    n_c, n_t = sample_size_proportions(0.10, 0.02, ratio=2.0)
    assert n_t == pytest.approx(2 * n_c, abs=1)
    assert n_c + n_t > 2 * 3_841


def test_power_round_trips_sample_size() -> None:
    n_c, n_t = sample_size_proportions(0.3, 0.02, power=0.9)
    assert power_proportions(0.3, 0.02, n_c, n_t) == pytest.approx(0.9, abs=0.005)
    assert minimum_detectable_effect(0.3, n_c, power=0.9) == pytest.approx(0.02, abs=2e-4)


def test_power_matches_simulation() -> None:
    rng = np.random.default_rng(8)
    n = 2_000
    rejections = 0
    for _ in range(1_000):
        xc, xt = rng.binomial(n, 0.2), rng.binomial(n, 0.235)
        pc, pt = xc / n, xt / n
        z = (pt - pc) / np.sqrt(pc * (1 - pc) / n + pt * (1 - pt) / n)
        rejections += abs(z) > 1.959964
    assert rejections / 1_000 == pytest.approx(power_proportions(0.2, 0.035, n, n), abs=0.04)


@pytest.mark.parametrize("args", [(0.0, 0.02), (0.99, 0.02), (0.1, 0.0)])
def test_invalid_power_inputs(args: tuple[float, float]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        sample_size_proportions(*args)
