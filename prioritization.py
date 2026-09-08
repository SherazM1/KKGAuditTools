"""
Opportunity prioritization helpers.

This module handles:
- confidence filtering
- duplicate / overlap reduction
- diversity-friendly selection
- final top-N result selection

It stays independent of Streamlit and AI providers.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from opportunity import Opportunity, rank_opportunities


DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_SIMILARITY_THRESHOLD = 0.78


def _normalize_text(value: str) -> str:
    """
    Normalize text for lightweight similarity comparison.
    """

    value = value.lower().strip()

    value = re.sub(
        r"[^a-z0-9\s]",
        " ",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    return value


def _similarity(
    left: str,
    right: str,
) -> float:
    """
    Return a similarity score between 0.0 and 1.0.
    """

    left_normalized = _normalize_text(left)
    right_normalized = _normalize_text(right)

    if not left_normalized or not right_normalized:
        return 0.0

    return SequenceMatcher(
        None,
        left_normalized,
        right_normalized,
    ).ratio()


def opportunity_similarity(
    left: Opportunity,
    right: Opportunity,
) -> float:
    """
    Compare two opportunities using both title and recommendation.

    Recommendation similarity is weighted more heavily because
    two differently titled findings may still recommend the same action.
    """

    title_similarity = _similarity(
        left.title,
        right.title,
    )

    recommendation_similarity = _similarity(
        left.recommendation,
        right.recommendation,
    )

    return (
        title_similarity * 0.35
        + recommendation_similarity * 0.65
    )


def filter_by_confidence(
    opportunities: list[Opportunity],
    *,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> list[Opportunity]:
    """
    Remove opportunities whose confidence is below the configured threshold.
    """

    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError(
            "min_confidence must be between 0.0 and 1.0."
        )

    return [
        opportunity
        for opportunity in opportunities
        if opportunity.confidence >= min_confidence
    ]


def deduplicate_opportunities(
    opportunities: list[Opportunity],
    *,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[Opportunity]:
    """
    Remove highly similar opportunities.

    The strongest-ranked opportunity is kept when two findings overlap.
    """

    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError(
            "similarity_threshold must be between 0.0 and 1.0."
        )

    ranked = rank_opportunities(
        opportunities
    )

    selected: list[Opportunity] = []

    for candidate in ranked:

        duplicate_found = False

        for existing in selected:

            if (
                candidate.criterion_id
                == existing.criterion_id
            ):
                duplicate_found = True
                break

            similarity = opportunity_similarity(
                candidate,
                existing,
            )

            if similarity >= similarity_threshold:
                duplicate_found = True
                break

        if not duplicate_found:
            selected.append(
                candidate
            )

    return selected


def prioritize_opportunities(
    opportunities: list[Opportunity],
    *,
    max_results: int,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[Opportunity]:
    """
    Apply the complete deterministic prioritization pipeline.

    Order:
    1. confidence filter
    2. ranking
    3. duplicate / overlap reduction
    4. final top-N limit
    """

    if max_results < 1:
        raise ValueError(
            "max_results must be at least 1."
        )

    confident = filter_by_confidence(
        opportunities,
        min_confidence=min_confidence,
    )

    deduplicated = deduplicate_opportunities(
        confident,
        similarity_threshold=similarity_threshold,
    )

    ranked = rank_opportunities(
        deduplicated
    )

    return ranked[:max_results]