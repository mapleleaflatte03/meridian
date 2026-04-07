#!/usr/bin/env python3
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import service_state


class ServiceStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='service-state-')
        self._subs = os.path.join(self._tmp, 'subscriptions.json')
        self._owner = os.path.join(self._tmp, 'owner_ledger.json')
        self._ledger = os.path.join(self._tmp, 'ledger.json')
        self._orig_subscriptions_path = service_state.subscriptions_path
        self._orig_owner_ledger_path = service_state.owner_ledger_path
        self._orig_ledger_path = service_state.ledger_path
        self._orig_ensure_subscription_aliases = service_state.ensure_subscription_aliases
        self._orig_ensure_accounting_aliases = service_state.ensure_accounting_aliases
        self._orig_legacy_subscriptions = service_state.LEGACY_SUBSCRIPTIONS_FILE
        self._orig_legacy_owner = service_state.LEGACY_OWNER_LEDGER_FILE
        self._orig_workspace = service_state.WORKSPACE
        self._orig_subscription_summary = service_state.subscription_service.subscription_summary
        self._orig_pilot_intake_snapshot = service_state.pilot_intake_snapshot

        service_state.subscriptions_path = lambda org_id=None: self._subs
        service_state.owner_ledger_path = lambda org_id=None: self._owner
        service_state.ledger_path = lambda org_id=None: self._ledger
        service_state.ensure_subscription_aliases = lambda org_id=None: {
            'subscriptions': self._subs,
            'subscriptions_backup': self._subs + '.bak',
            'subscriptions_lock': self._subs + '.lock',
            'canonical_source': 'capsule_file',
            'canonical_service_module': 'company.meridian_platform.subscription_service',
            'compatibility_mode': 'compatibility_alias',
            'compatibility_module': 'company.subscriptions',
            'canonical_paths': {
                'subscriptions': self._subs,
                'subscriptions_backup': self._subs + '.bak',
                'subscriptions_lock': self._subs + '.lock',
            },
            'compatibility_paths': {
                'subscriptions': os.path.join(self._tmp, 'company', 'subscriptions.json'),
                'subscriptions_backup': os.path.join(self._tmp, 'company', 'subscriptions.json.bak'),
                'subscriptions_lock': os.path.join(self._tmp, 'company', '.subscriptions.lock'),
            },
            'legacy_paths': {
                'subscriptions': os.path.join(self._tmp, 'company', 'subscriptions.json'),
                'subscriptions_backup': os.path.join(self._tmp, 'company', 'subscriptions.json.bak'),
                'subscriptions_lock': os.path.join(self._tmp, 'company', '.subscriptions.lock'),
            },
        }
        service_state.ensure_accounting_aliases = lambda org_id=None: {
            'owner_ledger': self._owner,
            'canonical_source': 'capsule_file',
            'canonical_service_module': 'company.meridian_platform.accounting_service',
            'compatibility_mode': 'compatibility_alias',
            'compatibility_module': 'company.accounting',
            'canonical_paths': {
                'owner_ledger': self._owner,
            },
            'compatibility_paths': {
                'owner_ledger': os.path.join(self._tmp, 'company', 'owner_ledger.json'),
            },
            'legacy_paths': {
                'owner_ledger': os.path.join(self._tmp, 'company', 'owner_ledger.json'),
            },
        }
        service_state.LEGACY_SUBSCRIPTIONS_FILE = os.path.join(self._tmp, 'company', 'subscriptions.json')
        service_state.LEGACY_OWNER_LEDGER_FILE = os.path.join(self._tmp, 'company', 'owner_ledger.json')
        service_state.WORKSPACE = self._tmp

    def tearDown(self):
        service_state.subscriptions_path = self._orig_subscriptions_path
        service_state.owner_ledger_path = self._orig_owner_ledger_path
        service_state.ledger_path = self._orig_ledger_path
        service_state.ensure_subscription_aliases = self._orig_ensure_subscription_aliases
        service_state.ensure_accounting_aliases = self._orig_ensure_accounting_aliases
        service_state.LEGACY_SUBSCRIPTIONS_FILE = self._orig_legacy_subscriptions
        service_state.LEGACY_OWNER_LEDGER_FILE = self._orig_legacy_owner
        service_state.WORKSPACE = self._orig_workspace
        service_state.subscription_service.subscription_summary = self._orig_subscription_summary
        service_state.pilot_intake_snapshot = self._orig_pilot_intake_snapshot
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_subscription_snapshot_reports_canonical_summary(self):
        with open(self._subs, 'w') as f:
            json.dump({
                'subscribers': {
                    '100': [
                        {'status': 'active', 'plan': 'trial', 'expires_at': ''},
                        {'status': 'cancelled', 'plan': 'premium-brief-monthly', 'expires_at': ''},
                    ],
                    '200': [
                        {
                            'status': 'active',
                            'plan': 'premium-brief-monthly',
                            'payment_verified': True,
                            'expires_at': '',
                        },
                    ],
                },
                'delivery_log': [{'id': 'd1'}, {'id': 'd2'}],
                '_meta': {
                    'service_scope': 'founding_meridian_service',
                    'bound_org_id': 'org_demo',
                    'internal_test_ids': ['100'],
                },
            }, f, indent=2)

        service_state.subscription_service.subscription_summary = lambda org_id=None: {
            'subscriber_count': 2,
            'subscription_count': 3,
            'active_subscription_count': 2,
            'draft_subscription_count': 1,
            'verified_paid_subscription_count': 1,
            'delivery_log_count': 2,
            'internal_test_id_count': 1,
            'external_target_count': 1,
        }
        with mock.patch.object(service_state.subscription_service, 'loom_delivery_queue_snapshot', return_value={
            'summary': {'total_jobs': 0, 'queued_count': 0, 'claimed_count': 0, 'completed_count': 0, 'blocked_count': 0},
            'queue_paths': {'inspect': '/api/subscriptions/loom-delivery-jobs', 'activation': '/api/subscriptions/activate-from-preview'},
            'delivery_jobs': [],
        }), mock.patch.object(service_state.subscription_service, 'loom_delivery_run_snapshot', return_value={
            'summary': {'total_runs': 0, 'delivered_count': 0, 'running_count': 0, 'executed_count': 0, 'blocked_count': 0, 'queued_count': 0},
            'delivery_runs': [],
        }):
            snap = service_state.subscription_snapshot('org_demo')
        self.assertEqual(snap['bound_org_id'], 'org_demo')
        self.assertEqual(snap['storage_model'], 'capsule_canonical_with_compatibility_alias')
        self.assertEqual(snap['management_mode'], 'institution_owned_service')
        self.assertTrue(snap['mutation_enabled'])
        self.assertEqual(snap['identity_model'], 'session')
        self.assertEqual(snap['meta']['service_scope'], 'institution_owned_subscription_service')
        self.assertEqual(snap['meta']['boundary_name'], 'subscriptions')
        self.assertEqual(snap['canonical_source'], 'service_module')
        self.assertEqual(
            snap['canonical_service_module'],
            'company.meridian_platform.subscription_service',
        )
        self.assertEqual(snap['canonical_path'], 'subscriptions.json')
        self.assertEqual(snap['compatibility_path_role'], 'compatibility_symlink')
        self.assertEqual(snap['compatibility_path'], 'company/subscriptions.json')
        self.assertEqual(snap['compatibility_module'], 'company.subscriptions')
        self.assertEqual(snap['compatibility_mode'], 'compatibility_alias')
        self.assertEqual(snap['alias_registry']['canonical_source'], 'capsule_file')
        self.assertEqual(
            snap['alias_registry']['canonical_paths']['subscriptions'],
            'subscriptions.json',
        )
        self.assertEqual(
            snap['alias_registry']['compatibility_paths']['subscriptions'],
            'company/subscriptions.json',
        )
        self.assertEqual(snap['alias_registry']['compatibility_mode'], 'compatibility_alias')
        self.assertIn('/api/subscriptions/add', snap['mutation_paths'])
        self.assertIn('/api/subscriptions/draft-from-preview', snap['mutation_paths'])
        self.assertIn('/api/subscriptions/activate-from-preview', snap['mutation_paths'])
        self.assertIn('/api/subscriptions/convert', snap['mutation_paths'])
        self.assertIn('/api/subscriptions/verify-payment', snap['mutation_paths'])
        self.assertIn('/api/subscriptions/remove', snap['mutation_paths'])
        self.assertEqual(snap['summary']['subscriber_count'], 2)
        self.assertEqual(snap['summary']['subscription_count'], 3)
        self.assertEqual(snap['summary']['active_subscription_count'], 2)
        self.assertEqual(snap['summary']['draft_subscription_count'], 1)
        self.assertEqual(snap['summary']['verified_paid_subscription_count'], 1)
        self.assertEqual(snap['summary']['delivery_log_count'], 2)
        self.assertEqual(snap['summary']['internal_test_id_count'], 1)
        self.assertEqual(snap['summary']['external_target_count'], 1)
        self.assertEqual(snap['loom_delivery_queue_summary']['total_jobs'], 0)
        self.assertEqual(snap['loom_delivery_queue_paths']['inspect'], '/api/subscriptions/loom-delivery-jobs')
        self.assertEqual(snap['loom_delivery_run_summary']['total_runs'], 0)

    def test_accounting_snapshot_reports_owner_summary(self):
        with open(self._owner, 'w') as f:
            json.dump({
                'owner': 'Son Nguyen The',
                'capital_contributed_usd': 2.0,
                'expenses_paid_usd': 1.25,
                'reimbursements_received_usd': 0.5,
                'draws_taken_usd': 0.25,
                'entries': [{'type': 'capital_contribution'}],
                '_meta': {
                    'service_scope': 'founding_meridian_service',
                    'bound_org_id': 'org_demo',
                },
            }, f, indent=2)

        snap = service_state.accounting_snapshot('org_demo')
        self.assertEqual(snap['bound_org_id'], 'org_demo')
        self.assertEqual(snap['storage_model'], 'capsule_owned_owner_ledger')
        self.assertEqual(snap['management_mode'], 'institution_owned_service')
        self.assertTrue(snap['mutation_enabled'])
        self.assertEqual(snap['identity_model'], 'session')
        self.assertEqual(snap['meta']['service_scope'], 'institution_owned_service')
        self.assertEqual(snap['canonical_source'], 'service_module')
        self.assertEqual(
            snap['canonical_service_module'],
            'company.meridian_platform.accounting_service',
        )
        self.assertEqual(snap['canonical_path'], 'owner_ledger.json')
        self.assertEqual(snap['compatibility_path_role'], 'compatibility_symlink')
        self.assertEqual(snap['compatibility_path'], 'company/owner_ledger.json')
        self.assertEqual(snap['compatibility_module'], 'company.accounting')
        self.assertEqual(snap['compatibility_mode'], 'compatibility_alias')
        self.assertEqual(snap['alias_registry']['canonical_source'], 'capsule_file')
        self.assertEqual(
            snap['alias_registry']['canonical_paths']['owner_ledger'],
            'owner_ledger.json',
        )
        self.assertEqual(
            snap['alias_registry']['compatibility_paths']['owner_ledger'],
            'company/owner_ledger.json',
        )
        self.assertEqual(snap['alias_registry']['compatibility_mode'], 'compatibility_alias')
        self.assertIn('/api/accounting/expense', snap['mutation_paths'])
        self.assertEqual(snap['summary']['capital_contributed_usd'], 2.0)
        self.assertEqual(snap['summary']['expenses_paid_usd'], 1.25)
        self.assertEqual(snap['summary']['reimbursements_received_usd'], 0.5)
        self.assertEqual(snap['summary']['draws_taken_usd'], 0.25)
        self.assertEqual(snap['summary']['unreimbursed_expenses_usd'], 0.75)
        self.assertEqual(snap['summary']['entry_count'], 1)


    def test_subscription_preview_snapshot_reports_review_queue(self):
        with mock.patch.object(service_state.subscription_preview_queue, 'subscription_preview_queue_snapshot', return_value={
            'bound_org_id': 'org_demo',
            'management_mode': 'manual_subscription_preview_queue',
            'mutation_enabled': True,
            'mutation_disabled_reason': '',
            'service_scope': 'institution_owned_subscription_preview_queue',
            'boundary_name': 'subscription_preview_queue',
            'identity_model': 'operator_review',
            'storage_model': 'capsule_canonical',
            'queue_paths': {
                'inspect': '/api/subscriptions/preview-queue',
                'source_review': '/api/pilot/intake/operator/review',
                'checkout_capture': '/api/subscriptions/checkout-capture',
            },
            'summary': {
                'bound_org_id': 'org_demo',
                'total_previews': 1,
                'previewed_count': 0,
                'reviewed_count': 1,
                'dismissed_count': 0,
                'superseded_count': 0,
                'checkout_claimed_count': 0,
                'latest_preview_at': '2026-03-25T00:00:00Z',
                'state_counts': {'previewed': 0, 'reviewed': 1, 'dismissed': 0, 'superseded': 0},
            },
            'subscription_previews': [{
                'preview_id': 'quote_pir_demo',
                'pilot_request_id': 'pir_demo',
                'state': 'reviewed',
                'checkout_claimed': False,
                'payment_capture_claimed': False,
                'fulfillment_claimed': False,
                'plan_options': [],
            }],
            'meta': {'boundary_name': 'subscription_preview_queue'},
        }):
            snap = service_state.subscription_preview_snapshot('org_demo')

        self.assertEqual(snap['bound_org_id'], 'org_demo')
        self.assertEqual(snap['management_mode'], 'manual_subscription_preview_queue')
        self.assertEqual(snap['boundary_name'], 'subscription_preview_queue')
        self.assertEqual(snap['queue_paths']['inspect'], '/api/subscriptions/preview-queue')
        self.assertEqual(snap['queue_paths']['checkout_capture'], '/api/subscriptions/checkout-capture')
        self.assertEqual(snap['summary']['total_previews'], 1)
        self.assertEqual(len(snap['preview_tail']), 1)

    def test_pilot_intake_snapshot_reports_request_queue(self):
        service_state.pilot_intake_snapshot = lambda org_id=None: {
            'bound_org_id': org_id,
            'management_mode': 'manual_pilot_intake',
            'mutation_enabled': True,
            'mutation_disabled_reason': '',
            'service_scope': 'manual_pilot_intake',
            'boundary_name': 'pilot_intake',
            'identity_model': 'public_submission',
            'storage_model': 'capsule_canonical',
            'request_paths': {
                'submit': '/api/pilot/intake',
                'inspect': '/api/pilot/intake',
                'operator_inspect': '/api/pilot/intake/operator',
                'operator_review': '/api/pilot/intake/operator/review',
            },
            'summary': {
                'bound_org_id': org_id,
                'total_requests': 1,
                'requested_count': 1,
                'reviewed_count': 0,
                'contacted_count': 0,
                'closed_count': 0,
                'contactable_count': 1,
                'latest_request_at': '2026-03-25T00:00:00Z',
                'status_counts': {'requested': 1, 'reviewed': 0, 'contacted': 0, 'closed': 0},
            },
            'requests_tail': [{
                'request_id': 'pir_demo',
                'name': 'Jane Doe',
                'company': 'Acme',
                'status': 'requested',
            }],
            'meta': {'boundary_name': 'pilot_intake'},
        }
        snap = service_state.pilot_intake_snapshot('org_demo')
        self.assertEqual(snap['bound_org_id'], 'org_demo')
        self.assertEqual(snap['management_mode'], 'manual_pilot_intake')
        self.assertTrue(snap['mutation_enabled'])
        self.assertEqual(snap['identity_model'], 'public_submission')
        self.assertEqual(snap['request_paths']['submit'], '/api/pilot/intake')
        self.assertEqual(snap['request_paths']['operator_inspect'], '/api/pilot/intake/operator')
        self.assertEqual(snap['summary']['total_requests'], 1)
        self.assertEqual(snap['requests_tail'][0]['request_id'], 'pir_demo')

    def test_accounting_snapshot_backfills_owner_capital_from_treasury(self):
        with open(self._owner, 'w') as f:
            json.dump({
                'capital_contributed_usd': 0.0,
                'expenses_paid_usd': 0.0,
                'reimbursements_received_usd': 0.0,
                'draws_taken_usd': 0.0,
                'entries': [],
                '_meta': {'bound_org_id': 'org_demo'},
            }, f, indent=2)
        with open(self._ledger, 'w') as f:
            json.dump({
                'treasury': {
                    'owner_capital_contributed_usd': 2.0,
                }
            }, f, indent=2)

        snap = service_state.accounting_snapshot('org_demo')

        self.assertEqual(snap['summary']['capital_contributed_usd'], 2.0)
        self.assertEqual(snap['management_mode'], 'institution_owned_service')
        self.assertTrue(snap['meta']['capital_sync_backfilled'])
        self.assertEqual(snap['meta']['capital_sync_source'], 'treasury_ledger')

        with open(self._owner) as f:
            saved = json.load(f)
        self.assertEqual(saved['capital_contributed_usd'], 2.0)
        self.assertEqual(saved['entries'][-1]['type'], 'capital_contribution_backfill')


if __name__ == '__main__':
    unittest.main()
