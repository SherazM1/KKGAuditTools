"""Filesystem-backed baseline storage for Display Compliance."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import json
from hashlib import sha256
from io import BytesIO
import shutil
from pathlib import Path
import re
import os
import time
import tempfile
import logging
import errno
from PIL import Image, UnidentifiedImageError
from .models import DisplayBaseline, ProductRegion, DisplaySection, DisplaySide, MatchingRequirements, ProductIdentity
from .mapping import MappingValidationError, validate_bbox, validate_regions


DEFAULT_BASELINE_STORAGE_ROOT = Path(__file__).resolve().parents[1] / "data" / "display_compliance" / "baselines"
logger = logging.getLogger(__name__)
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_RETRY_SECONDS = 0.05


class BaselineValidationError(ValueError):
    """Raised when baseline metadata does not satisfy the storage contract."""


class StaleBaselineRevisionError(ValueError):
    """Raised when a draft update was based on an obsolete revision."""


class BaselineLockTimeoutError(TimeoutError):
    """Raised when a local baseline lock cannot be acquired in time."""


@contextmanager
def _baseline_lock(root: Path, baseline_id: str):
    """Lock one baseline across local processes using the operating system."""
    lock_dir = root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{baseline_id}.lock"
    lock_file = lock_path.open("a+b")
    acquired = False

    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()

            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    acquired = True
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EDEADLK, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise BaselineLockTimeoutError(
                            f"Timed out waiting for baseline lock: {baseline_id}"
                        ) from exc
                    time.sleep(LOCK_RETRY_SECONDS)
        else:
            import fcntl

            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise BaselineLockTimeoutError(
                            f"Timed out waiting for baseline lock: {baseline_id}"
                        ) from exc
                    time.sleep(LOCK_RETRY_SECONDS)
        yield
    finally:
        if acquired:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

def _baseline_directory(root: Path, baseline_id: str) -> Path:
    """Resolve a baseline directory without allowing path traversal."""
    if not isinstance(baseline_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", baseline_id
    ):
        raise ValueError("Invalid baseline ID.")

    resolved_root = root.resolve()
    baseline_dir = (resolved_root / baseline_id).resolve()

    if baseline_dir.parent != resolved_root:
        raise ValueError("Baseline directory must remain inside storage root.")

    return baseline_dir


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    """Replace one file atomically using a temporary file beside it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _write_baseline_metadata(path: Path, baseline: DisplayBaseline) -> None:
    """Serialize completely before replacing existing metadata."""
    content = json.dumps(
        asdict(baseline),
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")
    _atomic_write_bytes(path, content)


def _validate_side_reference(side: DisplaySide, image_bytes: bytes) -> None:
    """Check that prepared PNG bytes match their side metadata."""
    if not image_bytes:
        raise ValueError(f"{side.name}: reference image is empty.")

    actual_hash = sha256(image_bytes).hexdigest()
    if actual_hash != side.reference_image_sha256:
        raise ValueError(f"{side.name}: reference fingerprint does not match.")

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format != "PNG":
                raise ValueError(
                    f"{side.name}: prepared reference must be PNG."
                )
            if image.size != (
                side.reference_width,
                side.reference_height,
            ):
                raise ValueError(
                    f"{side.name}: reference dimensions do not match."
                )
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(
            f"{side.name}: prepared reference image is invalid."
        ) from exc


def _validate_polygon(
    polygon: object,
    *,
    image_width: int,
    image_height: int,
    name: str,
) -> None:
    if not isinstance(polygon, (tuple, list)):
        raise BaselineValidationError(f"{name} must be a list of points.")
    if not polygon:
        return
    if len(polygon) < 3:
        raise BaselineValidationError(f"{name} needs at least three corners.")

    points: list[tuple[int, int]] = []
    for point in polygon:
        if not isinstance(point, (tuple, list)) or len(point) != 2:
            raise BaselineValidationError(f"{name} contains an invalid point.")
        x, y = point
        if type(x) is not int or type(y) is not int:
            raise BaselineValidationError(f"{name} coordinates must be integers.")
        if not (0 <= x <= image_width and 0 <= y <= image_height):
            raise BaselineValidationError(f"{name} must remain within the reference image.")
        points.append((x, y))

    twice_area = sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )
    if twice_area == 0:
        raise BaselineValidationError(f"{name} must have nonzero area.")


