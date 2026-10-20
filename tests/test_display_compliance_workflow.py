"""Reference-to-mapping workflow checks using temporary storage and mocks."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from io import BytesIO
import subprocess
import sys
import struct
from pathlib import Path
import zlib

from PIL import Image
import pytest

from display_compliance import page
from display_compliance.baseline import (
    ReferenceUpload,
    prepare_baseline,
    prepare_reference_image,
)
from display_compliance.mapping import (
    add_position,
    create_grid_positions,
    delete_position,
    update_position,
)
from display_compliance.models import DisplayBaseline, ProductRegion
from display_compliance.storage import LocalBaselineStorage


def _png_bytes(width: int = 16, height: int = 12) -> bytes:
    def chunk(kind: bytes, content: bytes) -> bytes:
        checksum = zlib.crc32(kind + content) & 0xFFFFFFFF
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\0" + b"\xff\x20\x10" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _Upload:
    def __init__(self, name: str, content: bytes) -> None:
        self.name = name
        self.content = content

    def getvalue(self) -> bytes:
        return self.content


class _UI:
    def __init__(
        self,
        *,
        state: dict[str, object] | None = None,
        clicked: set[str] | None = None,
        uploads: dict[str, _Upload] | None = None,
        values: dict[str, object] | None = None,
    ) -> None:
        self.session_state = state if state is not None else {}
        self.clicked = clicked or set()
        self.uploads = uploads or {}
        self.values = values or {}
        self.button_calls: list[dict[str, object]] = []
        self.checkbox_calls: list[dict[str, object]] = []
        self.image_calls: list[dict[str, object]] = []
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def button(self, label: str, **kwargs: object) -> bool:
        self.button_calls.append({"label": label, **kwargs})
        return (
            kwargs.get("key", label) in self.clicked
            and not bool(kwargs.get("disabled", False))
        )

    def checkbox(self, label: str, **kwargs: object) -> bool:
        self.checkbox_calls.append({"label": label, **kwargs})
        return bool(
            self.values.get(
                str(kwargs.get("key")),
                kwargs.get("value", False),
            )
        )

    def selectbox(self, label: str, *, options, **kwargs):
        key = str(kwargs["key"])
        value = self.values.get(key, self.session_state.get(key))
        if value not in options:
            value = options[0]
        self.session_state[key] = value
        return value

    def radio(self, label: str, options, **kwargs):
        value = self.values.get(str(kwargs.get("key")), options[0])
        return value if value in options else options[0]

    def text_input(self, label: str, **kwargs):
        key = str(kwargs.get("key", label))
        return str(self.values.get(key, kwargs.get("value", "")))

    def text_area(self, label: str, **kwargs):
        key = str(kwargs.get("key", label))
        return str(self.values.get(key, kwargs.get("value", "")))

    def number_input(self, label: str, **kwargs):
        key = str(kwargs.get("key", label))
        return self.values.get(key, kwargs.get("value", 0))

    def file_uploader(self, label: str, **kwargs):
        return self.uploads.get(str(kwargs.get("key")))

    def image(self, *args, **kwargs):
        self.image_calls.append({"args": args, **kwargs})

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def __getattr__(self, name: str):
        if name in {"expander", "spinner", "form"}:
            return lambda *args, **kwargs: _Context()
        if name == "columns":
            return lambda count: [self for _ in range(count)]
        if name == "form_submit_button":
            return lambda label, **kwargs: (
                label in self.clicked and not kwargs.get("disabled", False)
            )
        if name == "rerun":
            return lambda: None
        return lambda *args, **kwargs: None


@pytest.mark.parametrize(
    ("side_mode", "side_count"),
    [("One side", 1), ("Multiple sides", 2)],
)
def test_ui_creates_normalized_reference_sides_without_products(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    side_mode: str,
    side_count: int,
) -> None:
    original = _png_bytes()
    uploads = {
        f"display_compliance_side_upload_{index}": _Upload(
            f"side-{index}.png",
            original,
        )
        for index in range(side_count)
    }
    ui = _UI(
        clicked={"display_compliance_create_baseline"},
        uploads=uploads,
        values={
            "display_compliance_side_mode": side_mode,
            "display_compliance_side_count": side_count,
            "display_compliance_baseline_name": "Reference only",
        },
    )
    storage = LocalBaselineStorage(tmp_path)
    monkeypatch.setattr(page, "st", ui)
    monkeypatch.setattr(page, "LocalBaselineStorage", lambda: storage)
    monkeypatch.setattr(
        page,
        "_prepared_upload_preview",
        lambda image_bytes: prepare_reference_image(image_bytes).image_bytes,
    )
    monkeypatch.setattr(page, "_mapping_preview", lambda **kwargs: b"preview")

    page.render_display_compliance_view()

    baselines = storage.list_baselines()
    assert len(baselines) == 1
    baseline = baselines[0]
    assert len(baseline.sides) == side_count
    assert baseline.products == []
    for side in baseline.sides:
        normalized = prepare_reference_image(original)
        stored = storage.load_side_reference_image_bytes(
            baseline,
            side.side_id,
        )
        assert stored == normalized.image_bytes
        assert side.reference_image_sha256 == sha256(stored).hexdigest()
        with Image.open(BytesIO(stored)) as image:
            assert image.format == "PNG"
            assert image.size == (side.reference_width, side.reference_height)
    assert not ui.errors


def test_draft_positions_can_be_managed_and_saved_without_products(
    tmp_path: Path,
) -> None:
    prepared = prepare_baseline(
        name="No product assignments",
        uploads=[
            ReferenceUpload(
                side_name="Front",
                filename="front.png",
                image_bytes=_png_bytes(),
            )
        ],
    )
    baseline = prepared.baseline
    storage = LocalBaselineStorage(tmp_path)
    storage.save_prepared_baseline(baseline, prepared.reference_images)
    original = ProductRegion(
        region_id="position-original",
        bbox=(1, 1, 3, 3),
    )

    added = add_position(
        [original],
        bbox=(5, 1, 3, 3),
        image_width=baseline.reference_width,
        image_height=baseline.reference_height,
    )
    edited = update_position(
        added,
        region_id=original.region_id,
        bbox=(2, 2, 4, 4),
        image_width=baseline.reference_width,
        image_height=baseline.reference_height,
    )
    assert edited[0].region_id == original.region_id
    assert edited[0].bbox == (2, 2, 4, 4)
    assert edited[1].region_id != original.region_id

    deleted = delete_position(edited, region_id=edited[1].region_id)
    side = replace(baseline.sides[0], regions=deleted)
    updated = replace(baseline, sides=[side], revision=2)
    saved = storage.save_draft_update(updated, expected_revision=1)

    assert saved.products == []
    assert storage.load_baseline(baseline.baseline_id) == updated
    assert storage.load_side_reference_image_bytes(
        updated,
        side.side_id,
    ) == prepared.reference_images[side.side_id]


def test_preview_numbers_follow_mapping_order_without_changing_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    regions = [
        ProductRegion(region_id="position-z", bbox=(1, 1, 2, 2)),
        ProductRegion(region_id="position-a", bbox=(4, 1, 2, 2)),
    ]
    rendered: list[list[ProductRegion]] = []
    monkeypatch.setattr(
        page,
        "render_annotated_preview",
        lambda *, image_bytes, regions: rendered.append(regions) or b"preview",
    )

    assert page._mapping_preview(
        image_bytes=b"reference",
        regions=regions,
    ) == b"preview"
    assert [region.region_id for region in rendered[0]] == [
        "region_001",
        "region_002",
    ]
    assert [region.region_id for region in regions] == [
        "position-z",
        "position-a",
    ]


def test_switching_sides_keeps_each_unsaved_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = prepare_baseline(
        name="Two sides",
        uploads=[
            ReferenceUpload("Front", "front.png", _png_bytes()),
            ReferenceUpload("Back", "back.png", _png_bytes()),
        ],
    )
    baseline = prepared.baseline
    state: dict[str, object] = {}
    ui = _UI(state=state)
    monkeypatch.setattr(page, "st", ui)
    monkeypatch.setattr(page, "_mapping_preview", lambda **kwargs: b"preview")
    monkeypatch.setattr(page, "_render_mapping_editor", lambda **kwargs: None)
    monkeypatch.setattr(page, "_render_detection_diagnostics", lambda *_args: None)

    for index, side in enumerate(baseline.sides):
        draft_key = (
            f"display_compliance_mapping_draft_{baseline.baseline_id}_{side.side_id}"
        )
        region = ProductRegion(
            region_id=f"draft-{index}",
            bbox=(index + 1, 1, 2, 2),
        )
        state[draft_key] = {
            "regions": [region],
            "source_metadata": asdict(baseline),
        }
        page._render_candidate_detection(
            storage=type(
                "Storage",
                (),
                {
                    "load_side_reference_image_bytes": (
                        lambda _self, _baseline, _side_id: b"reference"
                    )
                },
            )(),
            baseline=baseline,
            side_id=side.side_id,
        )

    assert [
        state[
            f"display_compliance_mapping_draft_{baseline.baseline_id}_{side.side_id}"
        ]["regions"][0].region_id
        for side in baseline.sides
    ] == ["draft-0", "draft-1"]


def test_regeneration_button_requires_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = DisplayBaseline(
        baseline_id="regenerate-test",
        name="Draft",
        reference_filename="reference.png",
        reference_width=16,
        reference_height=12,
    )
    context = (baseline.baseline_id, baseline.revision, None, "")
    draft_key = (
        f"display_compliance_mapping_draft_{baseline.baseline_id}_legacy"
    )
    state = {
        draft_key: {
            "regions": [ProductRegion(region_id="keep-me", bbox=(1, 1, 3, 3))],
            "source_metadata": asdict(baseline),
        }
    }
    ui = _UI(state=state, clicked={f"display_compliance_generate_{context}"})
    detector_calls: list[bytes] = []
    monkeypatch.setattr(page, "st", ui)
    monkeypatch.setattr(page, "_mapping_preview", lambda **kwargs: b"preview")
    monkeypatch.setattr(page, "_render_mapping_editor", lambda **kwargs: None)
    monkeypatch.setattr(page, "_render_detection_diagnostics", lambda *_args: None)
    monkeypatch.setattr(
        page,
        "analyze_candidate_regions",
        lambda *, image_bytes: detector_calls.append(image_bytes),
    )
    storage = type(
        "Storage",
        (),
        {"load_reference_image_bytes": lambda _self, _baseline: b"reference"},
    )()

    page._render_candidate_detection(storage=storage, baseline=baseline)

    generation = next(
        call
        for call in ui.button_calls
        if call["label"] == "Generate Candidate Positions"
    )
    assert generation["disabled"] is True
    assert not detector_calls
    assert state[draft_key]["regions"][0].region_id == "keep-me"


def test_editor_add_edit_delete_controls_preserve_manual_position_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = ProductRegion(region_id="preserved-id", bbox=(1, 1, 3, 3))
    editor_key = "editor-workflow"
    edit_form_key = f"{editor_key}_Edit position_preserved-id"
    edit_ui = _UI(
        values={
            f"{editor_key}_operation": "Edit position",
            f"{editor_key}_selected": "preserved-id",
            f"{edit_form_key}_x": 2,
            f"{edit_form_key}_y": 2,
            f"{edit_form_key}_width": 4,
            f"{edit_form_key}_height": 4,
            f"{edit_form_key}_label": "Shelf position",
        },
        clicked={"Apply to Unsaved Draft"},
    )
    monkeypatch.setattr(page, "st", edit_ui)
    edited = page._render_mapping_editor(
        regions=[original],
        image_width=16,
        image_height=12,
        editor_key=editor_key,
        protected_region_ids=set(),
    )
    assert edited is not None
    assert edited[0].region_id == original.region_id
    assert edited[0].bbox == (2, 2, 4, 4)

    add_form_key = f"{editor_key}_Add position_new"
    add_ui = _UI(
        values={
            f"{editor_key}_operation": "Add position",
            f"{add_form_key}_x": 1,
            f"{add_form_key}_y": 6,
            f"{add_form_key}_width": 3,
            f"{add_form_key}_height": 3,
            f"{add_form_key}_label": "Added",
        },
        clicked={"Apply to Unsaved Draft"},
    )
    monkeypatch.setattr(page, "st", add_ui)
    with_added = page._render_mapping_editor(
        regions=edited,
        image_width=16,
        image_height=12,
        editor_key=editor_key,
        protected_region_ids=set(),
    )
    assert with_added is not None and len(with_added) == 2
    added_region_id = with_added[-1].region_id

    delete_ui = _UI(
        values={
            f"{editor_key}_operation": "Edit position",
            f"{editor_key}_selected": added_region_id,
        },
        clicked={"Delete Position from Draft"},
    )
    monkeypatch.setattr(page, "st", delete_ui)
    after_delete = page._render_mapping_editor(
        regions=with_added,
        image_width=16,
        image_height=12,
        editor_key=editor_key,
        protected_region_ids=set(),
    )
    assert after_delete == edited

    grid = create_grid_positions(
        bbox=(5, 1, 6, 4),
        rows=1,
        columns=2,
        image_width=16,
        image_height=12,
    )
    added = add_position(
        [*edited, *grid],
        bbox=(1, 6, 3, 3),
        image_width=16,
        image_height=12,
        label="Manual",
    )
    assert added[0].region_id == original.region_id
    assert len(added) == 4

    deleted = delete_position(added, region_id=added[-1].region_id)
    assert len(deleted) == 3
    assert original.region_id in {region.region_id for region in deleted}
    assert all(region.expected_product_id is None for region in deleted)


def test_confirmed_regeneration_replaces_unsaved_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = DisplayBaseline(
        baseline_id="regenerate-confirmed",
        name="Draft",
        reference_filename="reference.png",
        reference_width=16,
        reference_height=12,
    )
    context = (baseline.baseline_id, baseline.revision, None, "")
    draft_key = (
        f"display_compliance_mapping_draft_{baseline.baseline_id}_legacy"
    )
    checkbox_key = f"display_compliance_confirm_regenerate_{context}"
    state = {
        draft_key: {
            "regions": [ProductRegion(region_id="old-id", bbox=(1, 1, 3, 3))],
            "source_metadata": asdict(baseline),
        }
    }
    ui = _UI(
        state=state,
        clicked={f"display_compliance_generate_{context}"},
        values={checkbox_key: True},
    )
    replacement = ProductRegion(region_id="detector-id", bbox=(5, 1, 3, 3))

    @dataclass
    class Diagnostics:
        backend: str = "classical"

    class Result:
        regions = [replacement]
        diagnostics = Diagnostics()
        diagnostic_images = {}
        proposal_sample = []

    detector_calls: list[bytes] = []

    def detector(*, image_bytes: bytes):
        detector_calls.append(image_bytes)
        return Result()

    monkeypatch.setattr(page, "st", ui)
    monkeypatch.setattr(page, "_mapping_preview", lambda **kwargs: b"preview")
    monkeypatch.setattr(page, "_render_mapping_editor", lambda **kwargs: None)
    monkeypatch.setattr(page, "_render_detection_diagnostics", lambda *_args: None)
    monkeypatch.setattr(page, "analyze_candidate_regions", detector)
    storage = type(
        "Storage",
        (),
        {"load_reference_image_bytes": lambda _self, _baseline: b"reference"},
    )()

    page._render_candidate_detection(storage=storage, baseline=baseline)

    assert detector_calls == [b"reference"]
    new_ids = [region.region_id for region in state[draft_key]["regions"]]
    assert len(new_ids) == 1
    assert new_ids[0] not in {"old-id", replacement.region_id}
    assert state[draft_key]["regions"][0].bbox == replacement.bbox


def test_generated_positions_can_be_corrected_and_saved_without_products(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepared = prepare_baseline(
        name="Reference mapping",
        uploads=[
            ReferenceUpload(
                side_name="Front",
                filename="front.png",
                image_bytes=_png_bytes(),
            )
        ],
    )
    storage = LocalBaselineStorage(tmp_path)
    storage.save_prepared_baseline(
        prepared.baseline,
        prepared.reference_images,
    )
    baseline = storage.load_baseline(prepared.baseline.baseline_id)
    side = baseline.sides[0]
    context = (
        baseline.baseline_id,
        baseline.revision,
        side.side_id,
        side.reference_image_sha256,
    )
    draft_key = (
        f"display_compliance_mapping_draft_{baseline.baseline_id}_{side.side_id}"
    )
    generated_region = ProductRegion(
        region_id="detector-temporary-id",
        bbox=(1, 1, 3, 3),
    )

    @dataclass
    class Diagnostics:
        backend: str = "classical"

    class Result:
        regions = [generated_region]
        diagnostics = Diagnostics()
        diagnostic_images = {}
        proposal_sample = []

    monkeypatch.setattr(page, "_mapping_preview", lambda **kwargs: b"preview")
    monkeypatch.setattr(page, "_render_mapping_editor", lambda **kwargs: None)
    monkeypatch.setattr(page, "_render_detection_diagnostics", lambda *_args: None)
    monkeypatch.setattr(page, "analyze_candidate_regions", lambda **_kwargs: Result())
    monkeypatch.setattr(page, "st", _UI(clicked={f"display_compliance_generate_{context}"}))

    page._render_candidate_detection(
        storage=storage,
        baseline=baseline,
        side_id=side.side_id,
    )
    draft = page.st.session_state[draft_key]
    generated_id = draft["regions"][0].region_id
    assert generated_id != generated_region.region_id

    edited = update_position(
        draft["regions"],
        region_id=generated_id,
        bbox=(2, 2, 4, 4),
        image_width=side.reference_width,
        image_height=side.reference_height,
    )
    with_added = add_position(
        edited,
        bbox=(7, 1, 3, 3),
        image_width=side.reference_width,
        image_height=side.reference_height,
    )
    corrected_mapping = delete_position(
        with_added,
        region_id=with_added[-1].region_id,
    )
    draft["regions"] = corrected_mapping
    draft_key_context = f"display_compliance_save_mapping_{context}"
    ui = _UI(state={draft_key: draft}, clicked={draft_key_context})
    monkeypatch.setattr(page, "st", ui)

    page._render_candidate_detection(
        storage=storage,
        baseline=baseline,
        side_id=side.side_id,
    )

    saved = storage.load_baseline(baseline.baseline_id)
    assert saved.products == []
    assert [region.region_id for region in saved.sides[0].regions] == [
        generated_id
    ]
    assert saved.sides[0].regions[0].bbox == (2, 2, 4, 4)
    assert draft_key not in ui.session_state
    assert storage.load_side_reference_image_bytes(
        saved,
        side.side_id,
    ) == prepared.reference_images[side.side_id]


def test_detector_exports_are_resolvable_without_eager_sam_or_torch() -> None:
    script = """
import sys
import display_compliance.proposal_backends as backends
assert "display_compliance.proposal_backends.sam2_backend" not in sys.modules
assert "torch" not in sys.modules
import display_compliance.page
assert "display_compliance.proposal_backends.sam2_backend" not in sys.modules
assert "torch" not in sys.modules
from display_compliance.segmentation import analyze_candidate_regions
from display_compliance.proposal_backends import analyze_learned_candidate_regions
assert callable(analyze_candidate_regions)
assert callable(analyze_learned_candidate_regions)
assert "torch" not in sys.modules
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
