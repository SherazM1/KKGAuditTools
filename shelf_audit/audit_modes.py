"""

Audit mode and depth configuration.

Audit mode controls what part of the scene is being analyzed.
Audit depth controls reasoning depth, confidence thresholds,
and output volume.

Neither requires the user to choose a criteria category.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import AuditMode, AuditDepth


@dataclass(frozen=True)
class AuditModeConfig:
    mode: AuditMode
    label: str
    description: str
    requires_target_region: bool
    allows_context_comparison: bool

@dataclass(frozen=True)
class AuditDepthConfig:
    depth: AuditDepth
    label: str
    description: str
    max_candidates: int
    max_opportunities: int
    include_secondary: bool
    deep_reasoning: bool
    min_confidence: float



MODE_CONFIGS = {
    AuditMode.PRODUCT: AuditModeConfig(
        mode=AuditMode.PRODUCT,
        label="Product",
        description="Photograph and analyze a specific product and its shelf environment.",
        requires_target_region=False,
        allows_context_comparison=False
    ),

    AuditMode.EXPANDED: AuditModeConfig(
        mode=AuditMode.EXPANDED,
        label="Expanded",
        description="Analyze one selected target product and use the surrounding wider shelf scene to add context and drive results.",
        requires_target_region=True,
        allows_context_comparison=True
      
    ),

}


DEPTH_CONFIGS = {
    AuditDepth.QUICK: AuditDepthConfig(
        depth=AuditDepth.QUICK,
        label="Quick Audit",
        description="A fast audit that prioritizes the strongest, visible opportunities.",
        max_candidates = 8,
        max_opportunities=4,
        include_secondary=False,
        deep_reasoning=False,
        min_confidence=0.65
    ),

    AuditDepth.DEEP: AuditDepthConfig(
        depth=AuditDepth.DEEP,
        label="Deep Audit",
        description="A thorough audit that prioritizes depth and a broader set of opportunities.",
        max_candidates=14,
        max_opportunities=8,
        include_secondary=True,
        deep_reasoning=True,
        min_confidence=0.5
    ),
}

def get_depth_config(
    depth: AuditDepth,
) -> AuditDepthConfig:
    try:
        return DEPTH_CONFIGS[depth]
    
    except KeyError as exc:
        raise ValueError(
            f"Unsupported audit depth: {depth}"
        ) from exc


def get_mode_config(
    mode: AuditMode,
) -> AuditModeConfig:
    try:
        return MODE_CONFIGS[mode]

    except KeyError as exc:
        raise ValueError(
            f"Unsupported audit mode: {mode}"
        ) from exc