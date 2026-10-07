"""Sample-ratio mismatch and two-sample effect estimates with confidence intervals."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy import stats

ArrayLike = npt.ArrayLike


@dataclass(frozen=True)
class SRMResult:
    observed: tuple[int, ...]
    expected: tuple[float, ...]
    chi2: float
    p_value: float
    threshold: float

    @property
    def mismatch(self) -> bool:
        """True when allocation is implausible under the design; results are suspect."""
        return self.p_value < self.threshold


def srm_check(
    counts: Sequence[int], expected_shares: Sequence[float], threshold: float = 0.001
) -> SRMResult:
    """Pearson chi-square goodness-of-fit test of observed arm sizes vs the design split.

    The conventional threshold is strict (0.001) because SRM checks run on every
    experiment and a flag should mean "stop and debug assignment/logging"."""
    observed = np.asarray(counts, dtype=np.float64)
    shares = np.asarray(expected_shares, dtype=np.float64)
    if observed.shape != shares.shape or observed.size < 2:
        raise ValueError("counts and expected_shares must have the same length >= 2")
    if not np.isclose(shares.sum(), 1.0):
        raise ValueError("expected_shares must sum to 1")
    expected = shares * observed.sum()
    chi2 = float(((observed - expected) ** 2 / expected).sum())
    p_value = float(stats.chi2.sf(chi2, df=observed.size - 1))
    return SRMResult(
        observed=tuple(int(c) for c in counts),
        expected=tuple(float(e) for e in expected),
        chi2=chi2,
        p_value=p_value,
        threshold=threshold,
    )


@dataclass(frozen=True)
class EffectEstimate:
    """Treatment minus control, with a two-sided (1 - alpha) confidence interval."""

    control_mean: float
    treatment_mean: float
    diff: float
    se: float
    ci_low: float
    ci_high: float
    p_value: float
    n_control: int
    n_treatment: int
    alpha: float
    rel_lift: float
    rel_ci_low: float
    rel_ci_high: float

    def covers(self, value: float) -> bool:
        return self.ci_low <= value <= self.ci_high


def _relative(
    mc: float, mt: float, se_c: float, se_t: float, crit: float
) -> tuple[float, float, float]:
    """Relative lift mt/mc - 1 with a delta-method interval."""
    if mc == 0:
        return float("nan"), float("nan"), float("nan")
    ratio = mt / mc
    se_ratio = abs(ratio) * np.sqrt((se_t / mt) ** 2 + (se_c / mc) ** 2) if mt else se_t / mc
    return ratio - 1, ratio - 1 - crit * se_ratio, ratio - 1 + crit * se_ratio


def diff_proportions(
    x_control: int, n_control: int, x_treatment: int, n_treatment: int, alpha: float = 0.05
) -> EffectEstimate:
    """Difference in proportions with an unpooled Wald interval and matching z-test.

    The test uses the same unpooled standard error as the interval so the two never
    disagree about significance."""
    if min(n_control, n_treatment) <= 0:
        raise ValueError("both arms need at least one unit")
    pc, pt = x_control / n_control, x_treatment / n_treatment
    se_c = np.sqrt(pc * (1 - pc) / n_control)
    se_t = np.sqrt(pt * (1 - pt) / n_treatment)
    se = float(np.hypot(se_c, se_t))
    crit = float(stats.norm.ppf(1 - alpha / 2))
    diff = pt - pc
    # Both arms at 0% or 100%: no variance, so any difference is certain.
    z = abs(diff) / se if se > 0 else (0.0 if diff == 0 else np.inf)
    p_value = float(2 * stats.norm.sf(z))
    rel, rel_lo, rel_hi = _relative(pc, pt, float(se_c), float(se_t), crit)
    return EffectEstimate(
        control_mean=pc,
        treatment_mean=pt,
        diff=diff,
        se=se,
        ci_low=diff - crit * se,
        ci_high=diff + crit * se,
        p_value=p_value,
        n_control=n_control,
        n_treatment=n_treatment,
        alpha=alpha,
        rel_lift=rel,
        rel_ci_low=rel_lo,
        rel_ci_high=rel_hi,
    )


def diff_means(control: ArrayLike, treatment: ArrayLike, alpha: float = 0.05) -> EffectEstimate:
    """Welch's t-test and interval for a difference in means (unequal variances)."""
    c = np.asarray(control, dtype=np.float64)
    t = np.asarray(treatment, dtype=np.float64)
    if c.size < 2 or t.size < 2:
        raise ValueError("both arms need at least two observations")
    vc, vt = c.var(ddof=1) / c.size, t.var(ddof=1) / t.size
    se = float(np.sqrt(vc + vt))
    diff = float(t.mean() - c.mean())
    if se == 0:  # both arms constant: the difference is known exactly
        dof, crit = float("inf"), 0.0
        p_value = 1.0 if diff == 0 else 0.0
    else:
        dof = (vc + vt) ** 2 / (vc**2 / (c.size - 1) + vt**2 / (t.size - 1))
        crit = float(stats.t.ppf(1 - alpha / 2, dof))
        p_value = float(2 * stats.t.sf(abs(diff) / se, dof))
    rel, rel_lo, rel_hi = _relative(
        float(c.mean()), float(t.mean()), float(np.sqrt(vc)), float(np.sqrt(vt)), crit
    )
    return EffectEstimate(
        control_mean=float(c.mean()),
        treatment_mean=float(t.mean()),
        diff=diff,
        se=se,
        ci_low=diff - crit * se,
        ci_high=diff + crit * se,
        p_value=p_value,
        n_control=int(c.size),
        n_treatment=int(t.size),
        alpha=alpha,
        rel_lift=rel,
        rel_ci_low=rel_lo,
        rel_ci_high=rel_hi,
    )
