#!/usr/bin/env python3
"""RED tests for Research/Open Moat Lock (Slice 6).

Covers the programmatic open-source boundary classification:
- Open by default: protocol specs, reference code, tests, benchmarks
- Patent-candidate: hypercube pairing optimization, adaptive constitutional scoring, royalty-proof binding

Aligned with ROADMAP.md Phase D/E and the "Open vs Patent-Candidate Boundaries" section.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from commonwealth import get_research_moat_lock


class ResearchMoatLockTest(unittest.TestCase):
    def setUp(self):
        self.org_id = 'org_research_test'

    def test_returns_open_and_patent_candidate_classifications(self):
        """The moat lock must return both 'open' and 'patent_candidate' artifact lists."""
        result = get_research_moat_lock(self.org_id)
        self.assertIn('open', result)
        self.assertIn('patent_candidate', result)
        self.assertIsInstance(result['open'], list)
        self.assertIsInstance(result['patent_candidate'], list)

    def test_open_artifacts_include_protocol_specs(self):
        """Open artifacts must include protocol specs, reference code, tests, benchmarks."""
        result = get_research_moat_lock(self.org_id)
        open_artifacts = result['open']
        # Check that at least one artifact category is present
        categories = [item.get('category') for item in open_artifacts if isinstance(item, dict)]
        self.assertIn('protocol_specs', categories)

    def test_patent_candidate_artifacts_include_hypercube_optimization(self):
        """Patent-candidate artifacts must include hypercube pairing optimization."""
        result = get_research_moat_lock(self.org_id)
        patent_artifacts = result['patent_candidate']
        topics = [item.get('topic') for item in patent_artifacts if isinstance(item, dict)]
        self.assertIn('hypercube_pairing_optimization', topics)

    def test_returns_boundary_policy_statement(self):
        """The moat lock must return a boundary_policy statement."""
        result = get_research_moat_lock(self.org_id)
        self.assertIn('boundary_policy', result)
        self.assertIsInstance(result['boundary_policy'], str)
        self.assertGreater(len(result['boundary_policy']), 0)

    def test_returns_last_updated_timestamp(self):
        """The moat lock must return a last_updated timestamp."""
        result = get_research_moat_lock(self.org_id)
        self.assertIn('last_updated', result)
        self.assertIsInstance(result['last_updated'], str)


if __name__ == '__main__':
    unittest.main()
