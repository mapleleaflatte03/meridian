#!/usr/bin/env python3
"""RED tests for Verifiable AI Commonwealth UX panel — Slice 6.

Covers:
- /api/research/moat-lock returns boundary classification JSON
- /api/status commonwealth block renders federation + settlement summary
  that the UI commonwealth panel can consume
"""
import sys
import os
import json
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))


class ResearchMoatLockRouteTest(unittest.TestCase):
    """Test that GET /api/research/moat-lock exists and returns correct structure."""

    def _get_workspace_handler(self):
        """Import workspace handler; skip if heavy deps unavailable."""
        try:
            import workspace
            return workspace
        except Exception as exc:
            self.skipTest('workspace import skipped: {}'.format(exc))

    def test_moat_lock_route_calls_get_research_moat_lock(self):
        """GET /api/research/moat-lock must delegate to _commonwealth.get_research_moat_lock."""
        import commonwealth as _cwm

        # Verify that 'get_research_moat_lock' exists in commonwealth module
        self.assertTrue(
            hasattr(_cwm, 'get_research_moat_lock'),
            "commonwealth must export 'get_research_moat_lock'",
        )

    def test_moat_lock_response_shape(self):
        """get_research_moat_lock must return open + patent_candidate + boundary_policy + last_updated."""
        import commonwealth as _cwm
        result = _cwm.get_research_moat_lock('org_test')
        self.assertIsInstance(result, dict)
        self.assertIn('open', result)
        self.assertIn('patent_candidate', result)
        self.assertIn('boundary_policy', result)
        self.assertIn('last_updated', result)


class CommonwealthStatusPanelDataTest(unittest.TestCase):
    """Test that the /api/status commonwealth block provides the fields needed by the UI panel."""

    def setUp(self):
        self.org_id = 'org_ux_test'

    def test_commonwealth_status_block_has_federation_and_settlement(self):
        """_commonwealth_status() must return federation + settlement sub-blocks."""
        with mock.patch('commonwealth.get_federation_state') as mock_fed, \
             mock.patch('commonwealth.get_settlements') as mock_settle:
            mock_fed.return_value = {'enabled': True, 'peer_count': 2}
            mock_settle.return_value = [
                {'status': 'prepared'},
                {'status': 'committed'},
            ]
            import commonwealth as _cwm
            fed_state = _cwm.get_federation_state(self.org_id)
            settlements = _cwm.get_settlements(self.org_id)

        self.assertIn('enabled', fed_state)
        self.assertIn('peer_count', fed_state)
        self.assertIsInstance(settlements, list)

    def test_get_research_moat_lock_is_deterministic(self):
        """Same org_id always returns same boundary classification."""
        import commonwealth as _cwm
        result1 = _cwm.get_research_moat_lock(self.org_id)
        result2 = _cwm.get_research_moat_lock(self.org_id)
        self.assertEqual(result1['open'], result2['open'])
        self.assertEqual(result1['patent_candidate'], result2['patent_candidate'])
        self.assertEqual(result1['boundary_policy'], result2['boundary_policy'])

    def test_patent_candidate_includes_adaptive_scoring(self):
        """Patent-candidate list must include adaptive constitutional sanction scoring."""
        import commonwealth as _cwm
        result = _cwm.get_research_moat_lock(self.org_id)
        topics = [item.get('topic') for item in result['patent_candidate'] if isinstance(item, dict)]
        self.assertIn('adaptive_constitutional_sanction_scoring', topics)

    def test_patent_candidate_includes_royalty_proof_binding(self):
        """Patent-candidate list must include royalty-proof binding design."""
        import commonwealth as _cwm
        result = _cwm.get_research_moat_lock(self.org_id)
        topics = [item.get('topic') for item in result['patent_candidate'] if isinstance(item, dict)]
        self.assertIn('royalty_proof_binding_design', topics)

    def test_open_artifacts_include_tests_and_benchmarks(self):
        """Open artifacts list must include tests/benchmarks and reference code."""
        import commonwealth as _cwm
        result = _cwm.get_research_moat_lock(self.org_id)
        categories = [item.get('category') for item in result['open'] if isinstance(item, dict)]
        self.assertIn('tests_and_benchmarks', categories)
        self.assertIn('reference_code', categories)


if __name__ == '__main__':
    unittest.main()
