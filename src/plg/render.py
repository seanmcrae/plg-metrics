"""Plain-text rendering for CLI output."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd

from plg.experiment import Readout

Formatter = Callable[[Any], str]


def _missing(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def text(x: Any) -> str:
    return "" if _missing(x) else str(x)


def pct(x: Any) -> str:
    return "" if _missing(x) else f"{float(x):.1%}"


def num(digits: int = 4) -> Formatter:
    def fmt(x: Any) -> str:
        return "" if _missing(x) else f"{float(x):.{digits}f}"

    return fmt


def signed(digits: int = 4) -> Formatter:
    def fmt(x: Any) -> str:
        return "" if _missing(x) else f"{float(x):+.{digits}f}"

    return fmt


def table(df: pd.DataFrame, formats: Mapping[str, Formatter] | None = None) -> str:
    """Left-aligned first column, right-aligned rest; NaN renders as blank."""
    formats = formats or {}
    cols = [str(c) for c in df.columns]
    cells = [
        [formats.get(str(c), text)(v) for c, v in row.items()]
        for _, row in df.astype(object).iterrows()
    ]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(cols)]

    def line(values: Sequence[str]) -> str:
        parts = [
            v.ljust(w) if i == 0 else v.rjust(w)
            for i, (v, w) in enumerate(zip(values, widths, strict=True))
        ]
        return "  ".join(parts).rstrip()

    return "\n".join([line(cols), line(["-" * w for w in widths]), *map(line, cells)])


def format_readout(r: Readout, data_label: str) -> str:
    cfg = r.config
    level = f"{1 - cfg.alpha:.0%}"
    rows = []
    for m in r.metrics:
        rows.append(
            {
                "metric": m.spec.name,
                "role": m.spec.role,
                "control": m.raw.control_mean,
                "treatment": m.raw.treatment_mean,
                "raw diff": m.raw.diff,
                "raw p": m.raw.p_value,
                "CUPED diff": m.cuped.diff,
                f"{level} CI": f"[{m.cuped.ci_low:+.4f}, {m.cuped.ci_high:+.4f}]",
                "CUPED p": m.cuped.p_value,
                "p_adj": m.p_adjusted,
                "var red": m.variance_reduction,
                "truth": m.true_effect,
                "in CI": "" if m.truth_covered is None else ("yes" if m.truth_covered else "NO"),
            }
        )
    metrics = table(
        pd.DataFrame(rows),
        {
            "control": num(),
            "treatment": num(),
            "raw diff": signed(),
            "raw p": num(),
            "CUPED diff": signed(),
            "CUPED p": num(),
            "p_adj": num(),
            "var red": pct,
            "truth": signed(),
        },
    )

    primary = r.metric(cfg.primary.name)
    seq = r.sequential
    n_looks = len(seq)

    def first(column: str) -> str:
        hits = seq.index[seq[column]]
        if len(hits) == 0:
            return "never"
        i = int(hits[0])
        day = pd.Timestamp(str(seq.loc[i, "look_day"])).date()
        return f"{day} (look {i + 1} of {n_looks})"

    srm_flag = "MISMATCH" if r.srm.mismatch else "OK"
    lines = [
        f"Experiment: {cfg.experiment}   data: {data_label}",
        f"Units: control {r.srm.observed[0]:,} | treatment {r.srm.observed[1]:,}",
        f"SRM check: chi2 = {r.srm.chi2:.2f}, p = {r.srm.p_value:.3f} -> {srm_flag} "
        f"(flag if p < {r.srm.threshold})",
        "",
        metrics,
        "",
        f"CUPED covariate: {cfg.covariate}; {level} CI is for the CUPED diff. "
        f"p_adj: {cfg.correction} on CUPED p across secondary metrics; primary tested at alpha.",
        f"Bayesian ({primary.spec.name}, Beta(1,1) prior): "
        f"P(treatment > control) = {r.bayes.prob_treatment_better:.1%}, "
        f"95% credible diff [{r.bayes.diff_ci_low:+.4f}, {r.bayes.diff_ci_high:+.4f}], "
        f"expected loss if shipped = {r.bayes.expected_loss_treatment:.5f}",
        f"Sequential guardrail (mSPRT, tau = {cfg.sequential_tau}): final always-valid "
        f"p = {seq['always_valid_p'].iloc[-1]:.4f}; first safe stop: {first('msprt_reject')}.",
        f"  Naive daily peeking at p < {cfg.alpha} would have stopped: {first('naive_reject')}.",
        f"Power: baseline {primary.raw.control_mean:.1%}, "
        f"{min(primary.raw.n_control, primary.raw.n_treatment):,} per arm -> "
        f"MDE at 80% power = {r.mde_primary * 100:.2f} pp",
        "",
        f"Decision: {r.decision}",
    ]
    return "\n".join(lines)
