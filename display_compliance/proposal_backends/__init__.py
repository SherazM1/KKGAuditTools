"""Region proposal backends with lazy loading for the optional SAM backend."""

from __future__ import annotations

from importlib import import_module

from .base import (
    LearnedProposal,
    LearnedSegmentationDiagnostics,
    RegionProposalBackend,
    RegionProposalBackendUnavailable,
    RegionProposalResult,
)

_SAM2_EXPORTS = {
    "DEFAULT_LEARNED_MAX_SIDE_ENV",
    "DEFAULT_SAM2_CACHE_DIR_ENV",
    "DEFAULT_SAM2_CHECKPOINT_ENV",
    "DEFAULT_SAM2_MODEL_CONFIG",
    "DEFAULT_SAM2_MODEL_CONFIG_ENV",
    "DEFAULT_SAM2_TINY_CHECKPOINT_URL",
    "Sam2AutomaticMaskBackend",
    "analyze_learned_candidate_regions",
}

__all__ = [
    "DEFAULT_LEARNED_MAX_SIDE_ENV",
    "DEFAULT_SAM2_CACHE_DIR_ENV",
    "DEFAULT_SAM2_CHECKPOINT_ENV",
    "DEFAULT_SAM2_MODEL_CONFIG",
    "DEFAULT_SAM2_MODEL_CONFIG_ENV",
    "DEFAULT_SAM2_TINY_CHECKPOINT_URL",
    "LearnedProposal",
    "LearnedSegmentationDiagnostics",
    "RegionProposalBackend",
    "RegionProposalBackendUnavailable",
    "RegionProposalResult",
    "Sam2AutomaticMaskBackend",
    "analyze_learned_candidate_regions",
]


def __getattr__(name: str):
    if name not in _SAM2_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    backend = import_module(".sam2_backend", __name__)
    value = getattr(backend, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _SAM2_EXPORTS)
