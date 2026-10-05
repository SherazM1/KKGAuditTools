"""
Regression tests for Shelf Audit orchestration.

These tests verify cost-sensitive behavior without making
any network or paid AI calls.
"""

from __future__ import annotations

import io
import unittest
from unittest.mock import Mock

from PIL import Image

from shelf_audit.audit import run_audit
from shelf_audit.criteria import (
    CriteriaError,
    load_criteria,
)
from shelf_audit.infrastructure.cache import MemoryAuditCache
from shelf_audit.infrastructure.rate_limit import MemoryRateLimiter
from shelf_audit.infrastructure.usage import MemoryUsageTracker
from shelf_audit.models import (
    AuditDepth,
    AuditImage,
    AuditMode,
    AuditRequest,
    TargetRegion,
)
from shelf_audit.opportunity import Opportunity
from shelf_audit.providers.base import (
    AuditProvider,
    ProviderAnalysisResult,
    ProviderConfigurationError,
    ProviderTimeoutError,
    ProviderUsage,
)

def _make_test_image() -> AuditImage:
    """
    Create a small valid PNG entirely in memory.
    """

    buffer = io.BytesIO()

    image = Image.new(
        "RGB",
        (100, 100),
        "white",
    )

    image.save(
        buffer,
        format="PNG",
    )

    return AuditImage(
        data=buffer.getvalue(),
        media_type="image/png",
        filename="test.png",
        source="test",
    )


class CountingProvider(AuditProvider):
    """
    Small deterministic provider used to verify call counts.
    """

    name = "counting_test"
    model_name = "test-model"
    config_version = "3"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(
        self,
        request: AuditRequest,
    ) -> ProviderAnalysisResult:
        self.calls += 1

        available_ids = {
            criterion["id"]
            for criterion in request.criteria
        }

        criterion_id = (
            "stackable_opportunity"
            if "stackable_opportunity" in available_ids
            else next(iter(available_ids))
        )

        opportunities = [
            Opportunity(
                criterion_id=criterion_id,
                title="Test opportunity",
                evidence="Visible test evidence.",
                recommendation="Take a test action.",
                relevance=0.90,
                confidence=0.90,
                impact=0.90,
                actionability=0.90,
            )
        ]

        return ProviderAnalysisResult(
            opportunities=opportunities,
            usage=ProviderUsage(
                estimated_cost=0.0,
                provider_called=False,
                attempt_count=0,
            )
        )


class FailingWriteCache:
    """
    Cache whose write path always fails.

    Used to verify that cache infrastructure failure does
    not discard a successful provider result.
    """

    def get(
        self,
        fingerprint: str,
    ):
        return None

    def set(
        self,
        fingerprint: str,
        result,
    ) -> None:
        raise RuntimeError(
            "Intentional cache write failure."
        )


class ShelfAuditOrchestrationTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.image = _make_test_image()
        self.criteria = load_criteria()

    def _run(self, provider, **kwargs):
        return run_audit(
            image=self.image,
            criteria=self.criteria,
            mode=AuditMode.PRODUCT,
            depth=AuditDepth.QUICK,
            provider=provider,
            **kwargs,
        )

    def test_disabled_openai_cache_miss_blocks_before_limiter(self):
        provider = CountingProvider()
        provider.name = "openai"
        tracker = MemoryUsageTracker()
        limiter = Mock()
        with self.assertRaises(ProviderConfigurationError):
            self._run(provider, ai_enabled=False, cache=MemoryAuditCache(),
                      rate_limiter=limiter, rate_limit_key="test-user",
                      usage_tracker=tracker)
        self.assertEqual(provider.calls, 0)
        limiter.check_and_record.assert_not_called()
        record = tracker.all()[0]
        self.assertFalse(record.success)
        self.assertFalse(record.provider_called)
        self.assertEqual(record.attempt_count, 0)
        self.assertEqual(record.error_type, "ProviderConfigurationError")

    def test_disabled_openai_cache_hit_bypasses_provider_and_limiter(self):
        provider = CountingProvider()
        provider.name = "openai"
        cache = MemoryAuditCache()
        cached = self._run(provider, cache=cache)
        provider.analyze = Mock(side_effect=AssertionError("Unexpected provider call"))
        tracker = MemoryUsageTracker()
        limiter = Mock()
        result = self._run(provider, ai_enabled=False, cache=cache,
                           rate_limiter=limiter, rate_limit_key="test-user",
                           usage_tracker=tracker)
        self.assertEqual(result, cached)
        provider.analyze.assert_not_called()
        limiter.check_and_record.assert_not_called()
        record = tracker.all()[0]
        self.assertTrue(record.cache_hit)
        self.assertFalse(record.provider_called)
        self.assertEqual(record.attempt_count, 0)
        self.assertEqual(record.estimated_cost, 0.0)

    def test_disabled_ai_allows_non_openai_provider(self):
        provider = CountingProvider()
        result = self._run(provider, ai_enabled=False)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(result.opportunities), 1)

    def test_ai_enabled_requires_real_bool(self):
        provider = CountingProvider()
        with self.assertRaises(ProviderConfigurationError):
            self._run(provider, ai_enabled=0)
        self.assertEqual(provider.calls, 0)

    def test_failure_attempt_metadata_reaches_usage_tracker(self):
        provider = CountingProvider()
        error = ProviderTimeoutError("Test timeout", provider_called=True, attempt_count=1)
        provider.analyze = Mock(side_effect=error)
        tracker = MemoryUsageTracker()
        with self.assertRaises(ProviderTimeoutError) as caught:
            self._run(provider, usage_tracker=tracker)
        self.assertIs(caught.exception, error)
        record = tracker.all()[0]
        self.assertTrue(record.provider_called)
        self.assertEqual(record.attempt_count, 1)
        self.assertEqual(record.error_type, "ProviderTimeoutError")

    def test_malformed_exception_metadata_preserves_original_failure(self):
        class BadMetadataError(Exception):
            @property
            def provider_called(self):
                raise ValueError("Invalid metadata")

            attempt_count = "invalid"

        error = BadMetadataError("Original failure")
        provider = CountingProvider()
        provider.analyze = Mock(side_effect=error)
        tracker = MemoryUsageTracker()
        with self.assertRaises(BadMetadataError) as caught:
            self._run(provider, usage_tracker=tracker)
        self.assertIs(caught.exception, error)
        record = tracker.all()[0]
        self.assertFalse(record.provider_called)
        self.assertEqual(record.attempt_count, 0)

    def test_invalid_criteria_never_calls_provider(
        self,
    ) -> None:
        provider = CountingProvider()

        malformed_criteria = [
            {
                "id": "broken_criterion",
            }
        ]

        with self.assertRaises(
            CriteriaError
        ):
            run_audit(
                image=self.image,
                criteria=malformed_criteria,
                mode=AuditMode.PRODUCT,
                depth=AuditDepth.QUICK,
                provider=provider,
            )

        self.assertEqual(
            provider.calls,
            0,
        )

    def test_cache_hit_bypasses_provider_and_limiter(
        self,
    ) -> None:
        provider = CountingProvider()

        cache = MemoryAuditCache(
            max_entries=10,
            ttl_seconds=3600,
        )

        limiter = MemoryRateLimiter(
            max_requests=1,
            window_seconds=60,
        )

        first_result = run_audit(
            image=self.image,
            criteria=self.criteria,
            mode=AuditMode.PRODUCT,
            depth=AuditDepth.QUICK,
            provider=provider,
            cache=cache,
            rate_limiter=limiter,
            rate_limit_key="test-user",
        )

        second_result = run_audit(
            image=self.image,
            criteria=self.criteria,
            mode=AuditMode.PRODUCT,
            depth=AuditDepth.QUICK,
            provider=provider,
            cache=cache,
            rate_limiter=limiter,
            rate_limit_key="test-user",
        )

        self.assertEqual(
            provider.calls,
            1,
        )

        self.assertEqual(
            len(first_result.opportunities),
            len(second_result.opportunities),
        )

    def test_cache_write_failure_does_not_discard_success(
        self,
    ) -> None:
        provider = CountingProvider()

        result = run_audit(
            image=self.image,
            criteria=self.criteria,
            mode=AuditMode.PRODUCT,
            depth=AuditDepth.QUICK,
            provider=provider,
            cache=FailingWriteCache(),
        )

        self.assertEqual(
            provider.calls,
            1,
        )

        self.assertEqual(
            len(result.opportunities),
            1,
        )

    def test_expanded_without_target_crop_fails_before_provider(
        self,
    ) -> None:
        provider = CountingProvider()

        target_region = TargetRegion(
            x=0.10,
            y=0.10,
            width=0.40,
            height=0.40,
        )

        with self.assertRaises(
            ValueError
        ):
            run_audit(
                image=self.image,
                criteria=self.criteria,
                mode=AuditMode.EXPANDED,
                depth=AuditDepth.QUICK,
                target_region=target_region,
                target_crop=None,
                provider=provider,
            )

        self.assertEqual(
            provider.calls,
            0,
        )


if __name__ == "__main__":
    unittest.main()