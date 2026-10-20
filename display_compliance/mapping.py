"""Local position creation, editing, and validation for Display Compliance."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

from .models import ProductRegion


BBox = tuple[int, int, int, int]
MAX_MAPPING_REGIONS = 500


class MappingValidationError(ValueError):
    """Raised when a mapping operation would create invalid positions."""


def _require_integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise MappingValidationError(f"{name} must be an integer.")
    return value


def _validate_dimensions(image_width: int, image_height: int) -> None:
    _require_integer(image_width, "Image width")
    _require_integer(image_height, "Image height")
    if image_width <= 0 or image_height <= 0:
        raise MappingValidationError("Image dimensions must be positive.")


def validate_bbox(
    bbox: BBox,
    *,
    image_width: int,
    image_height: int,
) -> BBox:
    """Validate an (x, y, width, height) box in reference-image pixels."""
    _validate_dimensions(image_width, image_height)

    if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
        raise MappingValidationError(
            "A bounding box requires x, y, width, and height."
        )

    x, y, width, height = (
        _require_integer(value, name)
        for value, name in zip(bbox, ("X", "Y", "Width", "Height"))
    )

    if x < 0 or y < 0:
        raise MappingValidationError("Position coordinates cannot be negative.")
    if width <= 0 or height <= 0:
        raise MappingValidationError("Position width and height must be positive.")
    if x + width > image_width or y + height > image_height:
        raise MappingValidationError(
            "The position must fit inside the reference image."
        )

    return x, y, width, height


def bbox_polygon(bbox: BBox) -> tuple[tuple[int, int], ...]:
    """Return rectangle corners using image-edge coordinates."""
    x, y, width, height = bbox
    return (
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
    )


def validate_regions(
    regions: list[ProductRegion],
    *,
    image_width: int,
    image_height: int,
) -> None:
    """Validate IDs and geometry without imposing product-approval rules."""
    _validate_dimensions(image_width, image_height)

    if len(regions) > MAX_MAPPING_REGIONS:
        raise MappingValidationError(
            f"A side may contain at most {MAX_MAPPING_REGIONS} positions."
        )

    seen_ids: set[str] = set()

    for region in regions:
        if not isinstance(region.region_id, str) or not region.region_id.strip():
            raise MappingValidationError("Every position requires an ID.")
        if region.region_id in seen_ids:
            raise MappingValidationError(
                f"Duplicate position ID: {region.region_id}"
            )
        seen_ids.add(region.region_id)

        if type(region.required_occupied) is not bool:
            raise MappingValidationError(
                "Required occupancy must be true or false."
            )

        if region.bbox is None and not region.polygon:
            raise MappingValidationError(
                f"Position {region.region_id} has no geometry."
            )

        if region.bbox is not None:
            validate_bbox(
                region.bbox,
                image_width=image_width,
                image_height=image_height,
            )

        if region.polygon:
            if len(region.polygon) < 3:
                raise MappingValidationError(
                    f"Position {region.region_id} needs at least three corners."
                )

            points: list[tuple[int, int]] = []
            for point in region.polygon:
                if not isinstance(point, (tuple, list)) or len(point) != 2:
                    raise MappingValidationError("Invalid polygon corner.")

                x = _require_integer(point[0], "Polygon X")
                y = _require_integer(point[1], "Polygon Y")
                if not (0 <= x <= image_width and 0 <= y <= image_height):
                    raise MappingValidationError(
                        "Polygon corners must remain inside the image."
                    )
                points.append((x, y))

            twice_area = sum(
                points[index][0] * points[(index + 1) % len(points)][1]
                - points[(index + 1) % len(points)][0] * points[index][1]
                for index in range(len(points))
            )
            if twice_area == 0:
                raise MappingValidationError("Polygon area must be nonzero.")

            if region.bbox is not None:
                left, top, width, height = region.bbox
                if any(
                    not (
                        left <= x <= left + width
                        and top <= y <= top + height
                    )
                    for x, y in points
                ):
                    raise MappingValidationError(
                        "Polygon corners must fit within their bounding box."
                    )


def add_position(
    regions: list[ProductRegion],
    *,
    bbox: BBox,
    image_width: int,
    image_height: int,
    label: str = "",
    section_id: str | None = None,
) -> list[ProductRegion]:
    """Return a new mapping containing one additional position."""
    checked_bbox = validate_bbox(
        bbox,
        image_width=image_width,
        image_height=image_height,
    )
    updated = [
        *regions,
        ProductRegion(
            region_id=uuid4().hex,
            bbox=checked_bbox,
            polygon=bbox_polygon(checked_bbox),
            label=label.strip(),
            section_id=section_id,
        ),
    ]
    validate_regions(
        updated,
        image_width=image_width,
        image_height=image_height,
    )
    return updated


def update_position(
    regions: list[ProductRegion],
    *,
    region_id: str,
    bbox: BBox,
    image_width: int,
    image_height: int,
    label: str | None = None,
) -> list[ProductRegion]:
    """Edit a box while preserving its ID and expected-product link."""
    matches = [region for region in regions if region.region_id == region_id]
    if len(matches) != 1:
        raise MappingValidationError(
            "The edited position must occur exactly once."
        )

    checked_bbox = validate_bbox(
        bbox,
        image_width=image_width,
        image_height=image_height,
    )
    original = matches[0]
    geometry_changed = checked_bbox != original.bbox

    edited = replace(
        original,
        bbox=checked_bbox,
        polygon=(
            bbox_polygon(checked_bbox)
            if geometry_changed
            else original.polygon
        ),
        label=original.label if label is None else label.strip(),
        visual_signature=(
            None if geometry_changed else original.visual_signature
        ),
    )
    updated = [
        edited if region.region_id == region_id else region
        for region in regions
    ]
    validate_regions(
        updated,
        image_width=image_width,
        image_height=image_height,
    )
    return updated


def delete_position(
    regions: list[ProductRegion],
    *,
    region_id: str,
    protected_region_ids: set[str] | None = None,
) -> list[ProductRegion]:
    """Delete an unlinked position; callers supply product-reference IDs."""
    matches = [region for region in regions if region.region_id == region_id]
    if len(matches) != 1:
        raise MappingValidationError(
            "The deleted position must occur exactly once."
        )

    if (
        matches[0].expected_product_id is not None
        or region_id in (protected_region_ids or set())
    ):
        raise MappingValidationError(
            "Remove this position's product links before deleting it."
        )

    return [region for region in regions if region.region_id != region_id]


def create_grid_positions(
    *,
    bbox: BBox,
    rows: int,
    columns: int,
    image_width: int,
    image_height: int,
    section_id: str | None = None,
) -> list[ProductRegion]:
    """Create a new rectangular grid without modifying an existing mapping."""
    x, y, width, height = validate_bbox(
        bbox,
        image_width=image_width,
        image_height=image_height,
    )
    _require_integer(rows, "Rows")
    _require_integer(columns, "Columns")

    if rows <= 0 or columns <= 0:
        raise MappingValidationError("Rows and columns must be positive.")
    if rows * columns > MAX_MAPPING_REGIONS:
        raise MappingValidationError(
            f"A grid may contain at most {MAX_MAPPING_REGIONS} positions."
        )
    if columns > width or rows > height:
        raise MappingValidationError(
            "Grid cells must be at least one pixel wide and high."
        )

    regions: list[ProductRegion] = []

    for row in range(rows):
        top = y + (row * height) // rows
        bottom = y + ((row + 1) * height) // rows

        for column in range(columns):
            left = x + (column * width) // columns
            right = x + ((column + 1) * width) // columns
            cell_bbox = (left, top, right - left, bottom - top)

            regions.append(
                ProductRegion(
                    region_id=uuid4().hex,
                    bbox=cell_bbox,
                    polygon=bbox_polygon(cell_bbox),
                    label=f"R{row + 1}-C{column + 1}",
                    section_id=section_id,
                )
            )

    validate_regions(
        regions,
        image_width=image_width,
        image_height=image_height,
    )
    return regions