def validate_baseline(baseline: DisplayBaseline) -> None:
    """Validate all persisted baseline metadata before loading or writing."""
    if not isinstance(baseline, DisplayBaseline):
        raise BaselineValidationError("Baseline metadata has an invalid model.")
    if type(baseline.schema_version) is not int or baseline.schema_version not in {1, 2}:
        raise BaselineValidationError(
            f"Unsupported baseline schema version: {baseline.schema_version!r}"
        )
    if type(baseline.revision) is not int or baseline.revision < 1:
        raise BaselineValidationError("Baseline revision must be a positive integer.")
    if type(baseline.status) is not str or baseline.status not in {
        "draft",
        "approved",
    }:
        raise BaselineValidationError("Baseline status must be 'draft' or 'approved'.")

    for field_name, value in (
        ("Baseline ID", baseline.baseline_id),
        ("Baseline name", baseline.name),
        ("Reference filename", baseline.reference_filename),
        ("Category", baseline.category),
    ):
        if type(value) is not str or not value.strip():
            raise BaselineValidationError(f"{field_name} must be a nonempty string.")

    for field_name, value in (
        ("Reference width", baseline.reference_width),
        ("Reference height", baseline.reference_height),
    ):
        if type(value) is not int or value <= 0:
            raise BaselineValidationError(f"{field_name} must be a positive integer.")

    if not isinstance(baseline.regions, list):
        raise BaselineValidationError("Legacy positions must be a list.")
    if not isinstance(baseline.sides, list):
        raise BaselineValidationError("Display sides must be a list.")
    if not isinstance(baseline.products, list):
        raise BaselineValidationError("Products must be a list.")

    requirements = baseline.matching_requirements
    if not isinstance(requirements, MatchingRequirements):
        raise BaselineValidationError("Matching requirements have an invalid model.")
    if not isinstance(requirements.required_attributes, (tuple, list)):
        raise BaselineValidationError("Required attributes must be a list of names.")
    for attribute in requirements.required_attributes:
        if type(attribute) is not str or not attribute.strip():
            raise BaselineValidationError(
                "Matching requirements contain an empty or invalid attribute name."
            )
    if type(requirements.notes) is not str:
        raise BaselineValidationError("Matching requirement notes must be a string.")

    side_ids: set[str] = set()
    all_positions: dict[str | None, dict[str, ProductRegion]] = {}
    all_sections: dict[str, set[str]] = {}
    for side in baseline.sides:
        if not isinstance(side, DisplaySide):
            raise BaselineValidationError("Display side has an invalid model.")
        if type(side.side_id) is not str or not side.side_id.strip():
            raise BaselineValidationError("Every display side requires a nonempty ID.")
        if side.side_id in side_ids:
            raise BaselineValidationError(f"Duplicate display side ID: {side.side_id}")
        side_ids.add(side.side_id)
        if type(side.name) is not str or not side.name.strip():
            raise BaselineValidationError("Every display side requires a nonempty name.")
        if type(side.reference_filename) is not str or not side.reference_filename.strip():
            raise BaselineValidationError(
                f"{side.name}: reference filename must be a nonempty string."
            )
        for field_name, value in (
            ("Reference width", side.reference_width),
            ("Reference height", side.reference_height),
        ):
            if type(value) is not int or value <= 0:
                raise BaselineValidationError(
                    f"{side.name}: {field_name} must be a positive integer."
                )
        if type(side.reference_image_sha256) is not str:
            raise BaselineValidationError(
                f"{side.name}: reference fingerprint must be a string."
            )
        if not isinstance(side.sections, list) or not isinstance(side.regions, list):
            raise BaselineValidationError(
                f"{side.name}: sections and positions must be lists."
            )
        _validate_polygon(
            side.display_polygon,
            image_width=side.reference_width,
            image_height=side.reference_height,
            name=f"{side.name} display polygon",
        )

        section_ids: set[str] = set()
        for section in side.sections:
            if not isinstance(section, DisplaySection):
                raise BaselineValidationError(
                    f"{side.name}: section has an invalid model."
                )
            if type(section.section_id) is not str or not section.section_id.strip():
                raise BaselineValidationError(
                    f"{side.name}: every section requires a nonempty ID."
                )
            if section.section_id in section_ids:
                raise BaselineValidationError(
                    f"{side.name}: duplicate section ID: {section.section_id}"
                )
            section_ids.add(section.section_id)
            if type(section.name) is not str or not section.name.strip():
                raise BaselineValidationError(
                    f"{side.name}: every section requires a nonempty name."
                )
            if section.bbox is not None:
                try:
                    validate_bbox(
                        section.bbox,
                        image_width=side.reference_width,
                        image_height=side.reference_height,
                    )
                except (MappingValidationError, TypeError) as exc:
                    raise BaselineValidationError(
                        f"{side.name}, section {section.section_id}: {exc}"
                    ) from exc
            _validate_polygon(
                section.polygon,
                image_width=side.reference_width,
                image_height=side.reference_height,
                name=f"{side.name}, section {section.section_id} polygon",
            )

        try:
            validate_regions(
                side.regions,
                image_width=side.reference_width,
                image_height=side.reference_height,
            )
        except (MappingValidationError, TypeError, AttributeError) as exc:
            raise BaselineValidationError(f"{side.name}: {exc}") from exc
        for region in side.regions:
            if type(region.label) is not str:
                raise BaselineValidationError(
                    f"Position {region.region_id} label must be a string."
                )
            if region.visual_signature is not None and (
                type(region.visual_signature) is not str
            ):
                raise BaselineValidationError(
                    f"Position {region.region_id} visual signature must be a string."
                )
        all_positions[side.side_id] = {
            region.region_id: region for region in side.regions
        }
        all_sections[side.side_id] = section_ids

    if baseline.sides and baseline.regions:
        raise BaselineValidationError(
            "Side-based baselines cannot also contain legacy top-level positions."
        )
    try:
        validate_regions(
            baseline.regions,
            image_width=baseline.reference_width,
            image_height=baseline.reference_height,
        )
    except (MappingValidationError, TypeError, AttributeError) as exc:
        raise BaselineValidationError(f"Legacy positions: {exc}") from exc
    for region in baseline.regions:
        if type(region.label) is not str:
            raise BaselineValidationError(
                f"Position {region.region_id} label must be a string."
            )
        if region.visual_signature is not None and (
            type(region.visual_signature) is not str
        ):
            raise BaselineValidationError(
                f"Position {region.region_id} visual signature must be a string."
            )
    if not baseline.sides:
        all_positions[None] = {
            region.region_id: region for region in baseline.regions
        }

    product_ids: set[str] = set()
    for product in baseline.products:
        if not isinstance(product, ProductIdentity):
            raise BaselineValidationError("Product has an invalid model.")
        if type(product.product_id) is not str or not product.product_id.strip():
            raise BaselineValidationError("Every product requires a nonempty ID.")
        if product.product_id in product_ids:
            raise BaselineValidationError(
                f"Duplicate product ID: {product.product_id}"
            )
        product_ids.add(product.product_id)
        if type(product.name) is not str:
            raise BaselineValidationError("Product names must be strings.")
        if type(product.source) is not str or product.source not in {
            "manual",
            "ai",
        }:
            raise BaselineValidationError("Product source must be 'manual' or 'ai'.")
        if type(product.confirmed) is not bool:
            raise BaselineValidationError("Product confirmed must be a boolean.")
        if product.confirmed and not product.name.strip():
            raise BaselineValidationError("Confirmed products require a nonempty name.")
        if not isinstance(product.attributes, dict) or any(
            type(key) is not str or type(value) is not str
            for key, value in product.attributes.items()
        ):
            raise BaselineValidationError(
                "Product attributes must be a string-to-string mapping."
            )

        side_ref = product.reference_side_id
        region_ref = product.reference_region_id
        if side_ref is not None and (type(side_ref) is not str or not side_ref.strip()):
            raise BaselineValidationError("Product reference side ID is invalid.")
        if region_ref is not None and (
            type(region_ref) is not str or not region_ref.strip()
        ):
            raise BaselineValidationError("Product reference position ID is invalid.")
        if side_ref is not None and region_ref is None:
            raise BaselineValidationError(
                "Product reference side and position links must be supplied together."
            )
        if region_ref is not None:
            if side_ref is None and baseline.sides:
                raise BaselineValidationError(
                    "Side-based product position references require a side ID."
                )
            position_scope = side_ref
            if position_scope not in all_positions:
                raise BaselineValidationError(
                    f"Product {product.product_id} references an unknown side or legacy position."
                )
            if region_ref not in all_positions[position_scope]:
                raise BaselineValidationError(
                    f"Product {product.product_id} references an unknown position."
                )

    for side in baseline.sides:
        for region in side.regions:
            if region.section_id is not None:
                if type(region.section_id) is not str or (
                    region.section_id not in all_sections[side.side_id]
                ):
                    raise BaselineValidationError(
                        f"Position {region.region_id} references an unknown section."
                    )
            if region.expected_product_id is not None:
                if type(region.expected_product_id) is not str or (
                    region.expected_product_id not in product_ids
                ):
                    raise BaselineValidationError(
                        f"Position {region.region_id} references an unknown product."
                    )
    for region in baseline.regions:
        if region.section_id is not None:
            raise BaselineValidationError(
                f"Legacy position {region.region_id} cannot reference a side section."
            )
        if region.expected_product_id is not None and (
            type(region.expected_product_id) is not str
            or region.expected_product_id not in product_ids
        ):
            raise BaselineValidationError(
                f"Position {region.region_id} references an unknown product."
            )


