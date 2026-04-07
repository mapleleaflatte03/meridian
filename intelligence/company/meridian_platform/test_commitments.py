#!/usr/bin/env python3
import importlib.util
import os
import tempfile
import types
import unittest
from unittest import mock


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
COMMITMENTS_PY = os.path.join(PLATFORM_DIR, 'commitments.py')
WORKSPACE_PY = os.path.join(PLATFORM_DIR, 'workspace.py')


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CommitmentModuleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.commitments = _load_module(COMMITMENTS_PY, 'commitments_test_module')
        self.org_id = 'org_founding'
        self.orig_capsule_path = self.commitments.capsule_path
        self.commitments.capsule_path = lambda org_id, filename: os.path.join(self.tmp.name, filename)

    def tearDown(self):
        self.commitments.capsule_path = self.orig_capsule_path
        self.tmp.cleanup()

    def test_commitment_lifecycle_and_delivery_refs(self):
        record = self.commitments.propose_commitment(
            'host_peer',
            'org_peer',
            'Deliver the approved brief',
            commitment_id='com_demo',
            proposed_by='user_owner',
            note='Founding pilot agreement',
            org_id=self.org_id,
        )
        self.assertEqual(record['status'], 'proposed')
        self.assertEqual(record['institution_id'], self.org_id)
        self.assertEqual(record['target_institution_id'], 'org_peer')

        record = self.commitments.accept_commitment('com_demo', 'user_owner', org_id=self.org_id)
        self.assertEqual(record['status'], 'accepted')
        self.assertEqual(record['accepted_by'], 'user_owner')

        validated = self.commitments.validate_commitment_for_delivery(
            'com_demo',
            target_host_id='host_peer',
            target_institution_id='org_peer',
            org_id=self.org_id,
        )
        self.assertEqual(validated['commitment_id'], 'com_demo')

        record = self.commitments.record_delivery_ref(
            'com_demo',
            {
                'receipt_id': 'fedrcpt_123',
                'envelope_id': 'fed_123',
                'message_type': 'execution_request',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(record['delivery_refs']), 1)
        self.assertEqual(record['delivery_refs'][0]['receipt_id'], 'fedrcpt_123')
        self.assertIn('recorded_at', record['delivery_refs'][0])

        record = self.commitments.settle_commitment('com_demo', 'user_owner', org_id=self.org_id)
        self.assertEqual(record['status'], 'settled')
        summary = self.commitments.commitment_summary(self.org_id)
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['settled'], 1)
        self.assertEqual(summary['delivery_refs_total'], 1)

    def test_commitment_delivery_validation_rejects_target_mismatch(self):
        self.commitments.propose_commitment(
            'host_peer',
            'org_peer',
            'Deliver the approved brief',
            commitment_id='com_mismatch',
            proposed_by='user_owner',
            org_id=self.org_id,
        )
        self.commitments.accept_commitment('com_mismatch', 'user_owner', org_id=self.org_id)

        with self.assertRaises(ValueError):
            self.commitments.validate_commitment_for_delivery(
                'com_mismatch',
                target_host_id='host_other',
                target_institution_id='org_peer',
                org_id=self.org_id,
            )

    def test_federated_commitment_mirror_creates_and_updates_record(self):
        record = self.commitments.mirror_federated_commitment(
            'com_fed',
            org_id=self.org_id,
            message_type='commitment_proposal',
            source_host_id='host_sender',
            source_institution_id='org_sender',
            target_host_id='host_live',
            target_institution_id='org_peer',
            actor_id='user_sender',
            warrant_id='war_commit',
            envelope_id='fed_env_1',
            receipt_id='fed_rcpt_1',
            payload={
                'commitment_type': 'deliver_brief',
                'summary': 'Deliver the approved brief',
                'terms_payload': {'scope': 'brief'},
            },
        )
        self.assertEqual(record['status'], 'proposed')
        self.assertEqual(record['mirror_origin'], 'federation')
        self.assertEqual(record['federation_message_type'], 'commitment_proposal')
        self.assertEqual(record['mirrored_from_envelope_id'], 'fed_env_1')
        self.assertEqual(record['target_host_id'], 'host_live')
        self.assertEqual(record['target_institution_id'], 'org_peer')
        self.assertEqual(len(record['federation_refs']), 1)

        record = self.commitments.mirror_federated_commitment(
            'com_fed',
            org_id=self.org_id,
            message_type='commitment_acceptance',
            source_host_id='host_sender',
            source_institution_id='org_sender',
            target_host_id='host_live',
            target_institution_id='org_peer',
            actor_id='user_sender',
            warrant_id='war_commit',
            envelope_id='fed_env_2',
            receipt_id='fed_rcpt_2',
            payload={
                'commitment_type': 'deliver_brief',
                'summary': 'Deliver the approved brief',
                'terms_payload': {'scope': 'brief'},
            },
        )
        self.assertEqual(record['status'], 'accepted')
        self.assertEqual(record['accepted_by'], 'user_sender')
        self.assertEqual(record['accepted_at'], record['reviewed_at'])
        self.assertEqual(record['mirror_origin'], 'federation')
        self.assertEqual(record['federation_message_type'], 'commitment_acceptance')
        self.assertEqual(len(record['federation_refs']), 2)
        summary = self.commitments.commitment_summary(self.org_id)
        self.assertEqual(summary['accepted'], 1)

    def test_federated_commitment_breach_notice_marks_record_breached(self):
        record = self.commitments.mirror_federated_commitment(
            'com_fed_breach',
            org_id=self.org_id,
            message_type='commitment_breach_notice',
            source_host_id='host_sender',
            source_institution_id='org_sender',
            target_host_id='host_live',
            target_institution_id='org_peer',
            actor_id='user_sender',
            warrant_id='war_commit',
            envelope_id='fed_env_breach',
            receipt_id='fed_rcpt_breach',
            payload={
                'commitment_type': 'deliver_brief',
                'summary': 'Deliver the approved brief',
                'terms_payload': {'scope': 'brief'},
            },
        )
        self.assertEqual(record['status'], 'breached')
        self.assertEqual(record['state'], 'breached')
        self.assertEqual(record['mirror_origin'], 'federation')
        self.assertEqual(record['federation_message_type'], 'commitment_breach_notice')
        self.assertEqual(record['breached_by'], 'user_sender')
        self.assertEqual(record['breached_at'], record['reviewed_at'])
        self.assertEqual(record['mirrored_from_envelope_id'], 'fed_env_breach')
        self.assertEqual(len(record['federation_refs']), 1)

    def test_settlement_refs_are_recorded_and_deduped(self):
        self.commitments.propose_commitment(
            'host_peer',
            'org_peer',
            'Settle the approved brief',
            commitment_id='com_settle',
            proposed_by='user_owner',
            warrant_id='war_live_demo',
            org_id=self.org_id,
        )
        self.commitments.accept_commitment('com_settle', 'user_owner', org_id=self.org_id)

        validated = self.commitments.validate_commitment_for_settlement(
            'com_settle',
            org_id=self.org_id,
            warrant_id='war_live_demo',
        )
        self.assertEqual(validated['commitment_id'], 'com_settle')

        record = self.commitments.record_settlement_ref(
            'com_settle',
            {
                'proposal_id': 'ppo_live_demo',
                'tx_ref': 'ptx_live_demo',
                'verification_state': 'host_ledger_final',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(record['settlement_refs']), 1)
        self.assertEqual(record['settlement_refs'][0]['proposal_id'], 'ppo_live_demo')
        self.assertIn('recorded_at', record['settlement_refs'][0])

        record = self.commitments.record_settlement_ref(
            'com_settle',
            {
                'proposal_id': 'ppo_live_demo',
                'tx_ref': 'ptx_live_demo_v2',
                'verification_state': 'chain_final',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(record['settlement_refs']), 1)
        self.assertEqual(record['settlement_refs'][0]['tx_ref'], 'ptx_live_demo_v2')
        self.assertEqual(record['settlement_refs'][0]['verification_state'], 'chain_final')

        record = self.commitments.record_settlement_ref(
            'com_settle',
            {
                'envelope_id': 'fed_notice_demo',
                'receipt_id': 'fedrcpt_demo',
                'proposal_id': 'ppo_other_demo',
                'tx_ref': 'ptx_other_demo',
                'verification_state': 'host_ledger_final',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(record['settlement_refs']), 2)
        self.assertEqual(record['settlement_refs'][1]['envelope_id'], 'fed_notice_demo')
        self.assertEqual(record['settlement_refs'][1]['receipt_id'], 'fedrcpt_demo')

        record = self.commitments.record_settlement_ref(
            'com_settle',
            {
                'envelope_id': 'fed_notice_demo',
                'receipt_id': 'fedrcpt_demo',
                'proposal_id': 'ppo_other_demo_2',
                'tx_ref': 'ptx_other_demo_2',
                'verification_state': 'host_ledger_final_v2',
            },
            org_id=self.org_id,
        )
        self.assertEqual(len(record['settlement_refs']), 2)
        self.assertEqual(record['settlement_refs'][1]['verification_state'], 'host_ledger_final_v2')

        summary = self.commitments.commitment_summary(self.org_id)
        self.assertEqual(summary['accepted'], 1)
        self.assertEqual(summary['settlement_refs_total'], 2)


class WorkspaceCommitmentTests(unittest.TestCase):
    def setUp(self):
        self.workspace = _load_module(WORKSPACE_PY, 'workspace_commitment_test_module')

    def test_federation_send_records_commitment_delivery_ref(self):
        host_identity = types.SimpleNamespace(host_id='host_live')
        delivery = {
            'peer': {'transport': 'https'},
            'claims': {'envelope_id': 'fed_abc'},
            'receipt': {
                'receipt_id': 'fedrcpt_abc',
                'receiver_host_id': 'host_peer',
                'receiver_institution_id': 'org_peer',
            },
            'response': {},
        }
        fake_authority = types.SimpleNamespace(
            ensure_enabled=lambda: None,
            deliver=mock.Mock(return_value=delivery),
            snapshot=mock.Mock(return_value={'enabled': True}),
        )

        commitment_validate = mock.Mock(return_value={
            'commitment_id': 'com_demo',
            'status': 'accepted',
            'target_host_id': 'host_peer',
            'target_institution_id': 'org_peer',
        })
        commitment_record = mock.Mock(return_value={
            'commitment_id': 'com_demo',
            'status': 'accepted',
            'delivery_refs': [],
        })
        fake_commitments = types.SimpleNamespace(
            validate_commitment_for_delivery=commitment_validate,
            record_delivery_ref=commitment_record,
        )

        with mock.patch.object(self.workspace, '_runtime_host_state', return_value=(host_identity, {'admitted_org_ids': ['org_founding']})), \
             mock.patch.object(self.workspace, '_federation_authority', return_value=fake_authority), \
             mock.patch.object(self.workspace, 'log_event'), \
             mock.patch.object(self.workspace, 'commitments', fake_commitments):
            delivery_result, federation_state = self.workspace._deliver_federation_envelope(
                'org_founding',
                'host_peer',
                'org_peer',
                'notice',
                payload={'task': 'demo'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
                commitment_id='com_demo',
            )

        self.assertEqual(federation_state['enabled'], True)
        self.assertEqual(delivery_result['claims']['envelope_id'], 'fed_abc')
        commitment_validate.assert_called_once_with(
            'com_demo',
            target_host_id='host_peer',
            target_institution_id='org_peer',
            org_id='org_founding',
            warrant_id='',
        )
        commitment_record.assert_called_once()
        recorded_ref = commitment_record.call_args.args[1]
        self.assertEqual(recorded_ref['receipt_id'], 'fedrcpt_abc')
        self.assertEqual(recorded_ref['target_host_id'], 'host_peer')
        self.assertEqual(recorded_ref['target_institution_id'], 'org_peer')

    def test_federation_commitment_messages_require_cross_institution_warrant(self):
        host_identity = types.SimpleNamespace(host_id='host_live')
        delivery = {
            'peer': {'transport': 'https'},
            'claims': {'envelope_id': 'fed_commit_demo'},
            'receipt': {
                'receipt_id': 'fedrcpt_commit_demo',
                'receiver_host_id': 'host_peer',
                'receiver_institution_id': 'org_peer',
            },
            'response': {},
        }
        fake_authority = types.SimpleNamespace(
            ensure_enabled=lambda: None,
            deliver=mock.Mock(return_value=delivery),
            snapshot=mock.Mock(return_value={'enabled': True}),
        )
        validate_calls = []

        def fake_validate_warrant_for_execution(*args, **kwargs):
            validate_calls.append(kwargs)
            return {'warrant_id': kwargs.get('warrant_id', 'war_commit')}

        with mock.patch.object(self.workspace, '_runtime_host_state', return_value=(host_identity, {'admitted_org_ids': ['org_founding']})), \
             mock.patch.object(self.workspace, '_federation_authority', return_value=fake_authority), \
             mock.patch.object(self.workspace, 'log_event'), \
             mock.patch.object(self.workspace.commitments, 'validate_commitment_for_delivery', return_value={
                 'commitment_id': 'com_demo',
                 'status': 'accepted',
                 'target_host_id': 'host_peer',
                 'target_institution_id': 'org_peer',
             }), \
             mock.patch.object(self.workspace.commitments, 'validate_commitment_for_breach_notice', return_value={
                 'commitment_id': 'com_demo',
                 'status': 'breached',
                 'target_host_id': 'host_peer',
                 'target_institution_id': 'org_peer',
             }), \
             mock.patch.object(self.workspace.commitments, 'record_delivery_ref', return_value={
                 'commitment_id': 'com_demo',
                 'status': 'accepted',
                 'delivery_refs': [],
             }), \
             mock.patch.object(self.workspace, 'validate_warrant_for_execution', side_effect=fake_validate_warrant_for_execution):
            for message_type in ('commitment_proposal', 'commitment_acceptance', 'commitment_breach_notice'):
                self.workspace._deliver_federation_envelope(
                    'org_founding',
                    'host_peer',
                    'org_peer',
                    message_type,
                    payload={
                        'commitment_id': 'com_demo',
                        'commitment_type': 'deliver_brief',
                        'summary': 'Deliver the approved brief',
                    },
                    actor_type='user',
                    actor_id='user_owner',
                    session_id='ses_demo',
                    warrant_id='war_commit',
                    commitment_id='com_demo',
                )

        self.assertEqual(
            [call['action_class'] for call in validate_calls],
            [
                'cross_institution_commitment',
                'cross_institution_commitment',
                'cross_institution_commitment',
            ],
        )

    def test_federation_breach_notice_requires_breached_commitment_validation(self):
        host_identity = types.SimpleNamespace(host_id='host_live')
        delivery = {
            'peer': {'transport': 'https'},
            'claims': {'envelope_id': 'fed_breach_demo'},
            'receipt': {
                'receipt_id': 'fedrcpt_breach_demo',
                'receiver_host_id': 'host_peer',
                'receiver_institution_id': 'org_peer',
            },
            'response': {},
        }
        fake_authority = types.SimpleNamespace(
            ensure_enabled=lambda: None,
            deliver=mock.Mock(return_value=delivery),
            snapshot=mock.Mock(return_value={'enabled': True}),
        )
        commitment_validate = mock.Mock(return_value={
            'commitment_id': 'com_breach',
            'status': 'breached',
            'target_host_id': 'host_peer',
            'target_institution_id': 'org_peer',
        })
        commitment_record = mock.Mock(return_value={
            'commitment_id': 'com_breach',
            'status': 'breached',
            'delivery_refs': [],
        })
        fake_commitments = types.SimpleNamespace(
            validate_commitment_for_breach_notice=commitment_validate,
            record_delivery_ref=commitment_record,
        )

        with mock.patch.object(self.workspace, '_runtime_host_state', return_value=(host_identity, {'admitted_org_ids': ['org_founding']})), \
             mock.patch.object(self.workspace, '_federation_authority', return_value=fake_authority), \
             mock.patch.object(self.workspace, 'log_event'), \
             mock.patch.object(self.workspace, 'validate_warrant_for_execution', return_value={'warrant_id': 'war_commit'}), \
             mock.patch.object(self.workspace, 'commitments', fake_commitments):
            self.workspace._deliver_federation_envelope(
                'org_founding',
                'host_peer',
                'org_peer',
                'commitment_breach_notice',
                payload={'commitment_type': 'deliver_brief', 'summary': 'Deliver the approved brief'},
                actor_type='user',
                actor_id='user_owner',
                session_id='ses_demo',
                warrant_id='war_commit',
                commitment_id='com_breach',
            )

        commitment_validate.assert_called_once_with(
            'com_breach',
            target_host_id='host_peer',
            target_institution_id='org_peer',
            org_id='org_founding',
            warrant_id='war_commit',
        )
        commitment_record.assert_called_once()


if __name__ == '__main__':
    unittest.main()
