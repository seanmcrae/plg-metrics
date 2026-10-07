from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from plg.funnel import FunnelSpec, funnel, time_to_convert, user_funnel
from plg.store import Warehouse

STEPS = ("a", "b", "c")
T0 = datetime(2026, 1, 1, 9, 0)


def _wh(rows: list[tuple[int, str, float]]) -> Warehouse:
    """rows: (user_id, event_name, hours after T0)."""
    events = pd.DataFrame(
        {
            "user_id": [r[0] for r in rows],
            "event_name": [r[1] for r in rows],
            "event_ts": [T0 + timedelta(hours=r[2]) for r in rows],
        }
    )
    ids = sorted({r[0] for r in rows})
    users = pd.DataFrame(
        {
            "user_id": ids,
            "signup_ts": [T0] * len(ids),
            "channel": ["organic" if i % 2 else "referral" for i in ids],
            "plan": ["free"] * len(ids),
            "company_size": ["1-10"] * len(ids),
        }
    )
    return Warehouse.from_frames(users=users, events=events)


def _reached(wh: Warehouse, spec: FunnelSpec) -> dict[int, int]:
    """user_id -> number of steps reached."""
    df = user_funnel(wh, spec)
    cols = [f"t{k}" for k in range(len(spec.steps))]
    return {
        int(r.user_id): int(pd.Series([getattr(r, c) for c in cols]).notna().sum())
        for r in df.itertuples()
    }


SPEC = FunnelSpec(steps=STEPS, window=timedelta(hours=24))


def test_in_order_within_window_completes() -> None:
    assert _reached(_wh([(1, "a", 0), (1, "b", 1), (1, "c", 2)]), SPEC) == {1: 3}


def test_out_of_order_events_do_not_count() -> None:
    # b happens before a, so only a and then nothing (c needs b first).
    assert _reached(_wh([(1, "b", 0), (1, "a", 1), (1, "c", 2)]), SPEC) == {1: 1}


def test_later_step_after_skipped_step_needs_the_skipped_step() -> None:
    assert _reached(_wh([(1, "a", 0), (1, "c", 1), (1, "b", 2)]), SPEC) == {1: 2}


def test_window_is_measured_from_entry_not_previous_step() -> None:
    # b at 20h is inside 24h; c at 25h is outside even though it is 5h after b.
    assert _reached(_wh([(1, "a", 0), (1, "b", 20), (1, "c", 25)]), SPEC) == {1: 2}


def test_window_boundary_is_inclusive() -> None:
    assert _reached(_wh([(1, "a", 0), (1, "b", 24)]), SPEC) == {1: 2}


def test_entry_anchors_on_first_occurrence_of_step_zero() -> None:
    # Second "a" at 30h would complete in-window, but entry is the first "a".
    rows = [(1, "a", 0), (1, "a", 30), (1, "b", 31), (1, "c", 32)]
    assert _reached(_wh(rows), SPEC) == {1: 1}


def test_tied_timestamps_satisfy_ordering() -> None:
    assert _reached(_wh([(1, "a", 0), (1, "b", 0), (1, "c", 0)]), SPEC) == {1: 3}


def test_users_without_entry_step_are_excluded() -> None:
    assert _reached(_wh([(1, "b", 0), (2, "a", 0)]), SPEC) == {2: 1}


def test_entry_period_filters_entry_only() -> None:
    rows = [(1, "a", 0), (1, "b", 1), (2, "a", 48), (2, "b", 49)]
    spec = FunnelSpec(steps=STEPS, window=timedelta(hours=24), entry_end=T0 + timedelta(hours=12))
    assert _reached(_wh(rows), spec) == {1: 2}


def test_conversion_rates_and_segments() -> None:
    rows = [
        (1, "a", 0), (1, "b", 1), (1, "c", 2),
        (2, "a", 0), (2, "b", 1),
        (3, "a", 0),
        (4, "a", 0), (4, "b", 3), (4, "c", 4),
    ]  # fmt: skip
    wh = _wh(rows)
    overall = funnel(wh, SPEC)
    assert overall["users"].tolist() == [4, 3, 2]
    assert overall["conv_from_prev"].tolist() == pytest.approx([1.0, 0.75, 2 / 3])
    by = funnel(wh, SPEC, by="channel").set_index(["segment", "step"])
    assert by.loc[("organic", "c"), "users"] == 1  # users 1, 3
    assert by.loc[("referral", "c"), "users"] == 1  # users 2, 4
    assert by.loc[("referral", "b"), "conv_from_start"] == pytest.approx(1.0)


def test_time_to_convert_hours() -> None:
    rows = [(1, "a", 0), (1, "b", 2), (2, "a", 0), (2, "b", 4), (2, "c", 10)]
    ttc = time_to_convert(_wh(rows), SPEC).set_index("step")
    assert ttc.loc["b", "converters"] == 2
    assert ttc.loc["b", "p50"] == pytest.approx(3.0)
    assert ttc.loc["c", "mean_hours"] == pytest.approx(10.0)


@pytest.mark.parametrize(
    "kwargs",
    [{"steps": ("a",)}, {"steps": ("a", "a")}, {"window": timedelta(0)}],
)
def test_invalid_specs_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        FunnelSpec(**kwargs)  # type: ignore[arg-type]


def test_segment_column_is_validated() -> None:
    with pytest.raises(ValueError, match="invalid identifier"):
        funnel(_wh([(1, "a", 0)]), SPEC, by="plan; drop table users")


def test_synthetic_funnel_matches_event_counts(synthetic_dir: Path) -> None:
    wh = Warehouse(synthetic_dir)
    spec = FunnelSpec(window=timedelta(days=3650))
    result = funnel(wh, spec)
    # With an unbounded window the ordered funnel equals simple reach for steps the
    # generator emits strictly in order (all but invite_teammate).
    reach = wh.query(
        "SELECT event_name, count(DISTINCT user_id) AS n FROM events GROUP BY 1"
    ).set_index("event_name")["n"]
    by_step = result.set_index("step")["users"]
    for step in ("signup", "create_workspace", "connect_data_source", "create_dashboard"):
        assert by_step[step] == reach[step]
    assert by_step["invite_teammate"] < reach["invite_teammate"]
