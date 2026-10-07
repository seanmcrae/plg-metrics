# plg-metrics: product write-up

## Problem

Growth teams make most of their decisions from three artifacts: a funnel, a retention chart, and an A/B test readout. All three are easy to misread, and the errors are systematic rather than random.

- **Funnels lie about where users drop.** Unordered counts, inconsistent conversion windows, and re-anchoring on a user's latest visit inflate or deflate step conversion. A 14-day window reports a monetization problem that is really a timing problem: on the bundled synthetic data, 2.2% of entrants pay within 14 days and 4.8% within the full 112 days.
- **Retention charts show zeros nobody observed.** Young cohorts get plotted against weeks they have not lived through, which reads as a collapse.
- **Experiments get peeked at.** Checking a fixed-horizon p-value daily and stopping at the first p < 0.05 produces a false positive in 28.4% of A/A tests over 30 looks (2,000 simulations, `make validate`), roughly six times the error rate the team thinks it accepted.
- **Integrity checks run last, if at all.** A sample-ratio mismatch from a logging bug invalidates every number in a readout, but most dashboards show the lift first and the SRM warning, if any, at the bottom.
- **Secondary metrics turn into fishing.** With five metrics at alpha = 0.05, a team will see at least one "significant" movement in about 23% of experiments that change nothing.

The cost is decision error: shipping changes that do nothing, killing changes that work, and building roadmaps on activation definitions that are just proxies for "was already engaged".

## Users and jobs to be done

| User | Job | What they need from the tool |
| --- | --- | --- |
| Growth PM | "Tell me whether to ship onboarding_v2, and how sure I can be." | One readout with a decision line, the evidence behind it, and a refusal to answer when the data is broken (SRM). |
| Growth PM | "How long do I need to run this test?" | Sample size and duration from a baseline, an MDE, and daily traffic, including the effect of CUPED. |
| Product analyst | "Where is the funnel actually leaking, and for which segment?" | Ordered funnel with explicit window semantics, segment breakdowns, and time-to-convert. |
| Product analyst | "What should our activation metric be?" | A ranked list of early-behavior rules with coverage, precision, recall, and lift against week-4 retention. |
| Data scientist | "Can I trust these statistics?" | Methods tested against scipy, hand calculations, simulation, and synthetic ground truth. |
| Leadership | "Is the product getting stickier?" | DAU/MAU and a defined north-star series, weekly. |

## Scope

**In scope (v0.1)**

- Seeded synthetic event generator for a B2B SaaS funnel with segments, realistic drop-off and churn, a pre-period covariate, and an embedded experiment with an analytically known effect.
- DuckDB over Parquet; SQL in versioned `.sql` files with bound parameters.
- Ordered funnels with conversion windows, entry-period filters, segment breakdowns, time-to-convert.
- Weekly cohort retention (bounded and unbounded), day-N retention, DAU/WAU/MAU, a weekly north star.
- Activation-definition search.
- Experiment readout: SRM, difference in proportions and means with CIs, CUPED, Holm or BH, mSPRT always-valid p-values, beta-binomial probability to beat control, power and MDE.
- CLI, Streamlit dashboard, PNG export.

**Out of scope (v0.1)**

- Connectors to warehouses or product-analytics tools.
- A metric definition layer shared across tools.
- Account-level (multi-user workspace) analysis and cluster-robust errors.
- Heterogeneous-effect discovery, multi-armed bandits, interleaving.
- Experiment assignment. The tool reads assignments; it does not create them.

## Requirements

1. **Integrity first.** The readout runs SRM before any estimate; a mismatch (p < 0.001) overrides the decision to INVALID.
2. **Every estimate has an interval.** No point estimate is printed without a CI and a p-value; raw and CUPED estimates appear side by side.
3. **Primary vs secondary is explicit.** The primary metric is tested at alpha; secondaries are corrected as a family; any significant regression blocks a ship.
4. **Peeking is visible.** The readout states when the always-valid test first allowed a stop and when naive peeking would have stopped.
5. **No silent truncation.** Retention cells not fully observed are blank; ratios that need a full 28-day MAU window are blank until it exists.
6. **Reproducible.** The same seed produces byte-identical data; Monte Carlo summaries are seeded.
7. **Local and fast.** Each CLI command on the 20,000-user, 749k-event synthetic dataset completes in about 1.5 to 2.5 seconds wall time including interpreter start, measured on a 2-vCPU sandbox.
8. **Statistically verified in CI.** Stats functions match scipy or hand calculations; interval coverage and mSPRT error control are checked by simulation; the readout must recover the synthetic ground truth.

## Success metrics and evals

The tool measures itself in two ways: offline evals that run in this repository, and the product metrics a team would track once it is in use.

**Offline evals (shipping gates, run in CI or `make validate`)**

