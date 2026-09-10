"""
Audit orchestration.

This module coordinates:
- mode configuration
- depth configuration
- criteria selection
- guardrails
- request fingerprinting
- cache lookup / storage
- rate limiting
- provider execution
- opportunity prioritization
- usage tracking

It does not import Streamlit or any specific AI SDK.
"""

from __future__ import annotations

from time import perf_counter

from audit_modes import get_mode_config, get_depth_config
from guardrails import (
    validate_image,
    validate_mode,
    validate_selected_criteria,
    validate_opportunities,
)
from infrastructure.cache import build_request_fingerprint
from infrastructure.usage import AuditUsageRecord
from models import (
    AuditMode,
    AuditDepth,
    TargetRegion,
    AuditRequest,
    AuditResult,
)
from prioritization import prioritize_opportunities


def run_audit(
    *,
    image,
    criteria: list[dict],
    mode: AuditMode,
    depth: AuditDepth,
    provider,
    target_region: TargetRegion | None = None,
    cache=None,
    rate_limiter=None,
    rate_limit_key: str | None = None,
    usage_tracker=None,
) -> AuditResult:
    """
    Run one audit through the provider-neutral pipeline.

    Optional infrastructure:
    - cache
    - rate_limiter
    - usage_tracker
    """

    start_time = perf_counter()

    provider_name = getattr(
        provider,
        "name",
        provider.__class__.__name__,
    )

    model_name = getattr(
        provider,
        "model_name",
        None,
    )

    try:
        validate_image(image)

        validate_mode(
            mode,
            target_region=target_region,
        )

        validate_selected_criteria(criteria)

        mode_config = get_mode_config(mode)
        depth_config = get_depth_config(depth)

        request = AuditRequest(
            image=image,
            criteria=criteria,
            mode=mode,
            depth=depth,
            target_region=target_region,
        )

        fingerprint = build_request_fingerprint(
            image=image,
            mode=mode,
            criteria=criteria,
            depth=depth,
            target_region=target_region,
            provider_name=provider_name,
            model_name=model_name,
        )

        # -------------------------------------------------
        # Cache lookup
        # -------------------------------------------------

        if cache is not None:
            cached_result = cache.get(fingerprint)

            if cached_result is not None:
                duration = perf_counter() - start_time

                if usage_tracker is not None:
                    usage_tracker.record(
                        AuditUsageRecord(
                            mode=mode.value,
                            depth=depth.value,
                            provider_name=provider_name,
                            model_name=model_name,
                            cache_hit=True,
                            success=True,
                            criteria_count=len(criteria),
                            opportunity_count=len(
                                cached_result.opportunities
                            ),
                            duration_seconds=duration,
                        )
                    )

                return cached_result

        # -------------------------------------------------
        # Rate limiting
        # Only applied on cache miss
        # -------------------------------------------------

        if (
            rate_limiter is not None
            and rate_limit_key is not None
        ):
            rate_limiter.check_and_record(
                rate_limit_key
            )

        # -------------------------------------------------
        # Provider execution
        # -------------------------------------------------

        opportunities = provider.analyze(
            request
        )

        # -------------------------------------------------
        # Provider output guardrails
        # -------------------------------------------------

        opportunities = validate_opportunities(
            opportunities,
            criteria,
        )

        # -------------------------------------------------
        # Prioritization
        #
        # This handles:
        # - confidence filtering
        # - duplicate / overlap reduction
        # - priority scoring
        # - final Quick / Deep result limit
        # -------------------------------------------------

        prioritized = prioritize_opportunities(
            opportunities,
            max_results=depth_config.max_opportunities,
            min_confidence=depth_config.min_confidence,
        )

        result = AuditResult(
            opportunities=prioritized,
            mode=mode,
            depth=depth,
            criteria_evaluated=len(criteria),
        )

        # -------------------------------------------------
        # Cache store
        # -------------------------------------------------

        if cache is not None:
            cache.set(
                fingerprint,
                result,
            )

        # -------------------------------------------------
        # Usage tracking
        # -------------------------------------------------

        duration = perf_counter() - start_time

        if usage_tracker is not None:
            usage_tracker.record(
                AuditUsageRecord(
                    mode=mode.value,
                    depth=depth.value,
                    provider_name=provider_name,
                    model_name=model_name,
                    cache_hit=False,
                    success=True,
                    criteria_count=len(criteria),
                    opportunity_count=len(
                        result.opportunities
                    ),
                    duration_seconds=duration,
                )
            )

        return result

    except Exception as exc:
        duration = perf_counter() - start_time

        if usage_tracker is not None:
            usage_tracker.record(
                AuditUsageRecord(
                    mode=mode.value,
                    depth=depth.value,
                    provider_name=provider_name,
                    model_name=model_name,
                    cache_hit=False,
                    success=False,
                    criteria_count=len(criteria),
                    opportunity_count=0,
                    duration_seconds=duration,
                    error_type=type(exc).__name__,
                )
            )

        raise