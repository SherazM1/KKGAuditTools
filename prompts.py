"""
Prompt construction for the shelf audit tool.

This module is provider-neutral.
It does not call any AI API directly.
"""

from __future__ import annotations

import json

from audit_modes import get_mode_config
from models import AuditMode


PROMPT_VERSION = "v1"


def _compact_criteria(criteria: list[dict]) -> str:
    """
    Convert criteria into a compact model-facing JSON representation.
    """

    compact = []

    for criterion in criteria:
        compact.append(
            {
                "id": criterion["id"],
                "applies_when": criterion["applies_when"],
                "check": criterion["check"],
                "suggestion": criterion["suggestion"],
            }
        )

    return json.dumps(
        compact,
        separators=(",", ":"),
    )


def build_audit_prompt(
    criteria: list[dict],
    mode: AuditMode,
) -> str:
    """
    Build the opportunity-first audit prompt.
    """

    mode_config = get_mode_config(mode)
    criteria_json = _compact_criteria(criteria)

    return f"""
You are analyzing a retail shelf or merchandising photo.

Your job is NOT to mechanically score every criterion.

Your job is to understand the specific scene and identify the strongest
merchandising opportunities that are supported by visible evidence.

An opportunity may come from something that is present OR something that
is missing.

Examples:
- Product appears stackable but is not using vertical space effectively.
- There is no additional eye-level messaging.
- A tray, PDQ, riser, header, or other display element could improve visibility.
- Shelf space is being used inefficiently.
- Existing copy or messaging could communicate benefits more clearly.
- A digital or QR tie-in may be useful.
- Product arrangement could better separate the brand from nearby competitors.

Use the supplied criteria library as a toolbox of known opportunities.

Do not force criteria onto the photo.
Do not invent products, brands, fixture types, or details you cannot see.

For each opportunity you return:

1. Match it to a known criterion ID.
2. Explain the visible evidence that makes the opportunity relevant.
3. Give one concrete recommendation.
4. Score:
   - relevance from 0.0 to 1.0
   - confidence from 0.0 to 1.0
   - impact from 0.0 to 1.0

Prioritize opportunities that are:
- clearly supported by the image
- actionable
- likely to improve visibility, communication, placement, or merchandising impact

Be conservative when the image is unclear.
If evidence is weak or partially obscured, lower confidence instead of guessing.

Avoid returning multiple opportunities that are effectively the same recommendation.

Audit depth:
{mode_config.label}

Maximum opportunities to return:
{mode_config.max_opportunities}

Criteria:
{criteria_json}

Return ONLY valid JSON.
Do not include markdown or explanatory text outside the JSON.

Return this structure:

[
  {{
    "criterion_id": "known_criterion_id",
    "title": "Short opportunity title",
    "evidence": "Specific visible evidence from the photo",
    "recommendation": "Concrete recommended action",
    "relevance": 0.0,
    "confidence": 0.0,
    "impact": 0.0
  }}
]
""".strip()