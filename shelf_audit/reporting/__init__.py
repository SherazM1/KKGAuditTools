"""Provider-neutral report preparation for already-completed Shelf Audits."""

from .models import ReportMetadata, ReportOpportunity, ShelfOpportunityReport
from .report_builder import build_report

__all__ = [
    "ReportMetadata",
    "ReportOpportunity",
    "ShelfOpportunityReport",
    "build_report",
]
