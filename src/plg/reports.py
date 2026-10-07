"""Plain-text reports: run one analysis against a warehouse and render it.

The CLI prints these and the static site embeds them, so both show identical output.
"""

from __future__ import annotations

import pandas as pd

from plg.activation import ActivationSearch, RankBy, search_activation
from plg.engagement import north_star, stickiness
from plg.experiment import ExperimentConfig, analyze, experiment_units, ground_truth_effects
from plg.funnel import FunnelSpec, funnel, time_to_convert
from plg.render import format_readout, num, pct, table
from plg.retention import RetentionMode, day_n_retention, retention_matrix
from plg.store import Warehouse


def data_label(wh: Warehouse) -> str:
    synthetic = " (SYNTHETIC)" if wh.metadata.get("synthetic") else ""
    return f"{wh.data_dir}{synthetic}"


def funnel_report(wh: Warehouse, spec: FunnelSpec, by: str | None = None) -> str:
    """Overall funnel, optional conversion-from-entry by segment, and time-to-convert."""
    window_days = spec.window.total_seconds() / 86_400
    parts = [f"Funnel ({window_days:g}-day window)   data: {data_label(wh)}\n"]
    overall = funnel(wh, spec).drop(columns="step_index")
    parts.append(table(overall, {"conv_from_start": pct, "conv_from_prev": pct}))
    if by:
        seg = funnel(wh, spec, by=by)
        wide = seg.pivot(index="step_index", columns="segment", values="conv_from_start")
        wide.insert(0, "step", list(spec.steps))
        formats = {str(c): pct for c in wide.columns if c != "step"}
        parts.append(f"\nConversion from entry by {by}\n")
        parts.append(table(wide.reset_index(drop=True), formats))
    ttc = time_to_convert(wh, spec).drop(columns="step_index")
    parts.append("\nHours from entry to step (converters only)\n")
    parts.append(table(ttc, {c: num(1) for c in ("mean_hours", "p50", "p75", "p90")}))
    return "\n".join(parts)


def retention_report(wh: Warehouse, mode: RetentionMode = "bounded", weeks: int = 8) -> str:
    """Weekly signup-cohort retention matrix, weighted curve, and day-N retention."""
    m = retention_matrix(wh, mode, max_weeks=weeks)
    rates = m.rates.copy()
    rates.columns = [f"w{c}" for c in rates.columns]
    rates.insert(0, "users", m.cohort_sizes)
    rates.insert(0, "cohort", [str(pd.Timestamp(i).date()) for i in rates.index])
    formats = {c: pct for c in rates.columns if c.startswith("w")}
    curve = m.weighted_curve()
    return "\n".join(
        [
            f"Weekly cohort retention ({mode})   data: {data_label(wh)}\n",
            table(rates.reset_index(drop=True), formats),
            "\nWeighted: " + "  ".join(f"w{k} {v:.1%}" for k, v in curve.items()),
            "\nDay-N retention\n",
            table(day_n_retention(wh), {"retention": pct}),
        ]
    )


def engagement_report(wh: Warehouse, min_active_days: int = 3) -> str:
    """Weekly view of DAU/WAU/MAU stickiness and the north-star series."""
    st = stickiness(wh).dropna(subset=["dau_mau"])
    weekly = st.groupby(pd.to_datetime(st["day"]).dt.to_period("W-SUN").dt.start_time).agg(
        dau=("dau", "mean"), wau=("wau", "last"), mau=("mau", "last"), dau_mau=("dau_mau", "mean")
    )
    weekly.insert(0, "week", [str(i.date()) for i in weekly.index])
    ns = north_star(wh, min_active_days=min_active_days)
    ns["week"] = [str(pd.Timestamp(w).date()) for w in ns["week"]]
    return "\n".join(
        [
            f"Stickiness (weekly view)   data: {data_label(wh)}\n",
            table(weekly.reset_index(drop=True), {"dau": num(0), "dau_mau": pct}),
            f"\nNorth star: weekly engaged activated users (>= {min_active_days} active days)\n",
            table(ns, {"weau_wow": pct, "weau_share_of_wau": pct}),
        ]
    )


def activation_report(wh: Warehouse, rank_by: RankBy = "f1", top: int = 10) -> str:
    """Early-behavior rules ranked by how well they predict week-4 retention."""
    ranked, base = search_activation(wh, ActivationSearch(rank_by=rank_by))
    cols = ["rule", "coverage", "precision", "retention_without", "recall", "lift", "f1"]
    rendered = table(
        ranked[cols].head(top),
        {
            "coverage": pct,
            "precision": pct,
            "retention_without": pct,
            "recall": pct,
            "lift": num(2),
            "f1": num(3),
        },
    )
    return "\n".join(
        [
            f"Activation search (target: active in days 21-27)   data: {data_label(wh)}",
            f"Base week-4 retention: {base:.1%}\n",
            rendered,
        ]
    )


def experiment_report(wh: Warehouse, cfg: ExperimentConfig) -> str:
    """Full readout; raises ValueError when no units are enrolled in the experiment."""
    units = experiment_units(wh, cfg)
    return format_readout(analyze(units, cfg, ground_truth_effects(wh)), data_label(wh))
