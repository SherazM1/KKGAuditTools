import copy
import os
import unittest
from unittest.mock import Mock, patch

from shelf_audit.audit import run_audit
from shelf_audit.criteria import load_criteria
from shelf_audit.infrastructure.cache import MemoryAuditCache
from shelf_audit.models import AuditImage, AuditMode, AuditDepth
from shelf_audit.opportunity import Opportunity
from shelf_audit.providers.base import ProviderAnalysisResult, ProviderUsage


class DebugTraceTests(unittest.TestCase):
    def test_funnel_and_equivalence(self):
        criteria = load_criteria()[:5]
        candidates = [Opportunity(c['id'], title, 'Visible evidence', recommendation,
                                  value, confidence, value, value)
                      for c, title, recommendation, value, confidence in zip(
                          criteria,
                          ['Navigation', 'Navigation', 'Low confidence', 'Physical shelf', 'Other action'],
                          ['Improve signs', 'Improve signs', 'Low action', 'Use shelf space', 'Different action'],
                          [1, .9, .9, .8, .7], [1, 1, .1, 1, 1])]
        original = copy.deepcopy(candidates)
        provider = Mock(name='provider')
        provider.name = 'test'
        provider.model_name = 'test'
        provider.config_version = 'test'
        provider.analyze.return_value = ProviderAnalysisResult(candidates, ProviderUsage())
        kwargs = dict(image=AuditImage(b'image', 'image/png'), criteria=criteria,
                      mode=AuditMode.PRODUCT, depth=AuditDepth.QUICK, provider=provider)
        trace = {'stale': True}
        with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '0'}):
            off = run_audit(**kwargs, debug_trace=trace)
        self.assertEqual(trace, {})
        with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
            on = run_audit(**kwargs, debug_trace=trace)
        self.assertEqual(off, on)
        self.assertEqual(candidates, original)
        stages = trace['stages']
        self.assertEqual([len(v) for v in stages.values()], [5, 4, 3, len(on.opportunities), len(on.opportunities)])
        self.assertEqual(stages['RAW_PROVIDER_CANDIDATES'][2]['status'], 'removed_low_confidence')
        self.assertEqual(stages['AFTER_CONFIDENCE_FILTER'][1]['status'], 'removed_duplicate')
        self.assertEqual([r['criterion_id'] for r in stages['FINAL_SELECTED']],
                         [o.criterion_id for o in on.opportunities])
        self.assertEqual(stages['FINAL_SELECTED'][0]['priority_score'], on.opportunities[0].priority_score)
        candidates[0].title = 'Changed later'
        self.assertEqual(stages['RAW_PROVIDER_CANDIDATES'][0]['title'], 'Navigation')

    def test_cache_hit_has_only_final_stage(self):
        from test_shelf_audit_orchestration import CountingProvider, _make_test_image
        cache = MemoryAuditCache()
        provider = CountingProvider()
        kwargs = dict(image=_make_test_image(), criteria=load_criteria(), mode=AuditMode.PRODUCT,
                      depth=AuditDepth.QUICK, provider=provider, cache=cache)
        first = run_audit(**kwargs)
        trace = {}
        with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
            second = run_audit(**kwargs, debug_trace=trace)
        self.assertEqual(first, second)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(list(trace['stages']), ['FINAL_SELECTED'])
        self.assertIn('Cache hit', trace['note'])
        self.assertFalse(hasattr(second, 'debug_trace'))

    def test_ui_flag(self):
        from shelf_audit.page import _render_debug_trace
        with patch('shelf_audit.page.st') as st:
            with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '0'}):
                _render_debug_trace({'stages': {}})
            st.expander.assert_not_called()
            with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}):
                _render_debug_trace({'stages': {}})
            st.expander.assert_called_once_with('Audit Debug Trace')


    def test_selection_omissions_do_not_invent_reason(self):
        from shelf_audit.prioritization import prioritize_opportunities, snapshot_candidates
        candidates = [Opportunity(str(i), str(i), 'evidence', str(i), 1-i*.1, 1, 1, 1)
                      for i in range(3)]
        criteria = [{'id': str(i), 'opportunity_type': 'same'} for i in range(3)]
        trace = {}
        snapshot_candidates(trace, 'RAW_PROVIDER_CANDIDATES', candidates)
        expected = prioritize_opportunities(candidates, criteria=criteria, max_results=1)
        actual = prioritize_opportunities(candidates, criteria=criteria, max_results=1, debug_trace=trace)
        self.assertEqual(actual, expected)
        self.assertEqual([r['status'] for r in trace['stages']['AFTER_DUPLICATE_REDUCTION']],
                         ['kept', None, None])
        self.assertEqual(len(trace['stages']['AFTER_DIVERSITY_OR_SELECTION']), 1)

    def test_raw_snapshot_precedes_guardrails(self):
        from shelf_audit.guardrails import GuardrailError
        candidate = Opportunity('unknown_id', 'Raw title', 'Evidence', 'Action', 1, 1, 1, 1)
        provider = Mock()
        provider.name, provider.model_name, provider.config_version = 'test', 'test', 'test'
        provider.analyze.return_value = ProviderAnalysisResult([candidate], ProviderUsage())
        trace = {}
        with patch.dict(os.environ, {'SHELF_AUDIT_DEBUG_TRACE': '1'}), self.assertRaises(GuardrailError):
            run_audit(image=AuditImage(b'image', 'image/png'), criteria=load_criteria(),
                      mode=AuditMode.PRODUCT, depth=AuditDepth.QUICK, provider=provider, debug_trace=trace)
        self.assertEqual(trace['stages']['RAW_PROVIDER_CANDIDATES'][0]['title'], 'Raw title')
        self.assertEqual(list(trace['stages']), ['RAW_PROVIDER_CANDIDATES'])