class LocalBaselineStorage:
    """Local development storage for baseline metadata and reference images."""

    def __init__(self, root: Path = DEFAULT_BASELINE_STORAGE_ROOT) -> None:
        self.root = root
        self.listing_errors: list[dict[str, str]] = []

    def save_baseline(
        self,
        baseline: DisplayBaseline,
        image_bytes: bytes,
    ) -> None:
        validate_baseline(baseline)
        if baseline.status != "draft":
            raise ValueError("New baselines must be saved as drafts.")
        baseline_dir = _baseline_directory(self.root, baseline.baseline_id)
        metadata_path = baseline_dir / "baseline.json"

        if not image_bytes:
            raise ValueError("A reference image is required.")

        json.dumps(asdict(baseline), allow_nan=False)
        with _baseline_lock(self.root, baseline.baseline_id):
            self.root.mkdir(parents=True, exist_ok=True)
            baseline_dir.mkdir(exist_ok=False)
            try:
                reference_filename = _safe_reference_filename(
                    baseline.reference_filename
                )
                if reference_filename == "baseline.json":
                    raise ValueError(
                        "Reference filename conflicts with baseline metadata."
                    )
                image_path = baseline_dir / reference_filename
                _atomic_write_bytes(image_path, image_bytes)
                _write_baseline_metadata(metadata_path, baseline)
            except Exception:
                try:
                    shutil.rmtree(baseline_dir)
                except OSError:
                    logger.exception(
                        "Could not remove incomplete baseline %s",
                        baseline.baseline_id,
                    )
                raise

    def save_prepared_baseline(
        self,
        baseline: DisplayBaseline,
        reference_images: dict[str, bytes],
    ) -> None:
        """Create a new draft with one prepared reference per side."""
        validate_baseline(baseline)
        if baseline.status != "draft":
            raise ValueError("New baselines must be saved as drafts.")
        if not baseline.sides:
            raise ValueError("At least one display side is required.")
        if baseline.regions:
            raise ValueError(
                "Side-based baselines must store positions within their sides."
            )

        baseline_dir = _baseline_directory(self.root, baseline.baseline_id)
        side_ids = [side.side_id for side in baseline.sides]

        if len(set(side_ids)) != len(side_ids):
            raise ValueError("Display side IDs must be unique.")
        if set(reference_images) != set(side_ids):
            raise ValueError(
                "Reference images must match the baseline's side IDs exactly."
            )

        # Validate every path, image, and metadata payload before writing.
        side_paths: dict[str, Path] = {}
        for side in baseline.sides:
            side_dir = _baseline_directory(
                baseline_dir / "sides",
                side.side_id,
            )
            side_paths[side.side_id] = side_dir / "reference.png"
            _validate_side_reference(
                side,
                reference_images[side.side_id],
            )

        json.dumps(asdict(baseline), allow_nan=False)

        with _baseline_lock(self.root, baseline.baseline_id):
            self.root.mkdir(parents=True, exist_ok=True)

            # Exclusive directory creation prevents overwriting an existing
            # baseline, including another session creating the same ID.
            baseline_dir.mkdir(exist_ok=False)

            try:
                for side in baseline.sides:
                    _atomic_write_bytes(
                        side_paths[side.side_id],
                        reference_images[side.side_id],
                    )

                # Publish metadata last so listing does not expose a baseline
                # before all its references have been written.
                _write_baseline_metadata(
                    baseline_dir / "baseline.json",
                    baseline,
                )
            except Exception:
                # This directory was created exclusively by this call.
                try:
                    shutil.rmtree(baseline_dir)
                except OSError:
                    logger.exception(
                        "Could not remove incomplete baseline %s",
                        baseline.baseline_id,
                    )
                raise

    def load_side_reference_image_bytes(
        self,
        baseline: DisplayBaseline,
        side_id: str,
    ) -> bytes:
        """Load and verify the reference for a declared display side."""
        matching_sides = [
            side for side in baseline.sides
            if side.side_id == side_id
        ]
        if len(matching_sides) != 1:
            raise ValueError(
                "Requested side must occur exactly once in the baseline."
            )
        side = matching_sides[0]

        baseline_dir = _baseline_directory(
            self.root,
            baseline.baseline_id,
        )
        side_dir = _baseline_directory(
            baseline_dir / "sides",
            side_id,
        )
        image_path = (side_dir / "reference.png").resolve()

        if image_path.parent != side_dir:
            raise ValueError(
                "Reference image must remain inside its side directory."
            )

        image_bytes = image_path.read_bytes()
        _validate_side_reference(side, image_bytes)
        return image_bytes


    def save_draft_update(
        self,
        updated: DisplayBaseline,
        *,
        expected_revision: int,
    ) -> DisplayBaseline:
        """Atomically save a draft update guarded by its observed revision."""
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Expected revision must be a positive integer.")
        baseline_dir = _baseline_directory(self.root, updated.baseline_id)
        metadata_path = baseline_dir / "baseline.json"

        with _baseline_lock(self.root, updated.baseline_id):
            current = self.load_baseline(updated.baseline_id)
            if current.status != "draft" or updated.status != "draft":
                raise ValueError("Only draft baselines can be updated.")
            if current.revision != expected_revision:
                raise StaleBaselineRevisionError(
                    "The baseline revision is stale; reload before saving."
                )
            if updated.revision != current.revision + 1:
                raise ValueError(
                    "Updated baseline revision must be exactly one greater "
                    "than the current revision."
                )
            validate_baseline(updated)
            if updated.baseline_id != current.baseline_id:
                raise ValueError("Baseline ID cannot change in a draft update.")
            if updated.schema_version != current.schema_version:
                raise ValueError("Baseline schema version cannot change in a draft update.")
            self._validate_immutable_references(current, updated)
            _write_baseline_metadata(metadata_path, updated)
            return updated

    @staticmethod
    def _validate_immutable_references(
        current: DisplayBaseline,
        updated: DisplayBaseline,
    ) -> None:
        if updated.reference_filename != current.reference_filename:
            raise ValueError(
                "Reference filename cannot change in a draft update."
            )
        if (
            updated.reference_width != current.reference_width
            or updated.reference_height != current.reference_height
        ):
            raise ValueError("Reference dimensions cannot change in a draft update.")
        if [side.side_id for side in updated.sides] != [
            side.side_id for side in current.sides
        ]:
            raise ValueError("Display side membership and order cannot change.")
        for old_side, new_side in zip(current.sides, updated.sides):
            if new_side.reference_filename != old_side.reference_filename:
                raise ValueError(
                    f"Reference filename for side {old_side.side_id} "
                    "cannot change in a draft update."
                )
            if (
                new_side.reference_width != old_side.reference_width
                or new_side.reference_height != old_side.reference_height
            ):
                raise ValueError(
                    f"Reference dimensions for side {old_side.side_id} "
                    "cannot change in a draft update."
                )
            if new_side.reference_image_sha256 != old_side.reference_image_sha256:
                raise ValueError(
                    f"Reference fingerprint for side {old_side.side_id} "
                    "cannot change in a draft update."
                )

    def save_baseline_metadata(self, baseline: DisplayBaseline) -> None:
        """Backward-compatible guarded metadata update entry point."""
        if type(baseline.revision) is not int:
            raise ValueError("Updated baseline revision must be an integer.")
        self.save_draft_update(
            baseline,
            expected_revision=baseline.revision - 1,
        )

    def load_baseline(self, baseline_id: str) -> DisplayBaseline:
        baseline_dir = _baseline_directory(self.root, baseline_id)
        metadata_path = baseline_dir / "baseline.json"

        with metadata_path.open("r", encoding="utf-8") as metadata_file:
            payload = json.load(metadata_file)

        if not isinstance(payload, dict):
            raise ValueError("Baseline metadata must be a JSON object.")
        if payload.get("baseline_id") != baseline_id:
            raise ValueError("Baseline ID does not match its storage directory.")

        return baseline_from_dict(payload)

    def load_reference_image_bytes(self, baseline: DisplayBaseline) -> bytes:
        baseline_dir = _baseline_directory(self.root, baseline.baseline_id)
        image_path = baseline_dir / "reference_image.bin"

        if not image_path.is_file():
            # Compatibility with references saved by the original storage code.
            legacy_name = _safe_reference_filename(baseline.reference_filename)
            if legacy_name == "baseline.json":
                raise ValueError(
                    "Legacy reference filename conflicts with baseline metadata."
                )
            image_path = baseline_dir / legacy_name

        resolved_image_path = image_path.resolve()
        if resolved_image_path.parent != baseline_dir:
            raise ValueError("Reference image must remain inside its baseline directory.")

        return resolved_image_path.read_bytes()

    def list_baselines(self) -> list[DisplayBaseline]:
        "List healthy baselines, records entries that could not be loaded"
        self.listing_errors.clear()

        if not self.root.exists():
            return []

        baselines: list[DisplayBaseline] = []

        for metadata_path in sorted(self.root.glob("*/baseline.json")):
            baseline_id = metadata_path.parent.name
            
            try:
                baseline = self.load_baseline(baseline_id)
            except (
                OSError,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
                OverflowError
            ) as exc:
                self.listing_errors.append(
                    {
                        "baseline_id": baseline_id,
                        "message": str(exc)
                    }
                )
                logger.warning(
                    "Could not load display quality control baseline '%s': %s",
                    baseline_id,
                    exc,
                )
                continue
            baselines.append(baseline)

        return baselines


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BaselineValidationError(f"{name} must be an object.")
    return value


