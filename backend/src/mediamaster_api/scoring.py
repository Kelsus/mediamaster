"""Preference scoring for the To Watch column.

Rated history = Done shows with a rating + everything in La Poubelle.
Each rated show contributes a value: 3* -> +2, 2* -> +1, 1* -> 0, poubelle -> -2.

For each feature (source, service, show_type) we compute a Bayesian-smoothed
affinity: the feature value behaves as if it started with K imaginary ratings
at the global mean, so one glowing rec from a new source is pulled toward the
mean while a consistent track record dominates the prior.

An unwatched show's predicted score starts at the global mean and is nudged by
how far each of its features' affinities deviate from it, weighted by how much
signal the feature carries (who recommended it >> where it streams >> tv/movie).
"""

from collections import defaultdict
from typing import Optional

from .models import Show, Status

SMOOTHING_K = 3
RATING_VALUES = {3: 2.0, 2: 1.0, 1: 0.0}
POUBELLE_VALUE = -2.0
FEATURE_WEIGHTS = {"source": 1.0, "service": 0.5, "show_type": 0.25}


def _norm(value: Optional[str]) -> Optional[str]:
    return value.strip().casefold() if value else None


def _rated_value(show: Show) -> Optional[float]:
    if show.status == Status.poubelle:
        return POUBELLE_VALUE
    if show.status == Status.done and show.rating in RATING_VALUES:
        return RATING_VALUES[show.rating]
    return None


def score_board(shows: list[Show]) -> None:
    """Annotate to_watch shows in place with predicted_score and score_breakdown."""
    rated = [(s, v) for s in shows if (v := _rated_value(s)) is not None]
    # Cold start: until at least one Done show is rated, keep the prior neutral —
    # a handful of poubelle entries shouldn't make the whole queue look bad
    # (their features still drag matching shows down via the affinities).
    has_positive_signal = any(s.status == Status.done for s, _ in rated)
    mean = sum(v for _, v in rated) / len(rated) if has_positive_signal else 0.0

    # sums[feature][value] = (sum of rated values, count)
    sums: dict[str, dict[str, tuple[float, int]]] = {f: defaultdict(lambda: (0.0, 0)) for f in FEATURE_WEIGHTS}
    for show, value in rated:
        for feature in FEATURE_WEIGHTS:
            key = _norm(getattr(show, feature))
            if key is not None:
                total, count = sums[feature][key]
                sums[feature][key] = (total + value, count + 1)

    def affinity(feature: str, key: str) -> tuple[float, int]:
        total, count = sums[feature].get(key, (0.0, 0))
        return (SMOOTHING_K * mean + total) / (SMOOTHING_K + count), count

    for show in shows:
        if show.status != Status.to_watch:
            continue
        score = mean
        breakdown: dict = {"base": round(mean, 3)}
        for feature, weight in FEATURE_WEIGHTS.items():
            key = _norm(getattr(show, feature))
            if key is None:
                continue
            aff, count = affinity(feature, key)
            adjustment = weight * (aff - mean)
            score += adjustment
            if count > 0:
                breakdown[feature] = {
                    "value": getattr(show, feature),
                    "affinity": round(aff, 3),
                    "adjustment": round(adjustment, 3),
                    "rated_count": count,
                }
        show.predicted_score = round(score, 4)
        show.score_breakdown = breakdown


def sort_to_watch(shows: list[Show]) -> list[Show]:
    """Descending score, then newest first, then name — via composed stable sorts."""
    ordered = sorted(shows, key=lambda s: s.name.casefold())
    ordered.sort(key=lambda s: s.created_at, reverse=True)
    ordered.sort(key=lambda s: s.predicted_score or 0.0, reverse=True)
    return ordered
