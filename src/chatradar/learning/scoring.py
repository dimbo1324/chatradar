"""Weighted log-odds with an informative Dirichlet prior (Monroe, Colaresi, Quinn 2008,
"Fightin' Words"), as a z-score.

For a term w with counts y_t in the target class and y_b in the background, class sizes
n_t and n_b, and a prior alpha_w = alpha_0 * (y_t + y_b) / (n_t + n_b) taken from the pooled
corpus:

    delta = ln((y_t + a) / (n_t + a0 - y_t - a)) - ln((y_b + a) / (n_b + a0 - y_b - a))
    var   = 1 / (y_t + a) + 1 / (y_b + a)
    z     = delta / sqrt(var)

The prior shrinks rare terms toward the pooled rate, so a phrase seen twice cannot outrank a
phrase seen a hundred times; a positive z means the term is more typical of the target.

alpha_0 is `PRIOR_STRENGTH` at most, and never more than half of the pooled class sizes: a
prior bigger than the data would swallow it and make tiny classes look decisive.
"""

from __future__ import annotations

import math

PRIOR_STRENGTH = 500.0
"""alpha_0 for large corpora: pseudo-observations the pooled corpus contributes in total."""


def log_odds_z(
    target: int,
    background: int,
    target_total: int,
    background_total: int,
    *,
    prior_strength: float | None = None,
) -> float:
    """The z-score of one term; 0.0 when either class or the term is empty."""
    pooled_total = target_total + background_total
    if target <= 0 or target_total <= 0 or pooled_total <= 0:
        return 0.0
    if prior_strength is None:
        prior_strength = min(PRIOR_STRENGTH, pooled_total / 2)
    prior = prior_strength * (target + background) / pooled_total
    in_target = target + prior
    in_background = background + prior
    rest_target = target_total + prior_strength - in_target
    rest_background = background_total + prior_strength - in_background
    if rest_target <= 0 or rest_background <= 0:
        return 0.0
    delta = math.log(in_target / rest_target) - math.log(in_background / rest_background)
    return delta / math.sqrt(1.0 / in_target + 1.0 / in_background)
