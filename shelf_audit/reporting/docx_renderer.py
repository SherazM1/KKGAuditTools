"""Editable Word reports from final report data; no audit or Office dependency."""

from dataclasses import dataclass, replace
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path
import textwrap
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from PIL import Image

from .formatting import BLUE, NAVY, DEFAULT_LOGO_PATH, load_logo
from .models import ReportOpportunity, ShelfOpportunityReport
from .templates import NO_OPPORTUNITIES_TEXT, WHY_LABEL, RECOMMENDATION_LABEL

FRAME_WIDTH = 2.7
FRAME_HEIGHT = 3.2
PHOTO_MAX_WIDTH = FRAME_WIDTH - 0.12
PHOTO_MAX_HEIGHT = FRAME_HEIGHT - 0.25
MIN_BODY_FONT_SIZE = 10.0
BOOK_FONT = "Gotham-Book"
MEDIUM_FONT = "Gotham-Medium"
BOLD_FONT = "Gotham-Bold"
FRAME_X = 5.60  # Page-relative inches; frame ends at 8.30 on an 8.5-inch page.
FRAME_Y = 0.35
FRAME_BORDER_PT = 1.5
TEXT_CLEARANCE = 0.15
HEADER_TOP_MARGIN = 1.5


@dataclass(frozen=True)
class DocxLayout:
    section_spacing: float = 8
    body_spacing: float = 3
    content_spacing: float = 6
    signature_spacing: float = 14
    metadata_spacing: float = 2
    title_size: float = 13.5
    body_size: float = 10.5
    margin: float = 0.65


# Count controls body readability and base spacing; the architecture stays fixed.
LAYOUT_PRESETS = (
    DocxLayout(section_spacing=18, body_spacing=6, content_spacing=10, signature_spacing=28, body_size=11.5),
    DocxLayout(section_spacing=14, body_spacing=5, content_spacing=8, signature_spacing=24, body_size=11.5),
    DocxLayout(body_size=11),
    DocxLayout(section_spacing=5, body_spacing=2, content_spacing=4, signature_spacing=8),
    DocxLayout(section_spacing=5, body_spacing=2, content_spacing=4, signature_spacing=8, body_size=10),
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
    return PHOTO_MAX_WIDTH


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
        + layout.section_spacing + 6 + 2 * layout.body_spacing
    )


def photo_size(report: ShelfOpportunityReport, layout: DocxLayout) -> tuple[float, float] | None:
    """Actual proportional inline-photo dimensions in inches; no cropping."""
    dimensions = _photo_dimensions(report.audit_photo)
    if dimensions is None:
        return None
    image_width, image_height = dimensions
    scale = min(photo_box_width(layout) / image_width, PHOTO_MAX_HEIGHT / image_height)
    return image_width * scale, image_height * scale


def estimate_report_height(report: ShelfOpportunityReport, layout: DocxLayout) -> float:
    """Estimate the fixed composition; never use this to choose a structure."""
    width = (8.5 - 2 * layout.margin) * 72
    has_photo = photo_size(report, layout) is not None
    text_width = (FRAME_X - TEXT_CLEARANCE - layout.margin) * 72 if has_photo else width
    # Conservatively measure text at the upper-region width. Word releases the
    # width below the frame via native square wrapping. No image height or image
    # row is counted, so portrait/landscape cannot alter vertical spacing.
    height = _metadata_height(report, layout, text_width) + layout.content_spacing
    for item in report.opportunities:
        height += _opportunity_height(item, layout, text_width)
    if not report.opportunities:
        height += 24
    return height + layout.signature_spacing + 48


def select_layout(report: ShelfOpportunityReport) -> DocxLayout:
    """Distribute spare page height without any image-dependent calculation.

    Count chooses body size and base gaps. Conservative text measurements only
    limit extra spacing for long copy; they never move content or change layout.
    """
    count = len(report.opportunities)
    base = LAYOUT_PRESETS[min(max(count, 1), 5) - 1]
    if count == 0 or count >= 4:
        return base
    # Measure the narrow upper text region even with no photo, ensuring image
    # presence, dimensions, and frame height cannot participate in distribution.
    text_width = (FRAME_X - TEXT_CLEARANCE - base.margin) * 72
    natural_height = (
        _metadata_height(report, base, text_width) + base.content_spacing
        + sum(_opportunity_height(item, base, text_width) for item in report.opportunities)
        + base.signature_spacing + 48
    )
    available = (11 - HEADER_TOP_MARGIN - base.margin) * 72 - 40
    extra = max(0, min((320, 280, 140)[count - 1], available - natural_height))
    # Balanced rather than equal gaps: 55% between/before blocks, 45% before
    # signature. Everything remains paragraph spacing in ordinary Word flow.
    return replace(
        base,
        section_spacing=round(base.section_spacing + extra * 0.55 / count, 2),
        signature_spacing=round(base.signature_spacing + extra * 0.45, 2),
    )


def _rule(paragraph: Paragraph, edge: str = "top") -> None:
    borders = OxmlElement("w:pBdr")
    border = OxmlElement(f"w:{edge}")
    for key, value in (("val", "single"), ("sz", "4"), ("space", "6"), ("color", NAVY.lstrip("#"))):
        border.set(qn(f"w:{key}"), value)
    borders.append(border)
    paragraph._p.get_or_add_pPr().append(borders)


