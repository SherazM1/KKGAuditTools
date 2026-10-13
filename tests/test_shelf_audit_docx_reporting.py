"""Editable report content, original-photo handling, and provider-free UI tests."""

from dataclasses import asdict
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from docx import Document
from docx.text.paragraph import Paragraph
from docx.oxml.ns import qn
from PIL import Image
from streamlit.testing.v1 import AppTest

from shelf_audit.reporting import ReportMetadata, build_report
from shelf_audit.reporting.docx_renderer import (
    LAYOUT_PRESETS, MIN_BODY_FONT_SIZE, PHOTO_MAX_WIDTH, PHOTO_MAX_HEIGHT,
    estimate_report_height, render_docx, select_layout,
    photo_box_width, FRAME_WIDTH, FRAME_HEIGHT, FRAME_X, FRAME_Y, HEADER_TOP_MARGIN,
)
from shelf_audit.reporting.formatting import DEFAULT_LOGO_PATH
from shelf_audit.reporting.formatting import BLUE
from shelf_audit.reporting.templates import NO_OPPORTUNITIES_TEXT
from test_shelf_audit_reporting import completed_result


def photo_bytes(size=(600, 300), color="red", image_format="PNG"):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    return output.getvalue()


def docx_text(data):
    doc = Document(BytesIO(data))
    paragraphs = []
    # Preserve visible body order when the first finding is inside a table.
    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            paragraphs.append(block)
        else:
            for row in block.rows:
                for cell in row.cells:
                    paragraphs.extend(cell.paragraphs)
    for section in doc.sections:
        paragraphs.extend(section.header.paragraphs)
        paragraphs.extend(section.footer.paragraphs)
        for table in section.header.tables:
            for row in table.rows:
                for cell in row.cells:
                    paragraphs.extend(cell.paragraphs)
    return "\n".join(p.text for p in paragraphs)


def media_bytes(data):
    with ZipFile(BytesIO(data)) as package:
        return [package.read(name) for name in package.namelist() if name.startswith("word/media/")]


