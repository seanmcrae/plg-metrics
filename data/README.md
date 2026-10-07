# Data

Everything here is SYNTHETIC. No real users, companies, or events.

| Path | Contents |
| --- | --- |
| `sample_synthetic_3k/` | Committed sample: 3,000 users, seed 7. Small enough to inspect; too small for well-powered experiment readouts. |
| `synthetic/` | Full demo dataset (20,000 users, seed 7). Not committed; create it with `make data` or `plg generate`. |

Each dataset has four files:

- `users.parquet`: `user_id`, `signup_ts`, `channel`, `plan`, `company_size`
- `events.parquet`: `user_id`, `event_name`, `event_ts`
- `assignments.parquet`: `user_id`, `experiment`, `variant`, `assigned_ts`
- `metadata.json`: generator config, observation end, and the experiment's ground-truth effects

The generator lives in `src/plg/synthetic.py`. It is deterministic for a given
config and seed. There is no third-party data, so no license terms apply beyond
this repository's MIT license.
