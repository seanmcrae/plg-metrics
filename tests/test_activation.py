from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from plg.activation import ActivationSearch, score_rules, search_activation
from plg.store import Warehouse


def test_score_rules_hand_computed() -> None:
    # 10 users; "good" event done by users 0-3, of whom 3 retain; 1 of the other 6 retains.
    counts = pd.DataFrame({"good": [2, 2, 1, 1, 0, 0, 0, 0, 0, 0], "noise": [1, 0] * 5})
    label = pd.Series([True, True, True, False, True, False, False, False, False, False])
    search = ActivationSearch(candidates=("good", "noise"), thresholds=(1, 2), min_coverage=0.0)
    scored = score_rules(counts, label, search).set_index("rule")
    good = scored.loc["good >= 1 in first 7d"]
    assert good["coverage"] == pytest.approx(0.4)
    assert good["precision"] == pytest.approx(0.75)
    assert good["recall"] == pytest.approx(0.75)
    assert good["lift"] == pytest.approx(0.75 / 0.4)
    assert good["retention_without"] == pytest.approx(1 / 6)
    assert scored.index[0] == "good >= 1 in first 7d"


def test_min_coverage_filters_rare_rules() -> None:
    counts = pd.DataFrame({"rare": [5] + [0] * 99})
    label = pd.Series([True] + [False] * 99)
    search = ActivationSearch(candidates=("rare",), thresholds=(1,), min_coverage=0.05)
    assert score_rules(counts, label, search).empty


def test_rank_by_lift_prefers_high_thresholds() -> None:
    counts = pd.DataFrame({"e": [1, 2, 3, 3, 0, 0, 1, 0]})
    label = pd.Series([False, True, True, True, False, False, True, False])
    search = ActivationSearch(
        candidates=("e",), thresholds=(1, 3), min_coverage=0.0, rank_by="lift"
    )
    assert score_rules(counts, label, search)["threshold"].iloc[0] == 3


def test_synthetic_search_ranks_invites_above_docs(synthetic_dir: Path) -> None:
    ranked, base = search_activation(Warehouse(synthetic_dir))
    assert 0.1 < base < 0.6
    by_event = ranked.groupby("event")["lift"].max()
    # The generator wires invites and activation into churn; view_docs only rides
    # along with activity, so it should trail both.
    assert by_event["invite_teammate"] > by_event["view_docs"]
    assert by_event["create_dashboard"] > by_event["view_docs"] > 1.0
