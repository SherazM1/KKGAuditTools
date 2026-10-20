"""Streamlit UI for the Display Compliance module."""

from __future__ import annotations

from dataclasses import asdict
from dataclasses import replace
from uuid import uuid4

import streamlit as st
from .baseline import (
    MAX_DISPLAY_SIDES,
    ReferenceUpload,
    prepare_baseline,
    prepare_reference_image
)
from .models import DisplayBaseline, MatchingRequirements, ProductRegion
from .proposal_backends import (
    RegionProposalBackendUnavailable,
)
from .segmentation import (
    DisplayComplianceSegmentationError,
    analyze_candidate_regions,
    render_annotated_preview,
)

from .mapping import (
    MappingValidationError,
    add_position,
    create_grid_positions,
    delete_position,
    update_position,
    validate_regions,
)
from .storage import LocalBaselineStorage, baseline_from_dict

_SELECTED_BASELINE_KEY = "display_compliance_selected_baseline_id"
_ANNOTATED_PREVIEW_BYTES_KEY = "display_compliance_annotated_preview_bytes"
_ANNOTATED_PREVIEW_BASELINE_KEY = "display_compliance_annotated_preview_baseline_id"
_DETECTION_DIAGNOSTICS_KEY = "display_compliance_detection_diagnostics"
_DETECTION_DIAGNOSTIC_IMAGES_KEY = "display_compliance_detection_diagnostic_images"
_DETECTION_DIAGNOSTIC_SAMPLE_KEY = "display_compliance_detection_diagnostic_sample"
_DETECTION_DIAGNOSTIC_BASELINE_KEY = "display_compliance_detection_diagnostic_baseline_id"
_DETECTION_METHOD_KEY = "display_compliance_detection_method"
_CLASSICAL_METHOD = "Classical CV"
_LEARNED_METHOD = "Learned Segmentation - Experimental"


def _initialize_display_compliance_state() -> None:
    st.session_state.setdefault("display_compliance_created_baseline", None)
    st.session_state.setdefault("display_compliance_status_message", None)
    st.session_state.setdefault(_SELECTED_BASELINE_KEY, None)
    st.session_state.setdefault(_ANNOTATED_PREVIEW_BYTES_KEY, None)
    st.session_state.setdefault(_ANNOTATED_PREVIEW_BASELINE_KEY, None)
    st.session_state.setdefault(_DETECTION_DIAGNOSTICS_KEY, None)
    st.session_state.setdefault(_DETECTION_DIAGNOSTIC_IMAGES_KEY, None)
    st.session_state.setdefault(_DETECTION_DIAGNOSTIC_SAMPLE_KEY, None)
    st.session_state.setdefault(_DETECTION_DIAGNOSTIC_BASELINE_KEY, None)
    st.session_state.setdefault(_DETECTION_METHOD_KEY, _CLASSICAL_METHOD)


def _created_baseline() -> DisplayBaseline | None:
    payload = st.session_state.get("display_compliance_created_baseline")
    if not payload:
        return None
    return baseline_from_dict(payload)


def _baseline_metadata_rows(baseline: DisplayBaseline) -> list[dict[str, object]]:
    return [
        {"Field": "Baseline Name", "Value": baseline.name},
        {"Field": "Source Filename", "Value": baseline.reference_filename},
        {
            "Field": "Reference Dimensions",
            "Value": f"{baseline.reference_width} x {baseline.reference_height}",
        },
        {"Field": "Baseline ID", "Value": baseline.baseline_id},
        {"Field": "Detected Region Count", "Value": str(len(baseline.regions))},
    ]


def _sanitize_selected_baseline_state(baseline_options: dict[str, DisplayBaseline]) -> None:
    selected_baseline_id = st.session_state.get(_SELECTED_BASELINE_KEY)
    if selected_baseline_id is not None and selected_baseline_id not in baseline_options:
        st.session_state.pop(_SELECTED_BASELINE_KEY, None)


