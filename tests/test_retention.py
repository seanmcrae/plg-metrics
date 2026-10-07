from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from plg.retention import day_n_retention, retention_matrix
from plg.store import Warehouse

MON = datetime(2026, 1, 5, 10, 0)  # a Monday
OBS_END = datetime(2026, 2, 2)  # 28 days after MON's date


def _wh(signups: dict[int, datetime], active_days: dict[int, list[int]]) -> Warehouse:
    users = pd.DataFrame(
        {
            "user_id": list(signups),
            "signup_ts": list(signups.values()),
            "channel": "organic",
            "plan": "free",
            "company_size": "1-10",
        }
    )
    rows = [
        (uid, signups[uid].replace(hour=12) + timedelta(days=d))
        for uid, days in active_days.items()
        for d in days
    ]
    events = pd.DataFrame(
        {
            "user_id": [r[0] for r in rows],
            "event_name": "session_start",
            "event_ts": [r[1] for r in rows],
        }
    )
    return Warehouse.from_frames(users=users, events=events)


@pytest.fixture
def tiny() -> Warehouse:
    # Cohort 2026-01-05: users 1-4 (signups Mon/Mon/Wed/Sun). Cohort 2026-01-12: user 5.
    signups = {
        1: MON,
        2: MON,
        3: MON + timedelta(days=2),
        4: MON + timedelta(days=6),
        5: MON + timedelta(days=8),
    }
    active = {
        1: [0, 1, 8, 15],  # weeks 0, 1, 2
        2: [0, 20],  # weeks 0, 2 (skips week 1)
        3: [0],  # week 0 only
        4: [0, 7],  # weeks 0, 1
        5: [0, 9],  # weeks 0, 1
    }
    return _wh(signups, active)


def test_bounded_matrix_on_hand_built_data(tiny: Warehouse) -> None:
    m = retention_matrix(tiny, "bounded", max_weeks=3, observation_end=OBS_END)
    c1, c2 = pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-12")
    assert m.cohort_sizes.loc[c1] == 4
    assert m.rates.loc[c1, 0] == pytest.approx(1.0)
    assert m.rates.loc[c1, 1] == pytest.approx(2 / 4)  # users 1, 4
    assert m.rates.loc[c1, 2] == pytest.approx(2 / 4)  # users 1, 2
    # Cohort 1's last signup is 01-11; week 3 ends day 27 -> 02-07 >= OBS_END: incomplete.
    assert np.isnan(m.rates.loc[c1, 3])
    assert m.rates.loc[c2, 1] == pytest.approx(1.0)
    assert np.isnan(m.rates.loc[c2, 3])


def test_unbounded_counts_any_later_activity(tiny: Warehouse) -> None:
    m = retention_matrix(tiny, "unbounded", max_weeks=3, observation_end=OBS_END)
    c1 = pd.Timestamp("2026-01-05")
    # Week 1 unbounded: users 1, 2 (returns in week 2), 4.
    assert m.rates.loc[c1, 1] == pytest.approx(3 / 4)
    assert m.rates.loc[c1, 2] == pytest.approx(2 / 4)


def test_unbounded_dominates_bounded(synthetic_dir: Path) -> None:
    wh = Warehouse(synthetic_dir)
    bounded = retention_matrix(wh, "bounded").rates
    unbounded = retention_matrix(wh, "unbounded").rates
    mask = bounded.notna().to_numpy()
    assert mask.sum() > 40
    assert (unbounded.to_numpy()[mask] >= bounded.to_numpy()[mask]).all()
    curve = retention_matrix(wh, "unbounded").weighted_curve()
    assert curve.is_monotonic_decreasing


def test_weighted_curve_uses_complete_cells(tiny: Warehouse) -> None:
    m = retention_matrix(tiny, "bounded", max_weeks=3, observation_end=OBS_END)
    curve = m.weighted_curve()
    assert curve[0] == pytest.approx(1.0)
    assert curve[1] == pytest.approx((2 + 1) / 5)


def test_day_n_retention(tiny: Warehouse) -> None:
    out = day_n_retention(tiny, days=(1, 7), observation_end=OBS_END).set_index("day_n")
    assert out.loc[1, "eligible_users"] == 5
    assert out.loc[1, "retained_users"] == 1  # user 1
    assert out.loc[7, "retained_users"] == 1  # user 4


def test_invalid_mode(tiny: Warehouse) -> None:
    with pytest.raises(ValueError, match="unknown retention mode"):
        retention_matrix(tiny, "rolling")  # type: ignore[arg-type]
