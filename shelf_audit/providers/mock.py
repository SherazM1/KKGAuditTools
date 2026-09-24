"""
Mock provider for local testing.

This lets us test the complete audit pipeline
without using API keys or spending model tokens.

The mock intentionally returns predictable opportunities
that resemble the structure expected from a future AI provider.
"""

from __future__ import annotations

from ..models import AuditMode, AuditRequest
from ..opportunity import Opportunity
from .base import AuditProvider


class MockAuditProvider(AuditProvider):
    name = "mock"
    config_version = "2"

    def analyze(
        self,
        request: AuditRequest,
    ) -> list[Opportunity]:
        """
        Return predictable candidate opportunities.

        The mock does not inspect image pixels or attempt visual reasoning.

        Its purpose is to exercise:
        - criterion availability
        - confidence filtering
        - ranking
        - result limits
        - Product / Expanded request flow
        - existing execution gaps
        - unrealized opportunity types

        audit.py is responsible for final ranking and limiting.
        """

        opportunities: list[Opportunity] = []

        available_ids = {
            criterion["id"]
            for criterion in request.criteria
        }

        def add_if_available(
            criterion_id: str,
            *,
            title: str,
            evidence: str,
            recommendation: str,
            relevance: float,
            confidence: float,
            impact: float,
            actionability: float,
        ) -> None:
            if criterion_id not in available_ids:
                return

            opportunities.append(
                Opportunity(
                    criterion_id=criterion_id,
                    title=title,
                    evidence=evidence,
                    recommendation=recommendation,
                    relevance=relevance,
                    confidence=confidence,
                    impact=impact,
                    actionability=actionability,
                )
            )

        # -------------------------------------------------
        # Strong opportunities
        # -------------------------------------------------

        add_if_available(
            "dedicated_display_opportunity",
            title="Explore a dedicated display",
            evidence=(
                "The mock audit represents a case where the selected "
                "product could support a more intentional merchandising "
                "structure than standard shelf placement."
            ),
            recommendation=(
                "Evaluate an appropriately scaled dedicated display such "
                "as a PDQ, rack, sidekick, floorstand, or larger format "
                "when product volume and retail context support it."
            ),
            relevance=0.96,
            confidence=0.91,
            impact=0.94,
            actionability=0.88,
        )

        add_if_available(
            "stackable_opportunity",
            title="Use vertical stacking",
            evidence=(
                "The mock audit represents packaging that could support "
                "a stacked presentation and additional vertical presence."
            ),
            recommendation=(
                "Test a stacked arrangement to increase visual footprint "
                "and make better use of vertical merchandising space."
            ),
            relevance=0.95,
            confidence=0.90,
            impact=0.85,
            actionability=0.92,
        )

        add_if_available(
            "product_visibility_obstruction",
            title="Improve product visibility",
            evidence=(
                "The mock audit represents a case where part of the "
                "primary product presentation is obstructed."
            ),
            recommendation=(
                "Adjust product placement or fixture components so the "
                "primary package face and communication remain visible."
            ),
            relevance=0.92,
            confidence=0.89,
            impact=0.88,
            actionability=0.94,
        )

        add_if_available(
            "shelf_space_utilization",
            title="Improve shelf-space utilization",
            evidence=(
                "The mock audit represents visible merchandising space "
                "that could support a stronger product arrangement."
            ),
            recommendation=(
                "Review product facings, spacing, or fixture use to make "
                "better use of the available merchandising area."
            ),
            relevance=0.88,
            confidence=0.84,
            impact=0.82,
            actionability=0.91,
        )

        add_if_available(
            "header_messaging_opportunity",
            title="Add stronger overhead communication",
            evidence=(
                "The mock audit represents a presentation with usable "
                "space above the product or fixture."
            ),
            recommendation=(
                "Consider a header, topper, or raised graphic element to "
                "increase visibility and provide additional communication."
            ),
            relevance=0.86,
            confidence=0.82,
            impact=0.83,
            actionability=0.87,
        )

        add_if_available(
            "eye_level_messaging",
            title="Strengthen prominent messaging",
            evidence=(
                "The mock audit represents a product area that relies "
                "primarily on packaging for communication."
            ),
            recommendation=(
                "Add clear branded messaging near the product to improve "
                "visibility and communicate the main benefit quickly."
            ),
            relevance=0.84,
            confidence=0.80,
            impact=0.79,
            actionability=0.90,
        )

        add_if_available(
            "vertical_space_opportunity",
            title="Use available vertical space",
            evidence=(
                "The mock audit represents unused space above the current "
                "product presentation."
            ),
            recommendation=(
                "Evaluate stacking, a riser, header, or taller fixture "
                "configuration where the available space supports it."
            ),
            relevance=0.82,
            confidence=0.78,
            impact=0.81,
            actionability=0.85,
        )

        add_if_available(
            "facing_presentation_opportunity",
            title="Improve product facing",
            evidence=(
                "The mock audit represents multiple visible units that "
                "could be aligned more intentionally."
            ),
            recommendation=(
                "Improve facing alignment, product orientation, and "
                "grouping to create a cleaner presentation."
            ),
            relevance=0.79,
            confidence=0.77,
            impact=0.70,
            actionability=0.93,
        )

        # -------------------------------------------------
        # Expanded-context opportunities
        # -------------------------------------------------

        if request.mode is AuditMode.EXPANDED:
            add_if_available(
                "visual_separation_opportunity",
                title="Create stronger visual separation",
                evidence=(
                    "The mock Expanded audit represents a selected target "
                    "that competes visually with surrounding merchandise."
                ),
                recommendation=(
                    "Use appropriate signage, spacing, fixture structure, "
                    "or branded graphics to create a clearer target area."
                ),
                relevance=0.83,
                confidence=0.76,
                impact=0.80,
                actionability=0.81,
            )

            add_if_available(
                "cross_merch_pdq_opportunity",
                title="Explore cross-merchandising",
                evidence=(
                    "The mock Expanded audit represents surrounding retail "
                    "context that could support a related merchandising connection."
                ),
                recommendation=(
                    "Evaluate whether a tray, PDQ, or supporting signage "
                    "could create a useful cross-merchandising connection."
                ),
                relevance=0.70,
                confidence=0.67,
                impact=0.73,
                actionability=0.72,
            )

        # -------------------------------------------------
        # Existing-fixture opportunities
        # -------------------------------------------------

        add_if_available(
            "large_display_surface_utilization",
            title="Use more of the display surface",
            evidence=(
                "The mock audit represents a dedicated display with "
                "available structural or communication surfaces."
            ),
            recommendation=(
                "Use available front, side, or upper display surfaces "
                "more intentionally for branding and product communication."
            ),
            relevance=0.76,
            confidence=0.70,
            impact=0.78,
            actionability=0.80,
        )

        add_if_available(
            "display_capacity_utilization",
            title="Improve display capacity use",
            evidence=(
                "The mock audit represents a fixture that could use its "
                "available product capacity more effectively."
            ),
            recommendation=(
                "Adjust product quantity, facings, or display layout to "
                "make stronger use of the available fixture."
            ),
            relevance=0.72,
            confidence=0.68,
            impact=0.71,
            actionability=0.84,
        )

        # -------------------------------------------------
        # Lower-confidence candidates
        #
        # These intentionally help test confidence filtering.
        # -------------------------------------------------

        add_if_available(
            "digital_pdp_tie_in",
            title="Consider a digital tie-in",
            evidence=(
                "The mock audit represents a communication surface that "
                "could potentially support additional digital information."
            ),
            recommendation=(
                "Consider a QR code or digital connection when additional "
                "product education would benefit the shopper."
            ),
            relevance=0.60,
            confidence=0.60,
            impact=0.58,
            actionability=0.70,
        )

        add_if_available(
            "brand_cohesion_callouts",
            title="Strengthen messaging cohesion",
            evidence=(
                "The mock audit represents multiple communication elements "
                "that could work together more consistently."
            ),
            recommendation=(
                "Align visible graphics and benefit callouts so the "
                "presentation reads as a more cohesive branded experience."
            ),
            relevance=0.64,
            confidence=0.58,
            impact=0.67,
            actionability=0.76,
        )

        return opportunities