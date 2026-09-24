"""
Caching and request fingerprint helpers.

This module stays independent of Streamlit and AI providers.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from collections import OrderedDict
import copy
import time
from ..image_utils import hash_image
from ..models import AuditImage, AuditMode, AuditDepth, TargetRegion
from ..prompts import PROMPT_VERSION

AUDIT_CONFIG_VERSION = 1 


def _stable_json(data: Any) -> str:
    """
    Serialize data consistently so fingerprints are stable.
    """

    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_criteria(
        criteria: list[dict],
) -> str:
    """
    Build a hash for the complete criteria list.
    
    """

    serialized = _stable_json(criteria)

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


def build_request_fingerprint(
    *,
    image: AuditImage,
    mode: AuditMode,
    depth: AuditDepth,
    criteria: list[dict],
    provider_name: str,
    model_name: str | None = None,
    provider_config_version: str | None = None,
    target_region: TargetRegion | None = None,
) -> str:
    """
    Build a stable fingerprint for one audit request.

    The fingerprint changes when any important audit input changes.
    """

    criteria_hash = _hash_criteria(criteria)

    target_payload = None

    if target_region is not None:
        target_payload = {
            "x": target_region.x,
            "y": target_region.y,
            "width": target_region.width,
            "height": target_region.height,
        }

    payload = {
        "image_hash": hash_image(image),
        "mode": mode.value,
        "criteria_hash": criteria_hash,
        "prompt_version": PROMPT_VERSION,
        "provider": provider_name,
        "model": model_name,
        "depth": depth.value,
        "target_region": target_payload,
        "image_media_type": image.media_type,
        "audit_config_version": AUDIT_CONFIG_VERSION,
        "provider_config_version": provider_config_version,
    }

    serialized = _stable_json(payload)

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


class MemoryAuditCache:
    """
    Bounded in-memory cache for development and session use.

    Entries expire lazily and cached values are copied on read/write
    so callers cannot accidentally mutate stored results.
    """

    def __init__(
        self,
        *,
        max_entries: int = 100,
        ttl_seconds: int = 3600,
    ) -> None:

        if max_entries < 1:
            raise ValueError(
                "max_entries must be at least 1."
            )

        if ttl_seconds < 1:
            raise ValueError(
                "ttl_seconds must be at least 1."
            )

        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds

        self._store: OrderedDict[
            str,
            tuple[float, Any],
        ] = OrderedDict()

    def _remove_expired(
        self,
    ) -> None:
        """
        Remove entries whose TTL has expired.
        """

        now = time.monotonic()

        expired = [
            fingerprint
            for fingerprint, (
                expires_at,
                _,
            ) in self._store.items()
            if expires_at <= now
        ]

        for fingerprint in expired:
            self._store.pop(
                fingerprint,
                None,
            )

    def get(
        self,
        fingerprint: str,
    ) -> Any | None:

        self._remove_expired()

        entry = self._store.get(
            fingerprint
        )

        if entry is None:
            return None

        _, value = entry

        self._store.move_to_end(
            fingerprint
        )

        return copy.deepcopy(
            value
        )

    def set(
        self,
        fingerprint: str,
        value: Any,
    ) -> None:

        self._remove_expired()

        expires_at = (
            time.monotonic()
            + self.ttl_seconds
        )

        self._store[fingerprint] = (
            expires_at,
            copy.deepcopy(value),
        )

        self._store.move_to_end(
            fingerprint
        )

        while len(self._store) > self.max_entries:
            self._store.popitem(
                last=False
            )

    def has(
        self,
        fingerprint: str,
    ) -> bool:

        self._remove_expired()

        return fingerprint in self._store

    def clear(
        self,
    ) -> None:
        self._store.clear()