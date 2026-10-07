"""Always-valid inference via the mixture sequential probability ratio test.

Implements the normal-mixture mSPRT of Johari, Koomen, Pekelis & Walsh (2017),
"Peeking at A/B Tests". For a difference estimate with sampling variance V_n and
a N(0, tau^2) mixing distribution over the true effect, the likelihood ratio is

    Lambda_n = sqrt(V_n / (V_n + tau^2)) * exp(tau^2 * diff_n^2 / (2 V_n (V_n + tau^2)))

and the always-valid p-value is p_n = min(1, min_{m<=n} 1 / Lambda_m). Stopping the
first time p_n < alpha keeps the false-positive rate at or below alpha no matter
how often results are checked, which is what makes it a peeking guardrail.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy import stats


def msprt_likelihood_ratio(diff: float, variance: float, tau: float) -> float:
    if variance <= 0:
        raise ValueError("variance must be positive")
    tau2 = tau**2
    log_lr = 0.5 * np.log(variance / (variance + tau2)) + tau2 * diff**2 / (
        2 * variance * (variance + tau2)
    )
    return float(np.exp(min(log_lr, 700.0)))


def always_valid_p_values(
    diffs: npt.ArrayLike, variances: npt.ArrayLike, tau: float
) -> npt.NDArray[np.float64]:
    d_arr = np.asarray(diffs, dtype=np.float64)
    v_arr = np.asarray(variances, dtype=np.float64)
    if d_arr.shape != v_arr.shape:
        raise ValueError("diffs and variances must have the same shape")
    lrs = np.array([msprt_likelihood_ratio(d, v, tau) for d, v in zip(d_arr, v_arr, strict=True)])
    return np.minimum.accumulate(np.minimum(1.0, 1.0 / lrs))


def sequential_monitor(looks: pd.DataFrame, tau: float, alpha: float = 0.05) -> pd.DataFrame:
    """Annotate cumulative looks (columns ``diff``, ``se``) with fixed-horizon and
    always-valid p-values. ``naive_reject`` shows what peeking at the fixed-horizon
    test would conclude; ``msprt_reject`` is the safe stopping rule."""
    out = looks.copy()
    out["naive_p"] = 2 * stats.norm.sf(np.abs(out["diff"] / out["se"]))
    out["always_valid_p"] = always_valid_p_values(out["diff"], out["se"] ** 2, tau)
    out["naive_reject"] = out["naive_p"] < alpha
    out["msprt_reject"] = out["always_valid_p"] < alpha
    return out


def default_tau(mde: float) -> float:
    """Mixing scale: centring the prior's spread on the minimum effect of interest
    is a reasonable default that keeps power close to a fixed-horizon test there."""
    return abs(mde)
