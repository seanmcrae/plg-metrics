# Contributing

Bug reports, questions about the statistics, and pull requests are welcome.

## Setup

```bash
uv sync --extra dev --extra docs --locked   # Python 3.11+
make ci                                     # lint, format check, type check, tests
```

`make demo` runs every CLI command on the synthetic dataset, `make site` builds the documentation site into `site/`, and `make validate` reruns the 100-seed ground-truth validation (slow; about one readout per seed).

## Before opening a pull request

- `make ci` passes. CI also runs on Python 3.11 and 3.12 and builds the site.
- New statistics come with a test against scipy, a hand calculation, or a simulation with a fixed seed. Tests never touch the network.
- Analyses return DataFrames or dataclasses; formatting belongs in `render.py`, `reports.py`, or `plots.py`.
- SQL lives in `src/plg/sql/*.sql` with bound `$parameters`. Do not interpolate user input into SQL.
- Any number quoted in the README or `docs/` comes from running the code and says which data it was run on. If a change moves a quoted number, regenerate it (`make demo`, `make plots`, `make validate`) in the same pull request.
- If you edit `docs/architecture.mmd`, copy it into the README's mermaid block and run `make diagram` (needs Node 20+) to re-render the SVG.
- Add a line to `CHANGELOG.md` under "Unreleased".

## Commit messages

Imperative and specific: "Add Fieller interval for relative lift", not "fix stuff".
