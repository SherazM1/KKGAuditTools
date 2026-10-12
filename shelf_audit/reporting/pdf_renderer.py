"""Deterministic PDF layout consuming only client-facing report data."""

from html import escape
from io import BytesIO
from pathlib import Path

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
)

from .formatting import BLUE, NAVY, DEFAULT_LOGO_PATH, load_logo, metadata_rows
from .models import ShelfOpportunityReport
from .templates import NO_OPPORTUNITIES_TEXT, WHY_LABEL, RECOMMENDATION_LABEL


def render_pdf(report: ShelfOpportunityReport, *, logo_path: Path | None = DEFAULT_LOGO_PATH) -> bytes:
    """Render locally without fetching assets or interpreting finding markup.

    Small findings stay together; oversized findings may flow across pages.
    Image references remain optional and are not dereferenced in V1.
    """
    fonts = Path(reportlab.__file__).parent / "fonts"
    for name, filename in (("KKReport", "Vera.ttf"), ("KKReportBold", "VeraBd.ttf")):
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    body = ParagraphStyle("body", fontName="KKReport", fontSize=10, leading=15, textColor=colors.HexColor(NAVY), spaceAfter=12)
    heading = ParagraphStyle("heading", parent=body, fontName="KKReportBold", fontSize=16, leading=21, keepWithNext=True)
    title_style = ParagraphStyle("title", parent=heading, fontSize=24, leading=30, spaceAfter=6)
    label_style = ParagraphStyle("label", parent=body, fontName="KKReportBold", fontSize=8, leading=11, textColor=colors.HexColor(BLUE), spaceAfter=5, keepWithNext=True)
    meta_style = ParagraphStyle("metadata", parent=body, fontSize=9, leading=13, spaceAfter=7)

    def paragraph(text: str, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(escape(text).replace("\n", "<br/>"), style)

    logo = load_logo(logo_path)
    logo_reader = ImageReader(BytesIO(logo)) if logo else None
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=letter, leftMargin=48, rightMargin=48,
        topMargin=139, bottomMargin=55, title=report.title,
        author="Kendal King", invariant=1,
    )

    def page_identity(canvas, doc):
        canvas.saveState()
        width, height = letter
        if logo_reader:
            image_width, image_height = logo_reader.getSize()
            draw_width = 70
            draw_height = draw_width * image_height / image_width
            canvas.drawImage(logo_reader, 48, height - 30 - draw_height, width=draw_width, height=draw_height, mask="auto")
        if doc.page > 1:
            header = paragraph(report.title, meta_style)
            header.wrap(width - 190, 50)
            header.drawOn(canvas, 142, height - 65)
        canvas.setStrokeColor(colors.HexColor("#DCE1EA"))
        canvas.setLineWidth(0.5)
        canvas.line(48, height - 122, width - 48, height - 122)
        canvas.line(48, 43, width - 48, 43)
        footer = paragraph(report.footer_text, ParagraphStyle("footer", parent=body, fontSize=8, leading=10))
        footer.wrap(width - 140, 30)
        footer.drawOn(canvas, 48, 27)
        canvas.setFont("KKReport", 8)
        canvas.setFillColor(colors.HexColor(NAVY))
        canvas.drawRightString(width - 48, 27, str(doc.page))
        canvas.restoreState()

    story = [paragraph(report.title, title_style)]
    if report.subtitle:
        story.append(paragraph(report.subtitle))
    rows = metadata_rows(report.metadata)
    if rows:
        story.append(Spacer(1, 8))
        for label, value in rows:
            story.append(paragraph(f"{label}: {value}", meta_style))
    story.append(Spacer(1, 12))
    for item in report.opportunities:
        section = [
            HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#DCE1EA")),
            Spacer(1, 16), paragraph(f"{item.number:02d}", label_style),
            paragraph(item.title, heading), paragraph(WHY_LABEL.upper(), label_style),
            paragraph(item.evidence), paragraph(RECOMMENDATION_LABEL.upper(), label_style),
            paragraph(item.recommendation), Spacer(1, 8),
        ]
        section_height = sum(
            flowable.wrap(document.width, document.height)[1]
            + flowable.getSpaceBefore() + flowable.getSpaceAfter()
            for flowable in section
        )
        if section_height <= document.height - 12:
            story.append(KeepTogether(section))
        else:
            # A section taller than a page cannot stay together. Split long
            # paragraphs into modest fragments so the first page still gets
            # useful copy beneath its title instead of a large empty area.
            for flowable in section:
                pending = [flowable]
                while pending:
                    fragment = pending.pop(0)
                    if isinstance(fragment, Paragraph) and fragment.wrap(document.width, document.height)[1] > document.height / 3:
                        pieces = fragment.split(document.width, document.height / 3)
                        if pieces:
                            pending[0:0] = pieces
                            continue
                    story.append(fragment)
    if not report.opportunities:
        story.append(paragraph(NO_OPPORTUNITIES_TEXT))
    document.build(story, onFirstPage=page_identity, onLaterPages=page_identity)
    return buffer.getvalue()
