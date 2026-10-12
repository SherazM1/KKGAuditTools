"""Editable Word reports from final report data; no audit or Office dependency."""

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
import textwrap
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from PIL import Image

from .formatting import BLUE, NAVY, DEFAULT_LOGO_PATH, load_logo
from .models import ReportOpportunity, ShelfOpportunityReport
from .templates import NO_OPPORTUNITIES_TEXT, WHY_LABEL, RECOMMENDATION_LABEL

PHOTO_MAX_WIDTH = 4.75  # Inches; the same fixed box is used for both orientations.
PHOTO_MAX_HEIGHT = 2.1
MIN_BODY_FONT_SIZE = 10.0
BOOK_FONT = "Gotham-Book"
MEDIUM_FONT = "Gotham-Medium"
BOLD_FONT = "Gotham-Bold"
TOP_LEFT_FRACTION = 0.60
CELL_PADDING = 0.2  # Combined horizontal cell padding, in inches.


@dataclass(frozen=True)
class DocxLayout:
    section_spacing: float = 10
    metadata_spacing: float = 4
    title_size: float = 12
    body_size: float = 11
    margin: float = 0.7


# Tune spacing first, then headings/body, then margins. Never shrink below 10pt.
LAYOUT_PRESETS = (
    DocxLayout(),
    DocxLayout(section_spacing=5),
    DocxLayout(section_spacing=5, metadata_spacing=1),
    DocxLayout(section_spacing=5, metadata_spacing=1, title_size=11),
    DocxLayout(section_spacing=5, metadata_spacing=1, title_size=11, body_size=10),
    DocxLayout(section_spacing=5, metadata_spacing=1, title_size=11, body_size=10, margin=0.55),
)


def _photo_dimensions(data: bytes | None) -> tuple[int, int] | None:
    if not data:
        return None
    try:
        with Image.open(BytesIO(data)) as image:
            # These formats can be embedded unchanged by python-docx.
            if image.format not in ("PNG", "JPEG"):
                return None
            dimensions = image.size
            image.verify()
            return dimensions
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def _line_count(text: str, width_points: float, font_size: float) -> int:
    # A conservative layout estimate, not a Word pagination engine. This is
    # formatting only: wrapped strings are never used as report content.
    characters = max(1, int(width_points / (font_size * 0.55)))
    return sum(max(1, len(textwrap.wrap(line, width=characters))) for line in text.split("\n"))


def photo_box_width(layout: DocxLayout) -> float:
    """Limit the original photo to the usable right-cell width, in inches."""
    return min(PHOTO_MAX_WIDTH, (8.5 - 2 * layout.margin) * (1 - TOP_LEFT_FRACTION) - CELL_PADDING)


def _metadata_height(report: ShelfOpportunityReport, layout: DocxLayout, width: float) -> float:
    return sum(
        _line_count(f"{label}: {value or ''}", width, layout.body_size)
        * layout.body_size * 1.12 + layout.metadata_spacing
        for label, value in (
            ("Client", report.metadata.client), ("Retailer", report.metadata.retailer),
            ("Location", report.metadata.location),
        )
    )


def _opportunity_height(item: ReportOpportunity, layout: DocxLayout, width: float) -> float:
    return (
        _line_count(f"{item.number:02d}  {item.title}", width, layout.title_size) * layout.title_size * 1.12
        + 2 * 11
        + sum(_line_count(value, width, layout.body_size) * layout.body_size * 1.12 for value in (item.evidence, item.recommendation))
        + layout.section_spacing + 12
    )


def first_opportunity_fits(report: ShelfOpportunityReport, layout: DocxLayout) -> bool:
    """Choose A only when the whole first finding and metadata fit conservatively.

    Use the fixed photo-height budget rather than trying to paginate Word. No
    photo, no finding, or long/wrapped copy always selects the full-width layout.
    """
    if not report.opportunities or not _photo_dimensions(report.audit_photo):
        return False
    width = ((8.5 - 2 * layout.margin) * TOP_LEFT_FRACTION - CELL_PADDING) * 72
    height = _metadata_height(report, layout, width) + _opportunity_height(report.opportunities[0], layout, width)
    return height + 6 <= PHOTO_MAX_HEIGHT * 72


