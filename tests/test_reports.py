from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from plg.experiment import ExperimentConfig
from plg.funnel import FunnelSpec
from plg.reports import experiment_report, funnel_report
from plg.store import Warehouse


@pytest.fixture(scope="module")
def wh(synthetic_dir: Path) -> Warehouse:
    return Warehouse(synthetic_dir)


def test_experiment_report_shows_raw_and_cuped_p_values(wh: Warehouse) -> None:
    report = experiment_report(wh, ExperimentConfig(experiment="onboarding_v2"))
    header = next(line for line in report.splitlines() if line.startswith("metric"))
    columns = [c.strip() for c in header.split("  ") if c.strip()]
    assert columns.index("raw p") == columns.index("raw diff") + 1
    assert columns.index("CUPED p") > columns.index("95% CI")
    assert "(SYNTHETIC)" in report
    assert report.rstrip().splitlines()[-1].startswith("Decision: ")


def test_experiment_report_rejects_unknown_experiment(wh: Warehouse) -> None:
    with pytest.raises(ValueError, match="no units enrolled"):
        experiment_report(wh, ExperimentConfig(experiment="missing"))


def test_funnel_report_labels_fractional_windows(wh: Warehouse) -> None:
    report = funnel_report(wh, FunnelSpec(window=timedelta(hours=36)), by="plan")
    assert report.startswith("Funnel (1.5-day window)")
    assert "Conversion from entry by plan" in report
    assert "Hours from entry to step" in report
