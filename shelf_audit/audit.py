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

from .audit_modes import get_mode_config, get_depth_config
from .guardrails import (
    validate_image,
    validate_mode,
    validate_opportunities,
)
from .infrastructure.cache import build_request_fingerprint
from .infrastructure.usage import AuditUsageRecord
from .models import (
    AuditMode,
    AuditDepth,
    AuditImage,
    TargetRegion,
    AuditRequest,
    AuditResult,
)
from .prioritization import prioritize_opportunities
from .criteria import validate_criteria


def _record_usage_safely(
    usage_tracker,
    record: AuditUsageRecord,
) -> None:
    """
    Record usage without allowing telemetry failures
    to break or mask an audit result.
    """

    if usage_tracker is None:
        return

    try:
        usage_tracker.record(record)
    except Exception:
        pass


def run_audit(
    *,
    image,
    criteria: list[dict],
    mode: AuditMode,
    depth: AuditDepth,
    provider,
    target_region: TargetRegion | None = None,
    target_crop: AuditImage | None = None,
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

    provider_config_version = getattr(
        provider,
        "config_version",
        None,
    )

    mode_value = getattr(
        mode,
        "value",
        str(mode),
    )

    depth_value = getattr(
        depth,
        "value",
        str(depth),
    )

    try:
        criteria_count = len(criteria)
    except Exception:
        criteria_count = 0

    try:
        # -------------------------------------------------
        # Input validation
        # -------------------------------------------------

        validate_image(image)

        validate_mode(
            mode,
            target_region=target_region,
        )

        if mode is AuditMode.EXPANDED:
            if target_crop is None:
                raise ValueError(
                    "Expanded mode requires a targeted crop."
                )

            validate_image(target_crop)

        elif target_crop is not None:
            raise ValueError(
                "A target crop can only be used in the expanded audit mode."
            )

        criteria = validate_criteria(
            criteria
        )

        criteria_count = len(criteria)

        # Resolve configuration.
        # get_mode_config() also confirms the supplied mode is valid.
        get_mode_config(mode)

        depth_config = get_depth_config(depth)

        # -------------------------------------------------
        # Request construction
        # -------------------------------------------------

        request = AuditRequest(
            image=image,
            criteria=tuple(criteria),
            mode=mode,
            depth=depth,
            target_region=target_region,
            target_crop=target_crop
        )

        # -------------------------------------------------
        # Request fingerprint
        # -------------------------------------------------

        fingerprint = build_request_fingerprint(
            image=image,
            mode=mode,
            criteria=criteria,
            depth=depth,
            target_region=target_region,
            provider_name=provider_name,
            model_name=model_name,
            provider_config_version=provider_config_version,
        )

        # -------------------------------------------------
        # Cache lookup
        # -------------------------------------------------

        cached_result = None

        if cache is not None:
            try:
                cached_result = cache.get(
                    fingerprint
                )
            except Exception:
                cached_result = None

        if cached_result is not None:
            duration = perf_counter() - start_time

            _record_usage_safely(
                usage_tracker,
                AuditUsageRecord(
                    mode=mode_value,
                    depth=depth_value,
                    provider_name=provider_name,
                    model_name=model_name,
                    cache_hit=True,
                    success=True,
                    criteria_count=criteria_count,
                    opportunity_count=len(
                        cached_result.opportunities
                    ),
                    duration_seconds=duration,
                ),
            )

            return cached_result

        # -------------------------------------------------
        # Rate limiting
        # Only applied on cache miss
        # -------------------------------------------------

        if rate_limiter is None and rate_limit_key is not None:
            raise ValueError(
                "rate_limit_key cannot be provided without rate_limiter."
            )

        if rate_limiter is not None:
            if (
                not isinstance(rate_limit_key, str)
                or not rate_limit_key.strip()
            ):
                raise ValueError(
                    "A non-empty rate_limit_key is required "
                    "when rate_limiter is provided."
                )

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
            criteria=criteria,
            max_results=depth_config.max_opportunities,
            min_confidence=depth_config.min_confidence,
        )

        result = AuditResult(
            opportunities=prioritized,
            mode=mode,
            depth=depth,
            criteria_evaluated=criteria_count,
        )

        # -------------------------------------------------
        # Cache store
        #
        # A cache failure must not discard a successful
        # provider result.
        # -------------------------------------------------

        if cache is not None:
            try:
                cache.set(
                    fingerprint,
                    result,
                )
            except Exception:
                pass

        # -------------------------------------------------
        # Usage tracking
        #
        # Telemetry is intentionally nonfatal.
        # -------------------------------------------------

        duration = perf_counter() - start_time

        _record_usage_safely(
            usage_tracker,
            AuditUsageRecord(
                mode=mode_value,
                depth=depth_value,
                provider_name=provider_name,
                model_name=model_name,
                cache_hit=False,
                success=True,
                criteria_count=criteria_count,
                opportunity_count=len(
                    result.opportunities
                ),
                duration_seconds=duration,
            ),
        )

        return result

    except Exception as exc:
        duration = perf_counter() - start_time

        _record_usage_safely(
            usage_tracker,
            AuditUsageRecord(
                mode=mode_value,
                depth=depth_value,
                provider_name=provider_name,
                model_name=model_name,
                cache_hit=False,
                success=False,
                criteria_count=criteria_count,
                opportunity_count=0,
                duration_seconds=duration,
                error_type=type(exc).__name__,
            ),
        )

        raise