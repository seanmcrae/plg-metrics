from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from plg.engagement import north_star, stickiness
from plg.store import Warehouse

D0 = datetime(2026, 1, 5, 12)  # Monday


def _wh(sessions: list[tuple[int, int]], activations: dict[int, int] | None = None) -> Warehouse:
    """sessions: (user_id, day offset from D0); activations: user_id -> day offset."""
    rows = [(u, "session_start", D0 + timedelta(days=d)) for u, d in sessions]
    rows += [
        (u, "create_dashboard", D0 + timedelta(days=d)) for u, d in (activations or {}).items()
    ]
    events = pd.DataFrame(rows, columns=["user_id", "event_name", "event_ts"])
    ids = sorted({r[0] for r in rows})
    users = pd.DataFrame(
        {"user_id": ids, "signup_ts": D0, "channel": "x", "plan": "free", "company_size": "1-10"}
    )
    return Warehouse.from_frames(users=users, events=events)


def test_dau_wau_mau_windows() -> None:
    # User 1 active every day for 30 days; user 2 only on day 0; user 3 on day 25.
    sessions = [(1, d) for d in range(30)] + [(2, 0), (3, 25)]
    df = stickiness(_wh(sessions), observation_end=D0 + timedelta(days=30)).set_index("day")
    day27 = pd.Timestamp("2026-02-01")  # D0 + 27
    assert df.loc[day27, "dau"] == 1
    assert df.loc[day27, "wau"] == 2  # users 1, 3
    assert df.loc[day27, "mau"] == 3  # day 0 still inside the 28-day window
    assert df.loc[day27, "dau_mau"] == pytest.approx(1 / 3)
    day28 = pd.Timestamp("2026-02-02")
    assert df.loc[day28, "mau"] == 2  # user 2 aged out
    assert pd.isna(df.loc[pd.Timestamp("2026-01-10"), "dau_mau"])  # MAU window not yet complete


def test_north_star_requires_activation_and_engagement() -> None:
    sessions = (
        [(1, d) for d in range(3)]  # 3 days in week 1, activated day 1 -> counts
        + [(2, d) for d in range(3)]  # 3 days but never activated
        + [(3, 0)]  # activated but only 1 active day
        + [(4, d) for d in range(7, 11)]  # week 2, activated on day 9 (inside that week)
    )
    wh = _wh(sessions, activations={1: 1, 3: 0, 4: 9})
    df = north_star(wh, observation_end=D0 + timedelta(days=14)).set_index("week")
    w1, w2 = pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-12")
    assert df.loc[w1, "weekly_active_users"] == 3
    assert df.loc[w1, "weau"] == 1
    assert df.loc[w2, "weau"] == 1
    assert df.loc[w2, "weau_wow"] == pytest.approx(0.0)


def test_north_star_drops_incomplete_weeks() -> None:
    wh = _wh([(1, d) for d in range(10)], activations={1: 0})
    df = north_star(wh, observation_end=D0 + timedelta(days=10))
    assert len(df) == 1


def test_synthetic_stickiness_is_plausible(synthetic_dir: Path) -> None:
    df = stickiness(Warehouse(synthetic_dir)).dropna(subset=["dau_mau"])
    assert df["dau_mau"].between(0.05, 0.6).all()
    assert (df["dau"] <= df["wau"]).all()
    assert (df["wau"] <= df["mau"]).all()
