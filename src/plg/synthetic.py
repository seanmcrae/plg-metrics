"""Seeded generator for a SYNTHETIC B2B SaaS event stream.

Everything produced here is fictional. The generator models a product-led funnel

    signup -> create_workspace -> connect_data_source -> create_dashboard (activation)
           -> invite_teammate -> subscribe (paid)

with user segments (channel, plan, company size), a latent engagement trait that
drives drop-off and retention, and an embedded onboarding experiment
(``onboarding_v2``) whose true effect is known. Because each user's outcome
probabilities are explicit, the generator can compute the *expected* treatment
effect for the enrolled population and store it as ground truth, which the test
suite and the experiment readout use to check that the analysis recovers it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

EXPERIMENT_NAME = "onboarding_v2"
FUNNEL_STEPS = (
    "signup",
    "create_workspace",
    "connect_data_source",
    "create_dashboard",
    "invite_teammate",
    "subscribe",
)
ACTIVATION_EVENT = "create_dashboard"
ACTIVITY_EVENT = "session_start"

CHANNELS = {"organic": 0.35, "paid_search": 0.30, "referral": 0.15, "outbound": 0.20}
COMPANY_SIZES = {"1-10": 0.45, "11-50": 0.30, "51-200": 0.17, "201+": 0.08}
PLANS = {"free": 0.70, "trial": 0.30}

# Segment effects on the latent engagement trait and on step logits.
_CHANNEL_ENGAGEMENT = {"organic": 0.0, "paid_search": -0.3, "referral": 0.4, "outbound": -0.1}
_SIZE_CONNECT = {"1-10": -0.2, "11-50": 0.0, "51-200": 0.15, "201+": 0.25}
_SIZE_INVITE = {"1-10": -0.6, "11-50": 0.0, "51-200": 0.4, "201+": 0.6}
_SIZE_PAID = {"1-10": -0.3, "11-50": 0.0, "51-200": 0.3, "201+": 0.5}

_HOUR = 1.0 / 24.0


@dataclass(frozen=True)
class GeneratorConfig:
    """Knobs for the synthetic world. Defaults produce the bundled demo dataset."""

    n_users: int = 20_000
    seed: int = 7
    start: datetime = datetime(2026, 1, 5)
    signup_days: int = 84
    observation_days: int = 112
    experiment_start_day: int = 42
    treatment_share: float = 0.5
    # Additive logit lift on the connect_data_source step for onboarding_v2.
    treatment_logit_lift: float = 0.20
    # Fraction of treatment assignments silently dropped from the log (SRM bug).
    srm_drop_rate: float = 0.0
    activation_window_days: int = 14
    paid_window_days: int = 28
    active_days_window: int = 28

    @property
    def observation_end(self) -> datetime:
        return self.start + timedelta(days=self.observation_days)


@dataclass
class SyntheticDataset:
    users: pd.DataFrame
    events: pd.DataFrame
    assignments: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.users.to_parquet(out_dir / "users.parquet", index=False)
        self.events.to_parquet(out_dir / "events.parquet", index=False)
        self.assignments.to_parquet(out_dir / "assignments.parquet", index=False)
        (out_dir / "metadata.json").write_text(json.dumps(self.metadata, indent=2, default=str))


def _sigmoid(x: FloatArray) -> FloatArray:
    return 1.0 / (1.0 + np.exp(-x))


def _choice(rng: np.random.Generator, options: dict[str, float], n: int) -> npt.NDArray[Any]:
    return rng.choice(list(options), size=n, p=list(options.values()))


def _lookup(mapping: dict[str, float], keys: npt.NDArray[Any]) -> FloatArray:
    return np.array([mapping[k] for k in keys], dtype=np.float64)


@dataclass(frozen=True)
class _Delays:
    """Lognormal step delays in days. They do not depend on user traits, which keeps
    the probability of completing within a window a single constant per window."""

    workspace: tuple[float, float] = (0.3 * _HOUR, 1.0)
    connect: tuple[float, float] = (20 * _HOUR, 1.5)
    dashboard: tuple[float, float] = (30 * _HOUR, 1.3)
    invite: tuple[float, float] = (2.0, 1.0)
    paid: tuple[float, float] = (9.0, 0.8)

    def draw(self, rng: np.random.Generator, name: str, n: int) -> FloatArray:
        median, sigma = getattr(self, name)
        return rng.lognormal(np.log(median), sigma, size=n)


DELAYS = _Delays()


def _window_probabilities(cfg: GeneratorConfig, n_draws: int = 400_000) -> tuple[float, float]:
    """P(activation delay <= activation window) and P(activation + paid delay <= paid window)."""
    rng = np.random.default_rng(cfg.seed + 10_007)
    to_activation = sum(DELAYS.draw(rng, s, n_draws) for s in ("workspace", "connect", "dashboard"))
    to_paid = to_activation + DELAYS.draw(rng, "paid", n_draws)
    return (
        float(np.mean(to_activation <= cfg.activation_window_days)),
        float(np.mean(to_paid <= cfg.paid_window_days)),
    )


@dataclass(frozen=True)
class _Traits:
    z: FloatArray
    trial: FloatArray
    size_connect: FloatArray
    size_invite: FloatArray
    size_paid: FloatArray


def _step_probabilities(traits: _Traits, treated: FloatArray, lift: float) -> dict[str, FloatArray]:
    z, trial = traits.z, traits.trial
    p_workspace = _sigmoid(1.4 + 0.4 * z + 0.2 * trial)
    p_connect = _sigmoid(0.2 + 0.5 * z + 0.3 * trial + traits.size_connect + lift * treated)
    p_dashboard = _sigmoid(0.8 + 0.4 * z)
    return {
        "workspace": p_workspace,
        "connect": p_connect,
        "dashboard": p_dashboard,
        "reach_activation": p_workspace * p_connect * p_dashboard,
        "invite_if_active": _sigmoid(-0.6 + 0.4 * z + traits.size_invite),
        "invite_if_inactive": np.full_like(z, 0.03),
        "paid_if_invited": _sigmoid(-1.6 + 0.3 * z + 1.2 * trial + 0.9 + traits.size_paid),
        "paid_if_not_invited": _sigmoid(-1.6 + 0.3 * z + 1.2 * trial + traits.size_paid),
    }


def _daily_hazard_and_activity(
    z: FloatArray, activated: FloatArray, invited: FloatArray, weekend: BoolArray
) -> tuple[FloatArray, FloatArray]:
    """Per-user, per-day churn hazard and P(active | still alive), shape (n, days).

    Hazard decays with tenure (power law), which flattens retention curves the way
    real products do; activity dips on weekends."""
    n_days = weekend.shape[1]
    tenure = np.arange(1, n_days + 1, dtype=np.float64)
    base = _sigmoid(-1.6 - 0.5 * z - 1.3 * activated - 0.8 * invited)
    hazard = base[:, None] * tenure[None, :] ** -0.6
    p_active = _sigmoid(-0.2 + 0.6 * z + 0.7 * activated + 0.3 * invited)
    activity = p_active[:, None] * np.where(weekend, 0.45, 1.0)
    return hazard, activity


def _expected_active_days(
    z: FloatArray, activated: float, invited: float, weekend: BoolArray, window: int
) -> FloatArray:
    a = np.full_like(z, activated)
    i = np.full_like(z, invited)
    hazard, activity = _daily_hazard_and_activity(z, a, i, weekend[:, :window])
    survival = np.cumprod(1.0 - hazard, axis=1)
    return np.asarray((survival * activity).sum(axis=1), dtype=np.float64)


def _expected_outcomes(
    traits: _Traits,
    treated: FloatArray,
    weekend: BoolArray,
    cfg: GeneratorConfig,
    q_activation: float,
    q_paid: float,
) -> dict[str, FloatArray]:
    """Expected per-user metric values under a given assignment."""
    p = _step_probabilities(traits, treated, cfg.treatment_logit_lift)
    reach = p["reach_activation"]
    w = cfg.active_days_window
    days = {
        (a, i): _expected_active_days(traits.z, a, i, weekend, w) for a in (0, 1) for i in (0, 1)
    }
    active_days = reach * (
        p["invite_if_active"] * days[(1, 1)] + (1 - p["invite_if_active"]) * days[(1, 0)]
    ) + (1 - reach) * (
        p["invite_if_inactive"] * days[(0, 1)] + (1 - p["invite_if_inactive"]) * days[(0, 0)]
    )
    paid = (
        reach
        * q_paid
        * (
            p["invite_if_active"] * p["paid_if_invited"]
            + (1 - p["invite_if_active"]) * p["paid_if_not_invited"]
        )
    )
    return {
        "activated_14d": reach * q_activation,
        "active_days_28d": active_days,
        "paid_28d": paid,
    }


def _timestamps(base: pd.Timestamp, offsets_days: FloatArray) -> npt.NDArray[np.datetime64]:
    micros = np.round(offsets_days * 86_400e6).astype("int64")
    return np.datetime64(base.to_datetime64(), "us") + micros.astype("timedelta64[us]")


def generate(cfg: GeneratorConfig | None = None) -> SyntheticDataset:
    """Generate the synthetic dataset. Identical configs produce identical output."""
    cfg = cfg or GeneratorConfig()
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n_users
    start = pd.Timestamp(cfg.start)
    obs_days = float(cfg.observation_days)

    # --- users and segments -------------------------------------------------
    channel = _choice(rng, CHANNELS, n)
    size = _choice(rng, COMPANY_SIZES, n)
    plan = _choice(rng, PLANS, n)
    signup_day = rng.integers(0, cfg.signup_days, size=n)
    signup_hour = np.clip(rng.normal(14.0, 3.0, size=n), 0.0, 23.99)
    signup_offset = signup_day + signup_hour / 24.0

    traits = _Traits(
        z=rng.normal(0.0, 1.0, size=n) + _lookup(_CHANNEL_ENGAGEMENT, channel),
        trial=(plan == "trial").astype(np.float64),
        size_connect=_lookup(_SIZE_CONNECT, size),
        size_invite=_lookup(_SIZE_INVITE, size),
        size_paid=_lookup(_SIZE_PAID, size),
    )

    # --- experiment assignment ---------------------------------------------
    eligible = signup_day >= cfg.experiment_start_day
    treated_bool = eligible & (rng.random(n) < cfg.treatment_share)
    treated = treated_bool.astype(np.float64)

    # --- funnel progression --------------------------------------------------
    p = _step_probabilities(traits, treated, cfg.treatment_logit_lift)
    u = rng.random((n, 6))
    did_workspace = u[:, 0] < p["workspace"]
    did_connect = did_workspace & (u[:, 1] < p["connect"])
    activated = did_connect & (u[:, 2] < p["dashboard"])
    invite_p = np.where(activated, p["invite_if_active"], p["invite_if_inactive"])
    invited = u[:, 3] < invite_p
    paid_p = np.where(invited, p["paid_if_invited"], p["paid_if_not_invited"])
    paid = activated & (u[:, 4] < paid_p)

    t_workspace = signup_offset + DELAYS.draw(rng, "workspace", n)
    t_connect = t_workspace + DELAYS.draw(rng, "connect", n)
    t_dashboard = t_connect + DELAYS.draw(rng, "dashboard", n)
    invite_delay = DELAYS.draw(rng, "invite", n)
    t_invite = np.where(activated, t_dashboard + invite_delay, signup_offset + invite_delay)
    t_paid = t_dashboard + DELAYS.draw(rng, "paid", n)

    # --- daily activity ------------------------------------------------------
    horizon = cfg.observation_days
    day_index = np.arange(1, horizon + 1)
    calendar_day = signup_day[:, None] + day_index[None, :]
    weekday = (start.dayofweek + calendar_day) % 7
    weekend = weekday >= 5
    observed = calendar_day < cfg.observation_days

    hazard, activity_p = _daily_hazard_and_activity(
        traits.z, activated.astype(np.float64), invited.astype(np.float64), weekend
    )
    alive = np.cumprod(rng.random((n, horizon)) >= hazard, axis=1).astype(bool)
    active = alive & (rng.random((n, horizon)) < activity_p) & observed

    frames: list[pd.DataFrame] = []

    def emit(name: str, users: npt.NDArray[np.int64], offsets: FloatArray) -> None:
        keep = offsets < obs_days
        frames.append(
            pd.DataFrame(
                {
                    "user_id": users[keep] + 1,
                    "event_name": name,
                    "event_ts": _timestamps(start, offsets[keep]),
                }
            )
        )

    ids = np.arange(n)
    emit("signup", ids, signup_offset)
    emit("create_workspace", ids[did_workspace], t_workspace[did_workspace])
    emit("connect_data_source", ids[did_connect], t_connect[did_connect])
    emit("create_dashboard", ids[activated], t_dashboard[activated])
    emit("invite_teammate", ids[invited], t_invite[invited])
    emit("subscribe", ids[paid], t_paid[paid])
    emit(ACTIVITY_EVENT, ids, signup_offset + 1.0 / 1440.0)

    au, ad = np.nonzero(active)
    session_offset = signup_day[au] + day_index[ad] + rng.uniform(7, 21, size=au.size) / 24.0
    emit(ACTIVITY_EVENT, au, session_offset)

    # Feature usage on active days: candidates for the activation definition search.
    z_au, act_au = traits.z[au], activated[au].astype(np.float64)
    n_charts = rng.poisson(np.exp(-1.8 + 0.5 * z_au + 0.8 * act_au))
    chart_users = np.repeat(au, n_charts)
    chart_offset = np.repeat(session_offset, n_charts) + rng.uniform(0, 2, chart_users.size) / 24
    emit("add_chart", chart_users, chart_offset)
    integration = rng.random(au.size) < _sigmoid(-3.0 + 0.8 * act_au + 0.4 * z_au)
    emit("install_integration", au[integration], session_offset[integration] + 0.5 / 24)
    n_docs = rng.poisson(np.exp(-1.2 - 0.2 * z_au))
    docs_users = np.repeat(au, n_docs)
    docs_offset = np.repeat(session_offset, n_docs) + rng.uniform(0, 2, docs_users.size) / 24
    emit("view_docs", docs_users, docs_offset)

    # Pre-signup marketing pageviews: a pre-treatment covariate for CUPED.
    n_views = rng.poisson(np.exp(1.6 + 0.8 * traits.z))
    view_users = np.repeat(ids, n_views)
    view_offset = np.repeat(signup_offset, n_views) - rng.uniform(0.01, 14.0, view_users.size)
    emit("marketing_pageview", view_users, view_offset)

    events = (
        pd.concat(frames, ignore_index=True)
        .sort_values(["event_ts", "user_id"], kind="stable")
        .reset_index(drop=True)
    )
    events["user_id"] = events["user_id"].astype("int64")

    users = pd.DataFrame(
        {
            "user_id": ids + 1,
            "signup_ts": _timestamps(start, signup_offset),
            "channel": channel,
            "plan": plan,
            "company_size": size,
        }
    )

    logged = eligible & ~(treated_bool & (rng.random(n) < cfg.srm_drop_rate))
    assignments = pd.DataFrame(
        {
            "user_id": ids[logged] + 1,
            "experiment": EXPERIMENT_NAME,
            "variant": np.where(treated_bool[logged], "treatment", "control"),
            "assigned_ts": _timestamps(start, signup_offset[logged]),
        }
    )

    # --- ground truth: expected effect over the enrolled population ---------
    q_activation, q_paid = _window_probabilities(cfg)
    enrolled = _Traits(*(getattr(traits, f)[eligible] for f in traits.__dataclass_fields__))
    wk = weekend[eligible]
    ones = np.ones(int(eligible.sum()))
    as_control = _expected_outcomes(enrolled, 0 * ones, wk, cfg, q_activation, q_paid)
    as_treated = _expected_outcomes(enrolled, ones, wk, cfg, q_activation, q_paid)
    ground_truth = {
        metric: {
            "control_mean": float(as_control[metric].mean()),
            "treatment_mean": float(as_treated[metric].mean()),
            "true_effect": float((as_treated[metric] - as_control[metric]).mean()),
        }
        for metric in as_control
    }

    metadata: dict[str, Any] = {
        "synthetic": True,
        "description": "SYNTHETIC event data for a fictional B2B SaaS. Not real users.",
        "config": asdict(cfg),
        "observation_end": cfg.observation_end.isoformat(),
        "experiment": {
            "name": EXPERIMENT_NAME,
            "start": (cfg.start + timedelta(days=cfg.experiment_start_day)).isoformat(),
            "covariate": "marketing_pageview count in the 14 days before signup",
            "ground_truth": ground_truth,
        },
    }
    return SyntheticDataset(users, events, assignments, metadata)
