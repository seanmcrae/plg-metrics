"""Validate the experiment readout against synthetic ground truth across many seeds.

For each seed, generates a SYNTHETIC dataset, runs the onboarding_v2 readout, and
records whether each metric's interval covers the generator's true effect. Rows are
appended to a CSV after every seed, so an interrupted run resumes where it stopped.
Also simulates repeated peeking on A/A tests to compare naive and mSPRT error rates.

    uv run python scripts/validate_experiment.py --seeds 30 --out docs/validation/ground_truth.csv
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from plg.experiment import run_experiment
from plg.render import num, pct, table
from plg.stats.sequential import sequential_monitor
from plg.store import Warehouse
from plg.synthetic import GeneratorConfig, generate

FIRST_SEED = 1_000


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


def peeking_simulation(sims: int, looks: int, per_look: int, seed: int) -> tuple[float, float]:
    """Share of A/A tests (p = 0.3 both arms) declared significant at any daily look."""
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
    return naive / sims, msprt / sims


def summarize(rows: pd.DataFrame) -> str:
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
    formats = {c: num(4) for c in ("mean_true_effect", "mean_cuped_bias", "mean_se_ratio")}
    formats |= {c: pct for c in ("raw_coverage", "cuped_coverage", "power")}
    return table(summary.reset_index(), formats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--users", type=int, default=20_000)
    parser.add_argument("--out", type=Path, default=Path("docs/validation/ground_truth.csv"))
    parser.add_argument("--peeking-sims", type=int, default=2_000)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set(pd.read_csv(args.out)["seed"]) if args.out.exists() else set()
    for seed in range(FIRST_SEED, FIRST_SEED + args.seeds):
        if seed in done:
            continue
        frame = pd.DataFrame(validate_seed(seed, args.users))
        frame.to_csv(args.out, mode="a", header=not args.out.exists(), index=False)
        print(f"seed {seed}: done", flush=True)

    rows = pd.read_csv(args.out)
    print(
        f"\nGround-truth recovery over {rows['seed'].nunique()} seeds ({args.users:,} users each)\n"
    )
    print(summarize(rows))
    decisions = rows.drop_duplicates("seed")["decision"].value_counts()
    print("\nDecisions:", ", ".join(f"{k} {v}" for k, v in decisions.items()))
    naive, msprt = peeking_simulation(args.peeking_sims, looks=30, per_look=200, seed=0)
    print(
        f"\nA/A peeking ({args.peeking_sims:,} sims, 30 daily looks): "
        f"naive false-positive rate {naive:.1%}, mSPRT {msprt:.1%}"
    )


if __name__ == "__main__":
    main()
