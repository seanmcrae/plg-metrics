"""CUPED variance reduction (Deng, Xu, Kohavi, Walker 2013).

Adjusts each unit's outcome with a pre-treatment covariate X:

    Y_cuped = Y - theta * (X - mean(X)),   theta = cov(Y, X) / var(X)

theta is estimated on the pooled sample. Because X is measured before
assignment, its mean is the same in both arms in expectation, so the adjustment
leaves the treatment effect unbiased while removing the share of variance X
explains (about corr(X, Y)^2).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from plg.stats.frequentist import ArrayLike, EffectEstimate, diff_means


@dataclass(frozen=True)
class CupedResult:
    estimate: EffectEstimate
    unadjusted: EffectEstimate
    theta: float
    variance_reduction: float


def cuped_theta(y: npt.NDArray[np.float64], x: npt.NDArray[np.float64]) -> float:
    var_x = float(np.var(x, ddof=1))
    if var_x == 0:
        return 0.0
    return float(np.cov(y, x, ddof=1)[0, 1] / var_x)


def cuped_adjust(
    y: ArrayLike, x: ArrayLike, theta: float | None = None
) -> tuple[npt.NDArray[np.float64], float]:
    y_arr = np.asarray(y, dtype=np.float64)
    x_arr = np.asarray(x, dtype=np.float64)
    if y_arr.shape != x_arr.shape:
        raise ValueError("outcome and covariate must have the same shape")
    theta = cuped_theta(y_arr, x_arr) if theta is None else theta
    return y_arr - theta * (x_arr - x_arr.mean()), theta


def cuped_diff_means(
    y_control: ArrayLike,
    x_control: ArrayLike,
    y_treatment: ArrayLike,
    x_treatment: ArrayLike,
    alpha: float = 0.05,
) -> CupedResult:
    yc, yt = np.asarray(y_control, dtype=np.float64), np.asarray(y_treatment, dtype=np.float64)
    xc, xt = np.asarray(x_control, dtype=np.float64), np.asarray(x_treatment, dtype=np.float64)
    y = np.concatenate([yc, yt])
    adjusted, theta = cuped_adjust(y, np.concatenate([xc, xt]))
    adj_c, adj_t = adjusted[: yc.size], adjusted[yc.size :]
    var_y = float(np.var(y, ddof=1))
    reduction = 1.0 - float(np.var(adjusted, ddof=1)) / var_y if var_y > 0 else 0.0
    return CupedResult(
        estimate=diff_means(adj_c, adj_t, alpha),
        unadjusted=diff_means(yc, yt, alpha),
        theta=theta,
        variance_reduction=reduction,
    )
