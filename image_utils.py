"""
Image normalization and preprocessing helpers for the audit application.

Camera captures and uploaded files should both become
the same AuditImage structure before entering the audit pipeline.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps

from models import AuditImage


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
JPEG_QUALITY = 85


class ImageProcessingError(ValueError):
    """Raised when an image cannot be safely processed."""


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
    Normalize any image source into an AuditImage.
    """

    if not isinstance(data, bytes):
        raise ImageProcessingError(
            "Image data must be bytes."
        )

    if not data:
        raise ImageProcessingError(
            "Image data is empty."
        )

    resolved_media_type = detect_media_type(
        filename=filename,
        provided_type=media_type,
    )

    return AuditImage(
        data=data,
        media_type=resolved_media_type,
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

        if image.media_type == "image/png":
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
    Return image width and height.
    """

    try:
        with Image.open(
            BytesIO(image.data)
        ) as opened:
            return opened.size

    except Exception as exc:
        raise ImageProcessingError(
            "Could not read image dimensions."
        ) from exc


def hash_image(
    image: AuditImage,
) -> str:
    """
    Return a stable SHA-256 hash for caching and deduplication.
    """

    return hashlib.sha256(
        image.data
    ).hexdigest()