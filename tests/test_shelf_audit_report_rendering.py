"""Deterministic export/preview and report rerun regression tests."""

from dataclasses import asdict
from datetime import date
from html import escape
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from pypdf import PdfReader
from streamlit.testing.v1 import AppTest

from shelf_audit.reporting import ReportMetadata, build_report
from shelf_audit.reporting.formatting import DEFAULT_LOGO_PATH, load_logo, metadata_rows
from shelf_audit.reporting.pdf_renderer import render_pdf
from shelf_audit.reporting.preview_renderer import render_preview
from shelf_audit.reporting.templates import NO_OPPORTUNITIES_TEXT
from test_shelf_audit_reporting import completed_result


def pdf_text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)


class ShelfAuditReportRenderingTests(unittest.TestCase):
    def test_counts_content_order_and_backend_exclusion(self):
        for count in (0, 1, 2, 4, 8):
            with self.subTest(count=count):
                result = completed_result(count)
                for index, opportunity in enumerate(result.opportunities):
                    opportunity.title = f"Synthetic Tide-style test opportunity {index}"
                report = build_report(result)
                before_result, before_report = asdict(result), asdict(report)
                pdf = render_pdf(report)
                text, preview = pdf_text(pdf), render_preview(report)
                self.assertTrue(pdf.startswith(b"%PDF-"))
                positions = []
                for item in report.opportunities:
                    positions.append(text.index(item.title))
                    for value in (item.title, item.evidence, item.recommendation):
                        self.assertIn(value, text)
                        self.assertIn(escape(value), preview)
                self.assertEqual(positions, sorted(positions))
                for hidden in (
                    "criterion_id", "confidence", "relevance", "impact",
                    "actionability", "priority_score", "prompt_version",
                    "provider", "internal-", "criteria_evaluated",
                ):
                    self.assertNotIn(hidden, text)
                    self.assertNotIn(hidden, preview)
                self.assertEqual(asdict(result), before_result)
                self.assertEqual(asdict(report), before_report)
                if count == 0:
                    self.assertIn(NO_OPPORTUNITIES_TEXT, text)
                    self.assertIn(NO_OPPORTUNITIES_TEXT, preview)
                if count == 2:
                    self.assertEqual(len(PdfReader(BytesIO(pdf)).pages), 1)

    def test_metadata_and_absent_values(self):
        report = build_report(completed_result(1), metadata=ReportMetadata(
            client="Test Client", brand="Test Brand", retailer="Test Retailer",
            location="Test Store", audit_date=date(2026, 10, 12),
            account_lead="Test Lead", audit_reference="test-audit",
            photo_reference="test-photo", signature="Test Signature",
            signature_date=date(2026, 10, 13),
        ))
        text, preview = pdf_text(render_pdf(report)), render_preview(report)
        for label, value in metadata_rows(report.metadata):
            self.assertIn(value, text)
            self.assertIn(value, preview)
        blank = build_report(completed_result(0))
        self.assertEqual(metadata_rows(blank.metadata), ())
        self.assertNotIn("Audit Date:", pdf_text(render_pdf(blank)))

    def test_multiline_unicode_and_markup_are_plain_content(self):
        result = completed_result(1)
        result.opportunities[0].title = 'Test <b>title</b> & "copy"'
        result.opportunities[0].evidence = "Café — shopper’s view\nSecond line <script>alert(1)</script>"
        result.opportunities[0].recommendation = "Keep 100% of text ©."
        report = build_report(result)
        text = pdf_text(render_pdf(report))
        for item in report.opportunities:
            self.assertIn(item.title, text)
            self.assertIn(item.evidence, text)
            self.assertIn(item.recommendation, text)
        preview = render_preview(report)
        self.assertIn(escape(result.opportunities[0].evidence), preview)
        self.assertNotIn("<script>", preview)

    def test_logo_asset_and_missing_or_invalid_paths(self):
        self.assertTrue(DEFAULT_LOGO_PATH.is_file())
        self.assertEqual(load_logo(), DEFAULT_LOGO_PATH.read_bytes())
        self.assertEqual(
            sha256(DEFAULT_LOGO_PATH.read_bytes()).hexdigest(),
            "099bde9accdf8f4473eaa0534a94a7b8560e34f2e71333d360acba23b5cec835",
        )
        report = build_report(completed_result(1))
        page = PdfReader(BytesIO(render_pdf(report))).pages[0]
        self.assertTrue(page.images)
        self.assertIn("data:image/png;base64,", render_preview(report))
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.png"
            invalid = Path(directory) / "invalid.png"
            invalid.write_bytes(b"not an image")
            for path in (missing, invalid, None):
                with self.subTest(path=path):
                    self.assertIsNone(load_logo(path))
                    self.assertIn(report.title, pdf_text(render_pdf(report, logo_path=path)))
                    self.assertNotIn("data:image", render_preview(report, logo_path=path))

    def test_unwired_optional_image_reference_does_not_perform_io(self):
        report = build_report(completed_result(2), image_references={1: "https://invalid.example/crop.png", 2: "missing.png"})
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("image read")):
            self.assertTrue(render_pdf(report, logo_path=None).startswith(b"%PDF-"))
            self.assertIn(report.title, render_preview(report, logo_path=None))

    def test_multipage_flow_identity_and_small_sections_stay_together(self):
        report = build_report(completed_result(8))
        pages = PdfReader(BytesIO(render_pdf(report))).pages
        self.assertGreater(len(pages), 1)
        for page in pages:
            self.assertIn(report.title, page.extract_text())
            self.assertIn(report.footer_text, page.extract_text())
        for item in report.opportunities:
            matching = [page.extract_text() for page in pages if item.title.strip() in page.extract_text()]
            self.assertEqual(len(matching), 1)
            self.assertIn(item.evidence, matching[0])
            self.assertIn(item.recommendation, matching[0])

    def test_oversized_finding_can_split_without_failure_or_lost_text(self):
        result = completed_result(1)
        result.opportunities[0].evidence = "\n".join(f"Evidence line {index:03d}." for index in range(150))
        report = build_report(result)
        pdf = render_pdf(report)
        self.assertGreater(len(PdfReader(BytesIO(pdf)).pages), 2)
        self.assertIn("Evidence line 000.", PdfReader(BytesIO(pdf)).pages[0].extract_text())
        text = pdf_text(pdf)
        for line in result.opportunities[0].evidence.splitlines():
            self.assertIn(line, text)
        self.assertIn(result.opportunities[0].recommendation, text)

    def test_deterministic_pdf_bytes(self):
        report = build_report(completed_result(2))
        self.assertEqual(render_pdf(report), render_pdf(report))

    def test_rendering_does_not_import_provider_or_orchestration(self):
        # A fresh interpreter detects transitive imports, including UI modules.
        script = '''
import sys
from shelf_audit.reporting.models import ShelfOpportunityReport
from shelf_audit.reporting.pdf_renderer import render_pdf
from shelf_audit.reporting.preview_renderer import render_preview
from shelf_audit.reporting.ui import render_report_section
render_pdf(ShelfOpportunityReport())
render_preview(ShelfOpportunityReport())
assert not any(name.startswith('shelf_audit.providers') for name in sys.modules)
assert 'shelf_audit.audit' not in sys.modules
'''
        process = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)


