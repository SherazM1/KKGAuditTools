"""Editable Word reports from final report data; no audit or Office dependency."""

from dataclasses import dataclass
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from pathlib import Path
import textwrap
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from PIL import Image

from .font_embedding import embed_report_fonts, discover_font_assets
from .formatting import BLUE, NAVY, DEFAULT_LOGO_PATH, load_logo
from .models import ReportOpportunity, ShelfOpportunityReport
from .templates import NO_OPPORTUNITIES_TEXT, WHY_LABEL, RECOMMENDATION_LABEL

# Page-relative composition measured from MOLLI.pdf (US Letter).
FRAME_WIDTH = 2.48
FRAME_HEIGHT = 3.28
FRAME_X = 5.38
FRAME_Y = 2.29
FRAME_BORDER_PT = 1.0
TEXT_CLEARANCE = 0.15
PHOTO_MAX_WIDTH = FRAME_WIDTH - 0.24
PHOTO_MAX_HEIGHT = FRAME_HEIGHT - 0.36
HEADER_TOP_MARGIN = 0.55
CONTENT_TOP = 2.55
BLACK_FONT = "Gotham Black"
BOLD_FONT = "Gotham Bold"
BOOK_FONT = "Gotham Book"
MEDIUM_FONT = "Gotham Medium"  # Retained for existing callers; no report role.
MIN_BODY_FONT_SIZE = 10.0
TRACKING_PT = 1.2
LOGO_X, LOGO_Y, LOGO_WIDTH = 6.82, 0.40, 1.05


@dataclass(frozen=True)
class DocxLayout:
    section_spacing: float = 12
    body_spacing: float = 12
    content_spacing: float = 20
    signature_spacing: float = 0
    metadata_spacing: float = 0
    title_size: float = 12
    body_size: float = 10
    margin: float = 0.63


# One hierarchy and rhythm, independent of finding count.
LAYOUT_PRESETS = (DocxLayout(),) * 5


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


