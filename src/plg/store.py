"""DuckDB access layer over the Parquet event store.

Analyses talk to a :class:`Warehouse`, which exposes three views (``users``,
``events``, ``assignments``) and runs SQL kept as ``.sql`` files under
``plg/sql``. Parameters are bound with DuckDB's ``$name`` syntax, never string
formatting, except for identifiers that cannot be bound (validated first).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

TABLES = ("users", "events", "assignments")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@cache
def load_sql(name: str) -> str:
    """Return the text of ``plg/sql/<name>.sql``."""
    return resources.files("plg.sql").joinpath(f"{name}.sql").read_text(encoding="utf-8")


def quote_identifier(name: str) -> str:
    """Validate a column name before splicing it into SQL."""
    if not _IDENTIFIER.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return f'"{name}"'


class Warehouse:
    """Read-only DuckDB session over a directory of Parquet files."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        missing = [t for t in TABLES if not (self.data_dir / f"{t}.parquet").exists()]
        if missing:
            raise FileNotFoundError(
                f"{self.data_dir} is missing {', '.join(missing)}.parquet; run `plg generate` first"
            )
        self.con = duckdb.connect(":memory:")
        for table in TABLES:
            path = (self.data_dir / f"{table}.parquet").as_posix().replace("'", "''")
            self.con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")

    @classmethod
    def from_frames(cls, **frames: pd.DataFrame) -> Warehouse:
        """In-memory warehouse from DataFrames; used for small hand-built test data."""
        wh = cls.__new__(cls)
        wh.data_dir = Path()
        wh.con = duckdb.connect(":memory:")
        for table in TABLES:
            frame = frames.get(table, _empty(table))
            wh.con.register(f"_{table}_df", frame)
            wh.con.execute(f"CREATE VIEW {table} AS SELECT * FROM _{table}_df")
        return wh

    @property
    def metadata(self) -> dict[str, Any]:
        path = self.data_dir / "metadata.json"
        return dict(json.loads(path.read_text())) if path.exists() else {}

    def observation_end(self) -> datetime:
        """End of the observed period: metadata if present, else just after the last event."""
        if end := self.metadata.get("observation_end"):
            return datetime.fromisoformat(end)
        row = self.con.execute("SELECT max(event_ts) + INTERVAL 1 SECOND FROM events").fetchone()
        if row is None or row[0] is None:
            raise ValueError("events table is empty")
        return pd.Timestamp(row[0]).to_pydatetime()

    def query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or {}).df()

    def run(self, name: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        return self.query(load_sql(name), params)

    def close(self) -> None:
        self.con.close()


def _empty(table: str) -> pd.DataFrame:
    schemas: dict[str, dict[str, str]] = {
        "users": {
            "user_id": "int64",
            "signup_ts": "datetime64[us]",
            "channel": "object",
            "plan": "object",
            "company_size": "object",
        },
        "events": {"user_id": "int64", "event_name": "object", "event_ts": "datetime64[us]"},
        "assignments": {
            "user_id": "int64",
            "experiment": "object",
            "variant": "object",
            "assigned_ts": "datetime64[us]",
        },
    }
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in schemas[table].items()})
