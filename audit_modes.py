"""
Audit mode configuration.

Modes change audit depth and output volume.
They do NOT require the user to choose a criteria category.
"""

from __future__ import annotations

from dataclasses import dataclass

from models import AuditMode


@dataclass(frozen=True)
class AuditModeConfig:
    mode: AuditMode
    label: str
    description: str

    max_opportunities: int
    include_secondary: bool
    deep_reasoning: bool


MODE_CONFIGS = {
    AuditMode.QUICK: AuditModeConfig(
        mode=AuditMode.QUICK,
        label="Quick Audit",
        description="Find the strongest opportunities visible in the photo.",
        max_opportunities=3,
        include_secondary=False,
        deep_reasoning=False,
    ),

    AuditMode.FULL: AuditModeConfig(
        mode=AuditMode.FULL,
        label="Deep Audit",
        description="Perform a broader review and surface more opportunities.",
        max_opportunities=8,
        include_secondary=True,
        deep_reasoning=True,
    ),

    AuditMode.FOCUSED: AuditModeConfig(
        mode=AuditMode.FOCUSED,
        label="Focused Audit",
        description="Reserve for future targeted audits.",
        max_opportunities=5,
        include_secondary=True,
        deep_reasoning=True,
    ),
}


def get_mode_config(
    mode: AuditMode,
) -> AuditModeConfig:
    try:
        return MODE_CONFIGS[mode]

    except KeyError as exc:
        raise ValueError(
            f"Unsupported audit mode: {mode}"
        ) from exc