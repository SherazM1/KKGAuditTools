"""
Image normalization and preprocessing helpers for the audit application.

Camera captures and uploaded files should both become
the same AuditImage structure before entering the audit pipeline.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import math
from PIL import Image, ImageOps

from .models import AuditImage, TargetRegion


ALLOWED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

SUPPORTED_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
}

MAX_IMAGE_DIMENSION = 2048
MAX_RAW_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
JPEG_QUALITY = 85


class ImageProcessingError(ValueError):
    """Raised when an image cannot be safely processed."""


def _inspect_image_bytes(
    data: bytes,
) -> tuple[str, int, int]:
    """
    Inspect actual image contents without trusting filename
    or upload MIME metadata.

    Returns:
        media_type, width, height
    """

    if not isinstance(data, bytes):
        raise ImageProcessingError(
            "Image data must be bytes."
        )

    if not data:
        raise ImageProcessingError(
            "Image data is empty."
        )

    if len(data) > MAX_RAW_IMAGE_BYTES:
        raise ImageProcessingError(
            "Image file is too large."
        )

    try:
        with Image.open(
            BytesIO(data)
        ) as opened:

            image_format = (
                opened.format or ""
            ).upper()

            if image_format == "JPEG":
                media_type = "image/jpeg"

            elif image_format == "PNG":
                media_type = "image/png"

            else:
                raise ImageProcessingError(
                    "Only JPEG and PNG images are supported."
                )

            width, height = opened.size

    except ImageProcessingError:
        raise

    except Exception as exc:
        raise ImageProcessingError(
            "The image could not be decoded."
        ) from exc

    if width <= 0 or height <= 0:
        raise ImageProcessingError(
            "Image dimensions must be greater than zero."
        )

    pixel_count = width * height

    if pixel_count > MAX_IMAGE_PIXELS:
        raise ImageProcessingError(
            "Image dimensions are too large."
        )

    return (
        media_type,
        width,
        height,
    )


def detect_media_type(
    filename: str | None,
    provided_type: str | None = None,
) -> str:
    """
    Resolve a supported image media type.
    """

    if provided_type in SUPPORTED_MEDIA_TYPES:
        return provided_type

    if filename:
        suffix = Path(filename).suffix.lower()

        if suffix in ALLOWED_EXTENSIONS:
            return ALLOWED_EXTENSIONS[suffix]

    raise ImageProcessingError(
        "Could not determine a supported image type."
    )


def build_audit_image(
    data: bytes,
    *,
    filename: str | None = None,
    media_type: str | None = None,
    source: str | None = None,
) -> AuditImage:
    """
    Validate an image source and normalize it into an AuditImage.

    Actual image contents are authoritative. Filename and declared
    MIME type are treated only as supporting metadata.
    """

    (
        actual_media_type,
        _,
        _,
    ) = _inspect_image_bytes(
        data
    )

    if media_type in SUPPORTED_MEDIA_TYPES:
        if media_type != actual_media_type:
            raise ImageProcessingError(
                "The image contents do not match the declared image type."
            )

    if filename:
        suffix = Path(filename).suffix.lower()

        expected_type = ALLOWED_EXTENSIONS.get(
            suffix
        )

        if (
            expected_type is not None
            and expected_type != actual_media_type
        ):
            raise ImageProcessingError(
                "The image contents do not match the file extension."
            )

    return AuditImage(
        data=data,
        media_type=actual_media_type,
        filename=filename,
        source=source,
    )

def preprocess_audit_image(
    image: AuditImage,
    *,
    max_dimension: int = MAX_IMAGE_DIMENSION,
    jpeg_quality: int = JPEG_QUALITY,
) -> AuditImage:
    """
    Normalize orientation, resize oversized images,
    and re-encode them for efficient AI processing.
    """

    if max_dimension < 256:
        raise ImageProcessingError(
            "max_dimension is too small."
        )

    if not 1 <= jpeg_quality <= 100:
        raise ImageProcessingError(
            "jpeg_quality must be between 1 and 100."
        )

    actual_media_type, _, _ = _inspect_image_bytes(
        image.data
    )

    try:
        source = Image.open(
            BytesIO(image.data)
        )

        source.load()

    except Exception as exc:
        raise ImageProcessingError(
            "The image could not be decoded."
        ) from exc

    try:
        processed = ImageOps.exif_transpose(
            source
        )

        processed.thumbnail(
            (
                max_dimension,
                max_dimension,
            ),
            Image.Resampling.LANCZOS,
        )

        output = BytesIO()

        if actual_media_type == "image/png":
            processed.save(
                output,
                format="PNG",
                optimize=True,
            )

            output_media_type = "image/png"

        else:
            if processed.mode not in {
                "RGB",
                "L",
            }:
                processed = processed.convert(
                    "RGB"
                )

            processed.save(
                output,
                format="JPEG",
                quality=jpeg_quality,
                optimize=True,
            )

            output_media_type = "image/jpeg"

        return AuditImage(
            data=output.getvalue(),
            media_type=output_media_type,
            filename=image.filename,
            source=image.source,
        )

    except Exception as exc:
        raise ImageProcessingError(
            "The image could not be processed."
        ) from exc

    finally:
        source.close()


def get_image_dimensions(
    image: AuditImage,
) -> tuple[int, int]:
    """
    Return orientation-correct image width and height.
    """

    _inspect_image_bytes(
        image.data
    )

    try:
        with Image.open(
            BytesIO(image.data)
        ) as opened:

            oriented = ImageOps.exif_transpose(
                opened
            )

            return oriented.size

    except Exception as exc:
        raise ImageProcessingError(
            "Could not read image dimensions."
        ) from exc


def normalize_target_region(
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    canvas_width: float,
    canvas_height: float,
) -> TargetRegion:
    """
    Convert a target selection from displayed pixel coordinates
    into normalized 0.0-to-1.0 image coordinates.

    This keeps selections stable across different screen sizes
    and processed image resolutions.
    """


    values = {
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "canvas_width": canvas_width,
        "canvas_height": canvas_height,
    }

    for name, value in values.items():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ImageProcessingError(
                f"{name} must be a finite number."
            )

    if canvas_width <= 0 or canvas_height <= 0:
        raise ImageProcessingError(
            "Selection canvas dimensions must be greater than zero."
        )

    if width <= 0 or height <= 0:
        raise ImageProcessingError(
            "Target selection must have positive width and height."
        )

    if x < 0 or y < 0:
        raise ImageProcessingError(
            "Target selection cannot begin outside the image."
        )

    if x + width > canvas_width:
        raise ImageProcessingError(
            "Target selection extends beyond the right edge of the image."
        )

    if y + height > canvas_height:
        raise ImageProcessingError(
            "Target selection extends beyond the bottom edge of the image."
        )

    return TargetRegion(
        x=x / canvas_width,
        y=y / canvas_height,
        width=width / canvas_width,
        height=height / canvas_height,
    )



def crop_target_region(
    image: AuditImage,
    target_region: TargetRegion,
) -> AuditImage:
    """
    Crop one normalized target region from an AuditImage.

    The full image remains unchanged. This returns a separate
    AuditImage containing only the selected target product.
    """

    try:
        source = Image.open(
            BytesIO(image.data)
        )

        source.load()

    except Exception as exc:
        raise ImageProcessingError(
            "The image could not be decoded for target cropping."
        ) from exc

    try:
        oriented = ImageOps.exif_transpose(
            source
        )

        image_width, image_height = oriented.size

        left = round(
            target_region.x * image_width
        )

        top = round(
            target_region.y * image_height
        )

        right = round(
            (
                target_region.x
                + target_region.width
            )
            * image_width
        )

        bottom = round(
            (
                target_region.y
                + target_region.height
            )
            * image_height
        )

        left = max(
            0,
            min(left, image_width),
        )

        top = max(
            0,
            min(top, image_height),
        )

        right = max(
            0,
            min(right, image_width),
        )

        bottom = max(
            0,
            min(bottom, image_height),
        )

        if right <= left or bottom <= top:
            raise ImageProcessingError(
                "Target region produced an invalid crop."
            )

        cropped = oriented.crop(
            (
                left,
                top,
                right,
                bottom,
            )
        )

        output = BytesIO()

        if image.media_type == "image/png":
            cropped.save(
                output,
                format="PNG",
                optimize=True,
            )

            output_media_type = "image/png"

        else:
            if cropped.mode not in {
                "RGB",
                "L",
            }:
                cropped = cropped.convert(
                    "RGB"
                )

            cropped.save(
                output,
                format="JPEG",
                quality=JPEG_QUALITY,
                optimize=True,
            )

            output_media_type = "image/jpeg"

        return AuditImage(
            data=output.getvalue(),
            media_type=output_media_type,
            filename=image.filename,
            source="target_crop",
        )

    except ImageProcessingError:
        raise

    except Exception as exc:
        raise ImageProcessingError(
            "The selected target region could not be cropped."
        ) from exc

    finally:
        source.close()


def hash_image(
    image: AuditImage,
) -> str:
    """
    Return a stable SHA-256 hash for caching and deduplication.
    """

    return hashlib.sha256(
        image.data
    ).hexdigest()