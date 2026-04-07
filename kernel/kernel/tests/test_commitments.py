#!/usr/bin/env python3
import importlib.util
import pathlib
import shutil
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMITMENTS_PATH = ROOT / 'kernel' / 'commitments.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


commitments = _load_module('kernel_commitments_test', COMMITMENTS_PATH)
capsule = _load_module('kernel_capsule_test_for_commitments', CAPSULE_PATH)


class CommitmentCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_commitment_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def test_capsule_initializes_commitments_file(self):
        path = pathlib.Path(capsule.capsule_path(self.org_id, 'commitments.json'))
        self.assertTrue(path.exists())
        payload = commitments._load_store(self.org_id)
        self.assertEqual(payload['commitments'], {})
        self.assertIn('accepted', payload['states'])

    def test_propose_accept_validate_and_mark_delivery(self):
        record = commitments.propose_commitment(
            self.org_id,
            'host_beta',
            'org_beta',
            'Deliver the approved brief',
            'user_owner',
            terms_payload={'scope': 'demo'},
            warrant_id='war_demo',
        )
        self.assertEqual(record['status'], 'proposed')
        self.assertEqual(record['summary'], 'Deliver the approved brief')
        self.assertEqual(record['institution_id'], self.org_id)
        self.assertEqual(record['target_institution_id'], 'org_beta')
        accepted = commitments.accept_commitment(
            record['commitment_id'],
            'user_owner',
            org_id=self.org_id,
        )
        self.assertEqual(accepted['status'], 'accepted')
        self.assertEqual(accepted['accepted_by'], 'user_owner')
        validated = commitments.validate_commitment_for_delivery(
            record['commitment_id'],
            org_id=self.org_id,
            target_host_id='host_beta',
            target_institution_id='org_beta',
            warrant_id='war_demo',
        )
        self.assertEqual(validated['commitment_id'], record['commitment_id'])
        updated = commitments.record_delivery_ref(
            record['commitment_id'],
            {'receipt_id': 'fedrcpt_demo'},
            org_id=self.org_id,
        )
        self.assertEqual(updated['delivery_refs'][0]['receipt_id'], 'fedrcpt_demo')
        self.assertIn('recorded_at', updated['delivery_refs'][0])
        summary = commitments.commitment_summary(self.org_id)
        self.assertEqual(summary['accepted'], 1)
        self.assertEqual(summary['delivery_refs_total'], 1)

    def test_validate_rejects_unaccepted_commitment(self):
        record = commitments.propose_commitment(
            self.org_id,
            'host_beta',
            'org_beta',
            'Deliver the approved brief',
            'user_owner',
        )
        with self.assertRaises(ValueError):
            commitments.validate_commitment_for_delivery(
                record['commitment_id'],
                org_id=self.org_id,
                target_host_id='host_beta',
                target_institution_id='org_beta',
            )

    def test_validate_rejects_target_mismatch(self):
        record = commitments.propose_commitment(
            self.org_id,
            'host_beta',
            'org_beta',
            'Deliver the approved brief',
            'user_owner',
        )
        commitments.accept_commitment(record['commitment_id'], 'user_owner', org_id=self.org_id)
        with self.assertRaises(ValueError):
            commitments.validate_commitment_for_delivery(
                record['commitment_id'],
                org_id=self.org_id,
                target_host_id='host_gamma',
                target_institution_id='org_beta',
            )

    def test_review_transitions_to_breach_and_settle(self):
        record = commitments.propose_commitment(
            self.org_id,
            'host_beta',
            'org_beta',
            'Deliver the approved brief',
            'user_owner',
        )
        breached = commitments.breach_commitment(
            record['commitment_id'],
            'user_owner',
            org_id=self.org_id,
        )
        self.assertEqual(breached['status'], 'breached')
        settled = commitments.settle_commitment(
            record['commitment_id'],
            'user_owner',
            org_id=self.org_id,
        )
        self.assertEqual(settled['status'], 'settled')

    def test_settlement_refs_are_recorded_and_deduped(self):
        record = commitments.propose_commitment(
            self.org_id,
            'host_beta',
            'org_beta',
            'Settle the approved brief',
            'user_owner',
            warrant_id='war_demo',
        )
        commitments.accept_commitment(record['commitment_id'], 'user_owner', org_id=self.org_id)

        validated = commitments.validate_commitment_for_settlement(
            record['commitment_id'],
            org_id=self.org_id,
            warrant_id='war_demo',
        )
        self.assertEqual(validated['commitment_id'], record['commitment_id'])

        updated = commitments.record_settlement_ref(
            record['commitment_id'],
            {
                'proposal_id': 'ppo_demo',
                'tx_ref': 'ptx_demo',
                'verification_state': 'host_ledger_final',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(updated['settlement_refs']), 1)
        self.assertEqual(updated['settlement_refs'][0]['proposal_id'], 'ppo_demo')
        self.assertIn('recorded_at', updated['settlement_refs'][0])

        updated = commitments.record_settlement_ref(
            record['commitment_id'],
            {
                'proposal_id': 'ppo_demo',
                'tx_ref': 'ptx_demo_v2',
                'verification_state': 'chain_final',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(updated['settlement_refs']), 1)
        self.assertEqual(updated['settlement_refs'][0]['tx_ref'], 'ptx_demo_v2')
        self.assertEqual(updated['settlement_refs'][0]['verification_state'], 'chain_final')

        summary = commitments.commitment_summary(self.org_id)
        self.assertEqual(summary['accepted'], 1)
        self.assertEqual(summary['settlement_refs_total'], 1)

    def test_settlement_notice_refs_dedupe_by_envelope_and_receipt(self):
        record = commitments.propose_commitment(
            self.org_id,
            'host_beta',
            'org_beta',
            'Settle the approved brief',
            'user_owner',
            warrant_id='war_demo',
        )
        commitments.accept_commitment(record['commitment_id'], 'user_owner', org_id=self.org_id)

        updated = commitments.record_settlement_ref(
            record['commitment_id'],
            {
                'envelope_id': 'fed_env_demo',
                'receipt_id': 'fed_rcpt_demo',
                'proposal_id': 'ppo_demo',
                'tx_ref': 'ptx_demo',
                'verification_state': 'host_ledger_final',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(updated['settlement_refs']), 1)
        self.assertEqual(updated['settlement_refs'][0]['envelope_id'], 'fed_env_demo')

        updated = commitments.record_settlement_ref(
            record['commitment_id'],
            {
                'envelope_id': 'fed_env_demo',
                'receipt_id': 'fed_rcpt_demo',
                'proposal_id': 'ppo_demo_other',
                'tx_ref': 'ptx_demo_other',
                'verification_state': 'chain_final',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(updated['settlement_refs']), 1)
        self.assertEqual(updated['settlement_refs'][0]['verification_state'], 'chain_final')
        self.assertEqual(updated['settlement_refs'][0]['proposal_id'], 'ppo_demo_other')

        updated = commitments.record_settlement_ref(
            record['commitment_id'],
            {
                'receipt_id': 'fed_rcpt_demo_2',
                'proposal_id': 'ppo_demo_fresh',
                'tx_ref': 'ptx_demo_fresh',
                'verification_state': 'accepted',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(updated['settlement_refs']), 2)
        self.assertEqual(updated['settlement_refs'][0]['proposal_id'], 'ppo_demo_other')
        self.assertEqual(updated['settlement_refs'][1]['receipt_id'], 'fed_rcpt_demo_2')

    def test_sync_federated_commitment_proposal_creates_mirrored_record(self):
        record, created = commitments.sync_federated_commitment_proposal(
            self.org_id,
            'cmt_fed_demo',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id=self.org_id,
            summary='Deliver shared brief',
            actor_id='peer:host_alpha',
            terms_payload={'scope': 'shared-brief'},
            warrant_id='war_commit_demo',
        )
        self.assertTrue(created)
        self.assertEqual(record['commitment_id'], 'cmt_fed_demo')
        self.assertEqual(record['source_host_id'], 'host_alpha')
        self.assertEqual(record['source_institution_id'], 'org_alpha')
        self.assertEqual(record['target_host_id'], 'host_beta')
        self.assertEqual(record['target_institution_id'], self.org_id)

        same_record, created = commitments.sync_federated_commitment_proposal(
            self.org_id,
            'cmt_fed_demo',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id=self.org_id,
            summary='Deliver shared brief',
            actor_id='peer:host_alpha',
            terms_payload={'scope': 'shared-brief'},
            warrant_id='war_commit_demo',
        )
        self.assertFalse(created)
        self.assertEqual(same_record['commitment_id'], 'cmt_fed_demo')

    def test_validate_commitment_for_acceptance_dispatch_uses_source_host(self):
        record, _created = commitments.sync_federated_commitment_proposal(
            self.org_id,
            'cmt_accept_demo',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id=self.org_id,
            summary='Deliver shared brief',
            actor_id='peer:host_alpha',
            warrant_id='war_commit_demo',
        )
        accepted = commitments.accept_commitment(
            record['commitment_id'],
            'user_owner',
            org_id=self.org_id,
        )
        validated = commitments.validate_commitment_for_acceptance_dispatch(
            accepted['commitment_id'],
            org_id=self.org_id,
            target_host_id='host_alpha',
            target_institution_id='org_alpha',
            warrant_id='war_commit_demo',
        )
        self.assertEqual(validated['commitment_id'], accepted['commitment_id'])

    def test_validate_commitment_for_proposal_dispatch_uses_target_binding_and_warrant(self):
        record = commitments.propose_commitment(
            self.org_id,
            'host_beta',
            self.org_id,
            'Deliver shared brief',
            'user_owner',
            warrant_id='war_commit_demo',
        )
        validated = commitments.validate_commitment_for_proposal_dispatch(
            record['commitment_id'],
            org_id=self.org_id,
            target_host_id='host_beta',
            target_institution_id=self.org_id,
            warrant_id='war_commit_demo',
        )
        self.assertEqual(validated['commitment_id'], record['commitment_id'])
        with self.assertRaises(PermissionError):
            commitments.validate_commitment_for_proposal_dispatch(
                record['commitment_id'],
                org_id=self.org_id,
                target_host_id='host_gamma',
            )

    def test_validate_commitment_for_acceptance_dispatch_allows_distinct_acceptance_warrant(self):
        record, _created = commitments.sync_federated_commitment_proposal(
            self.org_id,
            'cmt_accept_warrant_demo',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id=self.org_id,
            summary='Deliver shared brief',
            actor_id='peer:host_alpha',
            warrant_id='war_proposal_demo',
        )
        accepted = commitments.accept_commitment(
            record['commitment_id'],
            'user_owner',
            org_id=self.org_id,
        )
        validated = commitments.validate_commitment_for_acceptance_dispatch(
            accepted['commitment_id'],
            org_id=self.org_id,
            target_host_id='host_alpha',
            target_institution_id='org_alpha',
            warrant_id='war_acceptance_demo',
        )
        self.assertEqual(validated['commitment_id'], accepted['commitment_id'])

    def test_validate_commitment_for_breach_notice_requires_breached_state(self):
        record, _created = commitments.sync_federated_commitment_proposal(
            self.org_id,
            'cmt_breach_state_demo',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id=self.org_id,
            summary='Deliver shared brief',
            actor_id='peer:host_alpha',
            warrant_id='war_proposal_demo',
        )
        with self.assertRaises(PermissionError):
            commitments.validate_commitment_for_breach_notice(
                record['commitment_id'],
                org_id=self.org_id,
                target_host_id='host_alpha',
                target_institution_id='org_alpha',
                warrant_id='war_breach_demo',
            )

    def test_validate_commitment_for_breach_notice_uses_source_binding_and_distinct_warrant(self):
        record, _created = commitments.sync_federated_commitment_proposal(
            self.org_id,
            'cmt_breach_dispatch_demo',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id=self.org_id,
            summary='Deliver shared brief',
            actor_id='peer:host_alpha',
            warrant_id='war_proposal_demo',
        )
        breached = commitments.breach_commitment(
            record['commitment_id'],
            'user_owner',
            org_id=self.org_id,
        )
        validated = commitments.validate_commitment_for_breach_notice(
            breached['commitment_id'],
            org_id=self.org_id,
            target_host_id='host_alpha',
            target_institution_id='org_alpha',
            warrant_id='war_breach_demo',
        )
        self.assertEqual(validated['commitment_id'], breached['commitment_id'])
        with self.assertRaises(PermissionError):
            commitments.validate_commitment_for_breach_notice(
                breached['commitment_id'],
                org_id=self.org_id,
                target_host_id='host_gamma',
                target_institution_id='org_alpha',
                warrant_id='war_breach_demo',
            )

    def test_sync_federated_commitment_proposal_rejects_source_or_target_mismatch(self):
        commitments.sync_federated_commitment_proposal(
            self.org_id,
            'cmt_fed_mismatch_demo',
            source_host_id='host_alpha',
            source_institution_id='org_alpha',
            target_host_id='host_beta',
            target_institution_id=self.org_id,
            summary='Deliver shared brief',
            actor_id='peer:host_alpha',
            warrant_id='war_commit_demo',
        )
        with self.assertRaises(ValueError):
            commitments.sync_federated_commitment_proposal(
                self.org_id,
                'cmt_fed_mismatch_demo',
                source_host_id='host_gamma',
                source_institution_id='org_alpha',
                target_host_id='host_beta',
                target_institution_id=self.org_id,
                summary='Deliver shared brief',
                actor_id='peer:host_alpha',
                warrant_id='war_commit_demo',
            )
        with self.assertRaises(ValueError):
            commitments.sync_federated_commitment_proposal(
                self.org_id,
                'cmt_fed_mismatch_demo',
                source_host_id='host_alpha',
                source_institution_id='org_alpha',
                target_host_id='host_delta',
                target_institution_id=self.org_id,
                summary='Deliver shared brief',
                actor_id='peer:host_alpha',
                warrant_id='war_commit_demo',
            )


if __name__ == '__main__':
    unittest.main()
