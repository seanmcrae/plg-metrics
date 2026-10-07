"""Validate the experiment readout against synthetic ground truth across many seeds.

For each seed, generates a SYNTHETIC dataset, runs the onboarding_v2 readout, and
records whether each metric's interval covers the generator's true effect. Rows are
appended to a CSV after every seed, so an interrupted run resumes where it stopped.
Also simulates repeated peeking on A/A tests to compare naive and mSPRT error rates,
and writes the combined summary next to the CSV.

    uv run python scripts/validate_experiment.py --seeds 30 --out docs/validation/ground_truth.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from plg.validation import FIRST_SEED, format_summary, peeking_simulation, validate_seed


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
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

    summary = format_summary(
        pd.read_csv(args.out), args.users, peeking_simulation(sims=args.peeking_sims)
    )
    summary_path = args.out.with_name("summary.txt")
    summary_path.write_text(summary + "\n")
    print(f"\n{summary}\n\nwrote {summary_path}")


if __name__ == "__main__":
    main()