def _sequence(value: object, name: str) -> list[object]:
    if not isinstance(value, (list, tuple)):
        raise BaselineValidationError(f"{name} must be a list.")
    return list(value)


def _string(value: object, name: str) -> str:
    if type(value) is not str:
        raise BaselineValidationError(f"{name} must be a string.")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise BaselineValidationError(f"{name} must be an integer.")
    return value


def _coordinate_tuple(value: object, name: str) -> tuple[object, ...]:
    return tuple(_sequence(value, name))


def _polygon_tuple(value: object, name: str) -> tuple[tuple[object, ...], ...]:
    return tuple(
        _coordinate_tuple(point, f"{name} point")
        for point in _sequence(value, name)
    )


def _region_from_dict(value: object) -> ProductRegion:
    """Reconstruct a position without normalizing malformed source types."""
    region = _object(value, "Position")
    bbox_value = region.get("bbox")
    bbox = (
        None
        if bbox_value is None
        else _coordinate_tuple(bbox_value, "Position bounding box")
    )
    polygon = _polygon_tuple(region.get("polygon", []), "Position polygon")
    required_occupied = region.get("required_occupied", True)
    if type(required_occupied) is not bool:
        raise BaselineValidationError("Required occupancy must be a boolean.")
    return ProductRegion(
        region_id=_string(region.get("region_id", ""), "Position ID"),
        bbox=bbox,
        polygon=polygon,
        label=_string(region.get("label", ""), "Position label"),
        visual_signature=_optional_string(
            region.get("visual_signature"),
            "Position visual signature",
        ),
        expected_product_id=_optional_string(
            region.get("expected_product_id"),
            "Expected product ID",
        ),
        section_id=_optional_string(region.get("section_id"), "Section ID"),
        required_occupied=required_occupied,
    )


