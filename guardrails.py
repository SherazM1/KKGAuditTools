"""
Guardrails and validation helpers for the audit application.

This module stays independent of Streamlit and AI providers.
"""

from __future__ import annotations

from models import AuditImage, AuditMode, CriterionResult, TargetRegion
from opportunity import Opportunity


SUPPORTED_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


class GuardrailError(ValueError):
    """Raised when audit input or output violates application rules."""


def validate_image(image: AuditImage) -> AuditImage:
    """
    Validate a normalized image before it enters the audit pipeline.
    """

    if not isinstance(image.data, bytes):
        raise GuardrailError(
            "Image data must be bytes."
        )

    if not image.data:
        raise GuardrailError(
            "Image is empty."
        )

    if image.media_type not in SUPPORTED_MEDIA_TYPES:
        raise GuardrailError(
            f"Unsupported image type: {image.media_type}"
        )

    if len(image.data) > MAX_IMAGE_BYTES:
        max_mb = MAX_IMAGE_BYTES // (1024 * 1024)

        raise GuardrailError(
            f"Image is too large. Maximum size is {max_mb} MB."
        )

    return image


def validate_mode(
    mode: AuditMode,
    target_region: TargetRegion | None = None,
) -> None:
    """
    Validate audit mode configuration.
    """

    if not isinstance(mode, AuditMode):
        raise GuardrailError(
            "Invalid audit mode."
        )

    if mode is AuditMode.EXPANDED:
        if target_region is None:
            raise GuardrailError(
                "Expanded audit mode requires a target region."
            )

        validate_target_region(
            target_region
        )

    elif target_region is not None:
        raise GuardrailError(
            "A target region can only be used in expanded audit mode."
        )


def validate_target_region(
    target_region: TargetRegion,
) -> TargetRegion:
    """
    Validate one normalized target region.

    Coordinates must remain within the 0.0 to 1.0 image space.
    """

    if not isinstance(target_region, TargetRegion):
        raise GuardrailError(
            "Target region is invalid."
        )

    values = {
        "x": target_region.x,
        "y": target_region.y,
        "width": target_region.width,
        "height": target_region.height,
    }

    for field_name, value in values.items():
        if not isinstance(value, (int, float)):
            raise GuardrailError(
                f"Target region '{field_name}' must be numeric."
            )

    if not 0.0 <= target_region.x <= 1.0:
        raise GuardrailError(
            "Target region x must be between 0.0 and 1.0."
        )

    if not 0.0 <= target_region.y <= 1.0:
        raise GuardrailError(
            "Target region y must be between 0.0 and 1.0."
        )

    if not 0.0 < target_region.width <= 1.0:
        raise GuardrailError(
            "Target region width must be greater than 0.0 and at most 1.0."
        )

    if not 0.0 < target_region.height <= 1.0:
        raise GuardrailError(
            "Target region height must be greater than 0.0 and at most 1.0."
        )

    if target_region.x + target_region.width > 1.0:
        raise GuardrailError(
            "Target region extends beyond the right edge of the image."
        )

    if target_region.y + target_region.height > 1.0:
        raise GuardrailError(
            "Target region extends beyond the bottom edge of the image."
        )

    return target_region


def validate_selected_criteria(
    criteria: list[dict],
) -> list[dict]:
    """
    Ensure the audit has at least one criterion to evaluate.
    """

    if not criteria:
        raise GuardrailError(
            "No criteria were selected for this audit."
        )

    return criteria


def validate_result_ids(
    results: list[CriterionResult],
    criteria: list[dict],
) -> list[CriterionResult]:
    """
    Prevent a model/provider from inventing criterion IDs.
    """

    allowed_ids = {
        criterion["id"]
        for criterion in criteria
    }

    for result in results:
        if result.id not in allowed_ids:
            raise GuardrailError(
                f"Unknown criterion returned: '{result.id}'"
            )

    return results


