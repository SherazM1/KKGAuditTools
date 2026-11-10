"""Actual response usage cost diagnostics, without network calls."""
import copy
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from shelf_audit.infrastructure.cost import (
    MODEL_PRICING, estimate_openai_request_cost, response_cost_diagnostic,
)
from shelf_audit.providers.openai import OpenAIAuditProvider, OpenAIProviderConfig


class CostTests(unittest.TestCase):
    def estimate(self, **kwargs):
        return estimate_openai_request_cost(model="gpt-6.1-sol", **kwargs)

    def test_exact_bucket_costs(self):
        cases = [
            (dict(input_tokens=1000, output_tokens=200), .004),
            (dict(input_tokens=1000, output_tokens=200, cached_input_tokens=600), .00286),
            (dict(input_tokens=1000, output_tokens=200, cache_write_tokens=600,
                  cache_write_30m_tokens=600), .0043),
            (dict(input_tokens=1000, output_tokens=200, cache_write_tokens=600,
                  cache_write_12h_tokens=600), .0058),
            (dict(input_tokens=1000, output_tokens=200, cached_input_tokens=200,
                  cache_write_tokens=500, cache_write_30m_tokens=300,
                  cache_write_12h_tokens=200), .00437),
        ]
        for usage, expected in cases:
            with self.subTest(usage=usage):
                result = self.estimate(**usage)
                self.assertEqual(result['estimated_cost_usd'], expected)
                self.assertTrue(result['estimate_complete'])

    def test_optional_details_missing_and_dict_or_sdk_usage(self):
        for usage in (dict(input_tokens=1000, output_tokens=200),
                      NS(input_tokens=1000, output_tokens=200),
                      NS(input_tokens=1000, output_tokens=200, input_tokens_details=None)):
            with self.subTest(usage=usage):
                result = response_cost_diagnostic(model='gpt-6.1-sol', usage=usage)
                self.assertEqual(result['estimated_cost_usd'], .004)
                self.assertTrue(result['estimate_complete'])
                self.assertEqual(result['cached_input_tokens'], 0)
                self.assertEqual(result['cache_write_tokens'], 0)

    def test_unknown_cache_write_ttl_is_partial_and_not_priced_as_input(self):
        result = self.estimate(input_tokens=1000, output_tokens=200, cache_write_tokens=600,
                               request_cache_ttl="unsupported")
        self.assertEqual(result['ordinary_input_tokens'], 400)
        self.assertEqual(result['estimated_cost_usd'], .0028)
        self.assertFalse(result['estimate_complete'])
        self.assertIn('TTL breakdown', result['reason'])

    def test_aggregate_writes_default_to_30m_without_double_counting(self):
        usage = NS(input_tokens=25973, output_tokens=352,
                   input_tokens_details=NS(cached_tokens=0, cache_write_tokens=25970))
        result = response_cost_diagnostic(model="gpt-6.1-sol", usage=usage)
        self.assertEqual(result['ordinary_input_tokens'], 3)
        self.assertEqual(result['cache_write_30m_tokens'], 0)  # Actual provider breakdown.
        self.assertEqual(result['effective_cache_write_30m_tokens'], 25970)
        self.assertEqual(result['estimated_cost_usd'], .068451)
        self.assertTrue(result['estimate_complete'])
        self.assertIsNone(result['reason'])
        self.assertEqual(result['cache_write_ttl_source'], 'default_30m')

    def test_provider_breakdown_precedes_request_configuration(self):
        for configured in (None, "30m", "12h", "unsupported"):
            with self.subTest(configured=configured):
                result = self.estimate(input_tokens=1000, output_tokens=200,
                    cache_write_tokens=600, cache_write_30m_tokens=200,
                    cache_write_12h_tokens=400, request_cache_ttl=configured)
                self.assertEqual(result['cache_write_ttl_source'], 'provider_breakdown')
                self.assertEqual(result['estimated_cost_usd'], .0053)
                self.assertTrue(result['estimate_complete'])

    def test_explicit_request_ttl_precedes_default(self):
        for configured, expected, bucket in (("30m", .0043, "30m"), ("12h", .0058, "12h")):
            with self.subTest(configured=configured):
                result = response_cost_diagnostic(model="gpt-6.1-sol", request_cache_ttl=configured,
                    usage=dict(input_tokens=1000, output_tokens=200,
                               input_tokens_details=dict(cache_write_tokens=600)))
                self.assertEqual(result['cache_write_ttl_source'], 'request_configuration')
                self.assertEqual(result['estimated_cost_usd'], expected)
                self.assertEqual(result[f'effective_cache_write_{bucket}_tokens'], 600)
                self.assertTrue(result['estimate_complete'])

    def test_unsupported_explicit_ttl_never_uses_default(self):
        for configured in ("unsupported", "", False):
            with self.subTest(configured=configured):
                result = self.estimate(input_tokens=1000, output_tokens=200,
                                      cache_write_tokens=600, request_cache_ttl=configured)
                self.assertEqual(result['cache_write_ttl_source'], 'unknown')
                self.assertEqual(result['effective_cache_write_30m_tokens'], 0)
                self.assertEqual(result['estimated_cost_usd'], .0028)
                self.assertFalse(result['estimate_complete'])

    def test_incomplete_provider_breakdown_is_not_overridden(self):
        result = self.estimate(input_tokens=1000, output_tokens=200, cache_write_tokens=600,
                              cache_write_30m_tokens=100)
        self.assertEqual(result['effective_cache_write_30m_tokens'], 100)
        self.assertEqual(result['cache_write_ttl_source'], 'provider_breakdown')
        self.assertFalse(result['estimate_complete'])

    def test_negative_ordinary_input_clamps_and_flags_inconsistency(self):
        result = self.estimate(input_tokens=100, output_tokens=20, cached_input_tokens=200)
        self.assertEqual(result['ordinary_input_tokens'], 0)
        self.assertFalse(result['estimate_complete'])

    def test_unknown_model_and_absent_usage(self):
        for model, usage in [('unknown', NS(input_tokens=10, output_tokens=10)),
                             ('gpt-6.1-sol', None), ('gpt-6.1-sol', NS())]:
            with self.subTest(model=model, usage=usage):
                result = response_cost_diagnostic(model=model, usage=usage)
                self.assertIsNone(result['estimated_cost_usd'])
                self.assertFalse(result['estimate_complete'])
                self.assertTrue(result['reason'])

    def test_malformed_details_are_nonfatal(self):
        for value in (-1, True, '100', float('nan')):
            result = response_cost_diagnostic(model='gpt-6.1-sol', usage=NS(
                input_tokens=1000, output_tokens=200,
                input_tokens_details=NS(cached_tokens=value)))
            self.assertFalse(result['estimate_complete'])
        class BadUsage:
            @property
            def input_tokens_details(self):
                raise RuntimeError('unreadable')
        self.assertIsNone(response_cost_diagnostic(model='gpt-6.1-sol', usage=BadUsage())['estimated_cost_usd'])

    def test_pricing_is_immutable(self):
        with self.assertRaises(TypeError):
            MODEL_PRICING['another'] = MODEL_PRICING['gpt-6.1-sol']
        with self.assertRaises(AttributeError):
            MODEL_PRICING['gpt-6.1-sol'].input_per_million = 0


