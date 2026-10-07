# Security policy

plg-metrics runs locally against Parquet files you supply. It has no server component, stores no credentials, and makes no network calls at runtime.

## Reporting a vulnerability

Please report suspected vulnerabilities privately through GitHub's [private vulnerability reporting](https://github.com/seanmcrae/plg-metrics/security/advisories/new) rather than a public issue. Include the version or commit, steps to reproduce, and the impact you expect. You can expect an acknowledgement within a week.

Areas of particular interest:

- SQL construction in the funnel query builder (`src/plg/funnel.py`) and segment column validation.
- Handling of untrusted Parquet files or `metadata.json` passed with `--data`.
- The Streamlit dashboard when exposed beyond localhost (the Docker image binds `0.0.0.0`; put it behind authentication if you deploy it).

## Supported versions

Only the latest release on `main` receives fixes.
