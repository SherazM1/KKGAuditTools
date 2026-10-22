"""Narrow normalized-region bridge for the prepared Shelf Audit image."""
import base64
from pathlib import Path

import streamlit.components.v1 as components

from .guardrails import validate_target_region
from .image_utils import get_image_dimensions
from .models import TargetRegion

MIN_TARGET_FRACTION = 0.01
_component = components.declare_component(
    "shelf_target_selector", path=str(Path(__file__).with_name("target_selector_frontend"))
)


def parse_selection(value):
    """Validate browser output without persisting display pixels."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise ValueError("Select one valid target rectangle.")
    region = validate_target_region(TargetRegion(**value))
    if min(region.width, region.height) < MIN_TARGET_FRACTION:
        raise ValueError("Target is too small. Drag a larger rectangle.")
    return region


def select_target(image, *, key, existing=None):
    width, height = get_image_dimensions(image)
    data_url = "data:" + image.media_type + ";base64," + base64.b64encode(image.data).decode("ascii")
    return _component(image=data_url, source_width=width, source_height=height,
                      identity=key, existing=existing, min_fraction=MIN_TARGET_FRACTION,
                      key=key, default=None)
