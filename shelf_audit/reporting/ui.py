"""Small Streamlit report action operating only on a completed AuditResult."""

import streamlit as st

from ..models import AuditResult
from .models import ReportMetadata
from .report_builder import build_report
from .pdf_renderer import render_pdf
from .preview_renderer import render_preview


def render_report_section(result: AuditResult) -> None:
    st.subheader("Shelf Opportunity Report")
    with st.form("shelf_audit_report_form"):
        st.caption("Optional report details. Leave fields blank if unavailable.")
        client = st.text_input("Client", key="shelf_report_client")
        brand = st.text_input("Brand", key="shelf_report_brand")
        retailer = st.text_input("Retailer", key="shelf_report_retailer")
        location = st.text_input("Location", key="shelf_report_location")
        audit_date = st.date_input("Audit Date", value=None, key="shelf_report_audit_date")
        account_lead = st.text_input("Account Lead", key="shelf_report_account_lead")
        audit_reference = st.text_input("Audit / Photo Reference", key="shelf_report_reference")
        submitted = st.form_submit_button("Create Report")
    if submitted:
        report = build_report(result, metadata=ReportMetadata(
            client=client or None, brand=brand or None, retailer=retailer or None,
            location=location or None, audit_date=audit_date,
            account_lead=account_lead or None, audit_reference=audit_reference or None,
        ))
        # Never retain a stale export if a replacement could not be rendered.
        st.session_state.pop("shelf_audit_report_document", None)
        try:
            pdf = render_pdf(report)
            preview = render_preview(report)
        except Exception:
            st.error("The report could not be prepared. Please try again.")
            return
        st.session_state["shelf_audit_report_document"] = (preview, pdf)
    document = st.session_state.get("shelf_audit_report_document")
    if document is not None:
        preview, pdf = document
        st.html(preview)
        st.download_button(
            "Download Report PDF", data=pdf, file_name="shelf_opportunity_report.pdf",
            mime="application/pdf", key="shelf_audit_report_download", on_click="ignore",
        )
