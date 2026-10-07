"""Command-line interface: ``plg <command>``."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from plg.activation import RankBy
from plg.experiment import Correction, ExperimentConfig
from plg.funnel import DEFAULT_STEPS, FunnelSpec
from plg.reports import (
    activation_report,
    engagement_report,
    experiment_report,
    funnel_report,
    retention_report,
)
from plg.retention import RetentionMode
from plg.stats.power import (
    minimum_detectable_effect,
    sample_size_means,
    sample_size_proportions,
)
from plg.store import Warehouse
from plg.synthetic import GeneratorConfig, generate

app = typer.Typer(
    help="Product-led-growth analytics: funnels, retention, activation, experiments.",
    no_args_is_help=True,
    add_completion=False,
)

DEFAULT_DATA = Path("data/synthetic")
DataOption = Annotated[Path, typer.Option("--data", "-d", help="Directory of Parquet tables.")]


def _warehouse(data: Path) -> Warehouse:
    try:
        return Warehouse(data)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


@app.command("generate")
def generate_cmd(
    out: Annotated[Path, typer.Option(help="Output directory.")] = DEFAULT_DATA,
    users: Annotated[int, typer.Option(help="Number of synthetic users.")] = 20_000,
    seed: Annotated[int, typer.Option(help="Random seed.")] = 7,
    srm_drop_rate: Annotated[
        float, typer.Option(help="Share of treatment assignments to drop (simulated SRM bug).")
    ] = 0.0,
) -> None:
    """Generate the SYNTHETIC event dataset (users, events, assignments, metadata)."""
    cfg = GeneratorConfig(n_users=users, seed=seed, srm_drop_rate=srm_drop_rate)
    ds = generate(cfg)
    ds.write(out)
    typer.echo(
        f"Wrote SYNTHETIC dataset to {out}: {len(ds.users):,} users, {len(ds.events):,} events, "
        f"{len(ds.assignments):,} experiment assignments (seed={seed})"
    )


@app.command("funnel")
def funnel_cmd(
    data: DataOption = DEFAULT_DATA,
    steps: Annotated[str, typer.Option(help="Comma-separated ordered steps.")] = ",".join(
        DEFAULT_STEPS
    ),
    window_days: Annotated[float, typer.Option(help="Conversion window from entry.")] = 14,
    by: Annotated[str | None, typer.Option(help="users column to break down by.")] = None,
) -> None:
    """Ordered funnel with a conversion window, optional segment breakdown, and time-to-convert."""
    spec = FunnelSpec(
        steps=tuple(s.strip() for s in steps.split(",")), window=timedelta(days=window_days)
    )
    typer.echo(funnel_report(_warehouse(data), spec, by))


@app.command("retention")
def retention_cmd(
    data: DataOption = DEFAULT_DATA,
    mode: Annotated[str, typer.Option(help="bounded (active in week N) or unbounded.")] = "bounded",
    weeks: Annotated[int, typer.Option(help="Weeks after signup to show.")] = 8,
) -> None:
    """Weekly signup-cohort retention matrix and day-N retention."""
    if mode not in ("bounded", "unbounded"):
        raise typer.BadParameter("mode must be 'bounded' or 'unbounded'")
    retention_mode: RetentionMode = "bounded" if mode == "bounded" else "unbounded"
    typer.echo(retention_report(_warehouse(data), retention_mode, weeks))


@app.command("engagement")
def engagement_cmd(
    data: DataOption = DEFAULT_DATA,
    min_active_days: Annotated[int, typer.Option(help="Active days/week for the north star.")] = 3,
) -> None:
    """DAU/WAU/MAU stickiness and the weekly engaged activated users north star."""
    typer.echo(engagement_report(_warehouse(data), min_active_days))


@app.command("activation")
def activation_cmd(
    data: DataOption = DEFAULT_DATA,
    rank_by: Annotated[str, typer.Option(help="f1, lift, or precision.")] = "f1",
    top: Annotated[int, typer.Option(help="Rules to show.")] = 10,
) -> None:
    """Rank early behaviors by how well they predict week-4 retention."""
    if rank_by not in ("f1", "lift", "precision"):
        raise typer.BadParameter("rank-by must be f1, lift, or precision")
    order: RankBy = "f1" if rank_by == "f1" else ("lift" if rank_by == "lift" else "precision")
    typer.echo(activation_report(_warehouse(data), order, top))


@app.command("experiment")
def experiment_cmd(
    name: Annotated[str, typer.Argument(help="Experiment name, e.g. onboarding_v2.")],
    data: DataOption = DEFAULT_DATA,
    correction: Annotated[str, typer.Option(help="holm or bh for secondary metrics.")] = "holm",
) -> None:
    """Full experiment readout: SRM, CUPED estimates, corrections, Bayesian, sequential."""
    if correction not in ("holm", "bh"):
        raise typer.BadParameter("correction must be holm or bh")
    corr: Correction = "holm" if correction == "holm" else "bh"
    wh = _warehouse(data)
    try:
        report = experiment_report(wh, ExperimentConfig(experiment=name, correction=corr))
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(report)


@app.command("power")
def power_cmd(
    baseline: Annotated[float, typer.Option(help="Control conversion rate (proportions).")] = 0.30,
    mde: Annotated[float, typer.Option(help="Absolute minimum detectable effect.")] = 0.02,
    alpha: Annotated[float, typer.Option(help="Two-sided significance level.")] = 0.05,
    power: Annotated[float, typer.Option(help="Target power.")] = 0.8,
    ratio: Annotated[float, typer.Option(help="Treatment/control allocation ratio.")] = 1.0,
    sd: Annotated[
        float | None, typer.Option(help="Outcome std. dev.; switches to a means test.")
    ] = None,
    variance_reduction: Annotated[
        float, typer.Option(help="Expected CUPED variance reduction (means test).")
    ] = 0.0,
    daily_units: Annotated[
        int | None, typer.Option(help="Eligible units per day, to estimate duration.")
    ] = None,
) -> None:
    """Sample size per arm for a proportion or mean metric."""
    if sd is None:
        n_c, n_t = sample_size_proportions(baseline, mde, alpha, power, ratio)
        typer.echo(
            f"Proportions: baseline {baseline:.1%}, MDE {mde * 100:+.2f} pp "
            f"({mde / baseline:+.1%} relative), alpha {alpha}, power {power:.0%}"
        )
    else:
        n_c, n_t = sample_size_means(sd, mde, alpha, power, ratio, variance_reduction)
        typer.echo(
            f"Means: sd {sd}, MDE {mde:+}, alpha {alpha}, power {power:.0%}, "
            f"variance reduction {variance_reduction:.0%}"
        )
    typer.echo(f"Required: control {n_c:,} + treatment {n_t:,} = {n_c + n_t:,} units")
    if daily_units:
        typer.echo(f"Duration at {daily_units:,} units/day: {-(-(n_c + n_t) // daily_units)} days")
    if sd is None:
        for n in (1_000, 5_000, 20_000):
            mde_n = minimum_detectable_effect(baseline, n, alpha, power)
            typer.echo(f"  MDE with {n:>6,} per arm: {mde_n * 100:.2f} pp")


@app.command("plots")
def plots_cmd(
    data: DataOption = DEFAULT_DATA,
    out: Annotated[Path, typer.Option(help="Directory for PNG charts.")] = Path("docs/img"),
    experiment: Annotated[str, typer.Option(help="Experiment for the CI plot.")] = "onboarding_v2",
) -> None:
    """Render funnel, retention heatmap, experiment CI, and sequential charts as PNGs."""
    from plg.plots import render_all  # matplotlib import is deferred: only this command needs it

    for path in render_all(_warehouse(data), out, experiment):
        typer.echo(f"wrote {path}")


if __name__ == "__main__":
    app()
