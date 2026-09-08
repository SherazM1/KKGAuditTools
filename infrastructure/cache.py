"""
Caching and request fingerprint helpers.

This module stays independent of Streamlit and AI providers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from image_utils import hash_image
from models import AuditImage, AuditMode
from prompts import PROMPT_VERSION


CRITERIA_VERSION = "v1"


def _stable_json(data: Any) -> str:
    """
    Serialize data consistently so fingerprints are stable.
    """

    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
    )


def build_request_fingerprint(
    *,
    image: AuditImage,
    mode: AuditMode,
    criteria: list[dict],
    provider_name: str,
    model_name: str | None = None,
) -> str:
    """
    Build a stable fingerprint for one audit request.

    The fingerprint changes when any important audit input changes.
    """

    criteria_ids = [
        criterion["id"]
        for criterion in criteria
    ]

    payload = {
        "image_hash": hash_image(image),
        "mode": mode.value,
        "criteria_ids": criteria_ids,
        "criteria_version": CRITERIA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "provider": provider_name,
        "model": model_name,
    }

    serialized = _stable_json(payload)

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


class MemoryAuditCache:
    """
    Very small in-memory cache for development/testing.

    Later this can be replaced with persistent storage without
    changing the rest of the audit pipeline.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get(
        self,
        fingerprint: str,
    ) -> Any | None:
        return self._store.get(fingerprint)

    def set(
        self,
        fingerprint: str,
        value: Any,
    ) -> None:
        self._store[fingerprint] = value

    def has(
        self,
        fingerprint: str,
    ) -> bool:
        return fingerprint in self._store

    def clear(self) -> None:
        self._store.clear()