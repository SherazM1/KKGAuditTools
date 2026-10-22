"""Deterministic Expanded UI/state checks; no browser touch emulation or AI calls."""

import io
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from streamlit.testing.v1 import AppTest

from shelf_audit.image_utils import normalize_target_region
from shelf_audit.models import AuditDepth, AuditMode, AuditResult
from shelf_audit.target_selector import parse_selection


def photo(color="green"):
    buffer = io.BytesIO()
    Image.new("RGB", (800, 400), color).save(buffer, format="PNG")
    return buffer.getvalue()


def rectangle(**changes):
    value = dict(x=.1, y=.1, width=.5, height=.5)
    value.update(changes)
    return value


class CoordinateTests(unittest.TestCase):
    def test_round_trip_and_dimensions(self):
        for width, height in ((280,140),(140,280),(1000,500),(500,1000)):
            region = normalize_target_region(x=width*.1,y=height*.1,
                width=width*.5,height=height*.5,canvas_width=width,canvas_height=height)
            self.assertEqual(parse_selection(vars(region)), region)
            self.assertEqual(vars(region), rectangle())

    def test_invalid_selections(self):
        for value in (rectangle(width=.001), rectangle(width=0), rectangle(x=-.1),
                      rectangle(x=float('nan')), rectangle(height=True), {}, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_selection(value)

    def test_full_frame_crop(self):
        from shelf_audit.image_utils import build_audit_image, crop_target_region, get_image_dimensions
        region = parse_selection(dict(x=0,y=0,width=1,height=1))
        self.assertEqual((region.x,region.y,region.width,region.height),(0,0,1,1))
        image = build_audit_image(photo())
        self.assertEqual(get_image_dimensions(crop_target_region(image,region)), (800,400))


class ExpandedPageTests(unittest.TestCase):
    def setUp(self):
        self.original = photo()
        self.uploaded = Mock(name="photo_input")
        self.uploaded.name = "shelf.png"
        self.uploaded.type = "image/png"
        self.uploaded.getvalue.return_value = self.original
        # Model only the component's keyed state contract, not touch events.
        self.drawings = {}
        self.canvas = self.enterContext(patch("shelf_audit.page.select_target", side_effect=lambda image, **kw: self.drawings.get(kw["key"])))
        self.enterContext(patch("shelf_audit.page.st.camera_input", return_value=self.uploaded))
        self.enterContext(patch("shelf_audit.page.st.file_uploader", return_value=self.uploaded))
        self.audit = self.enterContext(patch(
            "shelf_audit.page.run_audit",
            return_value=AuditResult([], AuditMode.EXPANDED, AuditDepth.DEEP, 0),
        ))
        self.enterContext(patch("shelf_audit.page.OpenAIAuditProvider"))
        self.report = self.enterContext(patch("shelf_audit.page.render_report_section"))
        import streamlit as st
        self.image = self.enterContext(patch("shelf_audit.page.st.image", wraps=st.image))
        self.app = AppTest.from_string("from shelf_audit.page import render\nrender()")
        self.app.run()
        self.assert_ok()

    def assert_ok(self):
        self.assertEqual(len(self.app.exception), 0)

    def draw(self, boxes=None):
        self.drawings[self.canvas.call_args.kwargs["key"]] = (
            rectangle() if boxes is None else boxes
        )
        self.app.run()
        self.assert_ok()

    def complete(self):
        self.draw()
        self.app.button(key="shelf_audit_analyze").click().run()
        self.assert_ok()
        self.assertIn("shelf_audit_completed_result", self.app.session_state)

    def test_new_image_remounts_canvas_clears_preview_and_completed_result(self):
        self.complete()
        old_key = self.canvas.call_args.kwargs["key"]
        self.app.session_state["shelf_audit_report_document"] = "old document"
        cache = self.app.session_state["shelf_audit_cache"]
        self.image.reset_mock()
        self.uploaded.getvalue.return_value = photo("yellow")
        self.app.run()
        self.assert_ok()
        self.assertNotEqual(self.canvas.call_args.kwargs["key"], old_key)
        self.assertTrue(self.app.button(key="shelf_audit_analyze").disabled)
        self.assertEqual(self.image.call_count, 0)  # No old crop preview.
        for key in ("shelf_audit_completed_result", "shelf_audit_completed_photo", "shelf_audit_report_document"):
            self.assertNotIn(key, self.app.session_state)
        self.assertIs(self.app.session_state["shelf_audit_cache"], cache)
        self.assertEqual(self.audit.call_count, 1)
        # Returning to the original image cannot resurrect its old drawing.
        self.uploaded.getvalue.return_value = self.original
        self.app.run()
        self.assertNotEqual(self.canvas.call_args.kwargs["key"], old_key)
        self.assertTrue(self.app.button(key="shelf_audit_analyze").disabled)

    def test_same_image_reruns_preserve_target_and_responsive_crop(self):
        self.complete()
        key = self.canvas.call_args.kwargs["key"]
        self.image.reset_mock()
        self.app.run()
        self.assert_ok()
        self.assertEqual(self.canvas.call_args.kwargs["key"], key)
        self.assertFalse(self.app.button(key="shelf_audit_analyze").disabled)
        self.assertIn("shelf_audit_completed_result", self.app.session_state)
        self.assertEqual(self.image.call_args.kwargs["caption"], "Selected audit area")
        self.assertTrue(self.image.call_args.kwargs["use_container_width"])
        self.assertEqual(self.audit.call_count, 1)
        request = self.audit.call_args.kwargs
        self.assertEqual(request["mode"], AuditMode.EXPANDED)
        self.assertEqual(request["depth"], AuditDepth.DEEP)
        self.assertEqual(request["target_region"].x, 0.1)
        self.assertIsNotNone(request["target_crop"])
        self.assertNotEqual(request["image"].data, request["target_crop"].data)

    def test_mode_and_depth_controls_and_labels_are_absent(self):
        self.assertEqual([r.key for r in self.app.radio], ["shelf_audit_image_source"])
        self.complete()
        visible = " ".join(e.value for collection in (self.app.caption, self.app.subheader, self.app.markdown) for e in collection)
        for label in ("Expanded", "Deep", "Product", "Quick", "Audit mode", "Audit depth"):
            self.assertNotIn(label, visible)

    def test_missing_target_blocks_analyze_and_never_defaults_to_full_frame(self):
        self.assertTrue(self.app.button(key="shelf_audit_analyze").disabled)
        self.assertTrue(any(e.value == "Select the area you want to audit." for e in self.app.info))
        self.audit.assert_not_called()
        self.assertNotIn("shelf_audit_completed_result", self.app.session_state)

    def test_legacy_widget_state_cannot_override_fixed_routing(self):
        self.app.session_state["shelf_audit_mode"] = "Product"
        self.app.session_state["shelf_audit_depth"] = "Quick Audit"
        self.complete()
        self.assertEqual(self.audit.call_args.kwargs["mode"], AuditMode.EXPANDED)
        self.assertEqual(self.audit.call_args.kwargs["depth"], AuditDepth.DEEP)

    def test_clear_target_keeps_image_and_mode_and_allows_redraw(self):
        self.complete()
        old_key = self.canvas.call_args.kwargs["key"]
        context = self.app.session_state["shelf_audit_active_context"]
        self.image.reset_mock()
        self.drawings[old_key] = None
        self.app.run()
        self.assert_ok()
        self.assertEqual(self.canvas.call_args.kwargs["key"], old_key)
        self.assertEqual(self.app.session_state["shelf_audit_active_context"], context)
        self.assertEqual(self.uploaded.getvalue(), self.original)
        self.assertTrue(self.app.button(key="shelf_audit_analyze").disabled)
        self.assertEqual(self.image.call_count, 0)
        self.assertNotIn("shelf_audit_completed_result", self.app.session_state)
        self.assertEqual(self.audit.call_count, 1)
        self.draw()
        self.assertFalse(self.app.button(key="shelf_audit_analyze").disabled)

    def test_invalid_or_missing_targets_block_analyze(self):
        for boxes in (
            [], [rectangle(), rectangle()], rectangle(width=0),
            rectangle(x=-5), rectangle(width=500), rectangle(width=.001),
        ):
            with self.subTest(boxes=boxes):
                self.draw(boxes)
                self.assertTrue(self.app.button(key="shelf_audit_analyze").disabled)
        self.audit.assert_not_called()

    def test_changed_target_invalidates_completed_result_and_report(self):
        self.complete()
        self.app.session_state["shelf_audit_report_document"] = "stale"
        self.draw(rectangle(x=.2))
        for key in ("shelf_audit_completed_result", "shelf_audit_completed_photo", "shelf_audit_report_document"):
            self.assertNotIn(key, self.app.session_state)
        self.assertEqual(self.audit.call_count, 1)
        self.assertFalse(self.app.button(key="shelf_audit_analyze").disabled)

    def test_full_frame_and_deep_preserved(self):
        self.draw(dict(x=0,y=0,width=1,height=1))
        self.app.button(key="shelf_audit_analyze").click().run()
        request = self.audit.call_args.kwargs
        self.assertEqual(request["depth"], AuditDepth.DEEP)
        self.assertEqual(request["mode"], AuditMode.EXPANDED)
        self.assertEqual(vars(request["target_region"]), dict(x=0,y=0,width=1,height=1))
        self.assertIsNotNone(request["target_crop"])

    def test_real_orchestration_cache_target_identity_telemetry_and_provider_payload(self):
        from shelf_audit.audit import run_audit
        from shelf_audit.providers.base import ProviderAnalysisResult, ProviderUsage
        from shelf_audit.providers.openai import OpenAIAuditProvider, OpenAIProviderConfig
        provider = Mock(name="audit_provider")
        provider.name, provider.model_name, provider.config_version = "mock", "test-model", "3"
        provider.analyze.return_value = ProviderAnalysisResult([], ProviderUsage())
        self.audit.side_effect = run_audit
        with patch("shelf_audit.page.OpenAIAuditProvider", return_value=provider):
            self.complete()
            self.app.button(key="shelf_audit_analyze").click().run()
            self.assert_ok()
            self.assertEqual(provider.analyze.call_count, 1)
            records = self.app.session_state["shelf_audit_usage_tracker"].all()
            self.assertEqual([(r.mode,r.depth,r.cache_hit) for r in records],
                             [("expanded","deep",False),("expanded","deep",True)])
            limiter = self.app.session_state["shelf_audit_rate_limiter"]
            self.assertEqual(limiter.remaining("shelf_audit"), 4)
            request = provider.analyze.call_args.args[0]
            adapter = OpenAIAuditProvider(config=OpenAIProviderConfig(model_name="test-model"))
            images = adapter._build_image_inputs(request)
            self.assertEqual([i["role"] for i in images], ["full_scene","target_crop"])
            self.assertEqual(vars(request.target_region), rectangle())
            self.app.run()  # Report rerun must not execute the audit again.
            self.assertEqual(provider.analyze.call_count, 1)
            self.draw(rectangle(x=.2))
            self.app.button(key="shelf_audit_analyze").click().run()
            self.assert_ok()
            self.assertEqual(provider.analyze.call_count, 2)
            self.assertEqual(limiter.remaining("shelf_audit"), 3)

    def test_upload_source_uses_same_image_identity(self):
        self.draw()
        old_key = self.canvas.call_args.kwargs["key"]
        self.app.radio(key="shelf_audit_image_source").set_value("Upload Existing Photo").run()
        self.assert_ok()
        self.assertEqual(self.canvas.call_args.kwargs["key"], old_key)
        self.assertFalse(self.app.button(key="shelf_audit_analyze").disabled)

    def test_removing_image_clears_previous_result_and_drawing(self):
        self.complete()
        with patch("shelf_audit.page.st.camera_input", return_value=None):
            self.app.run()
        self.assert_ok()
        self.assertNotIn("shelf_audit_completed_result", self.app.session_state)
        self.assertNotIn("shelf_audit_target_canvas_key", self.app.session_state)


if __name__ == "__main__":
    unittest.main()
