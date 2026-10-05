"""
Regression tests for Shelf Audit cache, rate limiting,
and in-memory usage telemetry.

These tests are deterministic and do not call any AI provider.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from shelf_audit.infrastructure.cache import (
    MemoryAuditCache,
)
from shelf_audit.infrastructure.rate_limit import (
    MemoryRateLimiter,
    RateLimitError,
)
from shelf_audit.infrastructure.usage import (
    AuditUsageRecord,
    MemoryUsageTracker,
)


def _usage_record(
    *,
    provider_name: str = "mock",
    cache_hit: bool = False,
    success: bool = True,
) -> AuditUsageRecord:
    return AuditUsageRecord(
        mode="product",
        depth="quick",
        provider_name=provider_name,
        cache_hit=cache_hit,
        success=success,
        criteria_count=3,
        opportunity_count=2,
        duration_seconds=0.25,
    )


class ShelfAuditInfrastructureTests(unittest.TestCase):

    # -------------------------
    # CACHE
    # -------------------------

    def test_cache_set_and_get(self) -> None:
        cache = MemoryAuditCache()

        cache.set(
            "abc",
            {"value": 123},
        )

        self.assertEqual(
            cache.get("abc"),
            {"value": 123},
        )

    def test_cache_missing_key_returns_none(
        self,
    ) -> None:
        cache = MemoryAuditCache()

        self.assertIsNone(
            cache.get("missing")
        )

    def test_cache_has_reports_existing_entry(
        self,
    ) -> None:
        cache = MemoryAuditCache()

        cache.set(
            "abc",
            {"value": 1},
        )

        self.assertTrue(
            cache.has("abc")
        )

    def test_cache_clear_removes_entries(
        self,
    ) -> None:
        cache = MemoryAuditCache()

        cache.set(
            "abc",
            {"value": 1},
        )

        cache.clear()

        self.assertFalse(
            cache.has("abc")
        )

    def test_cache_write_uses_deep_copy(
        self,
    ) -> None:
        cache = MemoryAuditCache()

        original = {
            "nested": {
                "value": 1,
            }
        }

        cache.set(
            "abc",
            original,
        )

        original["nested"]["value"] = 99

        cached = cache.get("abc")

        self.assertEqual(
            cached["nested"]["value"],
            1,
        )

    def test_cache_read_uses_deep_copy(
        self,
    ) -> None:
        cache = MemoryAuditCache()

        cache.set(
            "abc",
            {
                "nested": {
                    "value": 1,
                }
            },
        )

        first_read = cache.get("abc")

        first_read["nested"]["value"] = 99

        second_read = cache.get("abc")

        self.assertEqual(
            second_read["nested"]["value"],
            1,
        )

    def test_cache_evicts_oldest_entry(
        self,
    ) -> None:
        cache = MemoryAuditCache(
            max_entries=2,
        )

        cache.set(
            "first",
            1,
        )

        cache.set(
            "second",
            2,
        )

        cache.set(
            "third",
            3,
        )

        self.assertFalse(
            cache.has("first")
        )

        self.assertTrue(
            cache.has("second")
        )

        self.assertTrue(
            cache.has("third")
        )

    def test_cache_recently_read_entry_becomes_newest(
        self,
    ) -> None:
        cache = MemoryAuditCache(
            max_entries=2,
        )

        cache.set(
            "first",
            1,
        )

        cache.set(
            "second",
            2,
        )

        cache.get("first")

        cache.set(
            "third",
            3,
        )

        self.assertTrue(
            cache.has("first")
        )

        self.assertFalse(
            cache.has("second")
        )

        self.assertTrue(
            cache.has("third")
        )

    def test_cache_expired_entry_is_removed(
        self,
    ) -> None:
        with patch(
            "shelf_audit.infrastructure.cache.time.monotonic",
            side_effect=[
                100.0,
                100.0,
                111.0,
            ],
        ):
            cache = MemoryAuditCache(
                ttl_seconds=10,
            )

            cache.set(
                "abc",
                123,
            )

            self.assertIsNone(
                cache.get("abc")
            )

    def test_cache_invalid_max_entries_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            MemoryAuditCache(
                max_entries=0,
            )

    def test_cache_invalid_ttl_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            MemoryAuditCache(
                ttl_seconds=0,
            )

    # -------------------------
    # RATE LIMITER
    # -------------------------

    def test_rate_limiter_starts_with_full_capacity(
        self,
    ) -> None:
        limiter = MemoryRateLimiter(
            max_requests=5,
        )

        self.assertEqual(
            limiter.remaining("user"),
            5,
        )

    def test_rate_limiter_record_reduces_remaining(
        self,
    ) -> None:
        limiter = MemoryRateLimiter(
            max_requests=5,
        )

        limiter.record("user")

        self.assertEqual(
            limiter.remaining("user"),
            4,
        )

    def test_rate_limiter_blocks_when_limit_reached(
        self,
    ) -> None:
        limiter = MemoryRateLimiter(
            max_requests=2,
            window_seconds=60,
        )

        limiter.record("user")
        limiter.record("user")

        with self.assertRaises(
            RateLimitError
        ):
            limiter.check("user")

    def test_rate_limiter_check_and_record(
        self,
    ) -> None:
        limiter = MemoryRateLimiter(
            max_requests=2,
        )

        limiter.check_and_record(
            "user"
        )

        self.assertEqual(
            limiter.remaining("user"),
            1,
        )

    def test_rate_limiter_window_expiration_restores_capacity(
        self,
    ) -> None:
        limiter = MemoryRateLimiter(
            max_requests=2,
            window_seconds=10,
        )

        with patch(
            "shelf_audit.infrastructure.rate_limit.time.monotonic",
            side_effect=[
                100.0,
                101.0,
                111.0,
            ],
        ):
            limiter.record("user")
            limiter.record("user")

            self.assertEqual(
                limiter.remaining("user"),
                2,
            )

    def test_rate_limiter_clear_one_key(
        self,
    ) -> None:
        limiter = MemoryRateLimiter(
            max_requests=2,
        )

        limiter.record("user_a")
        limiter.record("user_b")

        limiter.clear("user_a")

        self.assertEqual(
            limiter.remaining("user_a"),
            2,
        )

        self.assertEqual(
            limiter.remaining("user_b"),
            1,
        )

    def test_rate_limiter_clear_all(
        self,
    ) -> None:
        limiter = MemoryRateLimiter(
            max_requests=2,
        )

        limiter.record("user_a")
        limiter.record("user_b")

        limiter.clear()

        self.assertEqual(
            limiter.remaining("user_a"),
            2,
        )

        self.assertEqual(
            limiter.remaining("user_b"),
            2,
        )

    def test_rate_limiter_invalid_max_requests_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            MemoryRateLimiter(
                max_requests=0,
            )

    def test_rate_limiter_invalid_window_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            MemoryRateLimiter(
                window_seconds=0,
            )

    # -------------------------
    # USAGE TRACKER
    # -------------------------

    def test_usage_tracker_records_entry(
        self,
    ) -> None:
        tracker = MemoryUsageTracker()

        record = _usage_record()

        tracker.record(
            record
        )

        self.assertEqual(
            tracker.count(),
            1,
        )

        self.assertEqual(
            tracker.all()[0],
            record,
        )

    def test_usage_tracker_preserves_order(
        self,
    ) -> None:
        tracker = MemoryUsageTracker()

        first = _usage_record(
            provider_name="first",
        )

        second = _usage_record(
            provider_name="second",
        )

        tracker.record(first)
        tracker.record(second)

        records = tracker.all()

        self.assertEqual(
            records[0].provider_name,
            "first",
        )

        self.assertEqual(
            records[1].provider_name,
            "second",
        )

    def test_usage_tracker_enforces_max_records(
        self,
    ) -> None:
        tracker = MemoryUsageTracker(
            max_records=2,
        )

        tracker.record(
            _usage_record(
                provider_name="first",
            )
        )

        tracker.record(
            _usage_record(
                provider_name="second",
            )
        )

        tracker.record(
            _usage_record(
                provider_name="third",
            )
        )

        records = tracker.all()

        self.assertEqual(
            len(records),
            2,
        )

        self.assertEqual(
            records[0].provider_name,
            "second",
        )

        self.assertEqual(
            records[1].provider_name,
            "third",
        )

    def test_usage_tracker_all_returns_new_list(
        self,
    ) -> None:
        tracker = MemoryUsageTracker()

        tracker.record(
            _usage_record()
        )

        records = tracker.all()

        records.clear()

        self.assertEqual(
            tracker.count(),
            1,
        )

    def test_usage_tracker_clear(
        self,
    ) -> None:
        tracker = MemoryUsageTracker()

        tracker.record(
            _usage_record()
        )

        tracker.clear()

        self.assertEqual(
            tracker.count(),
            0,
        )

    def test_usage_tracker_invalid_max_records_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            MemoryUsageTracker(
                max_records=0,
            )


if __name__ == "__main__":
    unittest.main()