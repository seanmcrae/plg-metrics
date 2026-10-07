"""Stickiness (DAU/WAU/MAU) and north-star metric tracking."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from plg.store import Warehouse
from plg.synthetic import ACTIVATION_EVENT, ACTIVITY_EVENT


def stickiness(
    wh: Warehouse,
    activity_event: str = ACTIVITY_EVENT,
    observation_end: datetime | None = None,
) -> pd.DataFrame:
    """Daily DAU/WAU/MAU with DAU/MAU and DAU/WAU ratios.

    Ratios are left NaN until a full 28-day window of history exists, because a
    partially filled MAU denominator inflates stickiness early in a dataset."""
    df = wh.run(
        "stickiness",
        {
            "activity_event": activity_event,
            "observation_end": observation_end or wh.observation_end(),
        },
    )
    df["dau_mau"] = (df["dau"] / df["mau"]).where(df["mau_window_complete"])
    df["dau_wau"] = (df["dau"] / df["wau"]).where(df["mau_window_complete"])
    return df


def north_star(
    wh: Warehouse,
    min_active_days: int = 3,
    activity_event: str = ACTIVITY_EVENT,
    activation_event: str = ACTIVATION_EVENT,
    observation_end: datetime | None = None,
) -> pd.DataFrame:
    """Weekly Engaged Activated Users with week-over-week change."""
    df = wh.run(
        "north_star",
        {
            "activity_event": activity_event,
            "activation_event": activation_event,
            "min_active_days": min_active_days,
            "observation_end": observation_end or wh.observation_end(),
        },
    )
    df["weau_wow"] = df["weau"].pct_change()
    df["weau_share_of_wau"] = df["weau"] / df["weekly_active_users"]
    return df
