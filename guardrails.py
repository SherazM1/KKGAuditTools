"""
Guardrails and validation helpers for the audit application.

This module stays independent of Streamlit and AI providers.
"""

from __future__ import annotations

from models import AuditImage, AuditMode, CriterionResult


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
    focused_category: str | None = None,
) -> None:
    """
    Validate audit mode configuration.
    """

    if not isinstance(mode, AuditMode):
        raise GuardrailError(
            "Invalid audit mode."
        )

    if mode is AuditMode.FOCUSED:
        if not focused_category:
            raise GuardrailError(
                "Focused audit mode requires a category."
            )

    elif focused_category is not None:
        raise GuardrailError(
            "A focused category can only be used in focused audit mode."
        )


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
    Validate logical relationships inside one model result.
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
    Validate the complete result set returned by a provider.
    """

    if not isinstance(results, list):
        raise GuardrailError(
            "Audit results must be returned as a list."
        )

    validate_result_ids(results, criteria)

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
        validate_result_logic(result)

    return results