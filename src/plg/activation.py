"""Activation definition search.

Enumerates candidate rules of the form "did <event> at least k times in the first
N days" and ranks them by how well they predict week-4 retention. The output is a
shortlist for a human to sanity-check (is the behavior something onboarding can
actually drive?), not an automatic definition: these are correlations, and an
experiment is the way to confirm a behavior is causal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np
import pandas as pd

from plg.store import Warehouse
from plg.synthetic import ACTIVITY_EVENT

DEFAULT_CANDIDATES = (
    "session_start",
    "connect_data_source",
    "create_dashboard",
    "add_chart",
    "install_integration",
    "invite_teammate",
    "view_docs",
)
RankBy = Literal["f1", "lift", "precision"]


@dataclass(frozen=True)
class ActivationSearch:
    candidates: tuple[str, ...] = DEFAULT_CANDIDATES
    thresholds: tuple[int, ...] = (1, 2, 3, 5, 8)
    early_days: int = 7
    target_start_day: int = 21
    target_end_day: int = 27
    min_coverage: float = 0.05
    rank_by: RankBy = "f1"


def behavior_matrix(
    wh: Warehouse,
    search: ActivationSearch,
    activity_event: str = ACTIVITY_EVENT,
    observation_end: datetime | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Wide per-user early-behavior counts and the boolean retention label."""
    long = wh.run(
        "activation_features",
        {
            "candidates": list(search.candidates),
            "early_days": search.early_days,
            "target_start_day": search.target_start_day,
            "target_end_day": search.target_end_day,
            "activity_event": activity_event,
            "observation_end": observation_end or wh.observation_end(),
        },
    )
    label = long.groupby("user_id")["retained"].first().astype(bool)
    counts = (
        long.dropna(subset=["event_name"])
        .pivot_table(index="user_id", columns="event_name", values="n", aggfunc="sum")
        .reindex(index=label.index, columns=list(search.candidates))
        .fillna(0)
        .astype(int)
    )
    return counts, label


def score_rules(counts: pd.DataFrame, label: pd.Series, search: ActivationSearch) -> pd.DataFrame:
    """Score every (event, threshold) rule; ranked best first."""
    y = label.to_numpy(dtype=bool)
    base_rate = float(y.mean())
    rows = []
    for event in counts.columns:
        values = counts[event].to_numpy()
        for k in search.thresholds:
            hit = values >= k
            n_hit = int(hit.sum())
            if n_hit == 0 or n_hit == len(hit):
                continue
            precision = float(y[hit].mean())
            retention_without = float(y[~hit].mean())
            recall = float(y[hit].sum() / y.sum()) if y.any() else 0.0
            rows.append(
                {
                    "rule": f"{event} >= {k} in first {search.early_days}d",
                    "event": event,
                    "threshold": k,
                    "coverage": n_hit / len(hit),
                    "precision": precision,
                    "retention_without": retention_without,
                    "recall": recall,
                    "lift": precision / base_rate if base_rate else np.nan,
                    "f1": 2 * precision * recall / (precision + recall)
                    if precision + recall
                    else 0.0,
                }
            )
    scored = pd.DataFrame(rows)
    if scored.empty:
        return scored
    scored = scored[scored["coverage"] >= search.min_coverage]
    return scored.sort_values(search.rank_by, ascending=False).reset_index(drop=True)


def search_activation(
    wh: Warehouse,
    search: ActivationSearch | None = None,
    observation_end: datetime | None = None,
) -> tuple[pd.DataFrame, float]:
    """Ranked candidate activation rules and the base week-4 retention rate."""
    search = search or ActivationSearch()
    counts, label = behavior_matrix(wh, search, observation_end=observation_end)
    return score_rules(counts, label, search), float(label.mean())
