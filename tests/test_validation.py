from __future__ import annotations

import pandas as pd
import pytest

from plg.validation import (
    PeekingResult,
    decision_counts,
    format_summary,
    peeking_simulation,
    summarize,
)


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "seed": [1, 1, 2, 2],
            "metric": ["a", "b", "a", "b"],
            "true_effect": [0.10, 1.0, 0.10, 1.0],
            "cuped_diff": [0.12, 0.8, 0.10, 1.4],
            "raw_covered": [True, False, True, True],
            "cuped_covered": [True, True, False, True],
            "se_ratio": [0.9, 0.7, 0.9, 0.9],
            "significant": [True, False, False, False],
            "decision": ["SHIP", "SHIP", "INCONCLUSIVE", "INCONCLUSIVE"],
        }
    )


def test_summarize_hand_computed() -> None:
    s = summarize(_rows()).set_index("metric")
    assert list(s.index) == ["a", "b"]
    assert s.loc["a", "mean_cuped_bias"] == pytest.approx(0.01)
    assert s.loc["b", "mean_cuped_bias"] == pytest.approx(0.1)
    assert s.loc["a", "cuped_coverage"] == pytest.approx(0.5)
    assert s.loc["b", "raw_coverage"] == pytest.approx(0.5)
    assert s.loc["b", "mean_se_ratio"] == pytest.approx(0.8)
    assert s.loc["a", "power"] == pytest.approx(0.5)


def test_decision_counts_one_per_seed() -> None:
    assert decision_counts(_rows()) == {"SHIP": 1, "INCONCLUSIVE": 1}


def test_format_summary_lines() -> None:
    text = format_summary(_rows(), 500, PeekingResult(10, 5, 0.3, 0.0))
    assert text.startswith("Ground-truth recovery over 2 seeds (500 users each)")
    assert "Decisions: SHIP 1, INCONCLUSIVE 1" in text
    assert text.endswith("naive false-positive rate 30.0%, mSPRT 0.0%")


def test_peeking_simulation_is_seeded_and_msprt_is_stricter() -> None:
    first = peeking_simulation(sims=150, looks=20, seed=4)
    assert first == peeking_simulation(sims=150, looks=20, seed=4)
    assert first.msprt_false_positive_rate < first.naive_false_positive_rate
