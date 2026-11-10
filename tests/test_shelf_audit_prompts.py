"""Deterministic instruction contracts; these do not predict live-model output."""

import unittest

from shelf_audit.audit_modes import get_depth_config
from shelf_audit.models import AuditDepth, AuditMode, TargetRegion
from shelf_audit.prompts import build_audit_prompt, PROMPT_VERSION


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

    def section(self, start, end):
        return self.prompt().split(start, 1)[1].split(end, 1)[0]

    def test_v20_three_part_gate_preserves_candidate_before_communication(self):
        self.assertEqual(PROMPT_VERSION, "v20")
        prompt = self.prompt()
        self.assertLess(prompt.index("STANDARD SHELF PHYSICAL SCAN:"),
                        prompt.index("ASSORTMENT AND SHOPPER NAVIGATION:"))
        scan = self.section("STANDARD SHELF PHYSICAL SCAN:",
                            "ENVIRONMENT-BASED REFERENCE LANGUAGE:")
        self.assertLess(scan.index("Inspect only what is visibly supported"),
                        scan.index("PHYSICAL CANDIDATE DECISION:"))
        for instruction in (
            "a physical candidate exists only when all three are true",
            "VISIBLE CONDITION: A specific physical condition is visibly supported",
            "PLAUSIBLE KKG RESPONSE: At least one KKG-produced physical solution fits that specific condition and the visible placement",
            "MEANINGFUL BENEFIT: The solution would materially improve presentation, visibility, containment, capacity, shopper access, organization, or brand presence",
            "When all three are true, generate and preserve the physical opportunity as a candidate before evaluating graphics, navigation, or education",
            "Do not recognize it internally and then omit it because a simpler communication idea is also valid",
            "may both be returned when they solve meaningfully different visible needs",
            "If any of the three conditions are not sufficiently supported, do not force a physical candidate",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, scan)
        self.assertLess(scan.index("1. VISIBLE CONDITION"), scan.index("2. PLAUSIBLE KKG RESPONSE"))
        self.assertLess(scan.index("2. PLAUSIBLE KKG RESPONSE"), scan.index("3. MEANINGFUL BENEFIT"))

    def test_placement_priority_section_and_families(self):
        prompt = self.prompt()
        self.assertLess(
            prompt.index("RETAIL PLACEMENT AND SCENE CONTEXT:"),
            prompt.index("PLACEMENT-LED OPPORTUNITY PRIORITY:"),
        )
        self.assertLess(
            prompt.index("PLACEMENT-LED OPPORTUNITY PRIORITY:"),
            prompt.index("PHYSICAL SOLUTION SELECTION:"),
        )
        priority = self.section(
            "PLACEMENT-LED OPPORTUNITY PRIORITY:",
            "PHYSICAL SOLUTION SELECTION:",
        )
        for instruction in (
            "ORDINARY INLINE SHELF: prioritize physical shelf use, containment, organization, visibility, tiering, trays, compact PDQs, risers, dividers, channels, and compact racks",
            "Then consider navigation, education, and graphics when they address a separate visible need",
            "PEGBOARD OR HANGING FIXTURE: prioritize hanging-system organization, rack or fixture improvement, headers, navigation, hook-related fixture graphics, branded hanging solutions, and appropriately scaled racks",
            "EXISTING GENERIC RACK: prioritize improving, branding, structurally modifying, or replacing the rack before defaulting to small shelf-level graphics",
            "A rack replacement must still be visibly justified",
            "SIDE-OF-FIXTURE: prioritize sidekicks, side-oriented racks, side-panel communication",
            "AISLE END OR END-OF-RUN: elevate endcap or sidecap opportunities",
            "FLOOR PLACEMENT: elevate dedicated floorstands or freestanding displays",
            "PALLET-SCALE: prioritize pallet graphics, pallet-display improvement",
            "quarter-, half-, or full-pallet solutions",
            "EXISTING BRANDED DISPLAY: first evaluate whether the display should be enhanced, modified, refreshed, rebranded, or replaced before suggesting unrelated smaller additions",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, priority)
        self.assertLess(
            priority.index("ORDINARY INLINE SHELF:"),
            priority.index("Then consider navigation, education, and graphics"),
        )

    def test_placement_priority_is_conditional_and_evidence_led(self):
        priority = self.section(
            "PLACEMENT-LED OPPORTUNITY PRIORITY:",
            "PHYSICAL SOLUTION SELECTION:",
        )
        for instruction in (
            "placement alone does not create an opportunity",
            "never lowers the evidence standard",
            "Do not prefer a larger solution merely because the placement allows it",
            "Evidence strength, physical fit, shopper value, and merchandising relevance still control the recommendation",
            "Do not suppress a strong smaller solution when it better solves the visible need",
            "Do not force an opportunity family merely because it is listed as a priority for that placement",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, priority)

    def test_selection_ladder_uses_placement_before_candidate_comparison(self):
        ladder = self.section("OPPORTUNITY SELECTION LADDER:", "VOICE AND PERSPECTIVE:")
        self.assertLess(
            ladder.index("identify the visible placement type"),
            ladder.index("Use the identified placement to raise the opportunity families"),
        )
        self.assertLess(
            ladder.index("Use the identified placement to raise the opportunity families"),
            ladder.index("If the selected target is on an ordinary retail shelf"),
        )
        self.assertIn(
            "Placement priority guides candidate consideration, but visible evidence still determines whether each opportunity is valid",
            ladder,
        )
        self.assertIn(
            "If the physical candidate decision passes, preserve that physical candidate before evaluating graphics, navigation, or education opportunities",
            ladder,
        )

    def test_candidate_priority_includes_placement_fit_without_overriding_evidence(self):
        prioritization = self.section(
            "Prioritize candidate opportunities that are:",
            "Be conservative when the image is unclear.",
        )
        for instruction in (
            "match the natural scale and merchandising role of the visible placement",
            "When two opportunities are similarly grounded, prefer the one that:",
            "better matches the natural scale and merchandising role of the visible placement",
            "provides greater commercial and merchandising leverage",
            "Placement fit and commercial leverage must NEVER override evidence",
            "Do not automatically prefer a larger or more expensive solution",
            "A smaller tray, rack, signage element, product riser, graphic treatment, or other compact solution should outrank a larger display when it is better supported by the scene",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prioritization)

    def test_placement_scale_is_in_final_language_check(self):
        final = self.section("FINAL LANGUAGE CHECK:", "Do not output this internal check.")
        self.assertIn(
            "Does this recommendation match the natural scale and merchandising role of the visible placement, or did I choose a solution that is too small, too large, or unrelated to the placement?",
            final,
        )

    def test_placement_priority_does_not_add_scoring_or_output_fields(self):
        prompt = self.prompt()
        self.assertNotIn("placement score", prompt.lower())
        self.assertNotIn("placement_score", prompt)
        config = get_depth_config(AuditDepth.DEEP)
        self.assertEqual(
            (config.max_candidates, config.min_confidence, config.max_opportunities),
            (14, .50, 8),
        )

    def test_selection_ladder_preserves_passed_physical_candidate(self):
        ladder = self.section("OPPORTUNITY SELECTION LADDER:", "VOICE AND PERSPECTIVE:")
        for instruction in (
            "If the physical candidate decision passes, preserve that physical candidate before evaluating graphics, navigation, or education opportunities",
            "Do not drop a supported physical candidate merely because another opportunity is easier to explain",
            "Do not require a physical candidate when the decision gate does not pass",
            "shelf height, package form, stackability, visible width and depth, containment, capacity, access",
            "tray, PDQ, riser, divider, channel, stacker, or compact-rack opportunities",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, ladder)

    def test_coverage_does_not_silently_replace_physical_candidate(self):
        coverage = self.section("OPPORTUNITY COVERAGE:", "RECOMMENDATION VARIETY:")
        for instruction in (
            "A strong, distinct physical shelf opportunity should not be omitted merely because a simpler graphics, navigation, or education opportunity is also valid",
            "Physical and communication findings may coexist when they solve different visible needs",
            "Do not force a physical finding when the physical decision gate does not pass",
            "Do not create extra findings merely to increase the count",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, coverage)

    def test_final_check_verifies_preservation_and_context(self):
        final = self.section("FINAL LANGUAGE CHECK:", "Do not output this internal check.")
        self.assertIn("If the standard-shelf physical candidate decision passed, did I preserve that physical opportunity as a candidate rather than silently replacing it with a graphics, navigation, or education idea?", final)
        self.assertIn("If surrounding merchandising materially supported the recommendation, did I briefly reference that visible context without turning the surroundings into a separate audit target?", final)

    def test_physical_requirements_are_specific_to_each_solution(self):
        scan = self.section("STANDARD SHELF PHYSICAL SCAN:", "ENVIRONMENT-BASED REFERENCE LANGUAGE:")
        for instruction in (
            "Apply physical requirements only to the formats that actually depend on them",
            "Stacking / tiering: require visible package stability, usable vertical clearance, reasonable shopper access, and product visibility",
            "Tray / divider / channel: require a compatible shelf footprint, product form, and a visible containment or organization need",
            "Product riser: require a visible reason elevation or tiering would improve visibility or presentation, plus appropriate clearance",
            "Compact rack: require visible footprint/support, product compatibility, and shopper access",
            "Do NOT require proof of unused vertical clearance for every physical format",
            "Do NOT allow one unsupported physical format to invalidate a different supported physical format",
            "Do not recommend stacking merely because products could theoretically be stacked",
            "Do not assume unseen shelf depth, exact dimensions, future inventory, retailer authorization, or ownership of nearby open space",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, scan)
        tray_rule = scan.split("- Tray / divider / channel:", 1)[1].split("- Product riser:", 1)[0]
        self.assertNotIn("clearance", tray_rule)
        self.assertNotIn("clearance or shopper access is not visibly supported", scan)
        self.assertNotIn("Do not generate a physical candidate when:", scan)

    def test_environment_reference_is_material_optional_and_target_bound(self):
        environment = self.section("ENVIRONMENT-BASED REFERENCE LANGUAGE:", "PHYSICAL MERCHANDISING UPGRADE:")
        for instruction in (
            "When nearby merchandising materially helped establish the opportunity, preserve that reference in the Why field",
            "so the client can understand what visible environmental evidence helped drive the recommendation",
            "Do NOT make environment language mandatory",
            "Do NOT mention surroundings when: - the target itself provides enough evidence - no useful comparison exists - nearby merchandising is unrelated",
            "the environment did not materially influence the recommendation",
            "The environment is supporting evidence, not a second audit target",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, environment)

    def test_existing_physical_scan_and_large_format_scopes_remain(self):
        prompt = self.prompt()
        scan = self.section("STANDARD SHELF PHYSICAL SCAN:", "ENVIRONMENT-BASED REFERENCE LANGUAGE:")
        for instruction in (
            "available shelf height", "visible package shape, stability, and clearance",
            "visible shelf width and footprint", "front-to-back shelf space",
            "containment", "rear product is obscured", "mixed product heights",
            "underused shelf space", "capacity, product visibility, shopper access, organization, or brand presence",
            "nearby merchandising provides a relevant physical reference",
        ):
            with self.subTest(scan_instruction=instruction):
                self.assertIn(instruction, scan)
        for instruction in (
            "pegboard or hanging-fixture context may support navigation graphics, headers, branded hanging systems, racks, or fixture graphics",
            "Recommend a sidekick or other side-oriented secondary display only when side-of-fixture placement is visibly established or strongly supported",
            "Recommend an endcap only when aisle-end or end-of-run context is visible",
            "Never infer an endcap location from an ordinary inline shelf",
            "Recommend a floorstand only when usable floor-placement context is visible",
            "Recommend quarter-pallet, half-pallet, full-pallet, or similar large floor-based formats only when the scene supports substantial visible product volume and an appropriate floor or pallet-scale placement",
            "When enhancement and replacement are both strongly supported and represent materially different KKG scopes, preserve both as separate candidates before ranking",
            "Do NOT automatically combine fixture enhancement and fixture replacement",
        ):
            with self.subTest(format_instruction=instruction):
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


    def test_pallet_execution_is_independent_of_package_branding(self):
        pallet = self.section("PALLET EXECUTION VS PRODUCT PACKAGING:", "PHYSICAL SOLUTION SELECTION:")
        for instruction in (
            "Evaluate the physical pallet execution separately from branding printed on the product packages",
            "Strong package branding does NOT by itself mean the pallet execution is a purpose-built branded display",
            "Branded cartons, cases, tubs, or packages stacked on a generic pallet, plain divider sheets, slip sheets, simple corrugate layers, or basic stacking support may still justify a branded pallet-display opportunity",
            "Do not call it weak merely because it lacks decorative graphics",
            "Judge whether the structure meaningfully presents, organizes, brands, navigates, or supports the product",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, pallet)

    def test_pallet_candidate_gate_and_preservation(self):
        pallet = self.section("PALLET EXECUTION VS PRODUCT PACKAGING:", "PHYSICAL SOLUTION SELECTION:")
        for instruction in (
            "evaluate the pallet execution itself before settling only on smaller signage, price communication, or navigation",
            "Generate and preserve a pallet-display candidate when ALL THREE are supported",
            "PALLET-SCALE PLACEMENT: Substantial pallet-scale or equivalent large-format merchandising is clearly visible",
            "GENERIC / BASIC EXECUTION: Product is primarily stacked on a generic pallet, divider sheets, slip sheets, simple corrugate support, or another basic structure rather than a purposeful branded display",
            "MEANINGFUL BENEFIT: A purpose-built branded pallet display could materially improve presentation, brand ownership, organization, navigation, stopping power, or shopper-facing execution",
            "When all three are supported, preserve that candidate before evaluating smaller graphics/navigation opportunities separately",
            "Do not force a pallet-display candidate when placement is uncertain, the current branded display structure is already strong, replacement is speculative, or there is no meaningful visible benefit",
            "Do not depend on assumed future inventory, retailer approval, unseen floor space, budget, or dimensions",
            "A pallet alone does not justify replacement",
            "may both be candidates when they represent distinct, supported scopes; do not force both",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, pallet)
        final = self.section("FINAL LANGUAGE CHECK:", "Do not output this internal check.")
        self.assertIn("For a pallet-scale target, did I evaluate the physical pallet execution separately from the branding printed on the product packages?", final)

    def test_pallet_graphics_and_v19_placement_priority_remain(self):
        prompt = self.prompt()
        for instruction in (
            "PALLET-SCALE: prioritize pallet graphics, pallet-display improvement",
            "Keep pallet-base graphics, pallet wraps, divider/tier graphics, variant navigation, price-sign integration, and quarter-, half-, or full-pallet formats available when supported",
            "Smaller pallet improvements remain valid when they are the better fit",
            "Placement priority guides candidate consideration, but visible evidence still determines whether each opportunity is valid",
            "Do not suppress a strong smaller solution when it better solves the visible need",
        ):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)
