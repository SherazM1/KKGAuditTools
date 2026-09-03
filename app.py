"""
Shelf Audit Tool

Current foundation:
- camera or image upload
- quick / deep audit modes
- provider-neutral audit pipeline
- ranked opportunities
- mock provider for development

Real AI provider will be connected later.
"""

import streamlit as st

from audit import run_audit
from audit_modes import get_mode_config
from criteria import load_criteria
from guardrails import GuardrailError
from image_utils import build_audit_image
from models import AuditMode
from providers.mock import MockAuditProvider


# ---------------------------------------------------------
# Page setup
# ---------------------------------------------------------

st.set_page_config(
    page_title="Shelf Audit Tool",
    page_icon="📸",
    layout="centered",
)

st.title("Shelf Audit Tool")

st.caption(
    "Take a shelf photo or upload an existing image to identify "
    "the strongest merchandising opportunities visible in the scene."
)


# ---------------------------------------------------------
# Load criteria
# ---------------------------------------------------------

try:
    criteria = load_criteria()

except Exception as exc:
    st.error(
        f"Audit criteria could not be loaded: {exc}"
    )
    st.stop()


# ---------------------------------------------------------
# Audit mode
# ---------------------------------------------------------

st.subheader("Audit depth")

mode_label = st.radio(
    "Choose how deep you want the audit to go:",
    options=[
        "Quick Audit",
        "Deep Audit",
    ],
    horizontal=True,
)

if mode_label == "Quick Audit":
    audit_mode = AuditMode.QUICK
else:
    audit_mode = AuditMode.FULL


mode_config = get_mode_config(audit_mode)

st.caption(mode_config.description)


# ---------------------------------------------------------
# Image source
# ---------------------------------------------------------

st.subheader("Shelf image")

input_method = st.radio(
    "Choose an image source:",
    options=[
        "Take Photo",
        "Upload Existing Photo",
    ],
    horizontal=True,
)


image_file = None
image_source = None


if input_method == "Take Photo":

    image_file = st.camera_input(
        "Take a shelf photo"
    )

    image_source = "camera"


else:

    image_file = st.file_uploader(
        "Upload a shelf photo",
        type=[
            "jpg",
            "jpeg",
            "png",
        ],
    )

    image_source = "upload"


# ---------------------------------------------------------
# Image preview + analyze
# ---------------------------------------------------------

if image_file is not None:

    image_bytes = image_file.getvalue()

    st.image(
        image_bytes,
        caption="Selected shelf image",
        use_container_width=True,
    )

    analyze = st.button(
        "Analyze Shelf",
        type="primary",
        use_container_width=True,
    )

    if analyze:

        try:

            audit_image = build_audit_image(
                image_bytes,
                filename=getattr(
                    image_file,
                    "name",
                    None,
                ),
                media_type=getattr(
                    image_file,
                    "type",
                    None,
                ),
                source=image_source,
            )

            provider = MockAuditProvider()

            with st.spinner(
                "Analyzing shelf opportunities..."
            ):

                result = run_audit(
                    image=audit_image,
                    criteria=criteria,
                    mode=audit_mode,
                    provider=provider,
                )

        except GuardrailError as exc:

            st.error(
                f"Image or audit validation failed: {exc}"
            )

            st.stop()

        except Exception as exc:

            st.error(
                f"The audit could not be completed: {exc}"
            )

            st.stop()


        # -------------------------------------------------
        # Results
        # -------------------------------------------------

        st.divider()

        st.subheader("Top Opportunities")

        if not result.opportunities:

            st.info(
                "No opportunities were identified for this image."
            )

        else:

            for index, opportunity in enumerate(
                result.opportunities,
                start=1,
            ):

                st.markdown(
                    f"### {index}. {opportunity.title}"
                )

                st.markdown(
                    f"**Why:** {opportunity.evidence}"
                )

                st.markdown(
                    f"**Recommendation:** "
                    f"{opportunity.recommendation}"
                )

                st.caption(
                    "Priority score: "
                    f"{opportunity.priority_score:.2f}"
                )

                st.write("")


        st.divider()

        st.caption(
            f"{result.criteria_evaluated} criteria available · "
            f"{mode_config.label}"
        )