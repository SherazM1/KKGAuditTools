"""
Shelf Audit Tool

Current foundation:
- camera or image upload
- product / expanded audit modes
- quick / deep audit depth
- provider-neutral audit pipeline
- ranked opportunities
- target-region image helpers
- single-target Expanded mode selection
- mock provider for development

Real AI provider will be connected later.
"""

import streamlit as st
from streamlit_drawable_canvas import st_canvas

from audit import run_audit
from audit_modes import get_mode_config, get_depth_config
from criteria import load_criteria
from guardrails import GuardrailError
from image_utils import (
    build_audit_image,
    normalize_target_region,
    crop_target_region,
    get_image_dimensions,
)
from models import AuditMode, AuditDepth
from providers.mock import MockAuditProvider


# ---------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------

MAX_CANVAS_WIDTH = 700
MAX_CANVAS_HEIGHT = 700


def _fit_canvas_dimensions(
    image_width: int,
    image_height: int,
) -> tuple[int, int]:
    """
    Fit the source image inside the Expanded-mode canvas
    without changing its aspect ratio.
    """

    if image_width <= 0 or image_height <= 0:
        raise ValueError(
            "Image dimensions must be greater than zero."
        )

    scale = min(
        MAX_CANVAS_WIDTH / image_width,
        MAX_CANVAS_HEIGHT / image_height,
        1.0,
    )

    canvas_width = max(
        1,
        round(image_width * scale),
    )

    canvas_height = max(
        1,
        round(image_height * scale),
    )

    return (
        canvas_width,
        canvas_height,
    )


def _extract_single_rectangle(
    canvas_result,
) -> dict | None:
    """
    Return the one rectangle currently drawn on the canvas.

    Expanded mode intentionally supports exactly one active
    target product.
    """

    if canvas_result.json_data is None:
        return None

    objects = canvas_result.json_data.get(
        "objects",
        [],
    )

    rectangles = [
        obj
        for obj in objects
        if str(obj.get("type", "")).lower() == "rect"
    ]

    if len(rectangles) != 1:
        return None

    return rectangles[0]


def _rectangle_coordinates(
    rectangle: dict,
) -> tuple[float, float, float, float]:
    """
    Resolve rectangle coordinates from Fabric.js canvas data.

    Fabric retains the original width and height when an object
    is resized, so scaleX and scaleY must also be applied.
    """

    x = float(
        rectangle.get(
            "left",
            0.0,
        )
    )

    y = float(
        rectangle.get(
            "top",
            0.0,
        )
    )

    width = float(
        rectangle.get(
            "width",
            0.0,
        )
    ) * float(
        rectangle.get(
            "scaleX",
            1.0,
        )
    )

    height = float(
        rectangle.get(
            "height",
            0.0,
        )
    ) * float(
        rectangle.get(
            "scaleY",
            1.0,
        )
    )

    return (
        x,
        y,
        width,
        height,
    )


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

st.subheader("Audit mode")

mode_label = st.radio(
    "Choose the type of shelf audit:",
    options=[
        "Product",
        "Expanded",
    ],
    horizontal=True,
)

if mode_label == "Product":
    audit_mode = AuditMode.PRODUCT
else:
    audit_mode = AuditMode.EXPANDED

mode_config = get_mode_config(
    audit_mode
)

st.caption(
    mode_config.description
)


# ---------------------------------------------------------
# Audit depth
# ---------------------------------------------------------

st.subheader("Audit depth")

depth_label = st.radio(
    "Choose how deep you want the audit to go:",
    options=[
        "Quick Audit",
        "Deep Audit",
    ],
    horizontal=True,
)

if depth_label == "Quick Audit":
    audit_depth = AuditDepth.QUICK
else:
    audit_depth = AuditDepth.DEEP

depth_config = get_depth_config(
    audit_depth
)

st.caption(
    depth_config.description
)


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
# Image preparation
# ---------------------------------------------------------

