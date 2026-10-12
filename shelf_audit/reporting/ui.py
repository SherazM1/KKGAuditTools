"""Three optional fields and one editable-report download; no audit execution."""

import streamlit as st

from ..models import AuditResult
from .models import ReportMetadata
from .report_builder import build_report
from .docx_renderer import render_docx


@st.fragment
def render_report_section(result: AuditResult, *, audit_photo: bytes | None = None) -> None:
    st.subheader("Shelf Opportunity Report")
    client = st.text_input("Client", key="shelf_report_client")
    retailer = st.text_input("Retailer", key="shelf_report_retailer")
    location = st.text_input("Location", key="shelf_report_location")
    report = build_report(result, metadata=ReportMetadata(
        client=client or None, retailer=retailer or None, location=location or None,
    ), audit_photo=audit_photo)
    # Prepare bytes from the current fields locally. The single download action
    # requires neither a second generation button nor a stored preview/export.
    try:
        document = render_docx(report)
    except Exception:
        st.error("The report could not be prepared. Please try again.")
        return
    st.download_button(
        "Download Report DOCX", data=document,
        file_name="shelf_opportunity_report.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        key="shelf_audit_report_download", on_click="ignore",
    )
