"""Weekly cohort retention (bounded and unbounded) and day-N retention curves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import pandas as pd

from plg.store import Warehouse
from plg.synthetic import ACTIVITY_EVENT

RetentionMode = Literal["bounded", "unbounded"]


@dataclass(frozen=True)
class RetentionMatrix:
    """Cohort x week retention rates. Cells a cohort has not fully lived through are NaN."""

    rates: pd.DataFrame
    cohort_sizes: pd.Series
    mode: RetentionMode

    def weighted_curve(self) -> pd.Series:
        """Cohort-size-weighted retention by week, over complete cells only."""
        weights = self.rates.notna().mul(self.cohort_sizes, axis=0)
        retained = self.rates.fillna(0).mul(self.cohort_sizes, axis=0)
        return retained.sum() / weights.sum()


def retention_matrix(
    wh: Warehouse,
    mode: RetentionMode = "bounded",
    max_weeks: int = 8,
    activity_event: str = ACTIVITY_EVENT,
    observation_end: datetime | None = None,
) -> RetentionMatrix:
    if mode not in ("bounded", "unbounded"):
        raise ValueError(f"unknown retention mode: {mode}")
    long = wh.run(
        "retention_cohorts",
        {
            "activity_event": activity_event,
            "observation_end": observation_end or wh.observation_end(),
            "max_weeks": max_weeks,
        },
    )
    long["rate"] = (long[f"retained_{mode}"] / long["cohort_size"]).where(long["complete"])
    rates = long.pivot(index="cohort_week", columns="week_number", values="rate")
    rates.columns.name = "week"
    sizes = long.groupby("cohort_week")["cohort_size"].first()
    return RetentionMatrix(rates=rates, cohort_sizes=sizes, mode=mode)


def day_n_retention(
    wh: Warehouse,
    days: tuple[int, ...] = (1, 7, 14, 28, 56),
    activity_event: str = ACTIVITY_EVENT,
    observation_end: datetime | None = None,
) -> pd.DataFrame:
    return wh.run(
        "day_n_retention",
        {
            "days": list(days),
            "activity_event": activity_event,
            "observation_end": observation_end or wh.observation_end(),
        },
    )
