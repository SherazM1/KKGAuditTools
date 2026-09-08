"""
Opportunity models and ranking helpers.

An opportunity represents a useful action the audit agent identifies
from the specific scene in the image.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Opportunity:
    criterion_id: str
    title: str
    evidence: str
    recommendation: str

    relevance: float
    confidence: float
    impact: float
    actionability: float

    priority_score: float = 0.0


def calculate_priority_score(
    relevance: float,
    confidence: float,
    impact: float,
    actionability: float,
) -> float:
    """
    Calculate an opportunity priority score.

    Values are expected between 0.0 and 1.0.
    """

    values = {
        "relevance": relevance,
        "confidence": confidence,
        "impact": impact,
        "actionability": actionability,
    }

    for name, value in values.items():
        if not isinstance(value, (int, float)):
            raise ValueError(
                f"{name} must be numeric."
            )

        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"{name} must be between 0.0 and 1.0."
            )

    return (
        relevance
        * confidence
        * impact
        * actionability
    )


def rank_opportunities(
    opportunities: list[Opportunity],
) -> list[Opportunity]:
    """
    Score and rank opportunities from strongest to weakest.
    """

    for opportunity in opportunities:
        opportunity.priority_score = calculate_priority_score(
            relevance=opportunity.relevance,
            confidence=opportunity.confidence,
            impact=opportunity.impact,
            actionability=opportunity.actionability,
        )

    return sorted(
        opportunities,
        key=lambda opportunity: opportunity.priority_score,
        reverse=True,
    )


def limit_opportunities(
    opportunities: list[Opportunity],
    max_results: int,
) -> list[Opportunity]:
    """
    Return only the strongest opportunities.
    """

    if max_results < 1:
        raise ValueError(
            "max_results must be at least 1."
        )

    ranked = rank_opportunities(opportunities)

    return ranked[:max_results]