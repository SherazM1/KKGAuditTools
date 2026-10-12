"""Prepare a report from a completed audit without invoking audit reasoning."""

from __future__ import annotations

from collections.abc import Mapping

from ..models import AuditResult
from .models import ReportMetadata, ReportOpportunity, ShelfOpportunityReport
from .templates import (
    DEFAULT_FOOTER_TEXT,
    DEFAULT_REPORT_SUBTITLE,
    DEFAULT_REPORT_TITLE,
)


def build_report(
    result: AuditResult,
    *,
    metadata: ReportMetadata | None = None,
    image_references: Mapping[int, str | None] | None = None,
    title: str = DEFAULT_REPORT_TITLE,
    subtitle: str | None = DEFAULT_REPORT_SUBTITLE,
    footer_text: str = DEFAULT_FOOTER_TEXT,
    audit_photo: bytes | None = None,
) -> ShelfOpportunityReport:
    """Copy final findings verbatim in order, numbered starting at one.

    Image references are opaque paths/identifiers keyed by the one-based report
    number. They are not loaded or generated here. Missing entries remain None.
    The input audit and its opportunities are never retained or mutated.
    Optional original upload bytes are carried unchanged, without image analysis.
    """
    opportunities = tuple(
        ReportOpportunity(
            number=number,
            title=opportunity.title,
            evidence=opportunity.evidence,
            recommendation=opportunity.recommendation,
            image_reference=(
                image_references.get(number)
                if image_references is not None
                else None
            ),
        )
        for number, opportunity in enumerate(result.opportunities, start=1)
    )
    return ShelfOpportunityReport(
        metadata=metadata if metadata is not None else ReportMetadata(),
        opportunities=opportunities,
        title=title,
        subtitle=subtitle,
        footer_text=footer_text,
        audit_photo=audit_photo,
    )