def _opportunity_height(item: ReportOpportunity, layout: DocxLayout, width: float) -> float:
    return (
        _line_count(f"{item.number:02d} {item.title}", width, layout.title_size) * 14
        + 12 + 2 * (13 + 1)
        + sum(_line_count(value, width, layout.body_size) * 12 for value in (item.evidence, item.recommendation))
        + layout.section_spacing + 2 * layout.body_spacing
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
    """Conservative body estimate, excluding the independently reserved footer."""
    width = (8.5 - 2 * layout.margin) * 72
    narrow = (FRAME_X - TEXT_CLEARANCE - layout.margin) * 72
    cursor = CONTENT_TOP * 72
    for item in report.opportunities:
        text_width = narrow if report.audit_photo and cursor < (FRAME_Y + FRAME_HEIGHT) * 72 else width
        cursor += _opportunity_height(item, layout, text_width)
    return cursor - CONTENT_TOP * 72


def select_layout(report: ShelfOpportunityReport) -> DocxLayout:
    """The approved type hierarchy never changes with count or copy length."""
    return LAYOUT_PRESETS[0]


def _set_tracking(run: Run, points: float = TRACKING_PT) -> None:
    """Word character spacing is in twentieths of a point, without text edits."""
    properties = run._r.get_or_add_rPr()
    spacing = properties.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        properties.insert_element_before(spacing, "w:w", "w:kern", "w:position", "w:sz",
                                         "w:szCs", "w:highlight", "w:u", "w:effect",
                                         "w:bdr", "w:shd", "w:fitText", "w:vertAlign")
    spacing.set(qn("w:val"), str(round(points * 20)))


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
    run.bold = family in (BOLD_FONT, BLACK_FONT)
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

    _anchor_picture(inline, FRAME_X, FRAME_Y)


def _anchor_picture(inline, x: float, y: float, *, wrap_left: bool = True) -> None:
    """Convert an unchanged image part to a fixed page-relative drawing."""
    anchor = OxmlElement("wp:anchor")
    for key, value in (("distT", "0"), ("distB", "0"), ("distL", str(int(Inches(TEXT_CLEARANCE)))), ("distR", "0"),
                       ("simplePos", "0"), ("relativeHeight", "0"), ("behindDoc", "0"),
                       ("locked", "1"), ("layoutInCell", "0"), ("allowOverlap", "1")):
        anchor.set(key, value)
    simple = OxmlElement("wp:simplePos")
    simple.set("x", "0")
    simple.set("y", "0")
    anchor.append(simple)
    for axis, position in (("H", x), ("V", y)):
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
    wrap = OxmlElement("wp:wrapSquare" if wrap_left else "wp:wrapNone")
    if wrap_left:
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
    height = Inches(0.16)
    anchor.find(qn("wp:extent")).set("cy", str(int(height)))
    anchor.find(qn("wp:positionV")).find(qn("wp:posOffset")).text = str(int(Inches(FRAME_Y + FRAME_HEIGHT - 0.18)))
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
    run.font.size = Pt(5)
    run.italic = True
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
    if BOOK_FONT not in discover_font_assets():
        raise FileNotFoundError("Shelf Audit DOCX requires licensed project asset Gotham-Book.ttf")
    layout = select_layout(report)
    document = Document()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = Inches(HEADER_TOP_MARGIN)
    section.bottom_margin = Inches(1.0)  # Reserve signature/footer independently.
    section.left_margin = section.right_margin = Inches(layout.margin)
    section.header_distance, section.footer_distance = Inches(0.3), Inches(0.18)
    width = 8.5 - 2 * layout.margin
    normal = document.styles["Normal"]
    normal.font.name, normal.font.size = BOOK_FONT, Pt(10)
    fonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    for script in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{script}"), BOOK_FONT)
    normal.font.color.rgb = RGBColor.from_string(NAVY.lstrip("#"))
    normal.paragraph_format.line_spacing = Pt(12)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.widow_control = True
    document.core_properties.title, document.core_properties.author = report.title, "Kendal King"

    def format_paragraph(paragraph, *, font=BOOK_FONT, size=10, line=12,
                         before=0, after=0, blue=False, tracked=False, keep_next=False):
        fmt = paragraph.paragraph_format
        fmt.space_before, fmt.space_after = Pt(before), Pt(after)
        fmt.line_spacing = Pt(line)
        fmt.keep_with_next = keep_next
        for run in paragraph.runs:
            _set_font(run, font)
            run.font.size = Pt(size)
            run.font.color.rgb = RGBColor.from_string((BLUE if blue else NAVY).lstrip("#"))
            if tracked:
                _set_tracking(run)

    title = document.add_paragraph(report.title)
    format_paragraph(title, font=BLACK_FONT, size=30, line=36, after=6, keep_next=True)
    title.paragraph_format.right_indent = Inches(1.20)
    logo = load_logo(logo_path)
    if logo:
        inline = section.header.paragraphs[0].add_run().add_picture(BytesIO(logo), width=Inches(LOGO_WIDTH))._inline
        _anchor_picture(inline, LOGO_X, LOGO_Y, wrap_left=False)
    if report.subtitle:
        subtitle = document.add_paragraph(report.subtitle.upper())
        format_paragraph(subtitle, font=BOLD_FONT, size=11, line=14, after=14,
                         blue=True, tracked=True, keep_next=True)
    for label, value in (("Client", report.metadata.client), ("Retailer", report.metadata.retailer),
                         ("Location", report.metadata.location)):
        paragraph = document.add_paragraph()
        label_run = paragraph.add_run(f"{label}: ")
        value_run = paragraph.add_run(value or "")
        format_paragraph(paragraph, size=12, line=14, keep_next=True)
        _set_font(label_run, BLACK_FONT)
        _set_font(value_run, BOOK_FONT)
    paragraph.paragraph_format.space_after = Pt(layout.content_spacing)
    _rule(paragraph, "bottom")
    image_size = photo_size(report, layout)
    if image_size:
        _add_audit_anchor(title, report.audit_photo, image_size)
        _add_image_caption(title)

    # Track paragraph heights at fixed leading. Native left-only square wrapping
    # also guards against differences in Word's line breaking at the release point.
    cursor = CONTENT_TOP * 72 - layout.section_spacing
    previous_after = 0
    panel_bottom = (FRAME_Y + FRAME_HEIGHT) * 72
    narrow = FRAME_X - TEXT_CLEARANCE - layout.margin

    def add_copy(text, *, font=BOOK_FONT, size=10, line=12, before=0, after=0,
                 blue=False, tracked=False, keep_next=False, divider=False):
        nonlocal cursor, previous_after
        # Word uses the larger adjacent paragraph gap, rather than their sum.
        cursor += max(0, before - previous_after)
        constrained = bool(image_size and cursor < panel_bottom)
        text_width = narrow if constrained else width
        paragraph = document.add_paragraph(text)
        format_paragraph(paragraph, font=font, size=size, line=line, before=before,
                         after=after, blue=blue, tracked=tracked, keep_next=keep_next)
        paragraph.paragraph_format.right_indent = Inches(width - text_width)
        if divider:
            _rule(paragraph)
        cursor += _line_count(text, text_width * 72, size) * line + after
        previous_after = after
        return paragraph

    for index, item in enumerate(report.opportunities):
        add_copy(f"{item.number:02d} {item.title}", font=BLACK_FONT, size=12, line=14,
                 before=layout.section_spacing, after=12,
                 keep_next=True, divider=index > 0)
        for label, text in ((WHY_LABEL, item.evidence), (RECOMMENDATION_LABEL, item.recommendation)):
            add_copy(label.upper(), font=BOLD_FONT, size=11, line=13, after=1,
                     blue=True, tracked=True, keep_next=True)
            add_copy(text, after=layout.body_spacing)
    if not report.opportunities:
        document.add_paragraph(NO_OPPORTUNITIES_TEXT)

    # Footer content reserves a stable bottom zone on every page, independent of
    # finding count. A right-aligned tab keeps both editable blanks on one row.
    signature = section.footer.paragraphs[0]
    signature.paragraph_format.tab_stops.add_tab_stop(Inches(width), WD_TAB_ALIGNMENT.RIGHT)
    signature.add_run("Signature: ")
    signature.add_run("__________________________")
    signature.add_run("\t")
    signature.add_run("Date: ")
    signature.add_run("__________________________")
    format_paragraph(signature, font=BOOK_FONT, size=10, line=14, after=18)
    _set_font(signature.runs[0], BLACK_FONT)
    _set_font(signature.runs[3], BLACK_FONT)
    _rule(signature, "bottom")
    footer = section.footer.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run(f"{report.footer_text} {datetime.now(ZoneInfo('America/Chicago')).year}")
    format_paragraph(footer, size=8, line=10)
    output = BytesIO()
    document.save(output)
    return embed_report_fonts(output.getvalue())
