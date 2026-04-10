#!/usr/bin/env python3
"""RED tests for Dynamic Constitutional Federation (Slice 3).

Covers L3 constitutional federation lifecycle:
- rule propagation with local-queue fallback (RFC-0007 § Delivery States)
- receiving-side envelope validation and replay protection

Reference: RFC-0007 (Dynamic Constitutional Federation)
"""
import os
import sys
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from commonwealth import (
    propagate_court_rule,
    receive_court_rule,
    get_propagations,
)


class CommonwealthCourtPropagationTest(unittest.TestCase):
    """Tests for propagate_court_rule — sender side."""

    def setUp(self):
        self.org_id = 'org_sender'
        self.peer_org_id = 'org_receiver'
        self.peer_host_id = 'host_receiver'

        self.prop_store = {'propagations': {}}

        load_patcher = mock.patch('commonwealth._load_store')
        save_patcher = mock.patch('commonwealth._save_store')
        self.mock_load = load_patcher.start()
        self.mock_save = save_patcher.start()
        self.addCleanup(load_patcher.stop)
        self.addCleanup(save_patcher.stop)

        def fake_load(org_id, filename):
            return self.prop_store

        def fake_save(data, org_id, filename):
            self.prop_store.update(data)

        self.mock_load.side_effect = fake_load
        self.mock_save.side_effect = fake_save

    def test_queues_locally_when_federation_module_unavailable(self):
        """RFC-0007: delivery_status must be queued_local, not a raised exception."""
        with mock.patch('commonwealth._load_federation_module', side_effect=ImportError('federation not available')):
            result = propagate_court_rule(
                self.org_id,
                peer_host_id=self.peer_host_id,
                peer_org_id=self.peer_org_id,
                rule_id='rule_001',
                rule_text='No unauthorized execution across constitutional boundaries',
                ruleset_version='2.1.0',
            )

        self.assertEqual(result['delivery_status'], 'queued_local')
        self.assertIn('propagation_id', result)
        self.assertEqual(result['peer_host_id'], self.peer_host_id)
        self.assertEqual(result['peer_org_id'], self.peer_org_id)
        self.assertEqual(result['rule_id'], 'rule_001')

    def test_queued_local_record_persists_to_store(self):
        """Queued rules are saved for eventual delivery."""
        with mock.patch('commonwealth._load_federation_module', side_effect=ImportError('no federation')):
            result = propagate_court_rule(
                self.org_id,
                peer_host_id=self.peer_host_id,
                peer_org_id=self.peer_org_id,
                rule_id='rule_002',
                rule_text='Advisory rule for federation alignment',
                ruleset_version='2.0.0',
            )

        rows = get_propagations(self.org_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['propagation_id'], result['propagation_id'])
        self.assertEqual(rows[0]['delivery_status'], 'queued_local')

    def test_propagate_validates_peer_host_id_required(self):
        with self.assertRaisesRegex(ValueError, 'peer_host_id is required'):
            propagate_court_rule(
                self.org_id,
                peer_host_id='',
                rule_id='rule_003',
                rule_text='R',
                ruleset_version='2.0.0',
            )

    def test_propagate_validates_rule_id_required(self):
        with self.assertRaisesRegex(ValueError, 'rule_id is required'):
            propagate_court_rule(
                self.org_id,
                peer_host_id=self.peer_host_id,
                rule_id='',
                rule_text='R',
                ruleset_version='2.0.0',
            )

    def test_envelope_issued_when_federation_delivers(self):
        """When FederationAuthority delivers successfully, status is envelope_issued."""
        fake_delivery = {
            'envelope': {'envelope_id': 'env_abc', 'signature': 'sig_xyz'},
            'receipt': {'accepted': True},
            'claims': {'source_org_id': self.org_id},
        }

        fake_fa_instance = mock.Mock()
        fake_fa_instance.deliver.return_value = fake_delivery
        fake_fa_class = mock.Mock(return_value=fake_fa_instance)
        fake_fed_module = mock.Mock(
            FederationAuthority=fake_fa_class,
            load_peer_registry=mock.Mock(return_value={}),
        )

        with mock.patch('commonwealth._runtime_host_state', return_value=('host_local', {})), \
             mock.patch('commonwealth._load_federation_module', return_value=fake_fed_module):
            result = propagate_court_rule(
                self.org_id,
                peer_host_id=self.peer_host_id,
                peer_org_id=self.peer_org_id,
                rule_id='rule_004',
                rule_text='Cross-institution enforcement rule',
                ruleset_version='2.1.0',
            )

        self.assertEqual(result['delivery_status'], 'envelope_issued')
        self.assertEqual(result['delivery_ref']['envelope']['envelope_id'], 'env_abc')


