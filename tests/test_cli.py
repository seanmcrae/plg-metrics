from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from plg.cli import app

runner = CliRunner()


@pytest.fixture(scope="module")
def small_data(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("cli")
    result = runner.invoke(app, ["generate", "--out", str(out), "--users", "6000", "--seed", "3"])
    assert result.exit_code == 0, result.output
    assert "SYNTHETIC" in result.output
    return out


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["funnel", "--by", "channel"], "Conversion from entry by channel"),
        (["funnel", "--window-days", "1"], "1-day window"),
        (
            ["retention", "--mode", "unbounded", "--weeks", "4"],
            "Weekly cohort retention (unbounded)",
        ),
        (["engagement"], "North star"),
        (["activation", "--rank-by", "lift"], "Base week-4 retention"),
        (["experiment", "onboarding_v2", "--correction", "bh"], "Decision:"),
    ],
)
def test_commands_run(small_data: Path, args: list[str], expected: str) -> None:
    result = runner.invoke(app, [*args, "--data", str(small_data)])
    assert result.exit_code == 0, result.output
    assert expected in result.output
    assert "(SYNTHETIC)" in result.output


def test_power_command() -> None:
    result = runner.invoke(app, ["power", "--baseline", "0.1", "--mde", "0.02"])
    assert result.exit_code == 0
    assert "control 3,841 + treatment 3,841" in result.output
    means = runner.invoke(
        app, ["power", "--sd", "1", "--mde", "0.2", "--variance-reduction", "0.36"]
    )
    assert "control 252" in means.output


def test_missing_data_fails_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["funnel", "--data", str(tmp_path)])
    assert result.exit_code == 1
    assert "plg generate" in result.output


def test_unknown_experiment_fails_cleanly(small_data: Path) -> None:
    result = runner.invoke(app, ["experiment", "nope", "--data", str(small_data)])
    assert result.exit_code == 1


def test_bad_option_values(small_data: Path) -> None:
    result = runner.invoke(app, ["retention", "--mode", "rolling", "--data", str(small_data)])
    assert result.exit_code != 0
