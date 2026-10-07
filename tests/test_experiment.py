from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from plg.experiment import (
    ExperimentConfig,
    adjust_p_values,
    analyze,
    experiment_units,
    ground_truth_effects,
    run_experiment,
    sequential_looks,
)
from plg.store import Warehouse
from plg.synthetic import GeneratorConfig, SyntheticDataset, generate

EXPERIMENT = "onboarding_v2"


def _warehouse(tmp_path: Path, cfg: GeneratorConfig) -> Warehouse:
    generate(cfg).write(tmp_path)
    return Warehouse(tmp_path)


def test_recovers_ground_truth_on_bundled_seed(synthetic_dir: Path) -> None:
    readout = run_experiment(Warehouse(synthetic_dir), EXPERIMENT)
    assert not readout.srm.mismatch
    for m in readout.metrics:
        assert m.true_effect is not None
        assert m.raw.covers(m.true_effect), m.spec.name
        assert m.truth_covered, m.spec.name
    assert readout.decision.startswith("SHIP")


@pytest.mark.parametrize("seed", [101, 202])
def test_primary_effect_recovered_across_seeds(tmp_path: Path, seed: int) -> None:
    wh = _warehouse(tmp_path, GeneratorConfig(seed=seed))
    primary = run_experiment(wh, EXPERIMENT).metric("activated_14d")
    assert primary.truth_covered
    assert primary.true_effect == pytest.approx(0.023, abs=0.004)


def test_srm_bug_invalidates_readout(tmp_path: Path) -> None:
    wh = _warehouse(tmp_path, GeneratorConfig(n_users=12_000, seed=5, srm_drop_rate=0.08))
    readout = run_experiment(wh, EXPERIMENT)
    assert readout.srm.mismatch
    assert readout.decision.startswith("INVALID")


def test_aa_test_does_not_ship(tmp_path: Path) -> None:
    wh = _warehouse(tmp_path, GeneratorConfig(n_users=12_000, seed=9, treatment_logit_lift=0.0))
    readout = run_experiment(wh, EXPERIMENT)
    truth = ground_truth_effects(wh)
    assert truth is not None
    assert truth["activated_14d"] == pytest.approx(0.0, abs=1e-12)
    assert readout.metric("activated_14d").truth_covered
    assert not readout.decision.startswith("SHIP")


def test_units_match_assignments_and_covariate_is_balanced(
    synthetic_dir: Path, synthetic: SyntheticDataset
) -> None:
    units = experiment_units(Warehouse(synthetic_dir), ExperimentConfig(EXPERIMENT))
    assert len(units) == len(synthetic.assignments)
    means = units.groupby("variant")["pre_pageviews"].mean()
    assert means["treatment"] == pytest.approx(means["control"], rel=0.08)
    assert set(units["activated"].unique()) <= {0, 1}


def test_cuped_reduces_variance_on_engagement_metric(synthetic_dir: Path) -> None:
    readout = run_experiment(Warehouse(synthetic_dir), EXPERIMENT)
    m = readout.metric("active_days_28d")
    assert m.variance_reduction > 0.1
    assert m.cuped.se < m.raw.se


def test_sequential_looks_accumulate(synthetic_dir: Path) -> None:
    units = experiment_units(Warehouse(synthetic_dir), ExperimentConfig(EXPERIMENT))
    looks = sequential_looks(units, "activated")
    assert looks["n"].is_monotonic_increasing
    assert looks["n"].iloc[-1] == len(units)
    assert (looks["se"].diff().dropna() < 0.002).all()


def test_primary_is_not_corrected_secondaries_are() -> None:
    out = adjust_p_values(["primary", "secondary", "secondary"], [0.03, 0.02, 0.04], "holm")
    assert out == pytest.approx([0.03, 0.04, 0.04])
    bh = adjust_p_values(["primary", "secondary", "secondary"], [0.03, 0.02, 0.04], "bh")
    assert bh == pytest.approx([0.03, 0.04, 0.04])


def test_unknown_experiment_raises(synthetic_dir: Path) -> None:
    with pytest.raises(ValueError, match="no units"):
        experiment_units(Warehouse(synthetic_dir), ExperimentConfig("does_not_exist"))


def test_regression_blocks_ship() -> None:
    n = 4_000
    units = pd.DataFrame(
        {
            "variant": ["control"] * n + ["treatment"] * n,
            "assigned_ts": pd.date_range("2026-01-01", periods=2 * n, freq="min"),
            "activated": [1] * 1_200 + [0] * 2_800 + [1] * 1_350 + [0] * 2_650,
            "active_days": [8] * n + [6] * n,
            "paid": [0, 1] * n,
            "pre_pageviews": [3, 4] * n,
        }
    )
    readout = analyze(units, ExperimentConfig(EXPERIMENT))
    assert readout.decision.startswith("DO NOT SHIP")
    assert "active_days_28d" in readout.decision
