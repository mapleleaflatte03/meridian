#!/usr/bin/env python3
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import court


class DynamicCourtContractTests(unittest.TestCase):
    def setUp(self):
        self.org_id = 'org_test_contract'
        self._tmpdir = tempfile.TemporaryDirectory(prefix='dynamic-court-contract-')
        self._root = pathlib.Path(self._tmpdir.name)
        self._records_path = self._root / 'court_records.json'
        self._rules_path = self._root / 'court_rules.json'
        self._proposals_path = self._root / 'court_rule_proposals.json'
        self._votes_path = self._root / 'court_votes.json'
        self._legacy_path = self._root / 'legacy_court_records.json'

        self._patches = [
            mock.patch('court._resolve_org_id', side_effect=lambda org_id=None: org_id or self.org_id),
            mock.patch('court._records_path', side_effect=lambda org_id=None: str(self._records_path)),
            mock.patch(
                'court._dynamic_projection_paths',
                side_effect=lambda org_id=None: {
                    'rules': str(self._rules_path),
                    'proposals': str(self._proposals_path),
                    'votes': str(self._votes_path),
                },
            ),
            mock.patch('court.RECORDS_FILE', str(self._legacy_path)),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self._patches):
            patch.stop()
        self._tmpdir.cleanup()

    def test_projection_files_include_rule_version_and_proof_ref(self):
        proposal_id = court.propose_rule(
            title='Runtime Proof Requirement',
            description='Enforce runtime proof before settlement',
            rule_text='proof.required=true',
            proposed_by='user_owner',
            org_id=self.org_id,
            action_ids=['settle'],
        )
        court.vote_on_proposal(
            proposal_id=proposal_id,
            voter_id='user_owner',
            vote='for',
            justification='ship',
            org_id=self.org_id,
        )
        tally = court.tally_proposal(proposal_id=proposal_id, org_id=self.org_id, quorum=1)
        rule_id = court.activate_rule(proposal_id=proposal_id, org_id=self.org_id)

        self.assertTrue(self._rules_path.exists())
        self.assertTrue(self._proposals_path.exists())
        self.assertTrue(self._votes_path.exists())
        self.assertIn('proof_ref', tally)

        rules_payload = json.loads(self._rules_path.read_text())
        proposals_payload = json.loads(self._proposals_path.read_text())
        votes_payload = json.loads(self._votes_path.read_text())

        rule = next((row for row in rules_payload.get('rules', []) if row.get('id') == rule_id), None)
        self.assertIsNotNone(rule)
        self.assertGreaterEqual(rule.get('rule_version', 0), 1)
        self.assertTrue(str(rule.get('proof_ref') or '').startswith('court_rule_activation:'))

        proposal = next(
            (row for row in proposals_payload.get('proposals', []) if row.get('id') == proposal_id),
            None,
        )
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.get('rule_id'), rule_id)
        self.assertEqual(proposal.get('rule_version'), rule.get('rule_version'))
        self.assertEqual(proposal.get('proof_ref'), rule.get('proof_ref'))

        vote = next((row for row in votes_payload.get('votes', []) if row.get('proposal_id') == proposal_id), None)
        self.assertIsNotNone(vote)
        self.assertEqual(vote.get('voter_id'), 'user_owner')

    def test_vote_is_idempotent_per_voter(self):
        proposal_id = court.propose_rule(
            title='Spend Guard',
            description='Idempotency check',
            rule_text='treasury.max_spend=5',
            proposed_by='user_owner',
            org_id=self.org_id,
        )
        court.vote_on_proposal(
            proposal_id=proposal_id,
            voter_id='user_owner',
            vote='for',
            org_id=self.org_id,
        )
        court.vote_on_proposal(
            proposal_id=proposal_id,
            voter_id='user_owner',
            vote='against',
            org_id=self.org_id,
        )

        proposals = court.get_proposals(org_id=self.org_id)
        proposal = next(row for row in proposals if row.get('id') == proposal_id)
        votes = proposal.get('votes') or {}
        self.assertEqual(len(votes), 1)
        self.assertEqual(votes['user_owner']['vote'], 'against')


if __name__ == '__main__':
    unittest.main()