def _clear_stale_preview_state(active_baseline_id: str | None) -> None:
    preview_baseline_id = st.session_state.get(_ANNOTATED_PREVIEW_BASELINE_KEY)
    if preview_baseline_id is not None and preview_baseline_id != active_baseline_id:
        st.session_state.pop(_ANNOTATED_PREVIEW_BYTES_KEY, None)
        st.session_state.pop(_ANNOTATED_PREVIEW_BASELINE_KEY, None)

    diagnostics_baseline_id = st.session_state.get(_DETECTION_DIAGNOSTIC_BASELINE_KEY)
    if diagnostics_baseline_id is not None and diagnostics_baseline_id != active_baseline_id:
        st.session_state.pop(_DETECTION_DIAGNOSTICS_KEY, None)
        st.session_state.pop(_DETECTION_DIAGNOSTIC_IMAGES_KEY, None)
        st.session_state.pop(_DETECTION_DIAGNOSTIC_SAMPLE_KEY, None)
        st.session_state.pop(_DETECTION_DIAGNOSTIC_BASELINE_KEY, None)


def _format_baseline_option(
    baseline_id: str | None,
    baseline_options: dict[str, DisplayBaseline],
) -> str:
    if baseline_id is None:
        return "Choose an option"
    baseline = baseline_options.get(baseline_id)
    return baseline.name if baseline is not None else "Unavailable baseline"