if image_file is not None:

    image_bytes = image_file.getvalue()

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

    except Exception as exc:
        st.error(
            f"The image could not be prepared: {exc}"
        )
        st.stop()


    # -----------------------------------------------------
    # Product mode
    # -----------------------------------------------------

    target_region = None
    target_crop = None

    if audit_mode is AuditMode.PRODUCT:

        st.image(
            image_bytes,
            caption="Selected shelf image",
            use_container_width=True,
        )


    # -----------------------------------------------------
    # Expanded mode
    # -----------------------------------------------------

    else:

        st.markdown(
            "### Select target product"
        )

        st.caption(
            "Draw one rectangle around the single product you want "
            "the audit to focus on."
        )

        try:
            image_width, image_height = get_image_dimensions(
                audit_image
            )

            canvas_width, canvas_height = _fit_canvas_dimensions(
                image_width,
                image_height,
            )

        except Exception as exc:
            st.error(
                f"The image dimensions could not be prepared: {exc}"
            )
            st.stop()

        canvas_result = st_canvas(
            fill_color="rgba(255, 0, 0, 0.15)",
            stroke_width=3,
            stroke_color="#ff4b4b",
            background_image=image_bytes,
            update_streamlit=True,
            height=canvas_height,
            width=canvas_width,
            drawing_mode="rect",
            background_image_fit="stretch",
            return_image_data=False,
            key="expanded_target_canvas",
        )

        if canvas_result.json_data is not None:
            st.write(canvas_result.json_data)

        rectangle = _extract_single_rectangle(
            canvas_result
        )

        canvas_objects = []

        if canvas_result.json_data is not None:
            canvas_objects = canvas_result.json_data.get(
                "objects",
                [],
            )

        rectangle_count = len(
            [
                obj
                for obj in canvas_objects
                if str(obj.get("type", "")).lower() == "rect"
            ]
        )

        if rectangle_count == 0:

            st.info(
                "Draw one rectangle around the target product "
                "to continue."
            )

        elif rectangle_count > 1:

            st.warning(
                "Expanded mode supports exactly one target product. "
                "Delete the extra rectangle(s) and keep only one."
            )

        elif rectangle is not None:

            try:
                angle = float(
                    rectangle.get(
                        "angle",
                        0.0,
                    )
                )

                if abs(angle) > 0.01:
                    st.warning(
                        "Keep the target rectangle unrotated so the "
                        "selected product can be mapped accurately."
                    )

                else:

                    (
                        selection_x,
                        selection_y,
                        selection_width,
                        selection_height,
                    ) = _rectangle_coordinates(
                        rectangle
                    )

                    target_region = normalize_target_region(
                        x=selection_x,
                        y=selection_y,
                        width=selection_width,
                        height=selection_height,
                        canvas_width=canvas_width,
                        canvas_height=canvas_height,
                    )

                    target_crop = crop_target_region(
                        audit_image,
                        target_region,
                    )

                    st.success(
                        "Target product selected."
                    )

                    st.image(
                        target_crop.data,
                        caption="Selected target product",
                        use_container_width=False,
                    )

            except Exception as exc:

                target_region = None
                target_crop = None

                st.warning(
                    f"The selected target could not be prepared: {exc}"
                )


    # -----------------------------------------------------
    # Analyze
    # -----------------------------------------------------

    expanded_target_ready = (
        audit_mode is AuditMode.EXPANDED
        and target_region is not None
    )

    analyze_disabled = (
        audit_mode is AuditMode.EXPANDED
        and not expanded_target_ready
    )

    analyze = st.button(
        "Analyze Shelf",
        type="primary",
        use_container_width=True,
        disabled=analyze_disabled,
    )


    if analyze:

        try:

            provider = MockAuditProvider()

            with st.spinner(
                "Analyzing shelf opportunities..."
            ):

                result = run_audit(
                    image=audit_image,
                    criteria=criteria,
                    mode=audit_mode,
                    depth=audit_depth,
                    target_region=target_region,
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
            f"{mode_config.label} · "
            f"{depth_config.label}"
        )