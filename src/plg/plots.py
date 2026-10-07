"""Matplotlib charts shared by the CLI (PNG export) and the Streamlit dashboard."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from plg.experiment import Readout, run_experiment
from plg.funnel import FunnelSpec, funnel
from plg.retention import RetentionMatrix, retention_matrix
from plg.store import Warehouse

INK = "#1f2933"
MUTED = "#7b8794"
ACCENT = "#2563eb"
SECOND = "#f59e0b"
TRUTH = "#dc2626"


def _style(ax: Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(colors=INK, labelsize=9)
    ax.title.set_color(INK)


def funnel_chart(steps: pd.DataFrame, title: str = "Onboarding funnel") -> Figure:
    """Horizontal bars of users per step, labelled with step and cumulative conversion."""
    fig, ax = plt.subplots(figsize=(8, 4.2), layout="constrained")
    labels = steps["step"].tolist()[::-1]
    users = steps["users"].to_numpy()[::-1]
    conv_start = steps["conv_from_start"].to_numpy()[::-1]
    conv_prev = steps["conv_from_prev"].to_numpy()[::-1]
    ax.barh(labels, users, color=ACCENT, alpha=0.85)
    for y, (n, cs, cp) in enumerate(zip(users, conv_start, conv_prev, strict=True)):
        ax.text(
            n + users.max() * 0.01,
            y,
            f"{n:,}  ({cs:.1%} of entry, {cp:.0%} of prev)",
            va="center",
            fontsize=8.5,
            color=INK,
        )
    ax.set_xlim(0, users.max() * 1.55)
    ax.set_xlabel("users", color=MUTED)
    ax.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    ax.set_title(title, loc="left", fontsize=11)
    _style(ax)
    return fig


def retention_heatmap(matrix: RetentionMatrix, title: str | None = None) -> Figure:
    """Cohort x week heatmap; incomplete cells are left blank rather than shown as zero."""
    rates = matrix.rates
    fig, ax = plt.subplots(figsize=(8, 4.8), layout="constrained")
    data = np.ma.masked_invalid(rates.to_numpy(dtype=float))
    im = ax.imshow(data, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for (i, j), value in np.ndenumerate(rates.to_numpy(dtype=float)):
        if not np.isnan(value):
            ax.text(
                j,
                i,
                f"{value:.0%}",
                ha="center",
                va="center",
                fontsize=7.5,
                color="white" if value > 0.6 else INK,
            )
    ax.set_xticks(range(rates.shape[1]), [f"W{c}" for c in rates.columns])
    cohort_labels = [
        f"{pd.Timestamp(c).date()}  (n={matrix.cohort_sizes[c]:,})" for c in rates.index
    ]
    ax.set_yticks(range(rates.shape[0]), cohort_labels)
    ax.set_xlabel("weeks since signup", color=MUTED)
    ax.set_title(title or f"Weekly cohort retention ({matrix.mode})", loc="left", fontsize=11)
    fig.colorbar(im, ax=ax, shrink=0.8, format=matplotlib.ticker.PercentFormatter(1.0))
    ax.tick_params(colors=INK, labelsize=8)
    return fig


def experiment_ci_plot(readout: Readout) -> Figure:
    """One panel per metric: raw vs CUPED interval for treatment minus control, with
    the generator's true effect marked when ground truth is available."""
    metrics = readout.metrics
    level = f"{1 - readout.config.alpha:.0%}"
    fig, axes = plt.subplots(
        len(metrics), 1, figsize=(8, 1.45 * len(metrics) + 0.9), layout="constrained"
    )
    for ax, m in zip(np.atleast_1d(axes), metrics, strict=True):
        rows = [("CUPED", m.cuped, ACCENT), ("raw", m.raw, MUTED)]
        for y, (label, est, color) in enumerate(rows):
            ax.errorbar(
                est.diff,
                y,
                xerr=[[est.diff - est.ci_low], [est.ci_high - est.diff]],
                fmt="o",
                color=color,
                capsize=4,
                lw=2,
            )
            ax.text(
                est.ci_high,
                y + 0.28,
                f"{label}: {est.diff:+.4f}  p={est.p_value:.3f}",
                fontsize=8,
                color=INK,
                ha="right",
            )
        ax.axvline(0, color=INK, lw=0.8)
        if m.true_effect is not None:
            ax.axvline(m.true_effect, color=TRUTH, lw=1.2, ls="--", label="true effect")
        ax.set_yticks([0, 1], ["CUPED", "raw"])
        ax.set_ylim(-0.6, 1.8)
        ax.set_title(
            f"{m.spec.name} ({m.spec.role}, var. reduction {m.variance_reduction:.0%})",
            loc="left",
            fontsize=9.5,
        )
        _style(ax)
    first = np.atleast_1d(axes)[0]
    if any(m.true_effect is not None for m in metrics):
        first.legend(loc="upper left", fontsize=8, frameon=False)
    fig.suptitle(
        f"{readout.config.experiment}: treatment - control, {level} CIs",
        x=0.01,
        ha="left",
        fontsize=11,
        color=INK,
    )
    return fig


def sequential_plot(readout: Readout) -> Figure:
    """Naive fixed-horizon p-value vs the always-valid mSPRT p-value at each daily look."""
    seq = readout.sequential
    alpha = readout.config.alpha
    fig, ax = plt.subplots(figsize=(8, 3.6), layout="constrained")
    ax.plot(seq["look_day"], seq["naive_p"], color=SECOND, lw=1.8, label="naive p (peeking)")
    ax.plot(seq["look_day"], seq["always_valid_p"], color=ACCENT, lw=1.8, label="always-valid p")
    ax.axhline(alpha, color=TRUTH, ls="--", lw=1, label=f"alpha = {alpha}")
    ax.set_yscale("log")
    ax.set_ylabel("p-value (log)", color=MUTED)
    ax.set_title(
        f"{readout.config.experiment}: sequential monitoring of {readout.config.primary.name}",
        loc="left",
        fontsize=11,
    )
    ax.legend(fontsize=8, frameon=False)
    fig.autofmt_xdate()
    _style(ax)
    return fig


def render_all(wh: Warehouse, out_dir: Path, experiment: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    readout = run_experiment(wh, experiment)
    figures = {
        "funnel.png": funnel_chart(funnel(wh, FunnelSpec())),
        "retention_heatmap.png": retention_heatmap(retention_matrix(wh, "bounded")),
        "experiment_ci.png": experiment_ci_plot(readout),
        "sequential.png": sequential_plot(readout),
    }
    paths = []
    for name, fig in figures.items():
        path = out_dir / name
        fig.savefig(path, dpi=150, facecolor="white")
        plt.close(fig)
        paths.append(path)
    return paths
