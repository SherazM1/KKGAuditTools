"""
Shelf Audit Tool

Current foundation:
- camera or image upload
- target-based UI using existing Expanded / Deep backend behavior
- provider-neutral audit pipeline
- ranked opportunities
- target-region image helpers
- single-target Expanded mode selection
- OpenAI provider controlled by server-side AI enablement
"""

import streamlit as st

from .audit import run_audit
from .criteria import load_criteria
from .guardrails import GuardrailError
from .image_utils import (
    build_audit_image,
    crop_target_region,
    hash_image,
    preprocess_audit_image,
)
from .models import AuditMode, AuditDepth
from .target_selector import select_target, parse_selection
from .providers.base import ProviderConfigurationError
from .providers.openai import OpenAIAuditProvider, OpenAIProviderConfig
from .infrastructure.cache import MemoryAuditCache
from .infrastructure.rate_limit import MemoryRateLimiter, RateLimitError
from .infrastructure.usage import MemoryUsageTracker
from .reporting.ui import render_report_section


# ---------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------

def _clear_completed_audit(state) -> None:
    for key in (
        "shelf_audit_completed_result",
        "shelf_audit_report_document",
        "shelf_audit_completed_photo",
    ):
        state.pop(key, None)


def _clear_expanded_target(state) -> None:
    """Remount the component so its rectangle/history cannot survive a reset.

    Target coordinates and crop previews are derived locally from this
    component on each run; there is no separately retained crop to restore.
    """
    old_key = state.pop("shelf_audit_target_canvas_key", None)
    if old_key is not None:
        state.pop(old_key, None)
    state.pop("shelf_audit_active_target", None)
    state["shelf_audit_target_generation"] = (
        state.get("shelf_audit_target_generation", 0) + 1
    )


def _sync_audit_context(state, image_id: str | None, mode: AuditMode) -> None:
    """Invalidate only image/mode-dependent UI state, not audit infrastructure."""
    context = (image_id, mode.value)
    previous = state.get("shelf_audit_active_context")
    if previous is not None and previous != context:
        _clear_expanded_target(state)
        _clear_completed_audit(state)
    state["shelf_audit_active_context"] = context


def _expanded_canvas_key(state, image_id: str) -> str:
    """Bind drawing state to the prepared image and current reset generation."""
    generation = state.get("shelf_audit_target_generation", 0)
    key = f"shelf_audit_expanded_target_canvas_{image_id}_{generation}"
    state["shelf_audit_target_canvas_key"] = key
    return key


def _sync_target(state, region) -> None:
    """Invalidate completed work whenever the normalized subject changes."""
    signature = None if region is None else (region.x, region.y, region.width, region.height)
    if state.get("shelf_audit_active_target") != signature:
        _clear_completed_audit(state)
    state["shelf_audit_active_target"] = signature


# ---------------------------------------------------------
# Page setup
# ---------------------------------------------------------

