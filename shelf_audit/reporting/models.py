"""Immutable client-facing report data; no provider or rendering dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .templates import (
    DEFAULT_FOOTER_TEXT,
    DEFAULT_REPORT_SUBTITLE,
    DEFAULT_REPORT_TITLE,
)


@dataclass(frozen=True, slots=True)
class ReportMetadata:
    """Business metadata supplied by the caller, never inferred from findings."""

    client: str | None = None
    brand: str | None = None
    retailer: str | None = None
    location: str | None = None
    audit_date: date | None = None
    account_lead: str | None = None
    audit_reference: str | None = None
    photo_reference: str | None = None
    signature: str | None = None
    signature_date: date | None = None


@dataclass(frozen=True, slots=True)
class ReportOpportunity:
    """Only the selected finding's client-facing content and optional image."""

    number: int
    title: str
    evidence: str
    recommendation: str
    image_reference: str | None = None


@dataclass(frozen=True, slots=True)
class ShelfOpportunityReport:
    """Data ready for a future renderer; an empty opportunity tuple is valid."""

    metadata: ReportMetadata = ReportMetadata()
    opportunities: tuple[ReportOpportunity, ...] = ()
    title: str = DEFAULT_REPORT_TITLE
    subtitle: str | None = DEFAULT_REPORT_SUBTITLE
    footer_text: str = DEFAULT_FOOTER_TEXT
