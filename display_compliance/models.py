"""Domain models for Display Compliance."""

from __future__ import annotations

from dataclasses import dataclass, field

@dataclass(frozen=True)
class MatchingRequirements:
    """User-confirmed attributes that must match at the positions."""
    required_attributes: tuple[str, ...] = ()
    notes: str = ""

@dataclass(frozen=True)
class ProductIdentity:
    """Expected product identity in a baseline display."""
    product_id: str
    name: str = ""
    attributes: dict[str, str] = field(default_factory=dict)
    source: str = "manual" # manual or ai
    confirmed: bool = False
    reference_side_id: str | None = None
    reference_region_id: str | None = None


@dataclass(frozen=True)
class ProductRegion:
    """Expected visual or product-placement region in a baseline display."""

    region_id: str
    bbox: tuple[int, int, int, int] | None = None
    polygon: tuple[tuple[int, int], ...] = ()
    label: str = ""
    visual_signature: str | None = None
    expected_product_id: str | None = None
    section_id: str | None = None
    required_occupied: bool = True

@dataclass(frozen=True)
class DisplaySection:
    """Optional organizational area within one display side"""

    section_id: str
    name: str
    bbox: tuple[int, int, int, int] | None = None
    polygon: tuple[tuple[int, int], ...] = ()

@dataclass(frozen=True)
class DisplaySide:
    """One photographed side with its own reference and expected positions."""
    side_id: str
    name: str
    reference_filename: str
    reference_width: int
    reference_height: int
    reference_image_sha256: str = ""
    display_polygon: tuple[tuple[int, int], ...] = ()
    sections: list[DisplaySection] = field(default_factory=list)
    regions: list[ProductRegion] = field(default_factory=list)


@dataclass(frozen=True)
class DisplayBaseline:
    """Display reference configuration; approval is in a next step."""

    baseline_id: str
    name: str
    reference_filename: str
    reference_width: int
    reference_height: int
    regions: list[ProductRegion] = field(default_factory=list)
    schema_version: int = 2
    revision: int = 1
    status: str = "draft" # draft or approved
    category: str = "other"
    matching_requirements: MatchingRequirements = field(default_factory=MatchingRequirements)
    products: list[ProductIdentity] = field(default_factory=list)
    sides: list[DisplaySide] = field(default_factory=list)



@dataclass(frozen=True)
class InspectionIssue:
    """Future-compatible record of a display inspection issue."""

    region_id: str
    issue_type: str
    confidence: float
    message: str


@dataclass(frozen=True)
class InspectionResult:
    """Future-compatible result for an inspection image."""

    status: str
    confidence: float
    issues: list[InspectionIssue] = field(default_factory=list)