def _set_font(run: Run, family: str) -> None:
    """Reference the installed face, without embedding or synthetic bolding."""
    run.font.name = family
    run.bold = family == BOLD_FONT
    fonts = run._r.get_or_add_rPr().rFonts
    for script in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{script}"), family)


def _add_audit_anchor(paragraph: Paragraph, data: bytes, size: tuple[float, float]) -> None:
    """One framed picture anchored to the page, with horizontal-only wrapping.

    DrawingML fillRect insets letterbox the original image inside the fixed shape
    (https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.drawing.fillrectangle).
    The embedded bytes remain unchanged; only picture geometry is formatted.
    """
    inline = paragraph.add_run().add_picture(BytesIO(data), width=Inches(FRAME_WIDTH), height=Inches(FRAME_HEIGHT))._inline
    picture = inline.xpath(".//pic:pic")[0]
    fill = picture.xpath("pic:blipFill/a:stretch/a:fillRect")[0]
    horizontal = round((1 - size[0] / FRAME_WIDTH) * 50000)
    vertical = round((1 - size[1] / FRAME_HEIGHT) * 50000)
    for edge, inset in (("l", horizontal), ("r", horizontal), ("t", vertical), ("b", vertical)):
        fill.set(edge, str(inset))
    outline = OxmlElement("a:ln")
    outline.set("w", str(int(FRAME_BORDER_PT * 12700)))
    color_fill = OxmlElement("a:solidFill")
    color = OxmlElement("a:srgbClr")
    color.set("val", NAVY.lstrip("#"))
    color_fill.append(color)
    outline.append(color_fill)
    picture.xpath("pic:spPr")[0].append(outline)

    anchor = OxmlElement("wp:anchor")
    for key, value in (("distT", "0"), ("distB", "0"), ("distL", str(int(Inches(TEXT_CLEARANCE)))), ("distR", "0"),
                       ("simplePos", "0"), ("relativeHeight", "0"), ("behindDoc", "0"),
                       ("locked", "1"), ("layoutInCell", "0"), ("allowOverlap", "1")):
        anchor.set(key, value)
    simple = OxmlElement("wp:simplePos")
    simple.set("x", "0")
    simple.set("y", "0")
    anchor.append(simple)
    for axis, position in (("H", FRAME_X), ("V", FRAME_Y)):
        element = OxmlElement(f"wp:position{axis}")
        element.set("relativeFrom", "page")
        offset = OxmlElement("wp:posOffset")
        offset.text = str(int(Inches(position)))
        element.append(offset)
        anchor.append(element)
    anchor.append(inline.extent)
    effect = OxmlElement("wp:effectExtent")
    for edge in ("l", "t", "r", "b"):
        effect.set(edge, "0")
    anchor.append(effect)
    wrap = OxmlElement("wp:wrapSquare")
    wrap.set("wrapText", "left")
    anchor.append(wrap)
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        element = inline.find(qn(tag))
        if element is not None:
            anchor.append(element)
    inline.getparent().replace(inline, anchor)


def _add_image_caption(paragraph: Paragraph) -> None:
    """A separate page-relative text shape; no paragraph/spacer in body flow."""
    anchor = deepcopy(paragraph._p.xpath(".//wp:anchor")[-1])
    height = Inches(0.22)
    anchor.find(qn("wp:extent")).set("cy", str(int(height)))
    anchor.find(qn("wp:positionV")).find(qn("wp:posOffset")).text = str(int(Inches(FRAME_Y + FRAME_HEIGHT + 0.07)))
    properties = anchor.find(qn("wp:docPr"))
    properties.set("id", str(paragraph.part.next_id))
    properties.set("name", "Audit reference image caption")
    anchor.remove(anchor.find(qn("a:graphic")))
    graphic = parse_xml('''<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
        xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
        xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <a:graphicData uri="http://schemas.microsoft.com/office/word/2010/wordprocessingShape">
        <wps:wsp><wps:cNvSpPr txBox="1"/><wps:spPr>
          <a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></a:xfrm>
          <a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln>
        </wps:spPr><wps:txbx><w:txbxContent><w:p/></w:txbxContent></wps:txbx>
        <wps:bodyPr lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr"/>
        </wps:wsp>
      </a:graphicData></a:graphic>''')
    extent = graphic.find(".//" + qn("a:ext"))
    extent.set("cx", str(int(Inches(FRAME_WIDTH))))
    extent.set("cy", str(int(height)))
    text_paragraph = Paragraph(graphic.find(".//" + qn("w:p")), paragraph._parent)
    text_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    text_paragraph.paragraph_format.space_before = text_paragraph.paragraph_format.space_after = Pt(0)
    text_paragraph.paragraph_format.line_spacing = 1.0
    run = text_paragraph.add_run("AUDIT REFERENCE IMAGE")
    _set_font(run, BOLD_FONT)
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor.from_string(NAVY.lstrip("#"))
    anchor.append(graphic)
    drawing = OxmlElement("w:drawing")
    drawing.append(anchor)
    paragraph.add_run()._r.append(drawing)