class ProviderCostTests(unittest.TestCase):
    def test_response_usage_reaches_debug_trace_and_preserves_requests_and_results(self):
        from test_shelf_audit_openai_provider import _fake_response, _product_request
        from shelf_audit.audit import run_audit
        from shelf_audit.infrastructure.cache import MemoryAuditCache
        from shelf_audit.infrastructure.usage import MemoryUsageTracker
        from unittest.mock import Mock
        request = _product_request()
        response = _fake_response()
        response.usage = NS(input_tokens=1000, output_tokens=200, total_tokens=1200,
                            input_tokens_details=NS(cached_tokens=200, cache_write_tokens=500))
        client = Mock()
        client.responses.create.return_value = response
        provider = OpenAIAuditProvider(config=OpenAIProviderConfig(
            model_name='gpt-6.1-sol', network_enabled=True), client=client)
        kwargs = dict(image=request.image, criteria=list(request.criteria), mode=request.mode,
                      depth=request.depth, provider=provider)
        off_trace, on_trace = {}, {}
        tracker = MemoryUsageTracker()
        with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '0'}):
            off = run_audit(**kwargs, debug_trace=off_trace, usage_tracker=tracker)
        sent = copy.deepcopy(client.responses.create.call_args.kwargs)
        cache = MemoryAuditCache()
        with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
            on = run_audit(**kwargs, debug_trace=on_trace, cache=cache, usage_tracker=tracker)
            cached_trace = {}
            cached = run_audit(**kwargs, debug_trace=cached_trace, cache=cache)
        self.assertEqual(off, on)
        self.assertEqual(on, cached)
        self.assertEqual(off_trace, {})
        self.assertEqual(client.responses.create.call_args.kwargs, sent)
        self.assertEqual(client.responses.create.call_count, 2)
        diagnostic = on_trace['api_usage_cost']
        self.assertEqual(diagnostic['estimated_cost_usd'], .00387)
        self.assertEqual(diagnostic['cache_write_ttl_source'], 'default_30m')
        self.assertEqual([diagnostic[name] for name in (
            'input_tokens', 'ordinary_input_tokens', 'cached_input_tokens',
            'cache_write_tokens', 'cache_write_30m_tokens', 'cache_write_12h_tokens', 'output_tokens')],
            [1000, 300, 200, 500, 0, 0, 200])
        self.assertTrue(diagnostic['estimate_complete'])
        self.assertTrue(diagnostic['provider_called'])
        self.assertFalse(diagnostic['application_cache_hit'])
        self.assertEqual(cached_trace['api_usage_cost']['estimated_cost_usd'], 0)
        self.assertFalse(cached_trace['api_usage_cost']['provider_called'])
        self.assertTrue(cached_trace['api_usage_cost']['application_cache_hit'])
        # Existing telemetry cost semantics remain unchanged.
        self.assertIsNone(tracker.all()[0].estimated_cost)
        self.assertIsNone(tracker.all()[1].estimated_cost)
        self.assertFalse(hasattr(on, 'debug_cost'))

    def test_missing_usage_and_unknown_model_audits_succeed(self):
        from test_shelf_audit_openai_provider import _fake_response, _product_request
        from shelf_audit.audit import run_audit
        from unittest.mock import Mock
        request = _product_request()
        for model, usage in [('gpt-6.1-sol', None), ('unpriced', NS(input_tokens=1, output_tokens=1))]:
            with self.subTest(model=model):
                response = _fake_response()
                response.usage = usage
                client = Mock()
                client.responses.create.return_value = response
                provider = OpenAIAuditProvider(config=OpenAIProviderConfig(
                    model_name=model, network_enabled=True), client=client)
                trace = {}
                with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
                    result = run_audit(image=request.image, criteria=list(request.criteria),
                                       mode=request.mode, depth=request.depth, provider=provider,
                                       debug_trace=trace)
                self.assertEqual(len(result.opportunities), 1)
                self.assertIsNone(trace['api_usage_cost']['estimated_cost_usd'])
                self.assertFalse(trace['api_usage_cost']['estimate_complete'])

    def test_sdk_extra_ttl_fields_are_read_defensively(self):
        from openai.types.responses.response_usage import InputTokensDetails
        details = InputTokensDetails(cached_tokens=0, cache_write_tokens=100,
                                    cache_write_tokens_details={'ttl_30m_tokens': 100})
        result = response_cost_diagnostic(model='gpt-6.1-sol', usage=NS(
            input_tokens=100, output_tokens=0, input_tokens_details=details))
        self.assertEqual(result['estimated_cost_usd'], .00025)
        self.assertTrue(result['estimate_complete'])

    def test_cost_ui_is_only_inside_existing_debug_expander(self):
        from shelf_audit.page import _render_debug_trace
        from unittest.mock import Mock
        trace = {'api_usage_cost': dict(model='gpt-6.1-sol', estimated_cost_usd=0,
                    estimate_complete=True, provider_called=False, application_cache_hit=True)}
        with patch('shelf_audit.page.st') as st:
            with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '0'}):
                _render_debug_trace(trace)
            self.assertEqual(st.mock_calls, [])
            with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
                _render_debug_trace(trace)
            st.expander.assert_called_once_with('Audit Debug Trace')
            st.write.assert_any_call('Estimated API cost for this audit execution: $0.0000')
            st.write.assert_any_call('Provider call: no | Application cache hit: yes')


    def test_default_ttl_ui_shows_full_estimate_and_effective_buckets(self):
        from shelf_audit.page import _render_debug_trace
        cost = response_cost_diagnostic(model='gpt-6.1-sol', usage=dict(
            input_tokens=25973, output_tokens=352,
            input_tokens_details=dict(cache_write_tokens=25970)))
        cost.update(provider_called=True, application_cache_hit=False)
        with patch('shelf_audit.page.st') as st, patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
            _render_debug_trace({'api_usage_cost': cost})
            st.write.assert_any_call('Estimated API cost for this audit execution: $0.0685')
            st.caption.assert_any_call('Cache-write TTL: default 30m')
            self.assertEqual(st.json.call_args.args[0]['effective_cache_write_30m_tokens'], 25970)
