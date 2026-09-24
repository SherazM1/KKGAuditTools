"""
Lightweight audit usage and telemetry helpers.

This module is provider-neutral and Streamlit-neutral.
It can later be replaced or extended with persistent analytics storage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AuditUsageRecord:
    """
    One audit execution record.
    """

    mode: str
    depth: str
    provider_name: str

    cache_hit: bool
    success: bool

    criteria_count: int
    opportunity_count: int

    duration_seconds: float

    model_name: str | None = None

    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None

    error_type: str | None = None

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class MemoryUsageTracker:
    """
    Simple bounded in-memory usage tracker for development.

    Later this can be replaced with a database or analytics backend.
    """

    def __init__(
        self,
        *,
        max_records: int = 500,
    ) -> None:

        if max_records < 1:
            raise ValueError(
                "max_records must be at least 1."
            )

        self.max_records = max_records
        self._records: list[AuditUsageRecord] = []

    def record(
        self,
        usage: AuditUsageRecord,
    ) -> None:
        self._records.append(usage)

        overflow = (
            len(self._records)
            - self.max_records
        )

        if overflow > 0:
            del self._records[:overflow]

    def all(
        self,
    ) -> list[AuditUsageRecord]:
        return list(self._records)

    def count(
        self,
    ) -> int:
        return len(self._records)

    def clear(
        self,
    ) -> None:
        self._records.clear()