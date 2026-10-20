"""Baseline creation logic for Display Compliance."""

from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError
from .models import DisplayBaseline, DisplaySide, MatchingRequirements
from uuid import uuid4

MAX_REFERENCE_BYTES = 20 * 1024 * 1024
MAX_REFERENCE_PIXELS = 24_000_000
MAX_DISPLAY_SIDES = 8

@dataclass(frozen=True)
class ReferenceUpload:
    """One named side and its original uploaded reference"""

    side_name: str
    filename: str
    image_bytes: bytes

@dataclass(frozen=True)
class PreparedReference:
    """Decoded, orientation-normalized reference."""
    image_bytes: bytes
    width: int
    height: int
    image_sha256: str

@dataclass(frozen=True)
class PreparedBaseline:
    """One baseline with its reference sides and regions to be expected."""
    baseline: DisplayBaseline
    reference_images: dict[str, bytes]

def create_baseline(
    *,
    name: str,
    filename: str,
    image_bytes: bytes,
) -> DisplayBaseline:
    """Compatibility entry point for the existing single-image workflow."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Display / baseline name is required.")

    # Fully validate the image, but retain its encoded dimensions while the
    # legacy caller still saves the original uploaded bytes.
    width, height = _read_image_dimensions(image_bytes)

    return DisplayBaseline(
        baseline_id=uuid4().hex,
        name=clean_name,
        reference_filename=filename,
        reference_width=width,
        reference_height=height,
        regions=[],
        status="draft",
    )

def _decode_reference(image_bytes: bytes) -> Image.Image:
    """Validate and fully decode an uploaded PNG/JPEG."""
    if not image_bytes:
        raise ValueError("A reference image is required.")
    if len(image_bytes) > MAX_REFERENCE_BYTES:
        raise ValueError("Reference image must be 20 MB or smaller.")

    try:
        with Image.open(BytesIO(image_bytes)) as source:
            if source.format not in {"PNG", "JPEG"}:
                raise ValueError("Reference image must be PNG or JPEG.")
            if getattr(source, "n_frames", 1) != 1:
                raise ValueError("Animated reference images are not supported.")

            width, height = source.size
            if width <= 0 or height <= 0:
                raise ValueError("Reference image has invalid dimensions.")
            if width * height > MAX_REFERENCE_PIXELS:
                raise ValueError(
                    "Reference image must contain no more than 24 million pixels."
                )

            source.load()
            return source.copy()
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError(
            "Reference image could not be decoded as a valid PNG or JPEG."
        ) from exc


def _read_image_dimensions(image_bytes: bytes) -> tuple[int, int]:
    """Read encoded dimensions after fully decoding the legacy upload."""
    image = _decode_reference(image_bytes)
    try:
        return image.size
    finally:
        image.close()


def prepare_reference_image(image_bytes: bytes) -> PreparedReference:
    """Normalize orientation and encode a metadata-free RGB reference."""
    source = _decode_reference(image_bytes)

    try:
        oriented = ImageOps.exif_transpose(source)
        try:
            # Composite transparent PNGs onto white consistently.
            rgba = oriented.convert("RGBA")
            try:
                background = Image.new("RGBA", rgba.size, "white")
                try:
                    background.alpha_composite(rgba)
                    rgb = background.convert("RGB")
                finally:
                    background.close()
            finally:
                rgba.close()

            try:
                output = BytesIO()
                rgb.save(output, format="PNG")
                normalized_bytes = output.getvalue()
                width, height = rgb.size
            finally:
                rgb.close()
        finally:
            if oriented is not source:
                oriented.close()
    finally:
        source.close()

    return PreparedReference(
        image_bytes=normalized_bytes,
        width=width,
        height=height,
        image_sha256=sha256(normalized_bytes).hexdigest(),
    )

def prepare_baseline(
    *,
    name: str,
    uploads: list[ReferenceUpload],
    category: str = "other",
    matching_requirements: MatchingRequirements | None = None,
) -> PreparedBaseline:
    """Create a draft with one normalized reference per named side."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Display / baseline name is required.")
    if not uploads:
        raise ValueError("At least one reference side is required.")
    if len(uploads) > MAX_DISPLAY_SIDES:
        raise ValueError(
            f"A display may contain at most {MAX_DISPLAY_SIDES} sides."
        )

    side_names = [upload.side_name.strip() for upload in uploads]
    if any(not side_name for side_name in side_names):
        raise ValueError("Every side requires a name.")
    if len({side_name.casefold() for side_name in side_names}) != len(side_names):
        raise ValueError("Side names must be unique within a display.")

    sides: list[DisplaySide] = []
    reference_images: dict[str, bytes] = {}

    for upload, side_name in zip(uploads, side_names):
        try:
            prepared = prepare_reference_image(upload.image_bytes)
        except ValueError as exc:
            raise ValueError(f"{side_name}: {exc}") from exc

        side_id = uuid4().hex
        sides.append(
            DisplaySide(
                side_id=side_id,
                name=side_name,
                reference_filename=upload.filename,
                reference_width=prepared.width,
                reference_height=prepared.height,
                reference_image_sha256=prepared.image_sha256,
            )
        )
        reference_images[side_id] = prepared.image_bytes

    first_side = sides[0]

    baseline = DisplayBaseline(
        baseline_id=uuid4().hex,
        name=clean_name,
        # Compatibility metadata only. Side-aware code must use sides.
        reference_filename=first_side.reference_filename,
        reference_width=first_side.reference_width,
        reference_height=first_side.reference_height,
        regions=[],
        schema_version=2,
        revision=1,
        status="draft",
        category=category.strip() or "other",
        matching_requirements=(
            matching_requirements
            if matching_requirements is not None
            else MatchingRequirements()
        ),
        sides=sides,
    )

    return PreparedBaseline(
        baseline=baseline,
        reference_images=reference_images,
    )


