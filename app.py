"""KKG Auditing hub entry point."""

import streamlit as st
import hmac
from shelf_audit import page as shelf_audit_page
from display_compliance import page as display_compliance_page


st.set_page_config(
    page_title="KKG Auditing",
    page_icon="📸",
    layout="centered",
)

def require_access_code() -> None:
    expected_code = st.secrets.get("APP_ACCESS_CODE")

    if not expected_code:
        st.error("Access has not been configured. Contact the app owner.")
        st.stop()

    if st.session_state.get("access_granted"):
        return

    st.title("KKG Auditing")
    st.write("Enter the access code to continue.")

    with st.form("access_code_form"):
        entered_code = st.text_input("Access code", type="password")
        submitted = st.form_submit_button("Continue")

    if submitted:
        if hmac.compare_digest(entered_code, str(expected_code)):
            st.session_state["access_granted"] = True
            st.rerun()
        st.error("Incorrect access code.")

    st.stop()

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