def render_docx(report: ShelfOpportunityReport, *, logo_path: Path | None = DEFAULT_LOGO_PATH) -> bytes:
    """Render editable paragraphs and original image bytes without modifying data.

    Only Client/Retailer/Location metadata is rendered in V1. Optional images that
    are absent or invalid are omitted; no paths from finding references are read.
    """
    layout = select_layout(report)
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin, section.bottom_margin = Inches(HEADER_TOP_MARGIN), Inches(layout.margin)
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
    header_width = FRAME_X - layout.margin - TEXT_CLEARANCE
    header_table = header.add_table(rows=1, cols=2, width=Inches(header_width))
    header_table.autofit = False
    header_table.columns[0].width = Inches(1.1)
    header_table.columns[1].width = Inches(header_width - 1.1)
    logo_cell, identity_cell = header_table.rows[0].cells
    logo_cell.width = Inches(1.1)
    identity_cell.width = Inches(header_width - 1.1)
    for cell in (logo_cell, identity_cell):
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    logo = load_logo(logo_path)
    if logo:
        logo_cell.paragraphs[0].add_run().add_picture(BytesIO(logo), width=Inches(0.88))
    title = identity_cell.paragraphs[0]
    title.add_run(report.title)
    format_paragraph(title, size=24, font=BOLD_FONT, after=2)
    if report.subtitle:
        subtitle = identity_cell.add_paragraph(report.subtitle.upper())
        format_paragraph(subtitle, size=12, font=BOLD_FONT, blue=True, after=0)

    def add_opportunity(container, item: ReportOpportunity, text_width: float) -> None:
        # Use exactly the same finding style inside the cell and at full width.
        short_section = sum(_line_count(value, text_width * 72, layout.body_size) for value in (item.title, item.evidence, item.recommendation)) <= 12
        heading = container.add_paragraph()
        heading.add_run(f"{item.number:02d}  ")
        heading.add_run(item.title)
        format_paragraph(heading, size=layout.title_size, font=BOLD_FONT, before=layout.section_spacing, after=4, keep_next=True)
        right_indent = Inches(width - text_width) if size and item.number == 1 else Inches(0)
        heading.paragraph_format.right_indent = right_indent
        if item.number > 2:
            _rule(heading)
        for label, text, last in (
            (WHY_LABEL, item.evidence, False),
            (RECOMMENDATION_LABEL, item.recommendation, True),
        ):
            paragraph = container.add_paragraph(label.upper())
            format_paragraph(paragraph, size=10.5, font=BOLD_FONT, blue=True, after=1, keep_next=True)
            paragraph.paragraph_format.right_indent = right_indent
            paragraph = container.add_paragraph(text)
            format_paragraph(paragraph, after=layout.body_spacing, keep_next=short_section and not last, keep_lines=short_section)
            paragraph.paragraph_format.right_indent = right_indent
            if item.number == 1 and last:
                _rule(paragraph, "bottom")

    # Metadata always precedes the main copy/photo region, at full usable width.
    for label, value in (
        ("Client", report.metadata.client), ("Retailer", report.metadata.retailer),
        ("Location", report.metadata.location),
    ):
        paragraph = document.add_paragraph()
        _set_font(paragraph.add_run(f"{label}: "), MEDIUM_FONT)
        _set_font(paragraph.add_run(value or ""), BOOK_FONT)
        paragraph.paragraph_format.space_after = Pt(layout.metadata_spacing)
    paragraph.paragraph_format.space_after = Pt(layout.metadata_spacing + layout.content_spacing)

    size = photo_size(report, layout)
    if size:
        # Stable first metadata paragraph owns one page-relative anchor. It has
        # no inline extent, table, or frame-height spacer in the body flow.
        _add_audit_anchor(document.paragraphs[0], report.audit_photo, size)
        _add_image_caption(document.paragraphs[0])
    text_width = FRAME_X - TEXT_CLEARANCE - layout.margin if size else width
    for item in report.opportunities:
        add_opportunity(document, item, text_width)
    if not report.opportunities:
        document.add_paragraph(NO_OPPORTUNITIES_TEXT)

    # These are ordinary editable paragraphs, not image-based signature artwork.
    for index, label in enumerate(("Signature", "Date")):
        paragraph = document.add_paragraph()
        paragraph.add_run(f"{label}:")
        paragraph.add_run("  " + ("______________________________" if index == 0 else "__________________"))
        format_paragraph(paragraph, after=8, before=layout.signature_spacing if index == 0 else 0, keep_next=index < 1, keep_lines=True)
        _set_font(paragraph.runs[0], BOLD_FONT)
        paragraph.runs[0].font.size = Pt(11)
        if index == 0:
            _rule(paragraph)
    footer = section.footer.paragraphs[0]
    footer.add_run(f"{report.footer_text} {datetime.now(ZoneInfo('America/Chicago')).year}")
    format_paragraph(footer, size=8, after=0)
    _rule(footer)
    output = BytesIO()
    document.save(output)
    return output.getvalue()
