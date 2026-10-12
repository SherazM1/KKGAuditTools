"""Report preparation uses completed findings without reasoning or rendering."""

from dataclasses import FrozenInstanceError, asdict
from datetime import date
import unittest
from unittest.mock import patch

from shelf_audit.models import AuditDepth, AuditMode, AuditResult
from shelf_audit.opportunity import Opportunity
from shelf_audit.reporting import ReportMetadata, build_report
from shelf_audit.reporting.templates import (
    DEFAULT_FOOTER_TEXT,
    DEFAULT_REPORT_SUBTITLE,
    DEFAULT_REPORT_TITLE,
    RECOMMENDATION_LABEL,
    WHY_LABEL,
)


def completed_result(count: int) -> AuditResult:
    return AuditResult(
        opportunities=[
            Opportunity(
                criterion_id=f"internal-{count - index}",
                title=f"  Finding {index}\n",
                evidence=f"Visible evidence {index}.",
                recommendation=f"Take action {index}.",
                relevance=0.9,
                confidence=0.8,
                impact=0.7,
                actionability=0.6,
                # Ascending scores catch accidental reranking.
                priority_score=index / max(count, 1),
            )
            for index in range(count)
        ],
        mode=AuditMode.PRODUCT,
        depth=AuditDepth.DEEP,
        criteria_evaluated=20,
    )


class ShelfAuditReportingTests(unittest.TestCase):
    def test_metadata_mapping(self):
        metadata = ReportMetadata(
            client="Client",
            brand="Brand",
            retailer="Retailer",
            location="Store 123",
            audit_date=date(2026, 10, 12),
            account_lead="Account lead",
            audit_reference="audit-123",
            photo_reference="photo.jpg",
            signature="Signed name",
            signature_date=date(2026, 10, 13),
        )
        report = build_report(
            completed_result(1), metadata=metadata,
            title="Custom title", subtitle=None, footer_text="Custom footer",
        )
        self.assertEqual(asdict(report.metadata), asdict(metadata))
        self.assertEqual(report.title, "Custom title")
        self.assertIsNone(report.subtitle)
        self.assertEqual(report.footer_text, "Custom footer")

    def test_missing_metadata_and_default_labels(self):
        report = build_report(completed_result(1))
        self.assertTrue(all(value is None for value in asdict(report.metadata).values()))
        self.assertEqual(report.title, DEFAULT_REPORT_TITLE)
        self.assertEqual(report.subtitle, DEFAULT_REPORT_SUBTITLE)
        self.assertEqual(report.footer_text, DEFAULT_FOOTER_TEXT)
        self.assertEqual(WHY_LABEL, "Why")
        self.assertEqual(RECOMMENDATION_LABEL, "Recommendation")

    def test_counts_order_and_verbatim_mapping(self):
        for count in (0, 1, 2, 4, 8, 12):
            with self.subTest(count=count):
                result = completed_result(count)
                report = build_report(result)
                self.assertEqual(len(report.opportunities), count)
                for number, (source, output) in enumerate(
                    zip(result.opportunities, report.opportunities), start=1
                ):
                    self.assertEqual(output.number, number)
                    self.assertEqual(output.title, source.title)
                    self.assertEqual(output.evidence, source.evidence)
                    self.assertEqual(output.recommendation, source.recommendation)
                    self.assertIsNone(output.image_reference)

    def test_zero_findings_is_successful_report(self):
        report = build_report(completed_result(0))
        self.assertEqual(report.opportunities, ())
        self.assertEqual(report.title, "Shelf Opportunity Report")

    def test_serialized_report_exposes_only_client_fields(self):
        report = build_report(completed_result(2))
        payload = asdict(report)
        self.assertEqual(set(payload), {
            "metadata", "opportunities", "title", "subtitle", "footer_text", "audit_photo",
        })
        self.assertEqual(set(payload["metadata"]), {
            "client", "brand", "retailer", "location", "audit_date",
            "account_lead", "audit_reference", "photo_reference", "signature",
            "signature_date",
        })
        for opportunity in payload["opportunities"]:
            self.assertEqual(set(opportunity), {
                "number", "title", "evidence", "recommendation", "image_reference",
            })

    def test_optional_images_are_associated_by_report_number(self):
        images = {1: "unwired/crop.png", 3: None}
        report = build_report(completed_result(4), image_references=images)
        self.assertEqual(
            [item.image_reference for item in report.opportunities],
            ["unwired/crop.png", None, None, None],
        )
        images[1] = "changed.png"
        self.assertEqual(report.opportunities[0].image_reference, "unwired/crop.png")

    def test_report_is_independent_and_does_not_mutate_audit(self):
        result = completed_result(2)
        before = asdict(result)
        report = build_report(result)
        self.assertEqual(asdict(result), before)
        result.opportunities[0].title = "Changed source"
        result.opportunities.clear()
        self.assertEqual(len(report.opportunities), 2)
        self.assertEqual(report.opportunities[0].title, "  Finding 0\n")
        with self.assertRaises(FrozenInstanceError):
            report.opportunities[0].title = "Changed report"
        with self.assertRaises(FrozenInstanceError):
            report.metadata.client = "Changed metadata"

    def test_report_does_not_invoke_audit_or_ranking(self):
        with (
            patch("shelf_audit.audit.run_audit", side_effect=AssertionError("audit called")),
            patch("shelf_audit.opportunity.rank_opportunities", side_effect=AssertionError("ranking called")),
            patch("shelf_audit.audit.prioritize_opportunities", side_effect=AssertionError("prioritization called")),
            patch("shelf_audit.providers.openai.OpenAIAuditProvider.analyze", side_effect=AssertionError("provider called")),
            patch("shelf_audit.providers.mock.MockAuditProvider.analyze", side_effect=AssertionError("provider called")),
        ):
            self.assertEqual(len(build_report(completed_result(2)).opportunities), 2)


if __name__ == "__main__":
    unittest.main()