class ShelfAuditDocxTests(unittest.TestCase):
    def test_page_anchor_is_fixed_and_independent_from_body_flow(self):
        for count in (0, 1, 2, 3, 4, 8):
            for size in ((300, 900), (900, 300)):
                with self.subTest(count=count, size=size):
                    report = build_report(completed_result(count), audit_photo=photo_bytes(size))
                    doc = Document(BytesIO(render_docx(report)))
                    self.assertEqual(len(doc.tables), 0)
                    self.assertEqual(len(doc.inline_shapes), 0)
                    anchors = doc.element.xpath("//wp:anchor")
                    self.assertEqual(len(anchors), 1)
                    anchor = anchors[0]
                    for axis, inches in (("H", FRAME_X), ("V", FRAME_Y)):
                        position = anchor.find(qn("wp:position" + axis))
                        self.assertEqual(position.get("relativeFrom"), "page")
                        self.assertAlmostEqual(int(position.find(qn("wp:posOffset")).text) / 914400, inches)
                    extent = anchor.find(qn("wp:extent"))
                    self.assertAlmostEqual(int(extent.get("cx")) / 914400, 2.7)
                    self.assertAlmostEqual(int(extent.get("cy")) / 914400, 3.2)
                    self.assertEqual((FRAME_X, FRAME_Y), (5.60, 0.35))
                    # Include the outer half of the unchanged 1.5pt stroke.
                    half_stroke = 0.75 / 72
                    section = doc.sections[0]
                    self.assertGreaterEqual(FRAME_X - half_stroke, 0)
                    self.assertGreaterEqual(FRAME_Y - half_stroke, 0)
                    self.assertLessEqual(FRAME_X + FRAME_WIDTH + half_stroke, section.page_width.inches)
                    self.assertLessEqual(FRAME_Y + FRAME_HEIGHT + half_stroke, section.page_height.inches)
                    self.assertLess(FRAME_Y, section.top_margin.inches)
                    self.assertEqual(anchor.find(qn("wp:wrapSquare")).get("wrapText"), "left")
                    self.assertEqual(anchor.get("distT"), "0")
                    self.assertEqual(anchor.get("distB"), "0")
                    outline = doc.element.xpath("//pic:spPr/a:ln")[0]
                    self.assertEqual(int(outline.get("w")) / 12700, 1.5)
                    self.assertEqual(outline.find(qn("a:solidFill")).find(qn("a:srgbClr")).get("val"), "141638")
                    for item in report.opportunities:
                        for value in (item.title, item.evidence, item.recommendation):
                            self.assertIn(value, "\n".join(p.text for p in doc.paragraphs))
                    self.assertTrue(doc.paragraphs[0]._p.xpath(".//wp:anchor"))
                    for p in doc.paragraphs[3:]:
                        self.assertFalse(p._p.xpath(".//wp:anchor"))

    def test_image_orientation_does_not_change_opportunity_spacing_or_estimates(self):
        for count in (2, 3, 4):
            reports = [build_report(completed_result(count), audit_photo=photo_bytes(size)) for size in ((300, 900), (900, 300))]
            self.assertEqual(estimate_report_height(reports[0], select_layout(reports[0])), estimate_report_height(reports[1], select_layout(reports[1])))
            documents = [Document(BytesIO(render_docx(report))) for report in reports]
            for first, second in zip(documents[0].paragraphs[3:], documents[1].paragraphs[3:]):
                self.assertEqual(first.text, second.text)
                self.assertEqual(first._p.pPr.xml, second._p.pPr.xml)

    def test_count_typography_and_page_distribution_ignore_image(self):
        for count, expected_size in ((1, 11.5), (2, 11.5), (3, 11), (4, 10.5), (8, 10)):
            report = build_report(completed_result(count))
            layout = select_layout(report)
            self.assertEqual(layout.body_size, expected_size)
            for image in (None, photo_bytes((300, 900)), photo_bytes((900, 300)), b"invalid"):
                self.assertEqual(select_layout(build_report(completed_result(count), audit_photo=image)), layout)
            result = completed_result(count)
            result.opportunities[0].evidence = "Long unchanged wording. " * 200
            long_layout = select_layout(build_report(result))
            self.assertEqual(long_layout.body_size, layout.body_size)
            self.assertLessEqual(long_layout.section_spacing, layout.section_spacing)
            self.assertLessEqual(long_layout.signature_spacing, layout.signature_spacing)
        for layout in LAYOUT_PRESETS:
            self.assertGreaterEqual(layout.body_size, 10)
            self.assertEqual(layout.margin, 0.65)
        two = select_layout(build_report(completed_result(2)))
        four = select_layout(build_report(completed_result(4)))
        self.assertGreater(two.section_spacing, four.section_spacing + 50)
        self.assertGreater(two.signature_spacing, four.signature_spacing + 100)
        for count in (1, 2, 3, 4, 8):
            report = build_report(completed_result(count))
            doc = Document(BytesIO(render_docx(report)))
            layout = select_layout(report)
            for item in report.opportunities:
                paragraph = next(p for p in doc.paragraphs if p.text == item.evidence)
                self.assertEqual(paragraph.runs[0].font.size.pt, layout.body_size)
            signature = next(p for p in doc.paragraphs if p.text.startswith("Signature:"))
            self.assertAlmostEqual(signature.paragraph_format.space_before.pt, layout.signature_spacing, delta=0.03)

    def test_header_sizes_dividers_and_signature_only(self):
        doc = Document(BytesIO(render_docx(build_report(completed_result(3)))))
        title, subtitle = doc.sections[0].header.tables[0].cell(0, 1).paragraphs
        self.assertEqual(title.runs[0].font.size.pt, 22)
        self.assertEqual(subtitle.runs[0].font.size.pt, 11)
        table = doc.sections[0].header.tables[0]
        self.assertLessEqual(doc.sections[0].left_margin.inches + sum(column.width.inches for column in table.columns), FRAME_X - 0.15 + 0.001)
        logo_extent = doc.sections[0].header._element.xpath(".//wp:extent")[0]
        self.assertAlmostEqual(int(logo_extent.get("cx")) / 914400, 0.88)
        self.assertIn(DEFAULT_LOGO_PATH.read_bytes(), media_bytes(render_docx(build_report(completed_result(3)))))
        headings = [p for p in doc.paragraphs if p.text.startswith(("01  ", "02  ", "03  "))]
        self.assertIsNone(headings[0]._p.pPr.find(qn("w:pBdr")))
        for heading in headings[1:]:
            border = heading._p.pPr.find(qn("w:pBdr")).find(qn("w:top"))
            self.assertEqual(border.get(qn("w:color")), "141638")
            self.assertEqual(border.get(qn("w:sz")), "4")
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertNotIn("Approved By", text)
        self.assertIn("Signature:  ______________________________", text)
        self.assertIn("Date:  __________________", text)

    def test_missing_invalid_photo_omits_frame_without_empty_columns(self):
        for photo in (None, b"invalid"):
            doc = Document(BytesIO(render_docx(build_report(completed_result(2), audit_photo=photo))))
            self.assertEqual(len(doc.tables), 0)
            self.assertIn("Visible evidence 0.", "\n".join(p.text for p in doc.paragraphs))

    def test_gotham_faces_in_expected_roles_and_no_embedded_fonts(self):
        result = completed_result(1)
        report = build_report(result, metadata=ReportMetadata(
            client="Test Client", retailer="Test Retailer", location="Test Location",
        ))
        data = render_docx(report)
        doc = Document(BytesIO(data))
        self.assertEqual(doc.styles["Normal"].font.name, "Gotham-Book")

        def assert_font(run, family):
            self.assertEqual(run.font.name, family)
            for script in ("ascii", "hAnsi", "eastAsia", "cs"):
                self.assertEqual(run._r.rPr.rFonts.get(qn(f"w:{script}")), family)

        title, subtitle = doc.sections[0].header.tables[0].cell(0, 1).paragraphs
        assert_font(title.runs[0], "Gotham-Bold")
        self.assertEqual(subtitle.text, "ACTIONABLE MERCHANDISING RECOMMENDATIONS")
        assert_font(subtitle.runs[0], "Gotham-Medium")
        self.assertEqual(str(subtitle.runs[0].font.color.rgb), BLUE.lstrip("#"))
        for paragraph in doc.paragraphs[:3]:
            assert_font(paragraph.runs[0], "Gotham-Medium")
            assert_font(paragraph.runs[1], "Gotham-Book")
        heading = next(p for p in doc.paragraphs if p.text.startswith("01  "))
        for run in heading.runs:
            assert_font(run, "Gotham-Bold")
        for label in ("WHY", "RECOMMENDATION"):
            paragraph = next(p for p in doc.paragraphs if p.text == label)
            assert_font(paragraph.runs[0], "Gotham-Medium")
        for text in (result.opportunities[0].evidence, result.opportunities[0].recommendation):
            paragraph = next(p for p in doc.paragraphs if p.text == text)
            assert_font(paragraph.runs[0], "Gotham-Book")
        for label in ("Signature:", "Date:"):
            paragraph = next(p for p in doc.paragraphs if p.text.startswith(label))
            assert_font(paragraph.runs[0], "Gotham-Medium")
            assert_font(paragraph.runs[1], "Gotham-Book")
        assert_font(doc.sections[0].footer.paragraphs[0].runs[0], "Gotham-Book")
        with ZipFile(BytesIO(data)) as package:
            self.assertFalse(any(name.startswith("word/fonts/") or name.endswith((".ttf", ".odttf")) for name in package.namelist()))

    def test_footer_year_is_calculated_at_render_time_without_mutating_report(self):
        report = build_report(completed_result(1))
        before = asdict(report)
        current_year = datetime.now(ZoneInfo("America/Chicago")).year
        self.assertIn(f"Generated by Kendal King © {current_year}", docx_text(render_docx(report)))
        for year in (2031, 2040):
            with self.subTest(year=year), patch("shelf_audit.reporting.docx_renderer.datetime") as clock:
                clock.now.return_value = datetime(year, 1, 1, tzinfo=ZoneInfo("America/Chicago"))
                self.assertIn(f"Generated by Kendal King © {year}", docx_text(render_docx(report)))
                clock.now.assert_called_once_with(ZoneInfo("America/Chicago"))
        self.assertEqual(asdict(report), before)

    def test_counts_order_verbatim_content_and_immutable_inputs(self):
        for count in (0, 1, 2, 3, 4, 8):
            with self.subTest(count=count):
                result = completed_result(count)
                report = build_report(result, audit_photo=photo_bytes())
                before_result, before_report = asdict(result), asdict(report)
                data = render_docx(report)
                text = docx_text(data)
                positions = []
                for item in report.opportunities:
                    positions.append(text.index(item.title))
                    for value in (item.title, item.evidence, item.recommendation):
                        self.assertIn(value, text)
                        self.assertEqual(text.count(value), 1)
                self.assertEqual(positions, sorted(positions))
                for hidden in (
                    "criterion_id", "confidence", "relevance", "impact", "actionability",
                    "priority_score", "provider", "prompt_version", "internal-",
                ):
                    self.assertNotIn(hidden, text)
                self.assertEqual(asdict(result), before_result)
                self.assertEqual(asdict(report), before_report)
                self.assertIn(report.footer_text, text)
                self.assertIn(report.title, text)
                self.assertIn(report.subtitle.upper(), text)
                self.assertNotIn("Approved By", text)
                self.assertIn("Signature:  ______________________________", text)
                self.assertIn("Date:  __________________", text)
                if count == 0:
                    self.assertIn(NO_OPPORTUNITIES_TEXT, text)

    def test_only_three_metadata_fields_rendered_even_if_others_supplied(self):
        metadata = ReportMetadata(
            client="Test Client", retailer="Test Retailer", location="Test Location",
            brand="Hidden Brand", audit_date=date(2026, 10, 12),
            account_lead="Hidden Lead", audit_reference="Hidden Audit",
            photo_reference="Hidden Photo", signature="Hidden Signature",
            signature_date=date(2026, 10, 13),
        )
        text = docx_text(render_docx(build_report(completed_result(1), metadata=metadata)))
        for value in (metadata.client, metadata.retailer, metadata.location):
            self.assertIn(value, text)
        for value in ("Hidden", "2026-10-12", "2026-10-13", "Account Lead", "Audit Date"):
            self.assertNotIn(value, text)
        blank = docx_text(render_docx(build_report(completed_result(0))))
        for label in ("Client:", "Retailer:", "Location:"):
            self.assertIn(label, blank)
        self.assertNotIn("None", blank)

    def test_literal_markup_unicode_and_whitespace_are_preserved(self):
        result = completed_result(1)
        result.opportunities[0].title = "  <b>Test title</b>  "
        result.opportunities[0].evidence = "Café — shopper’s view\nSecond line <script>literal</script>"
        result.opportunities[0].recommendation = "Keep 100% of text ©.\tNext step."
        report = build_report(result)
        text = docx_text(render_docx(report))
        for item in report.opportunities:
            for value in (item.title, item.evidence, item.recommendation):
                self.assertIn(value, text)

    def test_original_photo_bytes_and_bounded_aspect_ratio(self):
        for size, image_format in (((900, 300), "PNG"), ((300, 900), "PNG"), ((400, 300), "JPEG")):
            with self.subTest(size=size, image_format=image_format):
                photo = photo_bytes(size, image_format=image_format)
                report = build_report(completed_result(2), audit_photo=photo)
                self.assertIs(report.audit_photo, photo)
                data = render_docx(report)
                self.assertIn(photo, media_bytes(data))
                self.assertIn(DEFAULT_LOGO_PATH.read_bytes(), media_bytes(data))
                doc = Document(BytesIO(data))
                extent = doc.element.xpath("//wp:anchor/wp:extent")[0]
                fill = doc.element.xpath("//wp:anchor//a:fillRect")[0]
                width = int(extent.get("cx")) / 914400 * (1 - (int(fill.get("l")) + int(fill.get("r"))) / 100000)
                height = int(extent.get("cy")) / 914400 * (1 - (int(fill.get("t")) + int(fill.get("b"))) / 100000)
                self.assertAlmostEqual(width / height, size[0] / size[1], delta=0.0002)
                self.assertLessEqual(width, PHOTO_MAX_WIDTH + 0.0001)
                self.assertLessEqual(height, PHOTO_MAX_HEIGHT + 0.0001)
                self.assertEqual(fill.get("l"), fill.get("r"))
                self.assertEqual(fill.get("t"), fill.get("b"))

    def test_missing_invalid_photo_and_missing_logo_degrade_gracefully(self):
        with tempfile.TemporaryDirectory() as directory:
            for photo in (None, b"", b"not an image"):
                with self.subTest(photo=photo):
                    data = render_docx(build_report(completed_result(1), audit_photo=photo), logo_path=Path(directory) / "missing.png")
                    self.assertIn("Visible evidence 0.", docx_text(data))
                    self.assertEqual(media_bytes(data), [])
                    self.assertFalse(Document(BytesIO(data)).element.xpath("//wp:anchor"))

    def test_short_fixtures_fit_estimated_one_page_without_forced_breaks(self):
        for count, size in ((count, size) for count in (1, 2, 3, 4) for size in ((300, 900), (900, 300))):
            with self.subTest(count=count, size=size):
                report = build_report(completed_result(count), audit_photo=photo_bytes(size))
                layout = select_layout(report)
                available = (11 - HEADER_TOP_MARGIN - layout.margin) * 72 - 24
                self.assertLessEqual(estimate_report_height(report, layout), available)
                doc = Document(BytesIO(render_docx(report)))
                self.assertFalse(doc.element.xpath('//w:br[@w:type="page"]'))
                self.assertEqual(len(doc.sections), 1)
                self.assertGreaterEqual(doc.styles["Normal"].font.size.pt, MIN_BODY_FONT_SIZE)

    def test_dynamic_tuning_and_long_report_can_flow_without_truncation(self):
        result = completed_result(3)
        for opportunity in result.opportunities:
            opportunity.evidence = "Synthetic merchandising evidence with clear test wording. " * 6
            opportunity.recommendation = "Synthetic recommendation for testing report layout only. " * 4
        report = build_report(result, audit_photo=photo_bytes())
        self.assertNotEqual(select_layout(report), LAYOUT_PRESETS[0])
        self.assertGreaterEqual(select_layout(report).body_size, MIN_BODY_FONT_SIZE)
        result = completed_result(8)
        for index, item in enumerate(result.opportunities):
            item.evidence = f"Long test section {index}. " * 100
        report = build_report(result, audit_photo=photo_bytes())
        layout = select_layout(report)
        self.assertGreater(estimate_report_height(report, layout), (11 - HEADER_TOP_MARGIN - layout.margin) * 72)
        data = render_docx(report)
        text = docx_text(data)
        for item in report.opportunities:
            self.assertIn(item.evidence, text)
            self.assertIn(item.recommendation, text)
        doc = Document(BytesIO(data))
        approval = next(p for p in doc.paragraphs if p.text.startswith("Signature:"))
        self.assertTrue(approval.paragraph_format.keep_with_next)
        self.assertTrue(approval.paragraph_format.keep_together)

    def test_docx_ui_does_not_import_audit_provider_pdf_or_preview(self):
        script = '''
import sys
from shelf_audit.reporting.models import ShelfOpportunityReport
from shelf_audit.reporting.docx_renderer import render_docx
from shelf_audit.reporting.ui import render_report_section
render_docx(ShelfOpportunityReport())
assert not any(name.startswith('shelf_audit.providers') for name in sys.modules)
for name in ('shelf_audit.audit', 'shelf_audit.reporting.pdf_renderer', 'shelf_audit.reporting.preview_renderer'):
    assert name not in sys.modules, name
'''
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class ShelfAuditDocxUITests(unittest.TestCase):
    def test_three_fields_one_download_no_preview_and_no_provider_calls(self):
        import streamlit as st
        result = completed_result(2)
        app = AppTest.from_string('''
from shelf_audit.page import render
render()
''')
        app.session_state["shelf_audit_completed_result"] = result
        with (
            patch("shelf_audit.page.run_audit", side_effect=AssertionError("audit rerun")),
            patch("shelf_audit.page.OpenAIAuditProvider", side_effect=AssertionError("provider constructed")),
            patch("shelf_audit.reporting.ui.st.download_button", wraps=st.download_button) as download,
            patch("shelf_audit.reporting.ui.st.html", side_effect=AssertionError("preview rendered")),
        ):
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([field.label for field in app.text_input], ["Client", "Retailer", "Location"])
            self.assertEqual(len(app.date_input), 0)
            self.assertEqual(len(app.get("download_button")), 1)
            self.assertEqual(len(app.button), 0)
            self.assertEqual(download.call_args.args[0], "Download Report DOCX")
            self.assertEqual(download.call_args.kwargs["on_click"], "ignore")
            self.assertTrue(download.call_args.kwargs["file_name"].endswith(".docx"))
            app.text_input(key="shelf_report_client").set_value("Test Client").run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn("Test Client", docx_text(download.call_args.kwargs["data"]))
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any(element.value == "Shelf Opportunities" for element in app.subheader))

    def test_completed_audit_passes_original_photo_then_controls_never_reaudit(self):
        import streamlit as st
        original = photo_bytes((800, 300), "green")
        replacement = photo_bytes((300, 800), "yellow")
        uploaded = Mock()
        uploaded.name, uploaded.type = "original.png", "image/png"
        uploaded.getvalue.return_value = original
        first, second = completed_result(2), completed_result(1)
        app = AppTest.from_string('''
from shelf_audit.page import render
render()
''')
        with (
            patch("shelf_audit.page.st.file_uploader", return_value=uploaded),
            patch("shelf_audit.page.run_audit", side_effect=[first, second]) as audit,
            patch("shelf_audit.page.OpenAIAuditProvider") as provider,
            patch("shelf_audit.reporting.ui.st.download_button", wraps=st.download_button) as download,
        ):
            app.run()
            app.radio(key="shelf_audit_image_source").set_value("Upload Existing Photo").run()
            app.button(key="shelf_audit_analyze").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(audit.call_count, 1)
            self.assertEqual(app.session_state["shelf_audit_completed_photo"], original)
            self.assertIn(original, media_bytes(download.call_args.kwargs["data"]))
            # Changing the input doesn't change the photo associated with the
            # completed result until another explicit Analyze Shelf action.
            uploaded.getvalue.return_value = replacement
            app.text_input(key="shelf_report_location").set_value("Test Store").run()
            self.assertEqual(len(app.exception), 0)
            self.assertIn(original, media_bytes(download.call_args.kwargs["data"]))
            self.assertNotIn(replacement, media_bytes(download.call_args.kwargs["data"]))
            self.assertEqual(audit.call_count, 1)
            self.assertEqual(provider.call_count, 1)
            provider.return_value.analyze.assert_not_called()
            app.button(key="shelf_audit_analyze").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(audit.call_count, 2)
            self.assertIn(replacement, media_bytes(download.call_args.kwargs["data"]))
            self.assertEqual(app.session_state["shelf_audit_completed_result"], second)

    def test_failed_replacement_audit_clears_previous_photo_and_result(self):
        uploaded = Mock()
        uploaded.name, uploaded.type = "shelf.png", "image/png"
        uploaded.getvalue.return_value = photo_bytes()
        app = AppTest.from_string('''
from shelf_audit.page import render
render()
''')
        app.session_state["shelf_audit_completed_result"] = completed_result(1)
        app.session_state["shelf_audit_completed_photo"] = photo_bytes()
        with (
            patch("shelf_audit.page.st.camera_input", return_value=uploaded),
            patch("shelf_audit.page.run_audit", side_effect=RuntimeError("test failure")),
            patch("shelf_audit.page.OpenAIAuditProvider"),
        ):
            app.run()
            app.button(key="shelf_audit_analyze").click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertNotIn("shelf_audit_completed_photo", app.session_state)
            self.assertNotIn("shelf_audit_completed_result", app.session_state)
            self.assertEqual(len(app.get("download_button")), 0)

    def test_blank_fields_zero_findings_and_missing_photo_can_download(self):
        import streamlit as st
        app = AppTest.from_string('''
from shelf_audit.reporting.ui import render_report_section
from shelf_audit.models import AuditResult, AuditMode, AuditDepth
render_report_section(AuditResult([], AuditMode.PRODUCT, AuditDepth.DEEP, 0))
''')
        with patch("shelf_audit.reporting.ui.st.download_button", wraps=st.download_button) as download:
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual([field.label for field in app.text_input], ["Client", "Retailer", "Location"])
            self.assertIn(NO_OPPORTUNITIES_TEXT, docx_text(download.call_args.kwargs["data"]))


if __name__ == "__main__":
    unittest.main()
