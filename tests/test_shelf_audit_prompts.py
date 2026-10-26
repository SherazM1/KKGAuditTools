"""Deterministic instruction contracts; these do not predict live-model output."""

import unittest

from shelf_audit.audit_modes import get_depth_config
from shelf_audit.models import AuditDepth, AuditMode, TargetRegion
from shelf_audit.prompts import build_audit_prompt


class ShelfAuditPromptTests(unittest.TestCase):
    def prompt(self, region=None):
        return " ".join(build_audit_prompt(
            criteria=[], mode=AuditMode.EXPANDED, depth=AuditDepth.DEEP,
            target_region=region or TargetRegion(x=.2, y=.3, width=.4, height=.5),
        ).split())

    def test_context_supports_only_selected_target_and_is_optional(self):
        prompt = self.prompt()
        for instruction in (
            "relevant evidence supporting a recommendation for the selected target",
            "Never independently audit the surroundings",
            "Context is optional, not mandatory",
            "Do not invent a comparison merely because another product is visible",
            "nearby tuna in a tray", "nearby holder or rack",
            "independently determine whether the selected target actually supports that solution",
            "The selected target is the ONLY product or product area being audited",
            "Do not silently switch focus to a neighboring product",
            "x=0.2000, y=0.3000, width=0.4000, height=0.5000",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)

    def test_full_image_is_subject_without_forced_comparison(self):
        prompt = self.prompt(TargetRegion(x=0, y=0, width=1, height=1))
        self.assertIn("x=0.0000, y=0.0000, width=1.0000, height=1.0000", prompt)
        self.assertIn("the whole image is the audit subject", prompt)
        self.assertIn("do not force an outside comparison", prompt)

    def test_photo_artifacts_limit_claims_instead_of_creating_findings(self):
        prompt = self.prompt()
        for instruction in (
            "Do NOT treat photographic artifacts as physical merchandising conditions",
            "Blur, motion blur, compression, low resolution, glare, reflection",
            "camera focus", "distance from the shelf", "photographic shadows",
            "perspective distortion",
            "must not, by themselves, create a recommendation",
            "reduce confidence, limit text-reading claims",
            "cause unsupported observations to be omitted",
            "do not judge physical label legibility",
            "independently of camera quality",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)

    def test_physical_reasoning_precedes_graphics_without_banning_graphics(self):
        prompt = self.prompt()
        self.assertLess(prompt.index("2. Consider whether a physical"),
                        prompt.index("3. Consider communication or graphics"))
        for instruction in (
            "Choose the smallest meaningful KKG-produced solution supported by evidence",
            "Preserve a graphics solution separately only when it addresses a materially different need",
            "do not force a physical solution when none is justified",
            "Shelf strips, shelf talkers, navigation graphics, variant callouts, and messaging panels remain allowed",
            "not become a default fallback or fill an unused finding slot",
            "alternatives within one recommendation, not separate findings",
            "Do NOT automatically combine fixture enhancement and fixture replacement",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)

    def test_existing_maintenance_and_count_contracts_remain(self):
        prompt = self.prompt()
        for instruction in (
            "Store maintenance is NEVER a final client-facing recommendation",
            "straighten or face products", "pull products forward",
            "tidy, regroup, or reorganize merchandise",
            "correct a one-off hook, box, bottle, or package position",
            "Prefer the smallest meaningful KKG-produced solution",
            "There is no minimum result count",
            "Candidate opportunity limit: 14", "Final application result limit: 8",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)
        config = get_depth_config(AuditDepth.DEEP)
        self.assertEqual((config.max_candidates, config.min_confidence,
                          config.max_opportunities), (14, .50, 8))