def _render_detection_diagnostics(baseline_id: str) -> None:
    if st.session_state.get(_DETECTION_DIAGNOSTIC_BASELINE_KEY) != baseline_id:
        return
    diagnostics = st.session_state.get(_DETECTION_DIAGNOSTICS_KEY)
    if not diagnostics:
        return

    st.subheader("Detection Diagnostics")
    if diagnostics.get("backend") == "sam2":
        rows = [
            {"Metric": "Original width", "Value": diagnostics["original_width"]},
            {"Metric": "Original height", "Value": diagnostics["original_height"]},
            {"Metric": "Working width", "Value": diagnostics["working_width"]},
            {"Metric": "Working height", "Value": diagnostics["working_height"]},
            {"Metric": "Backend", "Value": "SAM 2"},
            {"Metric": "Device", "Value": diagnostics["device"]},
            {"Metric": "Model load seconds", "Value": diagnostics["model_load_seconds"]},
            {"Metric": "Inference seconds", "Value": diagnostics["inference_seconds"]},
            {"Metric": "Total seconds", "Value": diagnostics["total_seconds"]},
            {"Metric": "Raw learned masks", "Value": diagnostics["raw_mask_count"]},
            {"Metric": "Rejected too small", "Value": diagnostics["rejected_too_small"]},
            {"Metric": "Rejected too large", "Value": diagnostics["rejected_too_large"]},
            {"Metric": "Rejected thin/degenerate", "Value": diagnostics["rejected_degenerate"]},
            {"Metric": "Rejected aspect ratio", "Value": diagnostics["rejected_aspect_ratio"]},
            {"Metric": "Rejected low confidence", "Value": diagnostics["rejected_low_confidence"]},
            {"Metric": "Rejected low solidity", "Value": diagnostics["rejected_low_solidity"]},
            {
                "Metric": "After basic filtering",
                "Value": diagnostics["proposals_after_basic_filtering"],
            },
            {
                "Metric": "Removed by IoU dedup",
                "Value": diagnostics["removed_by_iou_deduplication"],
            },
            {
                "Metric": "Removed as nested duplicates",
                "Value": diagnostics["removed_by_nested_deduplication"],
            },
            {
                "Metric": "After duplicate cleanup",
                "Value": diagnostics["proposals_after_duplicate_cleanup"],
            },
            {"Metric": "Repeated-size clusters", "Value": diagnostics["size_cluster_count"]},
            {
                "Metric": "Repeated-size proposals",
                "Value": diagnostics["repeated_size_member_count"],
            },
            {
                "Metric": "Alignment-supported proposals",
                "Value": diagnostics["alignment_supported_count"],
            },
            {"Metric": "Final candidate regions", "Value": diagnostics["final_region_count"]},
        ]
    else:
        rows = [
            {"Metric": "Original width", "Value": diagnostics["original_width"]},
            {"Metric": "Original height", "Value": diagnostics["original_height"]},
            {"Metric": "Working width", "Value": diagnostics["working_width"]},
            {"Metric": "Working height", "Value": diagnostics["working_height"]},
            {"Metric": "Strategy A raw proposals", "Value": diagnostics["strategy_a_raw_proposal_count"]},
            {"Metric": "Strategy A after filtering", "Value": diagnostics["strategy_a_proposals_after_geometry_filter"]},
            {"Metric": "Strategy B raw proposals", "Value": diagnostics["strategy_b_raw_proposal_count"]},
            {"Metric": "Strategy B after filtering", "Value": diagnostics["strategy_b_proposals_after_geometry_filter"]},
            {"Metric": "Strategy C raw proposals", "Value": diagnostics["strategy_c_raw_proposal_count"]},
            {"Metric": "Strategy C after filtering", "Value": diagnostics["strategy_c_proposals_after_geometry_filter"]},
            {"Metric": "Merged pool before dedup", "Value": diagnostics["merged_pool_count_before_dedup"]},
            {
                "Metric": "Removed by IoU dedup",
                "Value": diagnostics["removed_by_iou_deduplication"],
            },
            {
                "Metric": "Removed by coverage dedup",
                "Value": diagnostics["removed_by_coverage_deduplication"],
            },
            {
                "Metric": "Removed during dedup",
                "Value": diagnostics["removed_by_deduplication"],
            },
            {"Metric": "Repeated-size clusters", "Value": diagnostics["size_cluster_count"]},
            {
                "Metric": "Repeated-size proposals",
                "Value": diagnostics["repeated_size_member_count"],
            },
            {
                "Metric": "Alignment-boosted proposals",
                "Value": diagnostics["alignment_boosted_count"],
            },
            {
                "Metric": "Multi-strategy proposals",
                "Value": diagnostics["multi_strategy_supported_count"],
            },
            {"Metric": "Final candidate regions", "Value": diagnostics["final_region_count"]},
        ]
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )

    diagnostic_images = st.session_state.get(_DETECTION_DIAGNOSTIC_IMAGES_KEY) or {}
    proposal_sample = st.session_state.get(_DETECTION_DIAGNOSTIC_SAMPLE_KEY) or []
    if not diagnostic_images and not proposal_sample:
        return

    with st.expander("View Detection Diagnostics"):
        for key, label in [
            ("normalized", "Normalized"),
            ("edges", "Edge Map"),
            ("threshold", "Adaptive Threshold"),
            ("morphology", "Morphology"),
            ("strategy_a_proposals", "Strategy A: Morphology Contours"),
            ("strategy_b_proposals", "Strategy B: Cleaned Edges"),
            ("strategy_c_proposals", "Strategy C: Structural Rectangles"),
            ("merged_proposals", "Merged Proposals Before Dedup"),
            ("final_proposals", "Final Proposals"),
            ("learned_raw_masks", "Learned: Raw Masks"),
            ("learned_raw_bboxes", "Learned: Raw Bounding Boxes"),
            ("learned_after_basic_filtering", "Learned: After Basic Filtering"),
            ("learned_after_duplicate_cleanup", "Learned: After Duplicate Cleanup"),
            ("learned_structurally_supported", "Learned: Structurally Supported"),
            ("learned_final_regions", "Learned: Final Regions"),
        ]:
            image_bytes = diagnostic_images.get(key)
            if image_bytes:
                st.image(image_bytes, caption=label, use_container_width=True)
        if proposal_sample:
            st.dataframe(proposal_sample, use_container_width=True, hide_index=True)


@st.cache_data(max_entries=8, ttl=3600, show_spinner=False)
def _prepared_upload_preview(image_bytes: bytes) -> bytes:
    """Return a normalized preview of an uploaded reference image."""
    prepared = prepare_reference_image(image_bytes)
    return prepared.image_bytes

