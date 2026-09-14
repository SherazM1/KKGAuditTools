"""KKG Auditing hub entry point."""

import streamlit as st

from shelf_audit import page as shelf_audit_page
from display_compliance import page as display_compliance_page


st.set_page_config(
    page_title="KKG Auditing",
    page_icon="📸",
    layout="centered",
)

# Add future module renderers here as they become available.
ROUTES = {
    "shelf_audit": shelf_audit_page.render,
    "display_compliance": display_compliance_page.render,
}

if st.session_state.get("hub_route") not in {"home", *ROUTES}:
    st.session_state["hub_route"] = "home"

st.title("KKG Auditing")

if st.session_state["hub_route"] == "home":
    st.caption("Choose an auditing tool to get started.")
    if st.button(
        "Shelf Audit",
        key="hub_open_shelf_audit",
        type="primary",
        use_container_width=True,
    ):
        st.session_state["hub_route"] = "shelf_audit"
        st.rerun()
    if st.button(
        "Display Compliance",
        key="hub_open_display_compliance",
        use_container_width=True,
    ):
        st.session_state["hub_route"] = "display_compliance"
        st.rerun()
else:
    if st.button("Home", key="hub_home"):
        st.session_state["hub_route"] = "home"
        st.rerun()
    ROUTES[st.session_state["hub_route"]]()