def _section_from_dict(value: object) -> DisplaySection:
    section = _object(value, "Section")
    bbox_value = section.get("bbox")
    return DisplaySection(
        section_id=_string(section.get("section_id", ""), "Section ID"),
        name=_string(section.get("name", ""), "Section name"),
        bbox=(
            None
            if bbox_value is None
            else _coordinate_tuple(bbox_value, "Section bounding box")
        ),
        polygon=_polygon_tuple(
            section.get("polygon", []),
            "Section polygon",
        ),
    )


def _side_from_dict(value: object) -> DisplaySide:
    side = _object(value, "Display side")
    return DisplaySide(
        side_id=_string(side.get("side_id", ""), "Display side ID"),
        name=_string(side.get("name", ""), "Display side name"),
        reference_filename=_string(
            side.get("reference_filename", ""),
            "Reference filename",
        ),
        reference_width=_integer(
            side.get("reference_width"),
            "Reference width",
        ),
        reference_height=_integer(
            side.get("reference_height"),
            "Reference height",
        ),
        reference_image_sha256=_string(
            side.get("reference_image_sha256", ""),
            "Reference fingerprint",
        ),
        display_polygon=_polygon_tuple(
            side.get("display_polygon", []),
            "Display polygon",
        ),
        sections=[
            _section_from_dict(section)
            for section in _sequence(side.get("sections", []), "Sections")
        ],
        regions=[
            _region_from_dict(region)
            for region in _sequence(side.get("regions", []), "Positions")
        ],
    )


