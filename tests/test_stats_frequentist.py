from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from plg.stats.frequentist import diff_means, diff_proportions, srm_check
from plg.stats.multiple import benjamini_hochberg, holm


def test_srm_matches_scipy_chisquare() -> None:
    res = srm_check([5_100, 4_900], [0.5, 0.5])
    ref = stats.chisquare([5_100, 4_900], [5_000, 5_000])
    assert res.chi2 == pytest.approx(ref.statistic)
    assert res.p_value == pytest.approx(ref.pvalue)
    assert not res.mismatch  # p ~ 0.046 is not an SRM at the 0.001 threshold


def test_srm_detects_lost_treatment_logging() -> None:
    # 6% of treatment exposures silently dropped from a 50/50 test of 20k.
    res = srm_check([10_000, 9_400], [0.5, 0.5])
    assert res.mismatch
    assert res.p_value < 1e-3


def test_srm_uneven_design_and_validation() -> None:
    assert not srm_check([8_000, 2_000], [0.8, 0.2]).mismatch
    assert srm_check([5_000, 5_000], [0.8, 0.2]).mismatch
    with pytest.raises(ValueError, match="sum to 1"):
        srm_check([1, 2], [0.5, 0.6])


def test_diff_proportions_hand_computed() -> None:
    est = diff_proportions(100, 1_000, 130, 1_000)
    se = np.sqrt(0.1 * 0.9 / 1_000 + 0.13 * 0.87 / 1_000)
    assert est.diff == pytest.approx(0.03)
    assert est.se == pytest.approx(se)
    assert est.ci_low == pytest.approx(0.03 - 1.959964 * se, abs=1e-6)
    assert est.p_value == pytest.approx(2 * stats.norm.sf(0.03 / se))
    assert est.rel_lift == pytest.approx(0.3)
    assert est.rel_ci_low < 0.3 < est.rel_ci_high


def test_diff_means_matches_scipy_welch() -> None:
    rng = np.random.default_rng(0)
    c = rng.normal(10, 3, 400)
    t = rng.normal(10.6, 4, 350)
    est = diff_means(c, t)
    ref = stats.ttest_ind(t, c, equal_var=False)
    ci = ref.confidence_interval(0.95)
    assert est.p_value == pytest.approx(ref.pvalue)
    assert est.ci_low == pytest.approx(ci.low)
    assert est.ci_high == pytest.approx(ci.high)
    assert est.covers(est.diff)


def test_ci_coverage_is_nominal() -> None:
    rng = np.random.default_rng(1)
    hits = sum(
        diff_proportions(
            int(rng.binomial(2_000, 0.2)), 2_000, int(rng.binomial(2_000, 0.23)), 2_000
        ).covers(0.03)
        for _ in range(1_000)
    )
    assert 0.93 <= hits / 1_000 <= 0.97


def test_holm_hand_computed() -> None:
    adj = holm([0.01, 0.04, 0.03, 0.005])
    assert adj == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_bh_hand_computed_and_matches_scipy() -> None:
    p = [0.01, 0.04, 0.03, 0.005]
    assert benjamini_hochberg(p) == pytest.approx([0.02, 0.04, 0.04, 0.02])
    rng = np.random.default_rng(2)
    many = rng.uniform(size=50) ** 2
    assert benjamini_hochberg(many) == pytest.approx(stats.false_discovery_control(many))


def test_corrections_cap_at_one_and_preserve_order() -> None:
    adj = holm([0.9, 0.8])
    assert (adj <= 1).all()
    assert benjamini_hochberg([0.9, 0.8]).tolist() == pytest.approx([0.9, 0.9])


def test_degenerate_arms_do_not_crash() -> None:
    assert diff_means([2.0, 2.0, 2.0], [3.0, 3.0, 3.0]).p_value == 0.0
    assert diff_means([2.0, 2.0], [2.0, 2.0]).p_value == 1.0
    assert diff_proportions(0, 100, 0, 100).p_value == pytest.approx(1.0)
