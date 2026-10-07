from __future__ import annotations

import pandas as pd
import pytest

from plg.synthetic import FUNNEL_STEPS, GeneratorConfig, SyntheticDataset, generate

SMALL = GeneratorConfig(n_users=1_500, seed=11)


def test_same_seed_is_byte_identical() -> None:
    a, b = generate(SMALL), generate(SMALL)
    pd.testing.assert_frame_equal(a.events, b.events)
    pd.testing.assert_frame_equal(a.users, b.users)
    pd.testing.assert_frame_equal(a.assignments, b.assignments)
    assert a.metadata == b.metadata


def test_different_seed_changes_data() -> None:
    a = generate(SMALL)
    b = generate(GeneratorConfig(n_users=1_500, seed=12))
    assert not a.events.equals(b.events)


def test_metadata_labels_data_synthetic(synthetic: SyntheticDataset) -> None:
    assert synthetic.metadata["synthetic"] is True
    assert "SYNTHETIC" in synthetic.metadata["description"]


def test_funnel_is_monotone_and_has_realistic_drop_off(synthetic: SyntheticDataset) -> None:
    reached = synthetic.events.groupby("event_name")["user_id"].nunique()
    counts = [int(reached[s]) for s in FUNNEL_STEPS if s != "invite_teammate"]
    assert counts == sorted(counts, reverse=True)
    activation_rate = reached["create_dashboard"] / reached["signup"]
    assert 0.2 < activation_rate < 0.45


def test_events_never_precede_signup_except_marketing(synthetic: SyntheticDataset) -> None:
    ev = synthetic.events.merge(synthetic.users[["user_id", "signup_ts"]], on="user_id")
    in_product = ev[ev["event_name"] != "marketing_pageview"]
    assert (in_product["event_ts"] >= in_product["signup_ts"]).all()
    pre = ev[ev["event_name"] == "marketing_pageview"]
    assert (pre["event_ts"] < pre["signup_ts"]).all()


def test_experiment_assignment_is_balanced_and_windowed(synthetic: SyntheticDataset) -> None:
    a = synthetic.assignments
    share = (a["variant"] == "treatment").mean()
    assert share == pytest.approx(0.5, abs=0.02)
    exp_start = pd.Timestamp(synthetic.metadata["experiment"]["start"])
    assert (a["assigned_ts"] >= exp_start).all()


def test_srm_bug_drops_treatment_rows() -> None:
    clean = generate(SMALL)
    buggy = generate(GeneratorConfig(n_users=1_500, seed=11, srm_drop_rate=0.2))
    assert (buggy.assignments["variant"] == "treatment").sum() < (
        clean.assignments["variant"] == "treatment"
    ).sum()
    assert (buggy.assignments["variant"] == "control").sum() == (
        clean.assignments["variant"] == "control"
    ).sum()


def test_ground_truth_effects_are_positive(synthetic: SyntheticDataset) -> None:
    truth = synthetic.metadata["experiment"]["ground_truth"]
    assert set(truth) == {"activated_14d", "active_days_28d", "paid_28d"}
    assert all(m["true_effect"] > 0 for m in truth.values())
