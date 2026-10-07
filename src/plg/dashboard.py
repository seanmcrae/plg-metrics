"""Streamlit dashboard: funnel, retention heatmap, and experiment readout.

Run with ``make dashboard`` or
``streamlit run src/plg/dashboard.py -- --data data/synthetic``.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from plg.experiment import Readout, run_experiment
from plg.funnel import DEFAULT_STEPS, FunnelSpec, funnel
from plg.plots import experiment_ci_plot, funnel_chart, retention_heatmap, sequential_plot
from plg.retention import RetentionMode, retention_matrix
from plg.store import Warehouse

SEGMENTS = ("channel", "plan", "company_size")


def _data_dir() -> Path:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    args, _ = parser.parse_known_args()
    return Path(args.data)


@st.cache_resource
def _warehouse(path: str) -> Warehouse:
    return Warehouse(Path(path))


@st.cache_data
def _readout(path: str, experiment: str) -> Readout:
    return run_experiment(_warehouse(path), experiment)


def funnel_tab(wh: Warehouse) -> None:
    left, right = st.columns(2)
    window = left.slider("Conversion window (days)", 1, 28, 14)
    segment = right.selectbox("Break down by", ("none", *SEGMENTS))
    spec = FunnelSpec(steps=DEFAULT_STEPS, window=timedelta(days=window))
    overall = funnel(wh, spec)
    st.pyplot(funnel_chart(overall, f"Funnel, {window}-day window"))
    if segment != "none":
        by = funnel(wh, spec, by=segment)
        wide = by.pivot(index="step", columns="segment", values="conv_from_start")
        st.dataframe(wide.loc[list(spec.steps)].style.format("{:.1%}"))


def retention_tab(wh: Warehouse) -> None:
    choice = st.radio("Mode", ("bounded", "unbounded"), horizontal=True)
    mode: RetentionMode = "bounded" if choice == "bounded" else "unbounded"
    weeks = st.slider("Weeks", 4, 12, 8)
    matrix = retention_matrix(wh, mode, max_weeks=weeks)
    st.pyplot(retention_heatmap(matrix))
    st.line_chart(matrix.weighted_curve().rename("retention"))


def experiment_tab(path: str) -> None:
    readout = _readout(path, "onboarding_v2")
    srm = readout.srm
    cols = st.columns(4)
    cols[0].metric("Control", f"{srm.observed[0]:,}")
    cols[1].metric("Treatment", f"{srm.observed[1]:,}")
    cols[2].metric("SRM p-value", f"{srm.p_value:.3f}", "mismatch" if srm.mismatch else "ok")
    cols[3].metric("P(treatment better)", f"{readout.bayes.prob_treatment_better:.1%}")
    st.info(readout.decision)
    rows = [
        {
            "metric": m.spec.name,
            "role": m.spec.role,
            "control": m.raw.control_mean,
            "treatment": m.raw.treatment_mean,
            "CUPED diff": m.cuped.diff,
            "CI low": m.cuped.ci_low,
            "CI high": m.cuped.ci_high,
            "p": m.cuped.p_value,
            "p adj": m.p_adjusted,
            "variance reduction": m.variance_reduction,
            "true effect": m.true_effect,
        }
        for m in readout.metrics
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.pyplot(experiment_ci_plot(readout))
    st.pyplot(sequential_plot(readout))


def main() -> None:
    st.set_page_config(page_title="PLG metrics", layout="wide")
    path = str(_data_dir())
    wh = _warehouse(path)
    synthetic = " (SYNTHETIC data)" if wh.metadata.get("synthetic") else ""
    st.title("PLG metrics")
    st.caption(f"Source: {path}{synthetic}")
    funnel_t, retention_t, experiment_t = st.tabs(["Funnel", "Retention", "Experiment"])
    with funnel_t:
        funnel_tab(wh)
    with retention_t:
        retention_tab(wh)
    with experiment_t:
        experiment_tab(path)


main()
