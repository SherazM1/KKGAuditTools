"""
Prompt construction for the shelf audit tool.

This module is provider-neutral.
It does not call any AI API directly.
"""

from __future__ import annotations

import json

from .audit_modes import get_mode_config, get_depth_config
from .models import AuditMode, AuditDepth, TargetRegion


PROMPT_VERSION = "v2"


def _compact_criteria(criteria: list[dict]) -> str:
    """
    Convert criteria into a compact model-facing JSON representation.
    """

    compact = []

    for criterion in criteria:
        item = {
            "id": criterion["id"],
            "category": criterion["category"],
            "applies_when": criterion["applies_when"],
            "check": criterion["check"],
            "suggestion": criterion["suggestion"],
        }

        optional_fields = (
            "priority",
            "opportunity_type",
            "visual_signals",
            "fixture_types",
            "comparison_allowed",
            "brand_context_required",
        )

        for field in optional_fields:
            if field in criterion:
                item[field] = criterion[field]

        compact.append(item)

    return json.dumps(
        compact,
        separators=(",", ":"),
    )



def _build_mode_instructions(
    mode: AuditMode,
    target_region: TargetRegion | None,
) -> str:
    """
    Build mode-specific reasoning instructions.
    """

    if mode is AuditMode.PRODUCT:
        return """
AUDIT MODE: PRODUCT

Treat the photographed product or product area as the audit target.

Focus recommendations on:
- the target product
- its immediate shelf placement
- visible merchandising conditions around it

Use surrounding shelf context only when it directly helps explain an
opportunity for the target.

Do not invent or search for a separate target product.
""".strip()

    if mode is AuditMode.EXPANDED:
        target_region_text = "No target region supplied."

        if target_region is not None:
            target_region_text = (
                f"x={target_region.x:.4f}, "
                f"y={target_region.y:.4f}, "
                f"width={target_region.width:.4f}, "
                f"height={target_region.height:.4f}"
            )

        return f"""
AUDIT MODE: EXPANDED

The user has selected exactly ONE target product within a wider shelf scene.

The selected target is the ONLY product being audited.

Selected target region:
{target_region_text}

Use the wider scene to understand:
- neighboring products
- nearby displays and fixtures
- competitor executions
- available shelf space
- surrounding merchandising patterns

Surrounding products are CONTEXT, not additional audit targets.

Recommendations must always relate back to the selected target.

A nearby competitor execution may inspire an opportunity, but do not claim
that a competitor is objectively better or invent information about either brand.

Do not silently switch focus to a neighboring product, even if it is more
visually prominent.

If the selected target cannot be identified confidently, preserve that
uncertainty rather than guessing.
""".strip()

    raise ValueError(
        f"Unsupported audit mode: {mode}"
    )


def _get_candidate_limit(
    depth: AuditDepth,
) -> int:
    """
    Determine how many candidate opportunities the model may return.

    Python performs the final filtering, deduplication, scoring,
    and result limiting.
    """

    if depth is AuditDepth.QUICK:
        return 8

    if depth is AuditDepth.DEEP:
        return 15

    raise ValueError(
        f"Unsupported audit depth: {depth}"
    )


def build_audit_prompt(
    criteria: list[dict],
    mode: AuditMode,
    depth: AuditDepth,
    target_region: TargetRegion | None = None,
) -> str:
    """
    Build the opportunity-first audit prompt.
    """

    mode_config = get_mode_config(mode)
    depth_config = get_depth_config(depth)

    criteria_json = _compact_criteria(criteria)

    mode_instructions = _build_mode_instructions(
        mode,
        target_region,
    )

    candidate_limit = _get_candidate_limit(
        depth
    )

    return f"""
You are analyzing a retail shelf or merchandising photo.

Your job is NOT to mechanically score every criterion.

Your job is to understand the specific scene and identify the strongest
merchandising opportunities that are supported by visible evidence.

An opportunity may come from something that is present OR something that
is missing.

Examples:
- Product appears stackable but is not using vertical space effectively.
- Additional eye-level messaging could improve communication.
- A tray, PDQ, riser, header, or other display element could improve visibility.
- Shelf space is being used inefficiently.
- Existing copy or messaging could communicate benefits more clearly.
- A digital or QR tie-in may be useful when supported by the visible context.
- Product arrangement could create stronger distinction within the shelf environment.

Use the supplied criteria library as a toolbox of known opportunities.

{mode_instructions}

REASONING RULES:

- Ground every judgment in visible evidence.
- Do not force a criterion onto the scene merely because it exists in the criteria library.
- Do not invent products, brands, fixtures, claims, dimensions, or features.
- Distinguish ABSENCE from INVISIBILITY.
- Something not visible in the image is not automatically proven to be absent.
- Absence may create an opportunity only when the image provides enough evidence
  that the relevant area or condition can actually be observed.
- Use physical shelf context such as shelves, shelf edges, facings, trays, PDQs,
  risers, headers, pegboards, empty space, stacking, and fixture structure.
- If something is blurry, tiny, obstructed, cropped out, or ambiguous, reduce
  confidence rather than guessing.
- Do not over-penalize missing features.
- A missing feature is only an opportunity when it is relevant to the visible
  merchandising situation.
- Prefer recommendations that are specific and realistically actionable.
- Avoid duplicate or substantially overlapping recommendations.
- Do not invent brand knowledge that is not visible in the image or supplied
  in the criteria.
- Do not treat surrounding products as evidence about the target unless the
  visible relationship is relevant to the recommendation.

For each opportunity you return:

1. Match it to a known criterion ID.
2. Explain the specific visible evidence that makes the opportunity relevant.
3. Give one concrete recommendation.
4. Score:
   - relevance from 0.0 to 1.0
   - confidence from 0.0 to 1.0
   - impact from 0.0 to 1.0
   - actionability from 0.0 to 1.0

Prioritize candidate opportunities that are:
- clearly supported by the image
- actionable
- likely to improve visibility, communication, placement, or merchandising impact
- meaningfully different from one another

Be conservative when the image is unclear.

If evidence is weak or partially obscured, lower confidence instead of guessing.

Audit mode:
{mode_config.label}

Audit depth:
{depth_config.label}

Candidate opportunity limit:
{candidate_limit}

Final application result limit:
{depth_config.max_opportunities}

You may return more candidates than the final application result limit.

The application will perform final:
- confidence filtering
- duplicate reduction
- priority scoring
- result selection

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
    "impact": 0.0,
    "actionability": 0.0
  }}
]
""".strip()