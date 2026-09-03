"""
Core vision logic for the shelf audit tool.
 
IMPORTANT: This file must never import streamlit. It should be callable from
a Streamlit button, a FastAPI route, a CLI script, or a test file identically.
That's what makes it portable when the frontend eventually changes.
"""
import base64
import json
from dataclasses import dataclass
 
 
@dataclass
class CriterionResult:
    id: str
    applies: bool
    met: bool | None
    evidence: str
    suggestion: str | None
 
 
def build_prompt(criteria: list[dict]) -> str:
    """Builds the instruction text sent alongside the photo."""
    criteria_json = json.dumps(criteria, indent=2)
    return f"""You are auditing a retail shelf photo taken at approximately eye level (~60 inches).
 
For EACH criterion below, determine:
1. "applies" - does this criterion apply to what's visible in this photo? (true/false)
2. "met" - if it applies, is the criterion satisfied? (true/false). If it doesn't apply, set this to null.
3. "evidence" - a short, specific description of what you see that supports your answer.
4. "suggestion" - if applies=true and met=false, write a concrete, actionable suggestion based on the
   criterion's suggestion template, adapted to what's actually in the photo. Otherwise set this to null.
 
Be conservative: only mark "applies": true when the criterion is genuinely relevant to what's in frame.
Do not guess at brand names or products you cannot clearly identify.
 
Criteria:
{criteria_json}
 
Return ONLY a valid JSON array, no other text, no markdown code fences. Format:
[
  {{"id": "criterion_id", "applies": true, "met": false, "evidence": "...", "suggestion": "..."}}
]"""
 
 
def _encode_image(image_bytes: bytes) -> str:
    return base64.standard_b64encode(image_bytes).decode("utf-8")
 
 
def evaluate_photo(image_bytes: bytes, criteria: list[dict], media_type: str = "image/jpeg") -> list[CriterionResult]:
    """
    Sends a shelf photo + criteria list to the vision model and returns
    structured, parsed results - one per criterion.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": _encode_image(image_bytes),
                        },
                    },
                    {"type": "text", "text": build_prompt(criteria)},
                ],
            }
        ],
    )
 
    raw_text = response.content[0].text.strip()
 
    # Defensive cleanup in case the model wraps output in code fences anyway
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()
 
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON. Raw response:\n{raw_text}") from e
 
    return [CriterionResult(**item) for item in parsed]