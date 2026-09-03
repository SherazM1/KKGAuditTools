"""
Image normalization helpers for the audit application.

Camera captures and uploaded files should both become
the same AuditImage structure before entering the audit pipeline.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from models import AuditImage


ALLOWED_EXTENSIONS = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def detect_media_type(
    filename: str | None,
    provided_type: str | None = None,
) -> str:
    """
    Resolve a supported image media type.
    """

    if provided_type in {
        "image/jpeg",
        "image/png",
    }:
        return provided_type

    if filename:
        suffix = Path(filename).suffix.lower()

        if suffix in ALLOWED_EXTENSIONS:
            return ALLOWED_EXTENSIONS[suffix]

    raise ValueError(
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


def hash_image(
    image: AuditImage,
) -> str:
    """
    Return a stable SHA-256 hash for caching and deduplication.
    """

    return hashlib.sha256(
        image.data
    ).hexdigest()