class CommonwealthCourtReceivingTest(unittest.TestCase):
    """Tests for receive_court_rule — receiver side (RFC-0007 § Receiving Side)."""

    def setUp(self):
        self.org_id = 'org_receiver'
        self.peer_org_id = 'org_sender'
        self.inbox_store = {'received_rules': {}, 'replay_index': {}}

        load_patcher = mock.patch('commonwealth._load_store')
        save_patcher = mock.patch('commonwealth._save_store')
        self.mock_load = load_patcher.start()
        self.mock_save = save_patcher.start()
        self.addCleanup(load_patcher.stop)
        self.addCleanup(save_patcher.stop)

        def fake_load(org_id, filename):
            return self.inbox_store

        def fake_save(data, org_id, filename):
            self.inbox_store.update(data)

        self.mock_load.side_effect = fake_load
        self.mock_save.side_effect = fake_save

    def _make_envelope(self, propagation_id='prop_r001', rule_id='rule_r001'):
        return {
            'message_type': 'court_rule_propagation',
            'payload': {
                'propagation_id': propagation_id,
                'rule_id': rule_id,
                'rule_text': 'Cross-institution constitutional advisory',
                'ruleset_version': '2.1.0',
                'source_org_id': self.peer_org_id,
            },
            'signature': 'valid_sig_value',
        }

    def test_valid_envelope_accepted_and_persisted(self):
        envelope = self._make_envelope()

        with mock.patch('commonwealth._validate_received_envelope', return_value=True):
            result = receive_court_rule(self.org_id, envelope=envelope)

        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['rule_id'], 'rule_r001')
        self.assertFalse(result.get('idempotent', False))

    def test_replay_is_blocked_and_idempotent(self):
        envelope = self._make_envelope(propagation_id='prop_r002', rule_id='rule_r002')

        with mock.patch('commonwealth._validate_received_envelope', return_value=True):
            first = receive_court_rule(self.org_id, envelope=envelope)
            second = receive_court_rule(self.org_id, envelope=envelope)

        self.assertEqual(first['status'], 'accepted')
        self.assertEqual(second['status'], 'replay_blocked')
        self.assertTrue(second['idempotent'])
        self.assertEqual(second['rule_id'], 'rule_r002')

    def test_invalid_signature_raises(self):
        envelope = self._make_envelope(propagation_id='prop_r003', rule_id='rule_r003')

        with mock.patch('commonwealth._validate_received_envelope', return_value=False):
            with self.assertRaisesRegex(ValueError, 'invalid federation envelope signature'):
                receive_court_rule(self.org_id, envelope=envelope)

    def test_receive_requires_propagation_id_in_payload(self):
        envelope = {
            'message_type': 'court_rule_propagation',
            'payload': {
                'rule_id': 'rule_r004',
                'rule_text': 'R',
                'ruleset_version': '1.0',
                'source_org_id': self.peer_org_id,
                # propagation_id intentionally missing
            },
            'signature': 'valid_sig_value',
        }

        with mock.patch('commonwealth._validate_received_envelope', return_value=True):
            with self.assertRaisesRegex(ValueError, 'propagation_id is required'):
                receive_court_rule(self.org_id, envelope=envelope)


if __name__ == '__main__':
    unittest.main()