| Eval | How | Current result (bundled synthetic data) |
| --- | --- | --- |
| Ground-truth recovery | 100 seeds x 20,000 users; does the CUPED 95% CI cover the generator's true effect? | 92% activation, 93% active days, 95% paid (one SE is about 2.2 pts) |
| Estimator bias | Mean CUPED estimate minus truth over 100 seeds | -0.0008 on a 0.0228 activation effect |
| Variance reduction | Mean CUPED SE / raw SE | 0.889 on active days (about 21% less variance) |
| Peeking control | A/A, 30 daily looks, 2,000 sims | naive 28.4% false positives, mSPRT 0.9% |
| SRM detection | Generator drops 8% of treatment logs | flagged, decision INVALID (test) |
| A/A sanity | Generator with zero lift | decision not SHIP (test) |
| Power calibration | Empirical vs predicted power on the primary metric | 68% observed vs 70% predicted |

**Product metrics (once adopted by a growth team)**

- **Time to insight:** minutes from "experiment ended" to a shareable readout. Target under 10 minutes, including data refresh; the CLI readout itself takes seconds.
- **Decision error rate:** share of shipped experiments whose effect fails to replicate in a holdout or follow-up test. Target under 10%.
- **Invalid-readout catch rate:** share of experiments with an SRM or logging defect caught before a decision. Target 100% of SRM-detectable defects.
- **Peeking stops avoided:** count of experiments where naive p crossed alpha before the always-valid p did. Reported per quarter as the value of the guardrail.
- **Activation definition stability:** whether the top-ranked rule stays in the top three across consecutive monthly cohorts.

## Trade-offs and alternatives considered

| Decision | Chosen | Alternative | Why |
| --- | --- | --- | --- |
| Compute | DuckDB in-process on Parquet | Warehouse (BigQuery, Snowflake) | Zero setup, sub-second queries at the bundled scale, and the SQL ports to a warehouse dialect with small changes. The cost is a single-machine ceiling; connectors are the first roadmap item. |
| Query style | `.sql` files plus one builder | ORM or a dataframe API | Analysts can read and review SQL; only the funnel needs a builder because its CTE chain depends on step count. |
| Inference | Frequentist primary, Bayesian alongside | Bayesian only | Frequentist error rates are what stakeholders and correction methods are defined against; P(better) and expected loss answer the question PMs actually ask. Showing both makes disagreement visible instead of hiding it. |
| Sequential method | mSPRT | O'Brien-Fleming alpha spending | mSPRT needs no fixed number of looks. Alpha spending has more power when the look schedule is known and honored, which in practice it rarely is. |
| Variance reduction | CUPED, one covariate | Regression adjustment with many covariates, CUPAC | CUPED is transparent and unbiased with a single pre-period metric. Multi-covariate and ML-based adjustment can reduce more variance; they are on the roadmap behind a metric layer that can supply the covariates. |
| Correction | Holm (FWER) default, BH optional | Bonferroni, no correction | Holm is never less powerful than Bonferroni and gives the same family-wise guarantee; BH suits exploratory readouts with many secondaries. |
| Activation ranking | F1 by default | Lift | Lift favors rare, extreme thresholds that cover few users; F1 balances precision and reach, which is what an onboarding target needs. |
| Validation data | Synthetic with analytic ground truth | Public event datasets | No public product dataset ships with a known experiment effect. Synthetic data is the only way to test whether the readout recovers the truth. |

## Risks

- **Synthetic optimism.** Real event data has bots, duplicate events, identity-stitching gaps, and clock skew. Mitigation: the next release adds data-quality checks (duplicate rate, late events, unknown users) that run before any analysis.
- **Misuse of activation search.** Teams may adopt the top correlational rule as the activation metric. Mitigation: output is labelled as a shortlist; the docs require an experiment before adoption.
- **Unit mismatch.** Users are the unit, but B2B outcomes like payment happen per account. Mitigation: account-level analysis with clustered errors is on the roadmap; until then the README states the limitation.
- **False confidence from a SHIP line.** A decision string can be over-trusted. Mitigation: the decision is always printed below the evidence and is downgraded by SRM or any significant regression.
- **Scale ceiling.** DuckDB on one machine will not handle billions of events. Mitigation: warehouse connectors that push the same SQL down.

## Roadmap

**Now (v0.1, this repository)**

- Funnels, retention, stickiness, north star, activation search.
- Experiment readout with SRM, CUPED, Holm/BH, mSPRT, beta-binomial, power.
- Multi-seed ground-truth validation, CLI, Streamlit dashboard.

**Next**

- Warehouse connectors (BigQuery, Snowflake, Postgres) that run the same `.sql` through a dialect layer, plus Segment and Amplitude export readers.
- A metric layer: metrics defined once in YAML (event, filter, window, aggregation, owner) and used by the CLI, dashboard, and readout, so "activation" means the same thing everywhere.
- Data-quality checks before analysis: duplicates, late-arriving events, unknown users, assignment drift.
- Account-level analysis with cluster-robust standard errors.

**Later**

- Multi-covariate regression adjustment and CUPAC.
- Heterogeneous treatment effects by segment, with correction.
- Experiment registry: pre-registered primary metric, MDE, and duration, checked against the readout.
- Scheduled readouts posted to Slack with the decision line and SRM status.