def validate_result_logic(
    result: CriterionResult,
) -> CriterionResult:
    """
    Validate logical relationships inside one criterion result.
    """

    if not isinstance(result.applies, bool):
        raise GuardrailError(
            f"Criterion '{result.id}' has invalid 'applies' value."
        )

    if result.met not in {True, False, None}:
        raise GuardrailError(
            f"Criterion '{result.id}' has invalid 'met' value."
        )

    if not result.applies and result.met is not None:
        raise GuardrailError(
            f"Criterion '{result.id}' is not applicable, "
            "so 'met' must be null."
        )

    if result.applies and result.met is None:
        raise GuardrailError(
            f"Criterion '{result.id}' applies, "
            "so 'met' must be true or false."
        )

    if not isinstance(result.evidence, str):
        raise GuardrailError(
            f"Criterion '{result.id}' evidence must be text."
        )

    if not result.evidence.strip():
        raise GuardrailError(
            f"Criterion '{result.id}' must include evidence."
        )

    if result.suggestion is not None:
        if not isinstance(result.suggestion, str):
            raise GuardrailError(
                f"Criterion '{result.id}' suggestion must be text or null."
            )

        if not result.suggestion.strip():
            raise GuardrailError(
                f"Criterion '{result.id}' suggestion cannot be empty."
            )

    if result.met is True and result.suggestion is not None:
        raise GuardrailError(
            f"Criterion '{result.id}' passed, "
            "so it should not include a corrective suggestion."
        )

    if not result.applies and result.suggestion is not None:
        raise GuardrailError(
            f"Criterion '{result.id}' is not applicable, "
            "so it should not include a suggestion."
        )

    return result


def validate_results(
    results: list[CriterionResult],
    criteria: list[dict],
) -> list[CriterionResult]:
    """
    Validate the complete criterion-result set returned by a provider.

    This is retained for compatibility with the older checklist-style
    result model.
    """

    if not isinstance(results, list):
        raise GuardrailError(
            "Audit results must be returned as a list."
        )

    validate_result_ids(
        results,
        criteria,
    )

    seen_ids = set()

    for result in results:
        if not isinstance(result, CriterionResult):
            raise GuardrailError(
                "Audit results contain an invalid result object."
            )

        if result.id in seen_ids:
            raise GuardrailError(
                f"Duplicate audit result returned for '{result.id}'."
            )

        seen_ids.add(result.id)

        validate_result_logic(
            result
        )

    return results


def validate_opportunities(
    opportunities: list[Opportunity],
    criteria: list[dict],
) -> list[Opportunity]:
    """
    Validate provider-generated opportunities before ranking.
    """

    if not isinstance(opportunities, list):
        raise GuardrailError(
            "Provider must return a list of opportunities."
        )

    allowed_ids = {
        criterion["id"]
        for criterion in criteria
    }

    seen_ids = set()

    for opportunity in opportunities:

        if not isinstance(opportunity, Opportunity):
            raise GuardrailError(
                "Provider returned an invalid opportunity object."
            )

        if opportunity.criterion_id not in allowed_ids:
            raise GuardrailError(
                f"Unknown criterion returned: "
                f"'{opportunity.criterion_id}'"
            )

        if opportunity.criterion_id in seen_ids:
            raise GuardrailError(
                f"Duplicate opportunity returned for "
                f"'{opportunity.criterion_id}'"
            )

        seen_ids.add(
            opportunity.criterion_id
        )

        if not isinstance(opportunity.title, str):
            raise GuardrailError(
                f"Opportunity '{opportunity.criterion_id}' "
                "title must be text."
            )

        if not opportunity.title.strip():
            raise GuardrailError(
                f"Opportunity '{opportunity.criterion_id}' "
                "must include a title."
            )

        if not isinstance(opportunity.evidence, str):
            raise GuardrailError(
                f"Opportunity '{opportunity.criterion_id}' "
                "evidence must be text."
            )

        if not opportunity.evidence.strip():
            raise GuardrailError(
                f"Opportunity '{opportunity.criterion_id}' "
                "must include evidence."
            )

        if not isinstance(opportunity.recommendation, str):
            raise GuardrailError(
                f"Opportunity '{opportunity.criterion_id}' "
                "recommendation must be text."
            )

        if not opportunity.recommendation.strip():
            raise GuardrailError(
                f"Opportunity '{opportunity.criterion_id}' "
                "must include a recommendation."
            )

        for field_name, value in {
            "relevance": opportunity.relevance,
            "confidence": opportunity.confidence,
            "impact": opportunity.impact,
            "actionability": opportunity.actionability,
        }.items():

            if not isinstance(value, (int, float)):
                raise GuardrailError(
                    f"{field_name} for "
                    f"'{opportunity.criterion_id}' "
                    "must be numeric."
                )

            if not 0.0 <= value <= 1.0:
                raise GuardrailError(
                    f"{field_name} for "
                    f"'{opportunity.criterion_id}' "
                    "must be between 0.0 and 1.0."
                )

    return opportunities