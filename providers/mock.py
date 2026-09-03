"""
Mock provider for local testing.

This lets us test the complete audit pipeline
without using API keys or spending model tokens.

The mock intentionally returns predictable opportunities
that resemble the structure expected from a future AI provider.
"""

from __future__ import annotations

from models import AuditRequest
from opportunity import Opportunity
from providers.base import AuditProvider


class MockAuditProvider(AuditProvider):
    name = "mock"

    def analyze(
        self,
        request: AuditRequest,
    ) -> list[Opportunity]:
        """
        Return predictable candidate opportunities.

        audit.py is responsible for ranking and limiting
        the final results based on audit mode.
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
                )
            )

        add_if_available(
            "stackable_opportunity",
            title="Use vertical stacking",
            evidence=(
                "The product packaging appears suitable for a "
                "stacked presentation with additional vertical presence."
            ),
            recommendation=(
                "Test a stacked arrangement to increase visual footprint "
                "and make better use of vertical shelf space."
            ),
            relevance=0.95,
            confidence=0.90,
            impact=0.85,
        )

        add_if_available(
            "eye_level_messaging",
            title="Strengthen eye-level messaging",
            evidence=(
                "The shelf area appears to rely primarily on product "
                "packaging for communication."
            ),
            recommendation=(
                "Add clear branded messaging near eye level to improve "
                "visibility and communicate the main benefit quickly."
            ),
            relevance=0.90,
            confidence=0.85,
            impact=0.80,
        )

        add_if_available(
            "shelf_space_utilization",
            title="Improve shelf-space utilization",
            evidence=(
                "The visible shelf area may support a more intentional "
                "product arrangement or stronger facing strategy."
            ),
            recommendation=(
                "Review product facings and spacing to use the available "
                "shelf area more effectively."
            ),
            relevance=0.78,
            confidence=0.78,
            impact=0.72,
        )

        add_if_available(
            "riser_additional_messaging",
            title="Consider a branded riser",
            evidence=(
                "The product presentation appears to have limited raised "
                "messaging above the primary shelf position."
            ),
            recommendation=(
                "Consider a branded riser to add visual height and create "
                "additional communication space."
            ),
            relevance=0.74,
            confidence=0.72,
            impact=0.76,
        )

        add_if_available(
            "brand_cohesion_callouts",
            title="Improve benefit communication",
            evidence=(
                "The presentation may benefit from clearer secondary "
                "messaging beyond the packaging itself."
            ),
            recommendation=(
                "Add concise brand-aligned benefit or result callouts that "
                "can be understood quickly from the aisle."
            ),
            relevance=0.71,
            confidence=0.70,
            impact=0.74,
        )

        add_if_available(
            "digital_pdp_tie_in",
            title="Add a digital tie-in",
            evidence=(
                "There is an opportunity to extend the in-store experience "
                "with additional product information."
            ),
            recommendation=(
                "Consider a QR code or similar digital element that connects "
                "the shopper to a relevant product page or supporting content."
            ),
            relevance=0.60,
            confidence=0.65,
            impact=0.58,
        )

        add_if_available(
            "cross_merch_pdq_opportunity",
            title="Explore cross-merchandising",
            evidence=(
                "The display may benefit from stronger visual connection "
                "to complementary products or adjacent categories."
            ),
            recommendation=(
                "Evaluate whether a tray, PDQ, or supporting signage could "
                "connect complementary products and strengthen the story."
            ),
            relevance=0.58,
            confidence=0.60,
            impact=0.66,
        )

        return opportunities