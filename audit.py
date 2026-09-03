"""
Audit orchestration.

This module coordinates:
- mode configuration
- criteria selection
- guardrails
- provider execution
- opportunity ranking

It does not import Streamlit or any specific AI SDK.
"""

from __future__ import annotations

from audit_modes import get_mode_config
from guardrails import (
    validate_image,
    validate_mode,
    validate_selected_criteria,
)
from models import AuditMode, AuditRequest, AuditResult
from opportunity import Opportunity, limit_opportunities


def run_audit(
    *,
    image,
    criteria: list[dict],
    mode: AuditMode,
    provider,
    focused_category: str | None = None,
) -> AuditResult:
    """
    Run one audit through the provider-neutral pipeline.
    """

    validate_image(image)

    validate_mode(
        mode,
        focused_category=focused_category,
    )

    validate_selected_criteria(criteria)

    mode_config = get_mode_config(mode)

    request = AuditRequest(
        image=image,
        criteria=criteria,
        mode=mode,
        focused_category=focused_category,
    )

    opportunities = provider.analyze(request)

    if not isinstance(opportunities, list):
        raise ValueError(
            "Provider must return a list of opportunities."
        )

    for opportunity in opportunities:
        if not isinstance(opportunity, Opportunity):
            raise ValueError(
                "Provider returned an invalid opportunity object."
            )

    ranked = limit_opportunities(
        opportunities,
        max_results=mode_config.max_opportunities,
    )

    return AuditResult(
        opportunities=ranked,
        mode=mode,
        criteria_evaluated=len(criteria),
    )