def _mapping_preview(
        *,
        image_bytes: bytes,
        regions: list[ProductRegion],

) -> bytes:
    """Show readable position numbers without changing any IDs"""
    if not regions:
        return image_bytes

    numbered_regions = [
        replace(region, region_id=f"region_{index:03}")
        for index, region in enumerate(regions, start=1)
    ]
    return render_annotated_preview(
        image_bytes=image_bytes,
        regions=numbered_regions,
    )









def _render_mapping_editor(
    *,
    regions: list[ProductRegion],
    image_width: int,
    image_height: int,
    editor_key: str,
    protected_region_ids: set[str],
) -> list[ProductRegion] | None:
    """Return changed positions after an explicit editor action."""
    st.subheader("Edit Positions")
    st.caption(
        "Coordinates use the full reference image: x, y, width, height. "
        f"Image size: {image_width} × {image_height} pixels."
    )

    operation = st.radio(
        "Mapping Action",
        ["Edit position", "Add position", "Add grid"],
        horizontal=True,
        key=f"{editor_key}_operation",
    )

    selected = None
    if operation == "Edit position":
        if not regions:
            st.info("Add a position or grid to begin.")
            return None

        region_options = {
            region.region_id: region
            for region in regions
        }
        labels = {
            region.region_id: (
                f"{index}. {region.label or 'Position'}"
            )
            for index, region in enumerate(regions, start=1)
        }
        selection_key = f"{editor_key}_selected"
        if st.session_state.get(selection_key) not in region_options:
            st.session_state.pop(selection_key, None)

        selected_id = st.selectbox(
            "Position",
            options=list(region_options),
            format_func=lambda value: labels[value],
            key=selection_key,
        )
        selected = region_options[selected_id]

        if selected.bbox is None:
            st.warning(
                "This position has polygon-only geometry. "
                "The rectangle editor cannot edit it yet."
            )
            return None

    defaults = (
        selected.bbox
        if selected is not None
        else (0, 0, image_width, image_height)
    )
    form_key = (
        f"{editor_key}_{operation}_"
        f"{selected.region_id if selected else 'new'}"
    )

    with st.form(form_key):
        columns = st.columns(4)
        values = []
        for column, name, value, minimum in zip(
            columns,
            ["X", "Y", "Width", "Height"],
            defaults,
            [0, 0, 1, 1],
        ):
            values.append(
                int(
                    column.number_input(
                        name,
                        min_value=minimum,
                        value=int(value),
                        step=1,
                        key=f"{form_key}_{name.lower()}",
                    )
                )
            )
        bbox = tuple(values)

        label = ""
        rows = 1
        grid_columns = 1

        if operation == "Add grid":
            left, right = st.columns(2)
            rows = int(
                left.number_input(
                    "Rows",
                    min_value=1,
                    max_value=500,
                    value=1,
                    step=1,
                    key=f"{form_key}_rows",
                )
            )
            grid_columns = int(
                right.number_input(
                    "Columns",
                    min_value=1,
                    max_value=500,
                    value=1,
                    step=1,
                    key=f"{form_key}_columns",
                )
            )
            st.caption(
                "Adds equal rectangular cells within the specified area. "
                "Existing positions are retained."
            )
        else:
            label = st.text_input(
                "Position Label",
                value=selected.label if selected else "",
                key=f"{form_key}_label",
            )

        apply_clicked = st.form_submit_button("Apply to Unsaved Draft")

        delete_clicked = False
        if selected is not None:
            linked = (
                selected.expected_product_id is not None
                or selected.region_id in protected_region_ids
            )
            delete_clicked = st.form_submit_button(
                "Delete Position from Draft",
                disabled=linked,
            )
            if linked:
                st.caption(
                    "Deletion is disabled because this position has product links."
                )

    try:
        if delete_clicked and selected is not None:
            return delete_position(
                regions,
                region_id=selected.region_id,
                protected_region_ids=protected_region_ids,
            )

        if not apply_clicked:
            return None

        if operation == "Edit position":
            return update_position(
                regions,
                region_id=selected.region_id,
                bbox=bbox,
                image_width=image_width,
                image_height=image_height,
                label=label,
            )

        if operation == "Add position":
            return add_position(
                regions,
                bbox=bbox,
                image_width=image_width,
                image_height=image_height,
                label=label,
            )

        grid = create_grid_positions(
            bbox=bbox,
            rows=rows,
            columns=grid_columns,
            image_width=image_width,
            image_height=image_height,
        )
        updated = [*regions, *grid]
        validate_regions(
            updated,
            image_width=image_width,
            image_height=image_height,
        )
        return updated

    except MappingValidationError as exc:
        st.error(str(exc))
        return None


