"""
Regression tests for Shelf Audit image preparation and target handling.

These tests do not call any AI provider or network service.
"""

from __future__ import annotations

import io
import math
import unittest
from unittest.mock import patch

from PIL import Image

from shelf_audit.image_utils import (
    build_audit_image,
    crop_target_region,
    get_image_dimensions,
    normalize_target_region,
    preprocess_audit_image,
)
from shelf_audit.models import TargetRegion


def _make_png_bytes(
    *,
    width: int = 100,
    height: int = 100,
) -> bytes:
    buffer = io.BytesIO()

    image = Image.new(
        "RGB",
        (width, height),
        "white",
    )

    image.save(
        buffer,
        format="PNG",
    )

    return buffer.getvalue()


def _make_exif_rotated_jpeg() -> bytes:
    """
    Create a 100x60 JPEG whose EXIF orientation requests
    a 90-degree rotation.

    After orientation normalization the image should report
    dimensions of 60x100.
    """

    buffer = io.BytesIO()

    image = Image.new(
        "RGB",
        (100, 60),
        "white",
    )

    exif = Image.Exif()

    # EXIF orientation 6 = rotate 90 degrees clockwise.
    exif[274] = 6

    image.save(
        buffer,
        format="JPEG",
        exif=exif,
    )

    return buffer.getvalue()


class ShelfAuditImageUtilsTests(
    unittest.TestCase
):
    def test_valid_png_builds_successfully(
        self,
    ) -> None:
        image = build_audit_image(
            _make_png_bytes(),
            filename="test.png",
            media_type="image/png",
            source="test",
        )

        self.assertEqual(
            image.media_type,
            "image/png",
        )

        self.assertTrue(
            image.data
        )

    def test_corrupted_image_bytes_are_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            build_audit_image(
                b"this is not an image",
                filename="broken.png",
                media_type="image/png",
                source="test",
            )

    def test_forged_mime_type_is_rejected(
        self,
    ) -> None:
        png_bytes = _make_png_bytes()

        with self.assertRaises(
            ValueError
        ):
            build_audit_image(
                png_bytes,
                filename="test.png",
                media_type="image/jpeg",
                source="test",
            )

    def test_filename_extension_mismatch_is_rejected(
        self,
    ) -> None:
        png_bytes = _make_png_bytes()

        with self.assertRaises(
            ValueError
        ):
            build_audit_image(
                png_bytes,
                filename="test.jpg",
                media_type="image/png",
                source="test",
            )

    def test_raw_byte_limit_is_enforced(
        self,
    ) -> None:
        png_bytes = _make_png_bytes()

        with patch(
            "shelf_audit.image_utils.MAX_RAW_IMAGE_BYTES",
            10,
        ):
            with self.assertRaises(
                ValueError
            ):
                build_audit_image(
                    png_bytes,
                    filename="test.png",
                    media_type="image/png",
                    source="test",
                )

    def test_pixel_limit_is_enforced(
        self,
    ) -> None:
        png_bytes = _make_png_bytes(
            width=100,
            height=100,
        )

        with patch(
            "shelf_audit.image_utils.MAX_IMAGE_PIXELS",
            5000,
        ):
            with self.assertRaises(
                ValueError
            ):
                build_audit_image(
                    png_bytes,
                    filename="test.png",
                    media_type="image/png",
                    source="test",
                )

    def test_exif_orientation_is_respected(
        self,
    ) -> None:
        image = build_audit_image(
            _make_exif_rotated_jpeg(),
            filename="rotated.jpg",
            media_type="image/jpeg",
            source="test",
        )

        width, height = get_image_dimensions(
            image
        )

        self.assertEqual(
            (width, height),
            (60, 100),
        )

    def test_preprocessed_image_remains_orientation_aware(
        self,
    ) -> None:
        image = build_audit_image(
            _make_exif_rotated_jpeg(),
            filename="rotated.jpg",
            media_type="image/jpeg",
            source="test",
        )

        prepared = preprocess_audit_image(
            image
        )

        width, height = get_image_dimensions(
            prepared
        )

        self.assertEqual(
            (width, height),
            (60, 100),
        )

    def test_valid_target_region_is_normalized(
        self,
    ) -> None:
        region = normalize_target_region(
            x=100,
            y=50,
            width=200,
            height=100,
            canvas_width=1000,
            canvas_height=500,
        )

        self.assertAlmostEqual(
            region.x,
            0.1,
        )

        self.assertAlmostEqual(
            region.y,
            0.1,
        )

        self.assertAlmostEqual(
            region.width,
            0.2,
        )

        self.assertAlmostEqual(
            region.height,
            0.2,
        )

    def test_nan_target_coordinate_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            normalize_target_region(
                x=math.nan,
                y=0,
                width=100,
                height=100,
                canvas_width=500,
                canvas_height=500,
            )

    def test_boolean_target_coordinate_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            normalize_target_region(
                x=True,
                y=0,
                width=100,
                height=100,
                canvas_width=500,
                canvas_height=500,
            )

    def test_out_of_bounds_target_region_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            normalize_target_region(
                x=450,
                y=100,
                width=100,
                height=100,
                canvas_width=500,
                canvas_height=500,
            )

    def test_crop_rejects_out_of_bounds_region(
        self,
    ) -> None:
        image = build_audit_image(
            _make_png_bytes(),
            filename="test.png",
            media_type="image/png",
            source="test",
        )

        invalid_region = TargetRegion(
            x=0.9,
            y=0.1,
            width=0.2,
            height=0.2,
        )

        with self.assertRaises(
            ValueError
        ):
            crop_target_region(
                image,
                invalid_region,
            )

    def test_valid_crop_is_created(
        self,
    ) -> None:
        image = build_audit_image(
            _make_png_bytes(
                width=200,
                height=100,
            ),
            filename="test.png",
            media_type="image/png",
            source="test",
        )

        region = TargetRegion(
            x=0.25,
            y=0.25,
            width=0.5,
            height=0.5,
        )

        crop = crop_target_region(
            image,
            region,
        )

        crop_width, crop_height = (
            get_image_dimensions(
                crop
            )
        )

        self.assertEqual(
            (crop_width, crop_height),
            (100, 50),
        )

    def test_tiny_valid_crop_is_not_empty(
        self,
    ) -> None:
        image = build_audit_image(
            _make_png_bytes(
                width=100,
                height=100,
            ),
            filename="test.png",
            media_type="image/png",
            source="test",
        )

        region = TargetRegion(
            x=0.10,
            y=0.10,
            width=0.001,
            height=0.001,
        )

        crop = crop_target_region(
            image,
            region,
        )

        width, height = get_image_dimensions(
            crop
        )

        self.assertGreaterEqual(
            width,
            1,
        )

        self.assertGreaterEqual(
            height,
            1,
        )


if __name__ == "__main__":
    unittest.main()