def _product_from_dict(value: object) -> ProductIdentity:
    product = _object(value, "Product")
    attributes = _object(product.get("attributes", {}), "Product attributes")
    confirmed = product.get("confirmed", False)
    if type(confirmed) is not bool:
        raise BaselineValidationError("Product confirmed must be a boolean.")
    return ProductIdentity(
        product_id=_string(product.get("product_id", ""), "Product ID"),
        name=_string(product.get("name", ""), "Product name"),
        attributes=attributes,
        source=_string(product.get("source", "manual"), "Product source"),
        confirmed=confirmed,
        reference_side_id=_optional_string(
            product.get("reference_side_id"),
            "Product reference side ID",
        ),
        reference_region_id=_optional_string(
            product.get("reference_region_id"),
            "Product reference position ID",
        ),
    )


def baseline_from_dict(payload: dict[str, object]) -> DisplayBaseline:
    """Load and validate current or legacy metadata without coercing values."""
    payload = _object(payload, "Baseline metadata")
    schema_version = _integer(payload.get("schema_version", 1), "Schema version")
    revision = _integer(payload.get("revision", 1), "Baseline revision")
    status = _string(payload.get("status", "draft"), "Baseline status")
    requirements = _object(
        payload.get("matching_requirements", {}),
        "Matching requirements",
    )
    required_attributes = _sequence(
        requirements.get("required_attributes", []),
        "Required attributes",
    )
    matching_requirements = MatchingRequirements(
        required_attributes=tuple(
            _string(attribute, "Required attribute")
            for attribute in required_attributes
        ),
        notes=_string(requirements.get("notes", ""), "Matching requirement notes"),
    )

    baseline = DisplayBaseline(
        baseline_id=_string(payload.get("baseline_id"), "Baseline ID"),
        name=_string(payload.get("name"), "Baseline name"),
        reference_filename=_string(
            payload.get("reference_filename"),
            "Reference filename",
        ),
        reference_width=_integer(
            payload.get("reference_width"),
            "Reference width",
        ),
        reference_height=_integer(
            payload.get("reference_height"),
            "Reference height",
        ),
        regions=[
            _region_from_dict(region)
            for region in _sequence(payload.get("regions", []), "Positions")
        ],
        schema_version=schema_version,
        revision=revision,
        status=status,
        category=_string(payload.get("category", "other"), "Category"),
        matching_requirements=matching_requirements,
        products=[
            _product_from_dict(product)
            for product in _sequence(payload.get("products", []), "Products")
        ],
        sides=[
            _side_from_dict(side)
            for side in _sequence(payload.get("sides", []), "Display sides")
        ],
    )
    validate_baseline(baseline)
    return baseline

def _safe_reference_filename(filename: str) -> str:
    name = Path(filename).name or "reference_image"
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return safe_name or "reference_image"
