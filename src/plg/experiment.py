"""End-to-end experiment readout: integrity, estimates, corrections, and guardrails."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from plg.stats.bayes import BayesResult, beta_binomial
from plg.stats.cuped import cuped_diff_means
from plg.stats.frequentist import EffectEstimate, SRMResult, diff_means, diff_proportions, srm_check
from plg.stats.multiple import benjamini_hochberg, holm
from plg.stats.power import minimum_detectable_effect
from plg.stats.sequential import sequential_monitor
from plg.store import Warehouse
from plg.synthetic import ACTIVATION_EVENT, ACTIVITY_EVENT

CONTROL, TREATMENT = "control", "treatment"
MetricKind = Literal["proportion", "mean"]
Correction = Literal["holm", "bh"]


@dataclass(frozen=True)
class MetricSpec:
    name: str
    column: str
    kind: MetricKind
    role: Literal["primary", "secondary"] = "secondary"

    def __post_init__(self) -> None:
        if self.kind not in ("proportion", "mean"):
            raise ValueError(f"unknown metric kind: {self.kind}")


@dataclass(frozen=True)
class ExperimentConfig:
    experiment: str
    metrics: tuple[MetricSpec, ...] = (
        MetricSpec("activated_14d", "activated", "proportion", "primary"),
        MetricSpec("active_days_28d", "active_days", "mean"),
        MetricSpec("paid_28d", "paid", "proportion"),
    )
    covariate: str = "pre_pageviews"
    expected_shares: tuple[float, float] = (0.5, 0.5)
    alpha: float = 0.05
    correction: Correction = "holm"
    activation_days: int = 14
    paid_days: int = 28
    active_days_window: int = 28
    sequential_tau: float = 0.02

    @property
    def primary(self) -> MetricSpec:
        return next(m for m in self.metrics if m.role == "primary")


@dataclass(frozen=True)
class MetricResult:
    spec: MetricSpec
    raw: EffectEstimate
    cuped: EffectEstimate
    variance_reduction: float
    p_adjusted: float
    true_effect: float | None = None

    @property
    def truth_covered(self) -> bool | None:
        return None if self.true_effect is None else self.cuped.covers(self.true_effect)


@dataclass
class Readout:
    config: ExperimentConfig
    srm: SRMResult
    metrics: list[MetricResult]
    bayes: BayesResult
    sequential: pd.DataFrame
    mde_primary: float
    notes: list[str] = field(default_factory=list)

    def metric(self, name: str) -> MetricResult:
        return next(m for m in self.metrics if m.spec.name == name)

    @property
    def decision(self) -> str:
        if self.srm.mismatch:
            return "INVALID: sample ratio mismatch; fix assignment/logging before reading results"
        primary = self.metric(self.config.primary.name)
        harmed = [
            m.spec.name
            for m in self.metrics
            if m.p_adjusted < self.config.alpha and m.cuped.diff < 0
        ]
        if harmed:
            return f"DO NOT SHIP: significant regression in {', '.join(harmed)}"
        if primary.p_adjusted < self.config.alpha and primary.cuped.diff > 0:
            return f"SHIP: {primary.spec.name} improved with no significant regressions"
        return "INCONCLUSIVE: no significant change in the primary metric"


def experiment_units(wh: Warehouse, cfg: ExperimentConfig) -> pd.DataFrame:
    """Per-user outcomes for everyone enrolled in the experiment."""
    units = wh.run(
        "experiment_metrics",
        {
            "experiment": cfg.experiment,
            "activation_event": ACTIVATION_EVENT,
            "activation_days": cfg.activation_days,
            "paid_event": "subscribe",
            "paid_days": cfg.paid_days,
            "activity_event": ACTIVITY_EVENT,
            "active_days_window": cfg.active_days_window,
            "covariate_event": "marketing_pageview",
        },
    )
    if units.empty:
        raise ValueError(f"no units enrolled in experiment {cfg.experiment!r}")
    unknown = set(units["variant"]) - {CONTROL, TREATMENT}
    if unknown:
        raise ValueError(f"unexpected variants: {sorted(unknown)}")
    return units


def _estimate(spec: MetricSpec, c: pd.Series, t: pd.Series, alpha: float) -> EffectEstimate:
    if spec.kind == "proportion":
        return diff_proportions(int(c.sum()), c.size, int(t.sum()), t.size, alpha)
    return diff_means(c.to_numpy(), t.to_numpy(), alpha)


def sequential_looks(units: pd.DataFrame, column: str) -> pd.DataFrame:
    """Cumulative difference and standard error at each enrollment day.

    Each look includes users enrolled up to that day, each scored on a fully
    matured outcome window, i.e. the analysis you would run on that day if you
    waited for outcomes to mature before each peek."""
    day = units["assigned_ts"].dt.floor("D")
    rows = []
    for look_day in sorted(day.unique()):
        sub = units[day <= look_day]
        c = sub.loc[sub["variant"] == CONTROL, column]
        t = sub.loc[sub["variant"] == TREATMENT, column]
        if c.size < 30 or t.size < 30:
            continue
        se = float(np.sqrt(c.var(ddof=1) / c.size + t.var(ddof=1) / t.size))
        rows.append(
            {"look_day": look_day, "n": len(sub), "diff": float(t.mean() - c.mean()), "se": se}
        )
    return pd.DataFrame(rows)


def adjust_p_values(roles: list[str], p_values: list[float], correction: Correction) -> list[float]:
    """The pre-registered primary metric is tested at alpha as-is; the secondary
    metrics form the correction family, so adding a secondary never dilutes the
    primary decision while still guarding against fishing among secondaries."""
    adjust = holm if correction == "holm" else benjamini_hochberg
    secondary = [i for i, role in enumerate(roles) if role != "primary"]
    out = list(p_values)
    if secondary:
        for i, p_adj in zip(secondary, adjust([p_values[i] for i in secondary]), strict=True):
            out[i] = float(p_adj)
    return out


def analyze(
    units: pd.DataFrame, cfg: ExperimentConfig, ground_truth: dict[str, float] | None = None
) -> Readout:
    is_c = units["variant"] == CONTROL
    control, treatment = units[is_c], units[~is_c]
    srm = srm_check([len(control), len(treatment)], list(cfg.expected_shares))

    estimates = []
    for spec in cfg.metrics:
        raw = _estimate(spec, control[spec.column], treatment[spec.column], cfg.alpha)
        cup = cuped_diff_means(
            control[spec.column].to_numpy(),
            control[cfg.covariate].to_numpy(),
            treatment[spec.column].to_numpy(),
            treatment[cfg.covariate].to_numpy(),
            cfg.alpha,
        )
        estimates.append((spec, raw, cup))

    adjusted = adjust_p_values(
        [spec.role for spec, _, _ in estimates],
        [cup.estimate.p_value for _, _, cup in estimates],
        cfg.correction,
    )
    truth = ground_truth or {}
    metrics = [
        MetricResult(
            spec=spec,
            raw=raw,
            cuped=cup.estimate,
            variance_reduction=cup.variance_reduction,
            p_adjusted=float(p_adj),
            true_effect=truth.get(spec.name),
        )
        for (spec, raw, cup), p_adj in zip(estimates, adjusted, strict=True)
    ]

    primary = cfg.primary
    pc, pt = control[primary.column], treatment[primary.column]
    bayes = beta_binomial(int(pc.sum()), pc.size, int(pt.sum()), pt.size)
    looks = sequential_monitor(
        sequential_looks(units, primary.column), cfg.sequential_tau, cfg.alpha
    )
    mde = minimum_detectable_effect(float(pc.mean()), min(pc.size, pt.size), cfg.alpha)
    return Readout(cfg, srm, metrics, bayes, looks, mde)


def ground_truth_effects(wh: Warehouse) -> dict[str, float] | None:
    truth = wh.metadata.get("experiment", {}).get("ground_truth")
    if not truth:
        return None
    return {name: float(v["true_effect"]) for name, v in truth.items()}


def run_experiment(wh: Warehouse, name: str) -> Readout:
    cfg = ExperimentConfig(experiment=name)
    return analyze(experiment_units(wh, cfg), cfg, ground_truth_effects(wh))