class ShelfAuditReportUITests(unittest.TestCase):
    def test_successful_audit_then_report_reruns_and_new_audit_reset(self):
        image_buffer = BytesIO()
        Image.new("RGB", (100, 100), "white").save(image_buffer, format="PNG")
        uploaded = Mock(name="uploaded_image")
        uploaded.name = "shelf.png"
        uploaded.type = "image/png"
        uploaded.getvalue.return_value = image_buffer.getvalue()
        first, second = completed_result(2), completed_result(1)
        app = AppTest.from_string('''
from shelf_audit.page import render
render()
''')
        with (
            patch("shelf_audit.page.st.camera_input", return_value=uploaded),
            patch("shelf_audit.page.run_audit", side_effect=[first, second]) as audit,
            patch("shelf_audit.page.OpenAIAuditProvider") as provider,
        ):
            app.run()
            app.button(key="shelf_audit_analyze").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(audit.call_count, 1)
            self.assertEqual(app.session_state["shelf_audit_completed_result"], first)
            next(button for button in app.button if button.label == "Create Report").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn(first.opportunities[1].evidence, pdf_text(app.session_state["shelf_audit_report_document"][1]))
            app.text_input(key="shelf_report_brand").set_value("Test brand")
            next(button for button in app.button if button.label == "Create Report").click().run()
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(audit.call_count, 1)
            self.assertEqual(provider.call_count, 1)
            provider.return_value.analyze.assert_not_called()
            app.button(key="shelf_audit_analyze").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(audit.call_count, 2)
            self.assertEqual(app.session_state["shelf_audit_completed_result"], second)
            self.assertNotIn("shelf_audit_report_document", app.session_state)

    def test_report_controls_retain_final_result_without_provider_calls(self):
        result = completed_result(2)
        app = AppTest.from_string('''
from shelf_audit.page import render
render()
''')
        app.session_state["shelf_audit_completed_result"] = result
        with (
            patch("shelf_audit.page.run_audit", side_effect=AssertionError("audit rerun")),
            patch("shelf_audit.page.OpenAIAuditProvider", side_effect=AssertionError("provider constructed")),
        ):
            app.run()
            self.assertEqual(len(app.exception), 0)
            app.text_input(key="shelf_report_client").set_value("Test client")
            next(button for button in app.button if button.label == "Create Report").click().run()
            self.assertEqual(len(app.exception), 0)
            preview, pdf = app.session_state["shelf_audit_report_document"]
            self.assertIn("Test client", preview)
            self.assertIn("Test client", pdf_text(pdf))
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.session_state["shelf_audit_report_document"][1], pdf)
            self.assertEqual(app.session_state["shelf_audit_completed_result"], result)
            self.assertTrue(any(element.value == "Shelf Opportunities" for element in app.subheader))

    def test_zero_findings_blank_metadata_can_create_report(self):
        app = AppTest.from_string('''
from shelf_audit.reporting.ui import render_report_section
from shelf_audit.models import AuditResult, AuditMode, AuditDepth
render_report_section(AuditResult([], AuditMode.PRODUCT, AuditDepth.DEEP, 0))
''')
        app.run()
        next(button for button in app.button if button.label == "Create Report").click().run()
        self.assertEqual(len(app.exception), 0)
        preview, pdf = app.session_state["shelf_audit_report_document"]
        self.assertIn(NO_OPPORTUNITIES_TEXT, preview)
        self.assertIn(NO_OPPORTUNITIES_TEXT, pdf_text(pdf))
        self.assertNotIn("Audit Date:", preview)


if __name__ == "__main__":
    unittest.main()
