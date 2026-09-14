"""
Criteria loading and validation for the shelf audit tool.

This module is intentionally provider-neutral.
It does not import Streamlit or any AI SDK.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CRITERIA_FILE = Path(__file__).resolve().parent / "criteria.json"

REQUIRED_FIELDS = {
    "id",
    "category",
    "applies_when",
    "check",
    "suggestion",
}

OPTIONAL_FIELDS = {
    "priority",
    "opportunity_type",
    "visual_signals",
    "fixture_types",
    "comparison_allowed",
    "brand_context_required",
}


class CriteriaError(ValueError):
    """Raised when the criteria configuration is invalid."""


def _validate_criterion(
    criterion: Any,
    index: int,
) -> dict:
    if not isinstance(criterion, dict):
        raise CriteriaError(
            f"Criterion #{index + 1} must be a JSON object."
        )

    missing_fields = REQUIRED_FIELDS - criterion.keys()

    if missing_fields:
        missing = ", ".join(sorted(missing_fields))

        raise CriteriaError(
            f"Criterion #{index + 1} is missing required fields: {missing}"
        )

    allowed_fields = REQUIRED_FIELDS | OPTIONAL_FIELDS
    unknown_fields = set(criterion.keys()) - allowed_fields

    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))

        raise CriteriaError(
            f"Criterion #{index + 1} contains unknown fields: {unknown}"
        )

    cleaned = {}

    # -------------------------------------------------
    # Required text fields
    # -------------------------------------------------

    for field in REQUIRED_FIELDS:
        value = criterion[field]

        if not isinstance(value, str):
            raise CriteriaError(
                f"Criterion #{index + 1} field '{field}' must be text."
            )

        value = value.strip()

        if not value:
            raise CriteriaError(
                f"Criterion #{index + 1} field '{field}' cannot be empty."
            )

        cleaned[field] = value

    # -------------------------------------------------
    # Optional text fields
    # -------------------------------------------------

    for field in {
        "opportunity_type",
    }:
        if field in criterion:
            value = criterion[field]

            if not isinstance(value, str):
                raise CriteriaError(
                    f"Criterion #{index + 1} field '{field}' must be text."
                )

            value = value.strip()

            if not value:
                raise CriteriaError(
                    f"Criterion #{index + 1} field '{field}' cannot be empty."
                )

            cleaned[field] = value

    # -------------------------------------------------
    # Optional list fields
    # -------------------------------------------------

    for field in {
        "visual_signals",
        "fixture_types",
    }:
        if field in criterion:
            value = criterion[field]

            if not isinstance(value, list):
                raise CriteriaError(
                    f"Criterion #{index + 1} field '{field}' must be a list."
                )

            cleaned_values = []

            for item in value:
                if not isinstance(item, str):
                    raise CriteriaError(
                        f"Criterion #{index + 1} field '{field}' "
                        "must contain only text values."
                    )

                item = item.strip()

                if not item:
                    raise CriteriaError(
                        f"Criterion #{index + 1} field '{field}' "
                        "cannot contain empty values."
                    )

                cleaned_values.append(item)

            cleaned[field] = cleaned_values

    # -------------------------------------------------
    # Optional boolean fields
    # -------------------------------------------------

    for field in {
        "comparison_allowed",
        "brand_context_required",
    }:
        if field in criterion:
            value = criterion[field]

            if not isinstance(value, bool):
                raise CriteriaError(
                    f"Criterion #{index + 1} field '{field}' "
                    "must be true or false."
                )

            cleaned[field] = value

    # -------------------------------------------------
    # Optional priority field
    # -------------------------------------------------

    if "priority" in criterion:
        value = criterion["priority"]

        if not isinstance(value, (int, float)):
            raise CriteriaError(
                f"Criterion #{index + 1} field 'priority' must be numeric."
            )

        if not 0.0 <= value <= 1.0:
            raise CriteriaError(
                f"Criterion #{index + 1} field 'priority' "
                "must be between 0.0 and 1.0."
            )

        cleaned["priority"] = float(value)

    return cleaned


def validate_criteria(criteria: Any) -> list[dict]:
    """
    Validate the complete criteria collection.

    Returns a cleaned list of criteria if valid.
    """

    if not isinstance(criteria, list):
        raise CriteriaError(
            "criteria.json must contain a JSON array."
        )

    if not criteria:
        raise CriteriaError(
            "criteria.json does not contain any criteria."
        )

    validated = []
    seen_ids = set()

    for index, criterion in enumerate(criteria):
        cleaned = _validate_criterion(
            criterion,
            index,
        )

        criterion_id = cleaned["id"]

        if criterion_id in seen_ids:
            raise CriteriaError(
                f"Duplicate criterion id found: '{criterion_id}'"
            )

        seen_ids.add(criterion_id)
        validated.append(cleaned)

    return validated


def load_criteria(
    path: Path | str | None = None,
) -> list[dict]:
    """
    Load and validate criteria from JSON.

    A custom path may be supplied for tests or future alternate criteria sets.
    """

    criteria_path = Path(path) if path else CRITERIA_FILE

    if not criteria_path.exists():
        raise FileNotFoundError(
            f"Criteria file not found: {criteria_path}"
        )

    try:
        raw_text = criteria_path.read_text(
            encoding="utf-8"
        )

    except OSError as exc:
        raise CriteriaError(
            f"Could not read criteria file: {exc}"
        ) from exc

    try:
        parsed = json.loads(raw_text)

    except json.JSONDecodeError as exc:
        raise CriteriaError(
            "criteria.json contains invalid JSON. "
            f"Line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc

    return validate_criteria(parsed)


def get_categories(
    criteria: list[dict],
) -> list[str]:
    """
    Return available criterion categories in alphabetical order.
    """

    categories = {
        criterion["category"]
        for criterion in criteria
    }

    return sorted(categories)


def filter_criteria(
    criteria: list[dict],
    *,
    category: str | None = None,
    ids: set[str] | None = None,
) -> list[dict]:
    """
    Return a subset of criteria.

    This will support future audit modes without coupling
    filtering logic to the UI.
    """

    filtered = criteria

    if category:
        filtered = [
            criterion
            for criterion in filtered
            if criterion["category"] == category
        ]

    if ids:
        filtered = [
            criterion
            for criterion in filtered
            if criterion["id"] in ids
        ]

    return filtered