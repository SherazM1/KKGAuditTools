"""Cost experiment controls, using local fake responses only."""
import copy
import hashlib
import os
import unittest
from unittest.mock import Mock, patch

from test_shelf_audit_openai_provider import _expanded_request, _fake_response
from shelf_audit.audit import run_audit
from shelf_audit.infrastructure.cache import MemoryAuditCache
from shelf_audit.infrastructure.cost import prompt_cache_reuse_ratio
from shelf_audit.models import TargetRegion, is_full_image_target
from shelf_audit.models import AuditMode, AuditDepth
from shelf_audit.criteria import load_criteria
from shelf_audit.prompts import build_audit_prompt
from shelf_audit.prompts import PROMPT_VERSION, _compact_criteria
from shelf_audit.providers.openai import OpenAIAuditProvider, OpenAIProviderConfig
from shelf_audit.providers.base import ProviderConfigurationError


class RequestEfficiencyTests(unittest.TestCase):
    def test_frozen_v20_instruction_lines(self):
        # Captured from pre-change v20 with the complete production criteria library.
        # Ignore only line order/blank lines: no instruction may be lost or rewritten.
        hashes = {
            ('product', 'quick'): '5abf651349b9562b4b043238cc98347c3e4f27c715ab97539ee4c8c4b0da6740',
            ('product', 'deep'): '04b970ae4073d7b8e6b58b676384d7db55051e0859b127b456ce2fb04be8902e',
            ('expanded', 'quick'): 'f51568828bf33acc3e3a7997c5981f1b1292013f4e582be15ac675f1789496ee',
            ('expanded', 'deep'): 'f338dc37cfcabe3475b2cd517670d8472677bc82f721970735fe1486cef5fab4',
        }
        for mode in AuditMode:
            for depth in AuditDepth:
                prompt = build_audit_prompt(load_criteria(), mode, depth, TargetRegion(.1, .1, .5, .5))
                lines = '\n'.join(sorted(line.strip() for line in prompt.splitlines() if line.strip()))
                self.assertEqual(hashlib.sha256(lines.encode()).hexdigest(), hashes[mode.value, depth.value])

    def provider(self, **config):
        client = Mock()
        client.responses.create.return_value = _fake_response()
        return OpenAIAuditProvider(config=OpenAIProviderConfig(
            model_name='gpt-6.1-sol', network_enabled=True, **config), client=client)

    def test_full_frame_tolerance_and_invalid_inputs(self):
        for region in (TargetRegion(0, 0, 1, 1),
                       TargetRegion(1e-8, 1e-8, 1-1e-8, 1-1e-8)):
            self.assertTrue(is_full_image_target(region))
        for region in (None, {}, TargetRegion(.1, 0, .9, 1),
                       TargetRegion(0, 0, .999, 1), TargetRegion(0, 0, float('nan'), 1),
                       TargetRegion(False, 0, 1, 1), TargetRegion(-1e-8, 0, 1, 1)):
            self.assertFalse(is_full_image_target(region))

    def test_image_count_scope_and_partial_behavior(self):
        provider = self.provider()
        request = _expanded_request()
        for region, count in ((TargetRegion(0, 0, 1, 1), 1),
                              (TargetRegion(1e-8, 0, 1-1e-8, 1), 1),
                              (request.target_region, 2)):
            request.target_region = region
            content = provider._build_response_input(request)[0]['content']
            self.assertEqual(len([c for c in content if c['type'] == 'input_image']), count)
            roles = [c['text'] for c in content if c['type'] == 'input_text']
            self.assertEqual('Image role: target_crop' in roles, count == 2)
            self.assertIn(f'x={region.x:.4f}', content[1]['text'])
            self.assertIn('the whole image is the audit', content[0]['text'])
            self.assertIs(request.target_region, region)
        request.target_crop = None
        with self.assertRaises(ProviderConfigurationError):
            provider._build_response_input(request)

    def test_missing_region_behavior_unchanged(self):
        request = _expanded_request()
        request.target_region = None
        content = self.provider()._build_response_input(request)[0]['content']
        self.assertIn('No target region supplied.', content[1]['text'])
        self.assertEqual(sum(c['type'] == 'input_image' for c in content), 2)

    def test_stable_prefix_and_breakpoint(self):
        request = _expanded_request()
        provider = self.provider()
        before = provider._build_response_input(request)[0]['content']
        request.target_region = TargetRegion(0, 0, 1, 1)
        request.image.data = b'different image content'
        after = provider._build_response_input(request)[0]['content']
        self.assertEqual(before[0], after[0])
        self.assertIn(_compact_criteria(list(request.criteria)), before[0]['text'])
        self.assertNotIn('x=0.1000', before[0]['text'])
        self.assertEqual(before[0]['prompt_cache_breakpoint'], {'mode': 'explicit'})
        self.assertEqual(PROMPT_VERSION, 'v20')

    def test_independent_detail_leaves_prompt_and_candidate_controls_unchanged(self):
        request = _expanded_request()
        control, experiment = self.provider(), self.provider(full_scene_image_detail='low')
        self.assertEqual(control.config.full_scene_image_detail, 'high')
        self.assertEqual(control.config.target_crop_image_detail, 'high')
        for provider, expected in ((control, ['high', 'high']), (experiment, ['low', 'high'])):
            provider.analyze(request)
            call = provider.client.responses.create.call_args.kwargs
            self.assertEqual([c['detail'] for c in call['input'][0]['content']
                              if c['type'] == 'input_image'], expected)
            self.assertNotIn('prompt_cache_retention', call)
            self.assertNotIn('prompt_cache_options', call)
        a = copy.deepcopy(control.client.responses.create.call_args.kwargs)
        b = copy.deepcopy(experiment.client.responses.create.call_args.kwargs)
        for call in (a, b):
            for c in call['input'][0]['content']:
                if c['type'] == 'input_image':
                    c.pop('detail')
        self.assertEqual(a, b)
        self.assertNotEqual(control.config_version, experiment.config_version)

    def test_ratio(self):
        self.assertEqual(prompt_cache_reuse_ratio(1000, 690), .69)
        self.assertEqual(prompt_cache_reuse_ratio(1000, 0), 0)
        for inputs, cached in ((None, None), (0, 0), (10, None), (10, 11), (True, 1)):
            self.assertIsNone(prompt_cache_reuse_ratio(inputs, cached))

    def test_trace_and_application_cache(self):
        request = _expanded_request()
        provider = self.provider()
        cache = MemoryAuditCache()
        kwargs = dict(image=request.image, criteria=list(request.criteria), mode=request.mode,
                      depth=request.depth, target_region=request.target_region,
                      target_crop=request.target_crop, provider=provider, cache=cache)
        for full_frame, expected in ((False, 2), (True, 1)):
            if full_frame:
                kwargs['target_region'] = TargetRegion(0, 0, 1, 1)
            trace = {}
            with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
                result = run_audit(**kwargs, debug_trace=trace)
                self.assertEqual(trace['request_cost']['images_sent'], expected)
                self.assertEqual(trace['request_cost']['target_crop_sent'], not full_frame)
                cached = run_audit(**kwargs, debug_trace=trace)
            self.assertEqual(result, cached)
            self.assertEqual(trace['request_cost']['images_sent'], 0)
            self.assertFalse(trace['request_cost']['target_crop_sent'])
            self.assertTrue(trace['api_usage_cost']['application_cache_hit'])
            self.assertFalse(trace['api_usage_cost']['provider_called'])
            self.assertEqual(trace['api_usage_cost']['estimated_cost_usd'], 0)
        self.assertEqual(provider.client.responses.create.call_count, 2)

    def test_debug_flag_does_not_change_provider_request(self):
        request = _expanded_request()
        provider = self.provider()
        with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '0'}):
            off = provider.analyze(request)
            call = copy.deepcopy(provider.client.responses.create.call_args.kwargs)
        with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
            on = provider.analyze(request)
        self.assertEqual(off.opportunities, on.opportunities)
        self.assertEqual(call, provider.client.responses.create.call_args.kwargs)
