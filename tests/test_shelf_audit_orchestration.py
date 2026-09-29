"""
Regression tests for Shelf Audit orchestration.

These tests verify cost-sensitive behavior without making
any network or paid AI calls.
"""

from __future__ import annotations

import io
import unittest

from PIL import Image

from shelf_audit.audit import run_audit
from shelf_audit.criteria import (
    CriteriaError,
    load_criteria,
)
from shelf_audit.infrastructure.cache import MemoryAuditCache
from shelf_audit.infrastructure.rate_limit import MemoryRateLimiter
from shelf_audit.models import (
    AuditDepth,
    AuditImage,
    AuditMode,
    AuditRequest,
    TargetRegion,
)
from shelf_audit.opportunity import Opportunity
from shelf_audit.providers.base import AuditProvider


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
    config_version = "1"

    def __init__(self) -> None:
        self.calls = 0

    def analyze(
        self,
        request: AuditRequest,
    ) -> list[Opportunity]:
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

        return [
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