def estimate_report_height(report: ShelfOpportunityReport, layout: DocxLayout) -> float:
    """Approximate adaptive body height, including reserved approval space."""
    width = (8.5 - 2 * layout.margin) * 72
    has_photo = _photo_dimensions(report.audit_photo) is not None
    left_width = width * TOP_LEFT_FRACTION - CELL_PADDING * 72 if has_photo else width
    metadata_height = _metadata_height(report, layout, left_width)
    first_in_table = first_opportunity_fits(report, layout)
    if first_in_table:
        metadata_height += _opportunity_height(report.opportunities[0], layout, left_width)
    photo_height = PHOTO_MAX_HEIGHT * 72 + 6 if has_photo else 0
    height = max(metadata_height, photo_height) + 12 + 78
    if not report.opportunities:
        return height + _line_count(NO_OPPORTUNITIES_TEXT, width, layout.body_size) * layout.body_size * 1.12
    for item in report.opportunities[1 if first_in_table else 0:]:
        height += _opportunity_height(item, layout, width)
    return height


def select_layout(report: ShelfOpportunityReport) -> DocxLayout:
    """Aim for one page for 0–4 findings; allow longer reports to flow normally."""
    if len(report.opportunities) > 4:
        return LAYOUT_PRESETS[1]
    for layout in LAYOUT_PRESETS:
        # Header is in the top margin. Include safety slack for Word table/line
        # metrics; actual page count depends on fonts and the receiving viewer.
        available = (11 - 1.15 - layout.margin) * 72 - 24
        if estimate_report_height(report, layout) <= available:
            return layout
    return LAYOUT_PRESETS[-1]


def _rule(paragraph: Paragraph) -> None:
    borders = OxmlElement("w:pBdr")
    border = OxmlElement("w:top")
    for key, value in (("val", "single"), ("sz", "4"), ("space", "6"), ("color", "DCE1EA")):
        border.set(qn(f"w:{key}"), value)
    borders.append(border)
    paragraph._p.get_or_add_pPr().append(borders)


def _set_font(run: Run, family: str) -> None:
    """Reference the installed face, without embedding or synthetic bolding."""
    run.font.name = family
    run.bold = False
    fonts = run._r.get_or_add_rPr().rFonts
    for script in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{script}"), family)


