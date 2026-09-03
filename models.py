"""
Shared data models for the audit application.

These models are provider-neutral and UI-neutral.
They can be used by Streamlit, tests, mock providers,
and future AI providers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AuditMode(str, Enum):
    QUICK = "quick"
    FULL = "full"
    FOCUSED = "focused"


@dataclass
class AuditImage:
    """
    Normalized image passed into the audit pipeline.
    """

    data: bytes
    media_type: str
    filename: str | None = None
    source: str | None = None


@dataclass
class CriterionResult:
    """
    Result returned for one audit criterion.
    """

    id: str
    applies: bool
    met: bool | None
    evidence: str
    suggestion: str | None = None


@dataclass
class AuditRequest:
    """
    Complete request sent through the audit pipeline.
    """

    image: AuditImage
    criteria: list[dict]
    mode: AuditMode
    focused_category: str | None = None


@dataclass
class AuditResult:
    """
    Complete result returned by an audit run.
    """

    opportunities: list
    mode: AuditMode
    criteria_evaluated: int

    @property
    def top_opportunities(self) -> list:
        return self.opportunities