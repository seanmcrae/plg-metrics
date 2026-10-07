"""Beta-binomial Bayesian comparison of two conversion rates."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import betaln


@dataclass(frozen=True)
class BayesResult:
    prob_treatment_better: float
    expected_loss_treatment: float
    diff_mean: float
    diff_ci_low: float
    diff_ci_high: float


def prob_b_beats_a(alpha_a: float, beta_a: float, alpha_b: float, beta_b: float) -> float:
    """Exact P(p_B > p_A) for independent Beta posteriors with integer alpha_b.

    Closed form from Evan Miller, "Formulas for Bayesian A/B Testing":

        sum_{i=0}^{alpha_b-1} B(alpha_a + i, beta_a + beta_b)
                              / ((beta_b + i) B(1 + i, beta_b) B(alpha_a, beta_a))
    """
    if alpha_b != int(alpha_b):
        raise ValueError("alpha_b must be an integer for the closed form")
    i = np.arange(int(alpha_b), dtype=np.float64)
    log_terms = (
        betaln(alpha_a + i, beta_a + beta_b)
        - np.log(beta_b + i)
        - betaln(1 + i, beta_b)
        - betaln(alpha_a, beta_a)
    )
    return float(np.clip(np.exp(log_terms).sum(), 0.0, 1.0))


def beta_binomial(
    x_control: int,
    n_control: int,
    x_treatment: int,
    n_treatment: int,
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
    credible: float = 0.95,
    n_samples: int = 200_000,
    seed: int = 0,
) -> BayesResult:
    """Posterior summary for treatment vs control under a shared Beta prior.

    The probability to beat control is exact; the credible interval and expected
    loss use seeded Monte Carlo draws, so results are reproducible."""
    a_c, b_c = prior_alpha + x_control, prior_beta + n_control - x_control
    a_t, b_t = prior_alpha + x_treatment, prior_beta + n_treatment - x_treatment
    rng = np.random.default_rng(seed)
    diff = rng.beta(a_t, b_t, n_samples) - rng.beta(a_c, b_c, n_samples)
    tail = (1 - credible) / 2
    return BayesResult(
        prob_treatment_better=prob_b_beats_a(a_c, b_c, a_t, b_t),
        expected_loss_treatment=float(np.maximum(-diff, 0).mean()),
        diff_mean=float(diff.mean()),
        diff_ci_low=float(np.quantile(diff, tail)),
        diff_ci_high=float(np.quantile(diff, 1 - tail)),
    )