def render_docx(report: ShelfOpportunityReport, *, logo_path: Path | None = DEFAULT_LOGO_PATH) -> bytes:
    """Render editable paragraphs and original image bytes without modifying data.

    Only Client/Retailer/Location metadata is rendered in V1. Optional images that
    are absent or invalid are omitted; no paths from finding references are read.
    """
    layout = select_layout(report)
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin, section.bottom_margin = Inches(1.15), Inches(layout.margin)
    section.left_margin = section.right_margin = Inches(layout.margin)
    section.header_distance = section.footer_distance = Inches(0.3)
    width = 8.5 - 2 * layout.margin
    normal = document.styles["Normal"]
    normal.font.name = BOOK_FONT
    normal.font.size = Pt(layout.body_size)
    normal.font.color.rgb = RGBColor.from_string(NAVY.lstrip("#"))
    normal.paragraph_format.line_spacing = 1.12
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.widow_control = True
    document.core_properties.title = report.title
    document.core_properties.author = "Kendal King"

    def format_paragraph(
        paragraph: Paragraph, *, size: float | None = None, font: str = BOOK_FONT,
        blue: bool = False, after: float = 3, before: float = 0,
        keep_next: bool = False, keep_lines: bool = False,
    ) -> None:
        paragraph.paragraph_format.space_before = Pt(before)
        paragraph.paragraph_format.space_after = Pt(after)
        paragraph.paragraph_format.keep_with_next = keep_next
        paragraph.paragraph_format.keep_together = keep_lines
        for run in paragraph.runs:
            _set_font(run, font)
            run.font.size = Pt(size or layout.body_size)
            run.font.color.rgb = RGBColor.from_string((BLUE if blue else NAVY).lstrip("#"))

    # A simple fixed table anchors the proportional official logo and identity.
    header = section.header
    header.paragraphs[0].paragraph_format.space_after = Pt(0)
    header.paragraphs[0].paragraph_format.line_spacing = Pt(1)
    header.paragraphs[0].paragraph_format.space_before = Pt(0)
    header_table = header.add_table(rows=1, cols=2, width=Inches(width))
    header_table.autofit = False
    header_table.columns[0].width = Inches(0.9)
    header_table.columns[1].width = Inches(width - 0.9)
    logo_cell, identity_cell = header_table.rows[0].cells
    logo_cell.width = Inches(0.9)
    identity_cell.width = Inches(width - 0.9)
    for cell in (logo_cell, identity_cell):
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    logo = load_logo(logo_path)
    if logo:
        logo_cell.paragraphs[0].add_run().add_picture(BytesIO(logo), width=Inches(0.55))
    title = identity_cell.paragraphs[0]
    title.add_run(report.title)
    format_paragraph(title, size=19, font=BOLD_FONT, after=2)
    if report.subtitle:
        subtitle = identity_cell.add_paragraph(report.subtitle.upper())
        format_paragraph(subtitle, size=10, font=MEDIUM_FONT, blue=True, after=0)

    def add_opportunity(container, item: ReportOpportunity, text_width: float) -> None:
        # Use exactly the same finding style inside the cell and at full width.
        short_section = sum(_line_count(value, text_width * 72, layout.body_size) for value in (item.title, item.evidence, item.recommendation)) <= 12
        heading = container.add_paragraph()
        heading.add_run(f"{item.number:02d}  ")
        heading.add_run(item.title)
        format_paragraph(heading, size=layout.title_size, font=BOLD_FONT, before=layout.section_spacing, after=4, keep_next=True)
        _rule(heading)
        for label, text, last in (
            (WHY_LABEL, item.evidence, False),
            (RECOMMENDATION_LABEL, item.recommendation, True),
        ):
            paragraph = container.add_paragraph(label.upper())
            format_paragraph(paragraph, size=9, font=MEDIUM_FONT, blue=True, after=1, keep_next=True)
            paragraph = container.add_paragraph(text)
            format_paragraph(paragraph, after=3, keep_next=short_section and not last, keep_lines=short_section)

    dimensions = _photo_dimensions(report.audit_photo)
    first_in_table = first_opportunity_fits(report, layout)
    if dimensions:
        top_table = document.add_table(rows=1, cols=2)
        top_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        top_table.autofit = False
        metadata_cell, photo_cell = top_table.rows[0].cells
        for column, cell, fraction in zip(top_table.columns, (metadata_cell, photo_cell), (TOP_LEFT_FRACTION, 1 - TOP_LEFT_FRACTION)):
            column.width = cell.width = Inches(width * fraction)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        # Explicitly suppress inherited borders, including internal rules.
        borders = OxmlElement("w:tblBorders")
        for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
            border = OxmlElement(f"w:{edge}")
            border.set(qn("w:val"), "nil")
            borders.append(border)
        top_table._tbl.tblPr.append(borders)
        # Prevent a compact adaptive row from splitting over a page boundary.
        if first_in_table:
            top_table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        metadata_container = metadata_cell
    else:
        metadata_container = document

    for index, (label, value) in enumerate((
        ("Client", report.metadata.client), ("Retailer", report.metadata.retailer),
        ("Location", report.metadata.location),
    )):
        paragraph = metadata_cell.paragraphs[0] if dimensions and index == 0 else metadata_container.add_paragraph()
        _set_font(paragraph.add_run(f"{label}: "), MEDIUM_FONT)
        _set_font(paragraph.add_run(value or ""), BOOK_FONT)
        paragraph.paragraph_format.space_after = Pt(layout.metadata_spacing)
    if dimensions:
        image_width, image_height = dimensions
        scale = min(photo_box_width(layout) / image_width, PHOTO_MAX_HEIGHT / image_height)
        paragraph = photo_cell.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph.add_run().add_picture(
            BytesIO(report.audit_photo), width=Inches(image_width * scale),
            height=Inches(image_height * scale),
        )
        if first_in_table:
            add_opportunity(metadata_cell, report.opportunities[0], width * TOP_LEFT_FRACTION - CELL_PADDING)
    spacer = document.add_paragraph()
    spacer.paragraph_format.space_after = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(4)

    for item in report.opportunities[1 if first_in_table else 0:]:
        add_opportunity(document, item, width)
    if not report.opportunities:
        document.add_paragraph(NO_OPPORTUNITIES_TEXT)

    # These are ordinary editable paragraphs, not image-based signature artwork.
    for index, label in enumerate(("Approved By", "Signature", "Date")):
        paragraph = document.add_paragraph()
        paragraph.add_run(f"{label}:")
        paragraph.add_run("  ______________________________")
        format_paragraph(paragraph, after=8, before=12 if index == 0 else 0, keep_next=index < 2, keep_lines=True)
        _set_font(paragraph.runs[0], MEDIUM_FONT)
        if index == 0:
            _rule(paragraph)
    footer = section.footer.paragraphs[0]
    footer.add_run(f"{report.footer_text} {datetime.now(ZoneInfo('America/Chicago')).year}")
    format_paragraph(footer, size=8, after=0)
    _rule(footer)
    output = BytesIO()
    document.save(output)
    return output.getvalue()
