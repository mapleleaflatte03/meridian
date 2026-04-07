#!/usr/bin/env python3
import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE_PY = os.path.join(ROOT, 'subscription_service.py')


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SubscriptionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.org_a = 'org_alpha'
        self.org_b = 'org_beta'
        self.service = _load_module(SERVICE_PY, 'subscription_service_test_module')
        self.orig_capsule_path = self.service.capsule_path
        self.orig_ensure_capsule = self.service.ensure_capsule

        def capsule_path(org_id, filename):
            org_dir = os.path.join(self.tmp.name, org_id or 'default')
            return os.path.join(org_dir, filename)

        def ensure_capsule(org_id):
            os.makedirs(os.path.join(self.tmp.name, org_id or 'default'), exist_ok=True)
            return os.path.join(self.tmp.name, org_id or 'default')

        self.service.capsule_path = capsule_path
        self.service.ensure_capsule = ensure_capsule

    def tearDown(self):
        self.service.capsule_path = self.orig_capsule_path
        self.service.ensure_capsule = self.orig_ensure_capsule
        self.tmp.cleanup()

    def _write_payment_tx(self, org_id, payment_key, *, payment_ref='', tx_hash='', amount=0.0):
        tx_path = os.path.join(self.tmp.name, org_id, 'transactions.jsonl')
        os.makedirs(os.path.dirname(tx_path), exist_ok=True)
        entry = {
            'type': 'customer_payment',
            'payment_key': payment_key,
            'payment_ref': payment_ref,
            'tx_hash': tx_hash,
            'amount': amount,
        }
        with open(tx_path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        return tx_path

    def test_add_list_and_check_are_org_scoped(self):
        self.service.add_subscription('111', org_id=self.org_a, actor='owner')
        self.service.add_subscription('222', org_id=self.org_b, actor='owner')

        self.assertEqual(len(self.service.list_subscriptions(org_id=self.org_a, telegram_id='111')), 1)
        self.assertEqual(len(self.service.list_subscriptions(org_id=self.org_b, telegram_id='222')), 1)
        self.assertEqual(self.service.list_subscriptions(org_id=self.org_a, telegram_id='222'), [])

        check = self.service.check_subscription('111', org_id=self.org_a)
        self.assertTrue(check['found'])
        self.assertTrue(check['active'])
        self.assertTrue(check['eligible_for_delivery'])
        self.assertEqual(check['subscription_count'], 1)

        summary_a = self.service.subscription_summary(self.org_a)
        summary_b = self.service.subscription_summary(self.org_b)
        self.assertEqual(summary_a['subscriber_count'], 1)
        self.assertEqual(summary_b['subscriber_count'], 1)
        self.assertEqual(summary_a['verified_paid_subscription_count'], 0)
        self.assertEqual(summary_b['verified_paid_subscription_count'], 0)

    def test_verify_payment_requires_evidence_and_records_delivery(self):
        with mock.patch.object(self.service._revenue_mod, 'find_customer_payment_evidence', return_value={
            'order_id': 'ord_123',
            'payment_key': 'pay_demo_1',
            'payment_ref': 'oid-123',
            'tx_hash': 'tx-abc',
            'amount': 9.99,
        }):
            created = self.service.add_subscription(
                '555',
                plan='premium-brief-monthly',
                payment_ref='oid-123',
                confirm_payment=True,
                org_id=self.org_a,
                actor='owner',
            )
        self.assertTrue(created['subscription']['payment_verified'])
        self.assertEqual(created['subscription']['payment_evidence']['payment_ref'], 'oid-123')

        delivery = self.service.record_delivery('555', 'premium-brief', org_id=self.org_a, actor='system')
        self.assertEqual(delivery['telegram_id'], '555')

        with mock.patch.object(self.service._revenue_mod, 'find_customer_payment_evidence', return_value={
            'order_id': 'ord_777',
            'payment_key': 'pay_demo_1',
            'payment_ref': 'oid-777',
            'tx_hash': 'tx-777',
            'amount': 9.99,
        }):
            verified = self.service.verify_payment('555', org_id=self.org_a, actor='owner')

        self.assertTrue(verified['subscription']['payment_verified'])
        self.assertEqual(verified['subscription']['payment_verified_by'], 'owner')
        self.assertEqual(verified['subscription']['payment_evidence']['order_id'], 'ord_777')

    def test_convert_trial_subscription_marks_trial_and_creates_paid_record(self):
        self.service.add_subscription('333', org_id=self.org_a, actor='owner')
        with mock.patch.object(self.service._revenue_mod, 'find_customer_payment_evidence', return_value={
            'order_id': 'ord_333',
            'payment_key': 'ref:oid-333',
            'payment_ref': 'oid-333',
            'tx_hash': 'tx-333',
            'amount': 9.99,
        }):
            result = self.service.convert_trial_subscription(
                '333',
                'premium-brief-monthly',
                payment_ref='oid-333',
                confirm_payment=True,
                org_id=self.org_a,
                actor='owner',
            )

        records = self.service.list_subscriptions(org_id=self.org_a, telegram_id='333')
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['status'], 'converted')
        self.assertTrue(result['subscription']['converted_from_trial'])
        self.assertTrue(result['subscription']['payment_verified'])

    def test_paid_subscription_is_blocked_without_payment_evidence(self):
        with mock.patch.object(self.service._revenue_mod, 'find_customer_payment_evidence', return_value=None):
            with self.assertRaises(ValueError):
                self.service.add_subscription(
                    '777',
                    plan='premium-brief-weekly',
                    payment_ref='missing',
                    confirm_payment=True,
                    org_id=self.org_a,
                    actor='owner',
                )

    def test_payment_verification_is_scoped_to_org_transactions(self):
        def evidence_lookup(*, payment_ref='', min_amount_usd=0.0, org_id=None, **_kwargs):
            if payment_ref == 'oid-org-b' and org_id == self.org_b:
                return {
                    'order_id': 'ord_org_b',
                    'payment_key': 'ref:oid-org-b',
                    'payment_ref': payment_ref,
                    'tx_hash': 'tx-org-b',
                    'amount': min_amount_usd,
                }
            return None

        with mock.patch.object(self.service._revenue_mod, 'find_customer_payment_evidence', side_effect=evidence_lookup):
            with self.assertRaises(ValueError):
                self.service.add_subscription(
                    '888',
                    plan='premium-brief-monthly',
                    payment_ref='oid-org-b',
                    confirm_payment=True,
                    org_id=self.org_a,
                    actor='owner',
                )

            created = self.service.add_subscription(
                '888',
                plan='premium-brief-monthly',
                payment_ref='oid-org-b',
                confirm_payment=True,
                org_id=self.org_b,
                actor='owner',
            )
        self.assertTrue(created['subscription']['payment_verified'])

    def test_active_delivery_targets_respects_internal_ids(self):
        payload = self.service.load_subscriptions(self.org_a)
        payload['_meta']['internal_test_ids'] = ['internal-1']
        payload['subscribers']['internal-1'] = [self.service.add_subscription('internal-1', org_id=self.org_a)['subscription']]
        payload['subscribers']['external-1'] = [self.service.add_subscription('external-1', org_id=self.org_a)['subscription']]
        self.service.save_subscriptions(payload, self.org_a)

        self.assertCountEqual(self.service.active_delivery_targets(self.org_a), ['external-1', 'internal-1'])
        self.assertEqual(self.service.active_delivery_targets(self.org_a, external_only=True), ['external-1'])


if __name__ == '__main__':
    unittest.main()