def render():
    """Render the Shelf Audit workflow within the parent hub."""
    st.title("Shelf Audit Tool")

    try:
        ai_enabled = st.secrets.get("AI_ENABLED", False)
    except FileNotFoundError:
        ai_enabled = False
    except Exception:
        st.error("AI analysis is not configured correctly. Contact the app owner.")
        st.stop()
        return

    if not isinstance(ai_enabled, bool):
        st.error("AI analysis is not configured correctly. Contact the app owner.")
        st.stop()
        return

    if "shelf_audit_cache" not in st.session_state:
        st.session_state["shelf_audit_cache"] = MemoryAuditCache()

    if "shelf_audit_rate_limiter" not in st.session_state:
        st.session_state["shelf_audit_rate_limiter"] = MemoryRateLimiter(
            max_requests=5,
            window_seconds=60,
        )

    if "shelf_audit_usage_tracker" not in st.session_state:
        st.session_state["shelf_audit_usage_tracker"] = MemoryUsageTracker(
            max_records = 500,
        )


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


    # Compatibility migration: only the page fixes these choices.
    # Backend enums, configurations, fingerprints and telemetry stay intact.
    audit_mode = AuditMode.EXPANDED
    audit_depth = AuditDepth.DEEP

    # ---------------------------------------------------------
    # Image source
    # ---------------------------------------------------------

    st.subheader("Shelf image")

    input_method = st.radio(
        "Choose an image source:",
        key="shelf_audit_image_source",
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
            "Take a shelf photo",
            key="shelf_audit_camera",
        )

        image_source = "camera"

    else:

        image_file = st.file_uploader(
            "Upload a shelf photo",
            key="shelf_audit_upload",
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

            audit_image = preprocess_audit_image(
                audit_image
            )

        except Exception as exc:
            _sync_audit_context(st.session_state, None, audit_mode)
            st.error(
                f"The image could not be prepared: {exc}"
            )
            st.stop()

        image_id = hash_image(audit_image)
        _sync_audit_context(st.session_state, image_id, audit_mode)

        target_region = None
        target_crop = None
        st.markdown("### Select the area you want to audit.")
        selection = select_target(
            audit_image, key=_expanded_canvas_key(st.session_state, image_id)
        )
        try:
            target_region = parse_selection(selection)
            if target_region is not None:
                target_crop = crop_target_region(audit_image, target_region)
                st.image(target_crop.data, caption="Selected audit area", use_container_width=True)
            else:
                st.info("Select the area you want to audit.")
        except Exception as exc:
            target_region = None
            target_crop = None
            st.warning(f"The selected target could not be prepared: {exc}")
        _sync_target(st.session_state, target_region)

        # -----------------------------------------------------
        # Analyze
        # -----------------------------------------------------

        target_ready = target_region is not None and target_crop is not None

        analyze = st.button(
            "Analyze Shelf",
            key="shelf_audit_analyze",
            type="primary",
            use_container_width=True,
            disabled=not target_ready,
        )


        if analyze and target_ready:

            _clear_completed_audit(st.session_state)

            try:

                api_key = None
                if ai_enabled:
                    try:
                        api_key = st.secrets.get("OPENAI_API_KEY", None)
                    except Exception:
                        raise ProviderConfigurationError(
                            "AI configuration is unavailable."
                        ) from None
                    if not isinstance(api_key, str) or not api_key.strip():
                        raise ProviderConfigurationError(
                            "AI configuration is incomplete."
                        )

                provider = OpenAIAuditProvider(
                    config=OpenAIProviderConfig(
                        model_name="gpt-6.1-sol",
                        request_timeout_seconds=45.0,
                        max_output_tokens=3000,
                        max_retries=0,
                        network_enabled=ai_enabled,
                        input_cost_per_million_tokens=2.0,
                        output_cost_per_million_tokens=10.0,
                        reasoning_effort="low",
                        image_detail="high",
                    ),
                    api_key=api_key,
                )

                with st.spinner(
                    "Analyzing shelf opportunities..."
                ):

                    result = run_audit(
                        image=audit_image,
                        criteria=criteria,
                        mode=audit_mode,
                        depth=audit_depth,
                        target_region=target_region,
                        target_crop=target_crop,
                        provider=provider,
                        cache=st.session_state["shelf_audit_cache"],
                        rate_limiter=st.session_state["shelf_audit_rate_limiter"],
                        rate_limit_key="shelf_audit",
                        usage_tracker=st.session_state["shelf_audit_usage_tracker"],
                        ai_enabled=ai_enabled,
                    )

            except GuardrailError as exc:

                st.error(
                    f"Image or audit validation failed: {exc}"
                )

                st.stop()

            except RateLimitError as exc:

                st.warning(
                    str(exc)
                )

                st.stop()

            except ProviderConfigurationError:

                st.error(
                    "AI analysis is not configured correctly. Contact the app owner."
                    if ai_enabled else "AI analysis is currently disabled."
                )

                st.stop()

            except Exception:

                st.error(
                    f"The audit could not be completed. Please try again later or contact the app owner."
                )

                st.stop()


            st.session_state["shelf_audit_completed_result"] = result
            # Retain the exact upload/camera bytes, not the processed audit image
            # or Expanded-mode crop. Associate them only with this successful run.
            st.session_state["shelf_audit_completed_photo"] = image_bytes

    else:
        _sync_audit_context(st.session_state, None, audit_mode)

    # Persist successful final results across report form/download reruns.
    result = st.session_state.get("shelf_audit_completed_result")
    if result is not None:
        st.divider()
        st.subheader("Shelf Opportunities")
        if not result.opportunities:
            st.info("No opportunities were identified for this image.")
        else:
            for index, opportunity in enumerate(result.opportunities, start=1):
                st.markdown(f"### {index}. {opportunity.title}")
                st.markdown(f"**Why:** {opportunity.evidence}")
                st.markdown(f"**Recommendation:** {opportunity.recommendation}")
                st.write("")
        st.divider()
        render_report_section(
            result, audit_photo=st.session_state.get("shelf_audit_completed_photo")
        )
