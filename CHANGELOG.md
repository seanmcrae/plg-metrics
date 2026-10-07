# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-07

### Added

- Seeded synthetic B2B SaaS event generator with segments, churn, a pre-period covariate, and an embedded `onboarding_v2` experiment with analytic ground truth.
- DuckDB-over-Parquet warehouse with versioned SQL and bound parameters.
- Ordered funnels with conversion windows, segment breakdowns, and time-to-convert.
- Weekly cohort retention (bounded and unbounded), day-N retention, DAU/WAU/MAU stickiness, and a weekly engaged-activated-users north star.
- Activation-definition search ranked by F1, lift, or precision against week-4 retention.
- Experiment readout: SRM check, raw and CUPED estimates, Holm or Benjamini-Hochberg correction for secondary metrics, mSPRT always-valid p-values, beta-binomial probability to beat control, and power/MDE.
- `plg` CLI, Streamlit dashboard, and matplotlib chart export.
- Multi-seed ground-truth validation and A/A peeking simulation (`make validate`).
- Static documentation site built from live analysis output (`make site`) and deployed to GitHub Pages.

[Unreleased]: https://github.com/seanmcrae/plg-metrics/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/seanmcrae/plg-metrics/releases/tag/v0.1.0