def _render_candidate_detection(
    *,
    storage: LocalBaselineStorage,
    baseline: DisplayBaseline,
    side_id: str | None = None,
) -> None:
    """Propose regions without immediately changing saved mapping."""
    side = None
    if side_id is not None:
        side = next(
            (item for item in baseline.sides if item.side_id == side_id),
            None,
        )
        if side is None:
            st.error("Selected side is unavailable.")
            return

    context = (
        baseline.baseline_id,
        baseline.revision,
        side_id,
        side.reference_image_sha256 if side else "",
    )
    draft_key = (
        f"display_compliance_mapping_draft_"
        f"{baseline.baseline_id}_{side_id or 'legacy'}"
    )
    saved_regions = side.regions if side else baseline.regions

    image_width = (side.reference_width if side else baseline.reference_width)
    image_height = (side.reference_height if side else baseline.reference_height)

    try:
        image_bytes = (
            storage.load_side_reference_image_bytes(baseline, side_id)
            if side_id is not None
            else storage.load_reference_image_bytes(baseline)
        )
    except (OSError, ValueError) as exc:
        st.error(f"Could not load reference: {exc}")
        return

    st.subheader("Draft Product Positions")
    st.caption(
        "Local detection suggests positions; it does not identify products. "
        "Generated candidates remain unsaved until you save the draft mapping."
    )

    if baseline.status != "draft":
        st.info(
            "This baseline is read-only. Creating an editable draft from an "
            "approved version will be added with the approval workflow."
        )
        try:
            preview = _mapping_preview(
                image_bytes=image_bytes,
                regions=saved_regions,
            )
            st.image(preview, use_container_width=True)
        except (DisplayComplianceSegmentationError, ValueError) as exc:
            st.error(f"Could not render saved mapping: {exc}")
        return

    method = st.selectbox(
        "Region Proposal Method",
        options=[_CLASSICAL_METHOD, _LEARNED_METHOD],
        key=f"display_compliance_method_{context}",
    )

    if method == _LEARNED_METHOD:
        st.caption(
            "SAM runs locally and may download model weights on first use. "
            "There is no external AI API charge."
        )

    existing_draft = st.session_state.get(draft_key)
    allow_replacement = False

    if existing_draft is not None:
        allow_replacement = st.checkbox(
            "Replace my unsaved mapping with newly detected candidates",
            value=False,
            key=f"display_compliance_confirm_regenerate_{context}",
        )

    if st.button(
        "Generate Candidate Positions",
        key=f"display_compliance_generate_{context}",
        type="primary",
        disabled=existing_draft is not None and not allow_replacement,
    ):
        try:
            with st.spinner("Analyzing reference image..."):
                if method == _LEARNED_METHOD:
                    from .proposal_backends import (
                        analyze_learned_candidate_regions,
                    )

                    result = analyze_learned_candidate_regions(
                        image_bytes=image_bytes
                    )
                else:
                    result = analyze_candidate_regions(
                        image_bytes=image_bytes
                    )

                candidates = [
                    replace(region, region_id=uuid4().hex)
                    for region in result.regions
                ]
                preview = _mapping_preview(
                    image_bytes=image_bytes,
                    regions=candidates,
                )

            st.session_state[draft_key] = {
                "regions": candidates,
                "preview": preview,
                "source_metadata": asdict(baseline),
            }

            diagnostic_context = str(context)
            st.session_state[_DETECTION_DIAGNOSTICS_KEY] = asdict(
                result.diagnostics
            )
            st.session_state[_DETECTION_DIAGNOSTIC_IMAGES_KEY] = (
                result.diagnostic_images
            )
            st.session_state[_DETECTION_DIAGNOSTIC_SAMPLE_KEY] = [
                asdict(row)
                for row in getattr(result, "proposal_sample", [])
            ]
            st.session_state[_DETECTION_DIAGNOSTIC_BASELINE_KEY] = (
                diagnostic_context
            )

            st.success(
                f"Generated {len(candidates)} unsaved candidate position(s)."
            )
        except Exception as exc:
            st.error(f"Candidate generation failed: {exc}")

    if draft_key not in st.session_state:
        if st.button(
            "Edit Saved Mapping / Start Manual Mapping",
            key=f"display_compliance_edit_saved_{context}",
        ):
            st.session_state[draft_key] = {
                "regions": list(saved_regions),
                "preview": image_bytes,
                "source_metadata": asdict(baseline),
            }

    

    draft = st.session_state.get(draft_key)
    displayed_regions = draft["regions"] if draft else saved_regions
    if draft is not None and draft["source_metadata"] != asdict(baseline):
        st.warning(
            "This draft was started from an earlier baseline revision. "
            "Your edits are retained, but saving is blocked by the revision "
            "check. Discard the draft to start from the current saved version."
        )

    st.metric("Saved Draft Positions", len(saved_regions))

    if draft is not None:
        protected_region_ids = {
            product.reference_region_id
            for product in baseline.products
            if product.reference_region_id is not None
            and product.reference_side_id == side_id
        }

        # Protect linked products and their reference crops until
        # product-link review is implemented.
        mapping_has_links = any(
            region.expected_product_id is not None
            for region in saved_regions
        ) or bool(protected_region_ids)

        if mapping_has_links:
            st.warning(
                "Editing is disabled for product-linked mappings until "
                "product-link review is implemented."
            )
        else:
            changed_regions = _render_mapping_editor(
                regions=displayed_regions,
                image_width=image_width,
                image_height=image_height,
                editor_key=draft_key,
                protected_region_ids=protected_region_ids,
            )
            if changed_regions is not None:
                draft["regions"] = changed_regions
                st.session_state[draft_key] = draft
                st.rerun()

        st.metric("Unsaved Draft Positions", len(displayed_regions))

        try:
            preview = _mapping_preview(
                image_bytes=image_bytes,
                regions=displayed_regions,
            )
            st.image(
                preview,
                caption="Unsaved draft mapping",
                use_container_width=True,
            )
        except (DisplayComplianceSegmentationError, ValueError) as exc:
            st.error(f"Could not render draft mapping: {exc}")
        st.caption(
            "Saving replaces this side's draft positions. Candidate boundaries "
            "still need review; this does not approve the baseline."
        )

        has_product_links = any(
            region.expected_product_id is not None
            for region in saved_regions
        ) or any(
            product.reference_region_id is not None
            and (
                product.reference_side_id == side_id
                if side_id is not None
                else product.reference_side_id is None
            )
            for product in baseline.products
        )

        if has_product_links:
            st.warning(
                "This mapping has product links. Replacement is disabled until "
                "the mapping editor can preserve or explicitly remove them."
            )

        if not displayed_regions:
            st.warning(
                "This draft has no positions. Add a position or a grid before saving."
            )

        if st.button(
            "Save Draft Mapping",
            key=f"display_compliance_save_mapping_{context}",
            disabled=not displayed_regions or has_product_links,
        ):
            try:
                current = storage.load_baseline(baseline.baseline_id)
                if asdict(current) != draft["source_metadata"]:
                    raise ValueError(
                        "The baseline changed after these candidates were "
                        "generated. Discard them and generate again."
                    )
                if current.status != "draft":
                    raise ValueError("Only draft baselines can be edited.")

                if side_id is None:
                    updated = replace(
                        current,
                        regions=list(displayed_regions),
                        revision=current.revision + 1,
                    )
                else:
                    updated = replace(
                        current,
                        sides=[
                            replace(item, regions=list(displayed_regions))
                            if item.side_id == side_id
                            else item
                            for item in current.sides
                        ],
                        revision=current.revision + 1,
                    )
                validate_regions(
                    displayed_regions,
                    image_width=image_width,
                    image_height=image_height,
                )

                storage.save_draft_update(
                    updated,
                    expected_revision=draft["source_metadata"]["revision"],
                )
                st.session_state.pop(draft_key, None)
                st.session_state["display_compliance_status_message"] = (
                    "Draft mapping saved. Baseline remains unapproved."
                )
            except (OSError, ValueError) as exc:
                st.error(f"Could not save mapping: {exc}")
            else:
                st.rerun()

        if st.button(
            "Discard Unsaved Candidates",
            key=f"display_compliance_discard_{context}",
        ):
            st.session_state.pop(draft_key, None)
            st.rerun()
    else:
        try:
            preview = _mapping_preview(
                image_bytes=image_bytes,
                regions=saved_regions,
            )
            st.image(
                preview,
                caption=(
                    "Saved draft mapping"
                    if saved_regions
                    else "Reference image"
                ),
                use_container_width=True,
            )
        except (DisplayComplianceSegmentationError, ValueError) as exc:
            st.error(f"Could not render saved mapping: {exc}")

    _render_detection_diagnostics(str(context))



