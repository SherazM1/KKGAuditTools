"""Debug-only estimates from actual response usage and user-supplied standard rates."""
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: Decimal
    cached_input_per_million: Decimal
    cache_write_30m_per_million: Decimal
    cache_write_12h_per_million: Decimal
    output_per_million: Decimal


MODEL_PRICING = MappingProxyType({
    "gpt-6.1-sol": ModelPricing(*(Decimal(rate) for rate in ("2", ".10", "2.50", "5", "10"))),
})


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def estimate_openai_request_cost(*, model, input_tokens=None, output_tokens=None,
                                cached_input_tokens=0, cache_write_tokens=0,
                                cache_write_30m_tokens=0, cache_write_12h_tokens=0,
                                request_cache_ttl=None):
    """Price disjoint buckets; request_cache_ttl describes configuration, never sets it."""
    reasons = []

    def count(value, name, required=False):
        if value is None:
            if required:
                reasons.append(f"{name} unavailable")
            return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            reasons.append(f"{name} invalid")
            return 0
        return value

    inputs = count(input_tokens, "input_tokens", True)
    outputs = count(output_tokens, "output_tokens", True)
    cached = count(cached_input_tokens, "cached_input_tokens")
    writes = count(cache_write_tokens, "cache_write_tokens")
    short = count(cache_write_30m_tokens, "cache_write_30m_tokens")
    long = count(cache_write_12h_tokens, "cache_write_12h_tokens")
    effective_short, effective_long = short, long
    ttl_source = "unknown"
    if short or long:
        ttl_source = "provider_breakdown"
    elif writes:
        if request_cache_ttl is None:
            effective_short = writes
            ttl_source = "default_30m"
        elif request_cache_ttl == "30m":
            effective_short = writes
            ttl_source = "request_configuration"
        elif request_cache_ttl == "12h":
            effective_long = writes
            ttl_source = "request_configuration"
        else:
            reasons.append("Explicit request cache TTL is unknown or unsupported")
    if effective_short + effective_long != writes:
        reasons.append("Cache-write TTL breakdown is missing or inconsistent")
    if cached + writes > inputs:
        reasons.append("Cached and cache-write tokens exceed input total")
    ordinary = max(0, inputs - cached - writes)
    pricing = MODEL_PRICING.get(model)
    cost = None
    if pricing is None:
        reasons.append("Model has no configured standard pricing")
    elif input_tokens is not None and output_tokens is not None:
        cost = float((ordinary * pricing.input_per_million
                      + cached * pricing.cached_input_per_million
                      + effective_short * pricing.cache_write_30m_per_million
                      + effective_long * pricing.cache_write_12h_per_million
                      + outputs * pricing.output_per_million) / Decimal(1_000_000))
    return dict(model=model, input_tokens=input_tokens, ordinary_input_tokens=ordinary,
                cached_input_tokens=cached, cache_write_tokens=writes,
                cache_write_30m_tokens=short, cache_write_12h_tokens=long,
                effective_cache_write_30m_tokens=effective_short,
                effective_cache_write_12h_tokens=effective_long,
                cache_write_ttl_source=ttl_source, request_cache_ttl=request_cache_ttl,
                output_tokens=output_tokens, estimated_cost_usd=cost,
                estimate_complete=not reasons, reason="; ".join(reasons) or None)


def response_cost_diagnostic(*, model, usage, request_cache_ttl=None):
    """Accept SDK objects or mappings; diagnostics must never fail a successful audit."""
    try:
        details = _field(usage, "input_tokens_details")
        ttl = _field(details, "cache_write_tokens_details")
        result = estimate_openai_request_cost(
            model=model, request_cache_ttl=request_cache_ttl,
            input_tokens=_field(usage, "input_tokens"),
            output_tokens=_field(usage, "output_tokens"),
            cached_input_tokens=_field(details, "cached_tokens", 0),
            cache_write_tokens=_field(details, "cache_write_tokens", 0),
            cache_write_30m_tokens=_field(ttl, "ttl_30m_tokens", 0),
            cache_write_12h_tokens=_field(ttl, "ttl_12h_tokens", 0),
        )
        if usage is None:
            result.update(estimated_cost_usd=None, estimate_complete=False, reason="Provider usage unavailable")
        return result
    except Exception:
        return dict(model=model, estimated_cost_usd=None, estimate_complete=False,
                    reason="Provider usage could not be read")
