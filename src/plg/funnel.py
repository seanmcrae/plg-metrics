"""Ordered funnels with conversion windows, segment breakdowns, and time-to-convert.

Semantics (documented because funnel tools disagree here):

* A user enters on their *first* occurrence of step 0 inside the entry period.
* Step k counts only if it happens at or after the timestamp matched for step k-1
  and no later than ``entry + window``. Matching greedily on the earliest
  qualifying event is optimal: if any ordered path exists inside the window,
  the earliest-match path does too.
* Events tied on timestamp satisfy the ordering (``>=``), since batch loggers
  frequently stamp consecutive events identically. Steps must be distinct events.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from plg.store import Warehouse, quote_identifier
from plg.synthetic import FUNNEL_STEPS

DEFAULT_STEPS = FUNNEL_STEPS


@dataclass(frozen=True)
class FunnelSpec:
    steps: tuple[str, ...] = DEFAULT_STEPS
    window: timedelta = timedelta(days=14)
    entry_start: datetime | None = None
    entry_end: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.steps) < 2:
            raise ValueError("a funnel needs at least two steps")
        if len(set(self.steps)) != len(self.steps):
            raise ValueError("funnel steps must be distinct events")
        if self.window <= timedelta(0):
            raise ValueError("conversion window must be positive")


def build_user_funnel_sql(n_steps: int) -> str:
    """SQL returning one row per entering user with the matched timestamp of each step
    (NULL once the user drops out). Step names are bound as ``$s0..$s{n-1}``."""
    ctes = [
        """base AS (
    SELECT user_id, event_name, event_ts FROM events
    WHERE event_name IN ({names})
)""".format(names=", ".join(f"$s{i}" for i in range(n_steps))),
        """step_0 AS (
    SELECT user_id, min(event_ts) AS t0
    FROM base
    WHERE event_name = $s0
      AND ($entry_start IS NULL OR event_ts >= $entry_start)
      AND ($entry_end IS NULL OR event_ts < $entry_end)
    GROUP BY user_id
)""",
    ]
    for k in range(1, n_steps):
        prev = ", ".join(f"s.t{i}" for i in range(k))
        ctes.append(
            f"""step_{k} AS (
    SELECT s.user_id, {prev}, min(b.event_ts) AS t{k}
    FROM step_{k - 1} AS s
    JOIN base AS b
      ON b.user_id = s.user_id
     AND b.event_name = $s{k}
     AND b.event_ts >= s.t{k - 1}
     AND b.event_ts <= s.t0 + to_seconds($window_seconds)
    GROUP BY s.user_id, {prev}
)"""
        )
    select = ", ".join(
        ["step_0.user_id", "step_0.t0"] + [f"step_{k}.t{k}" for k in range(1, n_steps)]
    )
    joins = "\n".join(f"LEFT JOIN step_{k} USING (user_id)" for k in range(1, n_steps))
    body = ",\n".join(ctes)
    return f"WITH {body}\nSELECT {select}\nFROM step_0\n{joins}"


def _params(spec: FunnelSpec) -> dict[str, Any]:
    params: dict[str, Any] = {f"s{i}": s for i, s in enumerate(spec.steps)}
    params["entry_start"] = spec.entry_start
    params["entry_end"] = spec.entry_end
    params["window_seconds"] = spec.window.total_seconds()
    return params


def user_funnel(wh: Warehouse, spec: FunnelSpec) -> pd.DataFrame:
    """Per-user matched step timestamps (columns ``t0..t{n-1}``)."""
    return wh.query(build_user_funnel_sql(len(spec.steps)), _params(spec))


def funnel(wh: Warehouse, spec: FunnelSpec, by: str | None = None) -> pd.DataFrame:
    """Step counts and conversion rates, optionally broken down by a ``users`` column.

    Returns columns: [segment,] step_index, step, users, conv_from_start, conv_from_prev.
    """
    n = len(spec.steps)
    reached = ", ".join(f"count(f.t{k}) AS n{k}" for k in range(n))
    if by is None:
        sql = f"WITH f AS ({build_user_funnel_sql(n)}) SELECT {reached} FROM f"
        wide = wh.query(sql, _params(spec))
        wide.insert(0, "segment", "all")
    else:
        col = quote_identifier(by)
        sql = (
            f"WITH f AS ({build_user_funnel_sql(n)}) "
            f"SELECT CAST(u.{col} AS VARCHAR) AS segment, {reached} "
            f"FROM f JOIN users AS u USING (user_id) GROUP BY 1 ORDER BY 1"
        )
        wide = wh.query(sql, _params(spec))
    return _long_format(wide, spec.steps, keep_segment=by is not None)


def _long_format(wide: pd.DataFrame, steps: tuple[str, ...], keep_segment: bool) -> pd.DataFrame:
    rows = []
    for _, r in wide.iterrows():
        start = int(r["n0"])
        for k, step in enumerate(steps):
            users = int(r[f"n{k}"])
            prev = int(r[f"n{k - 1}"]) if k else start
            rows.append(
                {
                    "segment": r["segment"],
                    "step_index": k,
                    "step": step,
                    "users": users,
                    "conv_from_start": users / start if start else float("nan"),
                    "conv_from_prev": users / prev if prev else float("nan"),
                }
            )
    out = pd.DataFrame(rows)
    return out if keep_segment else out.drop(columns="segment")


def time_to_convert(
    wh: Warehouse, spec: FunnelSpec, quantiles: tuple[float, ...] = (0.5, 0.75, 0.9)
) -> pd.DataFrame:
    """Hours from funnel entry to each later step, among users who reached it."""
    n = len(spec.steps)
    parts = []
    for k in range(1, n):
        qs = ", ".join(
            f"quantile_cont(epoch(t{k} - t0) / 3600.0, {q}) AS p{round(q * 100)}" for q in quantiles
        )
        parts.append(
            f"SELECT {k} AS step_index, count(t{k}) AS converters, "
            f"avg(epoch(t{k} - t0) / 3600.0) AS mean_hours, {qs} FROM f WHERE t{k} IS NOT NULL"
        )
    sql = f"WITH f AS ({build_user_funnel_sql(n)}) " + " UNION ALL ".join(parts) + " ORDER BY 1"
    out = wh.query(sql, _params(spec))
    out.insert(1, "step", [spec.steps[k] for k in out["step_index"]])
    return out
