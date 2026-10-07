"""Check the experiment readout against synthetic ground truth.

``validate_seed`` regenerates the SYNTHETIC dataset under one seed and records,
per metric, whether the readout's interval covers the generator's true effect.
``peeking_simulation`` measures how often repeated looks at an A/A test produce
a false positive under naive and mSPRT stopping rules.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from plg.experiment import run_experiment
from plg.render import num, pct, table
from plg.stats.sequential import sequential_monitor
from plg.store import Warehouse
from plg.synthetic import GeneratorConfig, generate

FIRST_SEED = 1_000


@dataclass(frozen=True)
class PeekingResult:
    sims: int
    looks: int
    naive_false_positive_rate: float
    msprt_false_positive_rate: float

    def describe(self) -> str:
        return (
            f"A/A peeking ({self.sims:,} sims, {self.looks} daily looks): "
            f"naive false-positive rate {self.naive_false_positive_rate:.1%}, "
            f"mSPRT {self.msprt_false_positive_rate:.1%}"
        )


def validate_seed(seed: int, n_users: int) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory() as tmp:
        generate(GeneratorConfig(n_users=n_users, seed=seed)).write(Path(tmp))
        readout = run_experiment(Warehouse(Path(tmp)), "onboarding_v2")
    return [
        {
            "seed": seed,
            "metric": m.spec.name,
            "true_effect": m.true_effect,
            "raw_diff": m.raw.diff,
            "cuped_diff": m.cuped.diff,
            "raw_covered": m.raw.covers(float(m.true_effect or 0.0)),
            "cuped_covered": m.truth_covered,
            "se_ratio": m.cuped.se / m.raw.se,
            "significant": m.p_adjusted < readout.config.alpha,
            "srm_flag": readout.srm.mismatch,
            "decision": readout.decision.split(":")[0],
        }
        for m in readout.metrics
    ]


def peeking_simulation(
    sims: int = 2_000, looks: int = 30, per_look: int = 200, seed: int = 0
) -> PeekingResult:
    """Share of A/A tests (p = 0.3 in both arms) declared significant at any daily look."""
    rng = np.random.default_rng(seed)
    naive = msprt = 0
    n = per_look * np.arange(1, looks + 1)
    for _ in range(sims):
        pc = rng.binomial(per_look, 0.3, looks).cumsum() / n
        pt = rng.binomial(per_look, 0.3, looks).cumsum() / n
        frame = pd.DataFrame(
            {"diff": pt - pc, "se": np.sqrt(pc * (1 - pc) / n + pt * (1 - pt) / n)}
        )
        mon = sequential_monitor(frame, tau=0.02)
        naive += bool(mon["naive_reject"].any())
        msprt += bool(mon["msprt_reject"].any())
    return PeekingResult(sims, looks, naive / sims, msprt / sims)


def summarize(rows: pd.DataFrame) -> pd.DataFrame:
    """Per-metric coverage, bias, variance reduction, and power across seeds."""
    summary = rows.groupby("metric", sort=False).agg(
        seeds=("seed", "nunique"),
        mean_true_effect=("true_effect", "mean"),
        mean_cuped_bias=("cuped_diff", "mean"),
        raw_coverage=("raw_covered", "mean"),
        cuped_coverage=("cuped_covered", "mean"),
        mean_se_ratio=("se_ratio", "mean"),
        power=("significant", "mean"),
    )
    summary["mean_cuped_bias"] -= summary["mean_true_effect"]
    return summary.reset_index()


def decision_counts(rows: pd.DataFrame) -> dict[str, int]:
    counts = rows.drop_duplicates("seed")["decision"].value_counts()
    return {str(k): int(v) for k, v in counts.items()}


def format_summary(rows: pd.DataFrame, n_users: int, peeking: PeekingResult) -> str:
    formats = {c: num(4) for c in ("mean_true_effect", "mean_cuped_bias", "mean_se_ratio")}
    formats |= {c: pct for c in ("raw_coverage", "cuped_coverage", "power")}
    decisions = ", ".join(f"{k} {v}" for k, v in decision_counts(rows).items())
    return "\n".join(
        [
            f"Ground-truth recovery over {rows['seed'].nunique()} seeds ({n_users:,} users each)\n",
            table(summarize(rows), formats),
            f"\nDecisions: {decisions}",
            f"\n{peeking.describe()}",
        ]
    )
