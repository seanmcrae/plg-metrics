from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from plg.store import Warehouse, load_sql, quote_identifier


def test_warehouse_reads_parquet_views(synthetic_dir: Path) -> None:
    wh = Warehouse(synthetic_dir)
    n_users = wh.query("SELECT count(*) AS n FROM users")["n"].iloc[0]
    assert n_users == 20_000
    assert wh.observation_end() == datetime(2026, 4, 27)


def test_missing_files_raise_helpful_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="plg generate"):
        Warehouse(tmp_path)


def test_sql_files_are_packaged() -> None:
    assert "activity_event" in load_sql("user_day_activity")


@pytest.mark.parametrize("bad", ["plan; DROP TABLE users", "1abc", "a-b", ""])
def test_identifier_validation_rejects_injection(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid identifier"):
        quote_identifier(bad)


def test_user_day_activity_dedupes_days() -> None:
    users = pd.DataFrame(
        {
            "user_id": [1],
            "signup_ts": pd.to_datetime(["2026-01-01 23:00"]),
            "channel": ["organic"],
            "plan": ["free"],
            "company_size": ["1-10"],
        }
    )
    events = pd.DataFrame(
        {
            "user_id": [1, 1, 1],
            "event_name": ["session_start"] * 3,
            "event_ts": pd.to_datetime(
                ["2026-01-01 23:30", "2026-01-02 08:00", "2026-01-02 09:00"]
            ),
        }
    )
    wh = Warehouse.from_frames(users=users, events=events)
    out = wh.run(
        "user_day_activity",
        {"activity_event": "session_start", "observation_end": datetime(2026, 2, 1)},
    )
    assert sorted(out["day_number"]) == [0, 1]
    assert wh.observation_end() == datetime(2026, 1, 2, 9, 0, 1)


def test_committed_sample_is_synthetic_and_queryable() -> None:
    sample = Path(__file__).resolve().parents[1] / "data" / "sample_synthetic_3k"
    wh = Warehouse(sample)
    assert wh.metadata["synthetic"] is True
    assert wh.metadata["config"]["n_users"] == 3_000
    assert wh.query("SELECT count(*) AS n FROM users")["n"].iloc[0] == 3_000
