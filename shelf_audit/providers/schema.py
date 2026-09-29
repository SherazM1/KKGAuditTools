"""
Strict provider response schema for Shelf Audit.

This module validates raw structured AI output before it enters
the provider-neutral opportunity pipeline.

It does not call any AI API directly.
"""

from __future__ import annotations

import math
from typing import Any

from ..opportunity import Opportunity


MAX_TITLE_LENGTH = 160
MAX_EVIDENCE_LENGTH = 1200
MAX_RECOMMENDATION_LENGTH = 1200


class ProviderResponseSchemaError(ValueError):
    """
    Raised when structured provider output does not match
    the expected Shelf Audit response schema.
    """


TOP_LEVEL_FIELDS = {
    "opportunities",
}

OPPORTUNITY_FIELDS = {
    "criterion_id",
    "title",
    "evidence",
    "recommendation",
    "relevance",
    "confidence",
    "impact",
    "actionability",
}


def _validate_text(
    value: Any,
    *,
    field_name: str,
    max_length: int,
) -> str:
    """
    Validate and normalize one required text field.
    """

    if not isinstance(value, str):
        raise ProviderResponseSchemaError(
            f"'{field_name}' must be text."
        )

    cleaned = value.strip()

    if not cleaned:
        raise ProviderResponseSchemaError(
            f"'{field_name}' cannot be empty."
        )

    if len(cleaned) > max_length:
        raise ProviderResponseSchemaError(
            f"'{field_name}' is too long."
        )

    return cleaned


def _validate_score(
    value: Any,
    *,
    field_name: str,
) -> float:
    """
    Validate one finite numeric score between 0.0 and 1.0.
    """

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ProviderResponseSchemaError(
            f"'{field_name}' must be a finite number."
        )

    numeric_value = float(value)

    if not 0.0 <= numeric_value <= 1.0:
        raise ProviderResponseSchemaError(
            f"'{field_name}' must be between 0.0 and 1.0."
        )

    return numeric_value


def parse_opportunity(
    raw: Any,
) -> Opportunity:
    """
    Validate one raw opportunity object and convert it
    into the provider-neutral Opportunity model.
    """

    if not isinstance(raw, dict):
        raise ProviderResponseSchemaError(
            "Each opportunity must be an object."
        )

    unknown_fields = (
        set(raw.keys())
        - OPPORTUNITY_FIELDS
    )

    if unknown_fields:
        unknown = ", ".join(
            sorted(unknown_fields)
        )

        raise ProviderResponseSchemaError(
            "Opportunity contains unexpected fields: "
            f"{unknown}"
        )

    missing_fields = (
        OPPORTUNITY_FIELDS
        - set(raw.keys())
    )

    if missing_fields:
        missing = ", ".join(
            sorted(missing_fields)
        )

        raise ProviderResponseSchemaError(
            "Opportunity is missing required fields: "
            f"{missing}"
        )

    criterion_id = _validate_text(
        raw["criterion_id"],
        field_name="criterion_id",
        max_length=200,
    )

    title = _validate_text(
        raw["title"],
        field_name="title",
        max_length=MAX_TITLE_LENGTH,
    )

    evidence = _validate_text(
        raw["evidence"],
        field_name="evidence",
        max_length=MAX_EVIDENCE_LENGTH,
    )

    recommendation = _validate_text(
        raw["recommendation"],
        field_name="recommendation",
        max_length=MAX_RECOMMENDATION_LENGTH,
    )

    relevance = _validate_score(
        raw["relevance"],
        field_name="relevance",
    )

    confidence = _validate_score(
        raw["confidence"],
        field_name="confidence",
    )

    impact = _validate_score(
        raw["impact"],
        field_name="impact",
    )

    actionability = _validate_score(
        raw["actionability"],
        field_name="actionability",
    )

    return Opportunity(
        criterion_id=criterion_id,
        title=title,
        evidence=evidence,
        recommendation=recommendation,
        relevance=relevance,
        confidence=confidence,
        impact=impact,
        actionability=actionability,
    )


def parse_provider_response(
    raw: Any,
    *,
    max_opportunities: int,
) -> list[Opportunity]:
    """
    Validate the complete structured provider response.

    A valid empty opportunity list is allowed and represents
    a successful audit with no sufficiently grounded findings.
    """

    if (
        isinstance(max_opportunities, bool)
        or not isinstance(max_opportunities, int)
        or max_opportunities < 0
    ):
        raise ValueError(
            "max_opportunities must be a non-negative integer."
        )

    if not isinstance(raw, dict):
        raise ProviderResponseSchemaError(
            "Provider response must be a JSON object."
        )

    unknown_fields = (
        set(raw.keys())
        - TOP_LEVEL_FIELDS
    )

    if unknown_fields:
        unknown = ", ".join(
            sorted(unknown_fields)
        )

        raise ProviderResponseSchemaError(
            "Provider response contains unexpected fields: "
            f"{unknown}"
        )

    missing_fields = (
        TOP_LEVEL_FIELDS
        - set(raw.keys())
    )

    if missing_fields:
        missing = ", ".join(
            sorted(missing_fields)
        )

        raise ProviderResponseSchemaError(
            "Provider response is missing required fields: "
            f"{missing}"
        )

    opportunities_raw = raw[
        "opportunities"
    ]

    if not isinstance(
        opportunities_raw,
        list,
    ):
        raise ProviderResponseSchemaError(
            "'opportunities' must be a list."
        )

    if len(opportunities_raw) > max_opportunities:
        raise ProviderResponseSchemaError(
            "Provider returned too many opportunities."
        )

    opportunities = [
        parse_opportunity(item)
        for item in opportunities_raw
    ]

    return opportunities