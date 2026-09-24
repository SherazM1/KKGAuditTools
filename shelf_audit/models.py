"""
Shared data models for the audit application.

These models are provider-neutral and UI-neutral.
They can be used by Streamlit, tests, mock providers,
and future AI providers.
"""

from __future__ import annotations
from .opportunity import Opportunity
from dataclasses import dataclass
from enum import Enum


class AuditMode(str, Enum):
    """
    What kind of audit is being performed.
    """

    PRODUCT = "product"
    EXPANDED = "expanded"


class AuditDepth(str, Enum):
    """
    How deeply the audit should analyze the scene.
    """

    QUICK = "quick"
    DEEP = "deep"


@dataclass
class TargetRegion:
    """
    Normalized target region used by Expanded mode.

    Coordinates are stored from 0.0 to 1.0 so the same
    selection works regardless of displayed or processed
    image resolution.
    """

    x: float
    y: float
    width: float
    height: float


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
    Legacy checklist-style result.

    Kept for compatibility with existing guardrails while
    the app transitions fully to opportunity-first results.
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
    criteria: tuple[dict, ...]

    mode: AuditMode
    depth: AuditDepth

    target_crop: AuditImage | None = None
    target_region: TargetRegion | None = None


@dataclass
class AuditResult:
    """
    Complete result returned by an audit run.
    """

    opportunities: list[Opportunity]
    mode: AuditMode
    depth: AuditDepth
    criteria_evaluated: int

    @property
    def top_opportunities(self,) -> list[Opportunity]:
        return list(
            self.opportunities
        )