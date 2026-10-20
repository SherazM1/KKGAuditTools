"""Focused checks for validated and revision-guarded baseline storage."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
import multiprocessing
from pathlib import Path
import struct
import zlib

import pytest

from display_compliance.baseline import (
    ReferenceUpload,
    prepare_baseline,
)
from display_compliance.models import (
    DisplayBaseline,
    DisplaySection,
    ProductIdentity,
    ProductRegion,
)
from display_compliance import page as display_page
from display_compliance.storage import (
    BaselineValidationError,
    LocalBaselineStorage,
    StaleBaselineRevisionError,
    baseline_from_dict,
)


def _png_bytes(width: int = 12, height: int = 10) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\0" + b"\xff\0\0" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def _legacy_baseline(baseline_id: str = "legacy-1") -> DisplayBaseline:
    return DisplayBaseline(
        baseline_id=baseline_id,
        name="Legacy",
        reference_filename="reference.png",
        reference_width=12,
        reference_height=10,
    )


def _side_baseline() -> tuple[DisplayBaseline, dict[str, bytes]]:
    prepared = prepare_baseline(
        name="Multi-side",
        uploads=[
            ReferenceUpload(
                side_name="Front",
                filename="front.png",
                image_bytes=_png_bytes(),
            )
        ],
    )
    side = prepared.baseline.sides[0]
    section = DisplaySection(
        section_id="shelf",
        name="Shelf",
        bbox=(0, 0, 12, 10),
    )
    region = ProductRegion(
        region_id="position-1",
        bbox=(1, 1, 4, 4),
        section_id=section.section_id,
    )
    baseline = replace(
        prepared.baseline,
        sides=[replace(side, sections=[section], regions=[region])],
        products=[
            ProductIdentity(
                product_id="product-1",
                name="Example",
                reference_side_id=side.side_id,
                reference_region_id=region.region_id,
                confirmed=True,
            )
        ],
    )
    return baseline, prepared.reference_images


def _race_update_worker(
    root: str,
    updated: DisplayBaseline,
    barrier: object,
    result_queue: object,
) -> None:
    try:
        barrier.wait(timeout=15)
        LocalBaselineStorage(Path(root)).save_draft_update(
            updated,
            expected_revision=1,
        )
        result_queue.put("saved")
    except StaleBaselineRevisionError:
        result_queue.put("stale")
    except Exception as exc:  # pragma: no cover - diagnostic on child failure
        result_queue.put(f"error:{type(exc).__name__}:{exc}")


def test_legacy_metadata_without_sides_still_loads_and_validates() -> None:
    payload = {
        "baseline_id": "legacy-1",
        "name": "Legacy",
        "reference_filename": "reference.png",
        "reference_width": 12,
        "reference_height": 10,
        "regions": [
            {
                "region_id": "legacy-position",
                "bbox": [1, 1, 3, 3],
                "polygon": [],
            }
        ],
        "products": [
            {
                "product_id": "legacy-product",
                "reference_side_id": None,
                "reference_region_id": "legacy-position",
            }
        ],
    }

    baseline = baseline_from_dict(payload)

    assert baseline.schema_version == 1
    assert baseline.sides == []
    assert baseline.regions[0].region_id == "legacy-position"
    assert baseline.products[0].reference_region_id == "legacy-position"


def test_side_based_round_trip_preserves_metadata_and_images(tmp_path: Path) -> None:
    baseline, images = _side_baseline()
    storage = LocalBaselineStorage(tmp_path)

    storage.save_prepared_baseline(baseline, images)

    assert storage.load_baseline(baseline.baseline_id) == baseline
    assert (
        storage.load_side_reference_image_bytes(
            baseline,
            baseline.sides[0].side_id,
        )
        == images[baseline.sides[0].side_id]
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload["sides"][0]["regions"][0].update(
                bbox=[10, 1, 4, 4]
            ),
            "fit inside",
        ),
        (
            lambda payload: payload["sides"][0]["regions"][0].update(
                section_id="missing"
            ),
            "unknown section",
        ),
        (
            lambda payload: payload["sides"][0]["regions"][0].update(
                expected_product_id="missing"
            ),
            "unknown product",
        ),
        (
            lambda payload: payload["products"][0].update(
                reference_region_id="missing"
            ),
            "unknown position",
        ),
    ],
)
def test_invalid_geometry_and_references_are_rejected(mutate, message) -> None:
    baseline, _ = _side_baseline()
    payload = asdict(baseline)
    mutate(payload)

    with pytest.raises(BaselineValidationError, match=message):
        baseline_from_dict(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("revision", True),
        ("revision", 1.5),
        ("schema_version", True),
        ("reference_width", True),
    ],
)
def test_boolean_and_fractional_integer_fields_are_rejected(field, value) -> None:
    payload = asdict(_legacy_baseline())
    payload[field] = value

    with pytest.raises(BaselineValidationError):
        baseline_from_dict(payload)


def test_boolean_product_confirmation_is_rejected() -> None:
    payload = asdict(_legacy_baseline())
    payload["products"] = [{"product_id": "p1", "confirmed": 1}]

    with pytest.raises(BaselineValidationError, match="boolean"):
        baseline_from_dict(payload)


def test_boolean_position_occupancy_is_rejected() -> None:
    payload = asdict(_legacy_baseline())
    payload["regions"] = [
        {
            "region_id": "position-1",
            "bbox": [1, 1, 3, 3],
            "required_occupied": 1,
        }
    ]

    with pytest.raises(BaselineValidationError, match="boolean"):
        baseline_from_dict(payload)


def test_stale_revision_is_rejected_without_changing_metadata(tmp_path: Path) -> None:
    baseline = _legacy_baseline()
    storage = LocalBaselineStorage(tmp_path)
    storage.save_baseline(baseline, _png_bytes())
    metadata_path = tmp_path / baseline.baseline_id / "baseline.json"
    original = metadata_path.read_bytes()

    updated = replace(baseline, name="stale edit", revision=2)
    with pytest.raises(StaleBaselineRevisionError):
        storage.save_draft_update(updated, expected_revision=2)

    assert metadata_path.read_bytes() == original


def test_approved_baseline_cannot_be_updated(tmp_path: Path) -> None:
    baseline = _legacy_baseline()
    storage = LocalBaselineStorage(tmp_path)
    storage.save_baseline(baseline, _png_bytes())
    approved_payload = asdict(replace(baseline, status="approved"))
    (tmp_path / baseline.baseline_id / "baseline.json").write_text(
        json.dumps(approved_payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Only draft"):
        storage.save_draft_update(
            replace(baseline, name="attempt", revision=2),
            expected_revision=1,
        )
    assert storage.load_baseline(baseline.baseline_id).status == "approved"


def test_metadata_compatibility_wrapper_routes_through_guarded_update(
    tmp_path: Path,
) -> None:
    baseline = _legacy_baseline("metadata-wrapper")
    storage = LocalBaselineStorage(tmp_path)
    storage.save_baseline(baseline, _png_bytes())

    updated = replace(baseline, name="updated", revision=2)
    storage.save_baseline_metadata(updated)
    assert storage.load_baseline(baseline.baseline_id) == updated

    with pytest.raises(StaleBaselineRevisionError):
        storage.save_baseline_metadata(updated)


@pytest.mark.parametrize(
    "changed_fields",
    [
        {"reference_filename": "replacement.png"},
        {"reference_width": 11},
        {"schema_version": 1},
    ],
)
def test_reference_or_schema_metadata_changes_are_rejected(
    tmp_path: Path,
    changed_fields: dict[str, object],
) -> None:
    baseline = _legacy_baseline()
    storage = LocalBaselineStorage(tmp_path)
    storage.save_baseline(baseline, _png_bytes())
    updated = replace(baseline, revision=2, **changed_fields)

    with pytest.raises(ValueError):
        storage.save_draft_update(updated, expected_revision=1)

    assert storage.load_baseline(baseline.baseline_id) == baseline


def test_side_order_and_fingerprint_cannot_change_in_draft_update(
    tmp_path: Path,
) -> None:
    baseline, images = _side_baseline()
    storage = LocalBaselineStorage(tmp_path)
    storage.save_prepared_baseline(baseline, images)
    side = baseline.sides[0]

    changed = replace(
        baseline,
        revision=2,
        sides=[replace(side, reference_image_sha256="f" * 64)],
    )
    with pytest.raises(ValueError, match="fingerprint"):
        storage.save_draft_update(changed, expected_revision=1)

    assert storage.load_baseline(baseline.baseline_id) == baseline


def test_creation_cannot_overwrite_existing_baseline(tmp_path: Path) -> None:
    baseline = _legacy_baseline("no-overwrite")
    storage = LocalBaselineStorage(tmp_path)
    storage.save_baseline(baseline, _png_bytes())

    with pytest.raises(FileExistsError):
        storage.save_baseline(
            replace(baseline, name="replacement"),
            _png_bytes(8, 8),
        )

    assert storage.load_baseline(baseline.baseline_id) == baseline


def test_two_process_updates_with_same_revision_have_one_winner(
    tmp_path: Path,
) -> None:
    baseline = _legacy_baseline("competing")
    storage = LocalBaselineStorage(tmp_path)
    storage.save_baseline(baseline, _png_bytes())

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_race_update_worker,
            args=(
                str(tmp_path),
                replace(baseline, name=f"racer-{index}", revision=2),
                barrier,
                result_queue,
            ),
        )
        for index in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
    for process in processes:
        if process.is_alive():
            process.terminate()
            process.join()

    outcomes = [result_queue.get(timeout=5) for _ in processes]
    assert all(process.exitcode == 0 for process in processes)
    assert sorted(outcomes) == ["saved", "stale"]
    assert storage.load_baseline(baseline.baseline_id).revision == 2


def test_malformed_baseline_does_not_hide_healthy_listing(tmp_path: Path) -> None:
    storage = LocalBaselineStorage(tmp_path)
    healthy = _legacy_baseline("healthy")
    storage.save_baseline(healthy, _png_bytes())
    malformed_dir = tmp_path / "malformed"
    malformed_dir.mkdir()
    (malformed_dir / "baseline.json").write_text(
        json.dumps(
            {
                "baseline_id": "malformed",
                "name": "Bad",
                "reference_filename": "bad.png",
                "reference_width": True,
                "reference_height": 10,
            }
        ),
        encoding="utf-8",
    )

    assert storage.list_baselines() == [healthy]
    assert storage.listing_errors[0]["baseline_id"] == "malformed"


class _PageFake:
    def __init__(self, state: dict[str, object], clicked: set[str]) -> None:
        self.session_state = state
        self.clicked = clicked
        self.errors: list[str] = []

    def __getattr__(self, name: str):
        if name == "selectbox":
            return lambda label, *, options, **kwargs: options[0]
        if name == "button":
            return lambda label, **kwargs: kwargs.get("key") in self.clicked
        if name == "checkbox":
            return lambda *args, **kwargs: kwargs.get("value", False)
        if name == "error":
            return self.errors.append
        if name == "session_state":
            return self.session_state
        return lambda *args, **kwargs: None


def test_failed_page_save_retains_unsaved_draft_and_position_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _legacy_baseline("ui-baseline")
    region = ProductRegion(
        region_id="stable-position-id",
        bbox=(1, 1, 3, 3),
    )
    draft_key = (
        f"display_compliance_mapping_draft_{baseline.baseline_id}_legacy"
    )
    draft = {
        "regions": [region],
        "source_metadata": asdict(baseline),
    }

    class Storage:
        def load_reference_image_bytes(self, _baseline):
            return _png_bytes()

        def load_baseline(self, _baseline_id):
            return baseline

        def save_draft_update(self, *_args, **_kwargs):
            raise StaleBaselineRevisionError("stale update")

    fake_st = _PageFake(
        {
            draft_key: draft,
            display_page._DETECTION_DIAGNOSTICS_KEY: None,
        },
        {f"display_compliance_save_mapping_{(baseline.baseline_id, baseline.revision, None, '')}"},
    )
    monkeypatch.setattr(display_page, "st", fake_st)
    monkeypatch.setattr(display_page, "LocalBaselineStorage", Storage)
    monkeypatch.setattr(display_page, "_render_mapping_editor", lambda **_kwargs: None)
    monkeypatch.setattr(display_page, "_mapping_preview", lambda **_kwargs: b"preview")

    display_page._render_candidate_detection(
        storage=Storage(),
        baseline=baseline,
    )

    assert fake_st.session_state[draft_key]["regions"][0].region_id == (
        "stable-position-id"
    )
    assert any("stale update" in message for message in fake_st.errors)