def render_display_compliance_view() -> None:
    """Render side-based baseline setup and draft mapping."""
    _initialize_display_compliance_state()
    storage = LocalBaselineStorage()

    st.title("Display Compliance")
    st.caption(
        "Set up correct reference photos and draft product positions. "
        "Product recognition and inspection checking are not enabled yet."
    )

    st.subheader("Create Display Baseline")
    baseline_name = st.text_input(
        "Display Name",
        key="display_compliance_baseline_name",
    )
    category = st.selectbox(
        "Product Category",
        options=["gift_cards", "batteries", "candy", "mixed", "other"],
        format_func=lambda value: value.replace("_", " ").title(),
        key="display_compliance_category",
    )

    attribute_defaults = {
        "gift_cards": ["retailer"],
        "batteries": ["brand", "battery_type", "pack_count"],
        "candy": ["brand", "product", "flavor", "package_size"],
        "mixed": [],
        "other": [],
    }
    attributes_text = st.text_input(
        "Attributes That Must Match",
        value=", ".join(attribute_defaults[category]),
        help=(
            "Comma-separated requirements. For example: retailer, denomination. "
            "These are saved instructions; enforcement is not implemented yet."
        ),
        key=f"display_compliance_attributes_{category}",
    )
    requirement_notes = st.text_area(
        "Placement Rules / Acceptable Variations",
        help="For example: seasonal artwork variations are acceptable.",
        key="display_compliance_requirement_notes",
    )

    side_mode = st.radio(
        "Display Sides",
        options=["One side", "Multiple sides"],
        horizontal=True,
        key="display_compliance_side_mode",
    )

    side_count = 1
    if side_mode == "Multiple sides":
        side_count = int(
            st.number_input(
                "Number of Sides",
                min_value=2,
                max_value=MAX_DISPLAY_SIDES,
                value=2,
                step=1,
                key="display_compliance_side_count",
            )
        )

    uploads: list[ReferenceUpload] = []
    all_uploaded = True
    default_names = ["Front", "Back", "Left", "Right"]

    for index in range(side_count):
        with st.expander(f"Reference Side {index + 1}", expanded=True):
            default_name = (
                default_names[index]
                if index < len(default_names)
                else f"Side {index + 1}"
            )
            side_name = st.text_input(
                "Side Name",
                value=default_name,
                key=f"display_compliance_side_name_{index}",
            )
            uploaded = st.file_uploader(
                "Correct Reference Photo",
                type=["png", "jpg", "jpeg"],
                key=f"display_compliance_side_upload_{index}",
            )

            if uploaded is None:
                all_uploaded = False
            else:
                uploaded_bytes = uploaded.getvalue()
                try:
                    preview_bytes = _prepared_upload_preview(uploaded_bytes)
                except ValueError as exc:
                    all_uploaded = False
                    st.error(f"{side_name or 'Reference side'}: {exc}")
                else:
                    st.image(
                        preview_bytes,
                        caption=side_name,
                        use_container_width=True,
                    )
                    uploads.append(
                        ReferenceUpload(
                            side_name=side_name,
                            filename=uploaded.name,
                            image_bytes=uploaded_bytes,
                        )
                    )

    if st.button(
        "Create Draft Baseline",
        type="primary",
        disabled=not all_uploaded,
        key="display_compliance_create_baseline",
    ):
        try:
            required_attributes = tuple(
                dict.fromkeys(
                    value.strip().lower()
                    for value in attributes_text.split(",")
                    if value.strip()
                )
            )
            prepared = prepare_baseline(
                name=baseline_name,
                uploads=uploads,
                category=category,
                matching_requirements=MatchingRequirements(
                    required_attributes=required_attributes,
                    notes=requirement_notes.strip(),
                ),
            )
            storage.save_prepared_baseline(
                prepared.baseline,
                prepared.reference_images,
            )

            # This assignment precedes creation of the selector below.
            st.session_state[_SELECTED_BASELINE_KEY] = (
                prepared.baseline.baseline_id
            )
            st.session_state["display_compliance_status_message"] = (
                f"Draft baseline saved with "
                f"{len(prepared.baseline.sides)} side(s)."
            )
        except (OSError, ValueError) as exc:
            st.error(f"Could not create baseline: {exc}")

    message = st.session_state.pop(
        "display_compliance_status_message",
        None,
    )
    if message:
        st.success(message)

    saved_baselines = storage.list_baselines()
    if storage.listing_errors:
        st.warning(
            f"{len(storage.listing_errors)} baseline(s) could not be loaded."
        )
        with st.expander("Baseline loading details"):
            st.dataframe(
                storage.listing_errors,
                use_container_width=True,
                hide_index=True,
            )

    baseline_options = {
        baseline.baseline_id: baseline
        for baseline in saved_baselines
    }
    _sanitize_selected_baseline_state(baseline_options)

    if not saved_baselines:
        st.info("Create a draft baseline above to begin.")
        return

    st.subheader("Saved Baselines")
    selected_id = st.selectbox(
        "Select Display",
        options=[None, *baseline_options],
        format_func=lambda value: _format_baseline_option(
            value,
            baseline_options,
        ),
        key=_SELECTED_BASELINE_KEY,
    )
    if selected_id is None:
        return

    baseline = baseline_options[selected_id]
    st.caption(
        f"Status: {baseline.status} · Revision: {baseline.revision} · "
        f"Category: {baseline.category}"
    )
    st.write(
        "Required attributes: "
        + (
            ", ".join(baseline.matching_requirements.required_attributes)
            or "Not specified"
        )
    )
    if baseline.matching_requirements.notes:
        st.write(baseline.matching_requirements.notes)

    if baseline.sides:
        side_options = {
            side.side_id: side
            for side in baseline.sides
        }
        selected_side_id = st.selectbox(
            "Reference Side",
            options=list(side_options),
            format_func=lambda value: side_options[value].name,
            key=f"display_compliance_selected_side_{baseline.baseline_id}",
        )
        _render_candidate_detection(
            storage=storage,
            baseline=baseline,
            side_id=selected_side_id,
        )
    else:
        st.info(
            "Legacy single-reference baseline. Existing image and regions "
            "remain available; conversion to sides has not been performed."
        )
        _render_candidate_detection(
            storage=storage,
            baseline=baseline,
        )



def render() -> None:
    """Render Display Compliance inside the KKG Auditing hub."""
    render_display_compliance_view()
