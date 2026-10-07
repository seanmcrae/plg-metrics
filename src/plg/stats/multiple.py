"""Multiple-comparison corrections returning adjusted p-values in input order."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import numpy.typing as npt


def holm(p_values: Sequence[float]) -> npt.NDArray[np.float64]:
    """Holm step-down adjusted p-values (controls family-wise error rate)."""
    p = np.asarray(p_values, dtype=np.float64)
    m = p.size
    order = np.argsort(p, kind="stable")
    stepped = p[order] * (m - np.arange(m))
    adjusted = np.minimum(np.maximum.accumulate(stepped), 1.0)
    out = np.empty(m)
    out[order] = adjusted
    return out


def benjamini_hochberg(p_values: Sequence[float]) -> npt.NDArray[np.float64]:
    """Benjamini-Hochberg adjusted p-values (controls false discovery rate)."""
    p = np.asarray(p_values, dtype=np.float64)
    m = p.size
    order = np.argsort(p, kind="stable")
    scaled = p[order] * m / np.arange(1, m + 1)
    adjusted = np.minimum(np.minimum.accumulate(scaled[::-1])[::-1], 1.0)
    out = np.empty(m)
    out[order] = adjusted
    return out
