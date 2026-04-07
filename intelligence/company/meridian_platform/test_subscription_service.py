#!/usr/bin/env python3
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import subscription_service


class SubscriptionServiceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='subscription-service-')
        self._subs = os.path.join(self._tmp, 'subscriptions.json')
        self._backup = os.path.join(self._tmp, 'subscriptions.json.bak')
        self._lock = os.path.join(self._tmp, '.subscriptions.lock')
        self._tx = os.path.join(self._tmp, 'transactions.jsonl')
        self.org_id = 'org_demo'

        with open(self._subs, 'w') as f:
            json.dump(subscription_service._default_subscriptions(self.org_id), f, indent=2)
        with open(self._backup, 'w') as f:
            json.dump(subscription_service._default_subscriptions(self.org_id), f, indent=2)
        with open(self._lock, 'w') as f:
            f.write('')
        with open(self._tx, 'w') as f:
            f.write('')

        self._orig_primary = subscription_service.subscriptions_path
        self._orig_backup = subscription_service.subscriptions_backup_path
        self._orig_lock = subscription_service.subscriptions_lock_path
        self._orig_ensure_aliases = subscription_service.ensure_subscription_aliases
        self._orig_load_transactions = subscription_service._revenue_mod.load_transactions

        subscription_service.subscriptions_path = lambda org_id=None: self._subs
        subscription_service.subscriptions_backup_path = lambda org_id=None: self._backup
        subscription_service.subscriptions_lock_path = lambda org_id=None: self._lock
        subscription_service.ensure_subscription_aliases = lambda org_id=None: None

        def _load_transactions():
            with open(self._tx) as f:
                return [
                    json.loads(line)
                    for line in f
                    if line.strip()
                ]

        subscription_service._revenue_mod.load_transactions = _load_transactions

    def tearDown(self):
        subscription_service.subscriptions_path = self._orig_primary
        subscription_service.subscriptions_backup_path = self._orig_backup
        subscription_service.subscriptions_lock_path = self._orig_lock
        subscription_service.ensure_subscription_aliases = self._orig_ensure_aliases
        subscription_service._revenue_mod.load_transactions = self._orig_load_transactions
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _append_tx(self, entry):
        with open(self._tx, 'a') as f:
            f.write(json.dumps(entry) + '\n')

    def test_default_and_normalized_meta_include_storage_and_identity(self):
        default_payload = subscription_service._default_subscriptions(self.org_id)
        self.assertEqual(default_payload['_meta']['service_scope'], 'institution_owned_subscription_service')
        self.assertEqual(default_payload['_meta']['boundary_name'], 'subscriptions')
        self.assertEqual(default_payload['_meta']['identity_model'], 'session')
        self.assertEqual(default_payload['_meta']['storage_model'], 'capsule_canonical_with_compatibility_alias')
        self.assertEqual(default_payload['_meta']['bound_org_id'], self.org_id)
        self.assertEqual(default_payload['loom_delivery_jobs'], {})
        self.assertEqual(default_payload['loom_delivery_runs'], [])

        normalized = subscription_service._normalize_subscriptions(
            {
                'subscribers': {},
                '_meta': {'bound_org_id': 'org_existing'},
            },
            self.org_id,
        )
        self.assertEqual(normalized['_meta']['service_scope'], 'institution_owned_subscription_service')
        self.assertEqual(normalized['_meta']['boundary_name'], 'subscriptions')
        self.assertEqual(normalized['_meta']['identity_model'], 'session')
        self.assertEqual(normalized['_meta']['storage_model'], 'capsule_canonical_with_compatibility_alias')
        self.assertEqual(normalized['_meta']['bound_org_id'], self.org_id)
        self.assertEqual(normalized['loom_delivery_jobs'], {})
        self.assertEqual(normalized['loom_delivery_runs'], [])

    def test_institution_license_catalog_internal_still_returns_valid_structure(self):
        """Internal catalog function preserved for backward compat; gateway returns 410."""
        catalog = subscription_service.institution_license_catalog()
        self.assertEqual(catalog['schema_version'], 'meridian.institution_license_catalog.v1')
        self.assertEqual(catalog['default_plan'], subscription_service.INSTITUTION_LICENSE_DEFAULT_PLAN)
        self.assertEqual(catalog['checkout_capture_path'], '/api/institution/license/checkout-capture')
        self.assertGreaterEqual(len(catalog['plans']), 2)
        default_plan = next(
            plan for plan in catalog['plans']
            if plan['plan'] == subscription_service.INSTITUTION_LICENSE_DEFAULT_PLAN
        )
        self.assertGreater(default_plan['price_usd'], 0)
        self.assertGreater(default_plan['revenue_share_pct'], 0)

    def test_capture_institution_license_checkout_internal_is_idempotent_for_binding_event(self):
        """Internal function preserved for ledger continuity; gateway returns 410."""
        payment_ref = '0xinstlicense01'
        tx_hash = '0x' + ('ab' * 32)
        settlement = {
            'mode': 'verified_base_usdc_recorded',
            'payment_ref': payment_ref,
            'tx_hash': tx_hash,
            'evidence': {
                'order_id': 'ord_inst_license',
                'payment_ref': payment_ref,
                'tx_hash': tx_hash,
                'amount': 299.0,
            },
        }

        with mock.patch.object(
            subscription_service,
            'ensure_base_usdc_customer_payment',
            return_value=settlement,
        ), mock.patch.object(
            subscription_service._revenue_mod,
            'append_tx',
            side_effect=lambda entry: self._append_tx(entry),
        ):
            first = subscription_service.capture_institution_license_checkout(
                plan_name=subscription_service.INSTITUTION_LICENSE_DEFAULT_PLAN,
                payment_ref=payment_ref,
                tx_hash=tx_hash,
                institution_name='Acme Ops',
                buyer_name='Jane',
                buyer_contact='jane@example.com',
                org_id=self.org_id,
            )
            second = subscription_service.capture_institution_license_checkout(
                plan_name=subscription_service.INSTITUTION_LICENSE_DEFAULT_PLAN,
                payment_ref=payment_ref,
                tx_hash=tx_hash,
                institution_name='Acme Ops',
                buyer_name='Jane',
                buyer_contact='jane@example.com',
                org_id=self.org_id,
            )

        self.assertEqual(first['license_id'], second['license_id'])
        self.assertEqual(first['order_id'], 'ord_inst_license')
        self.assertEqual(first['plan'], subscription_service.INSTITUTION_LICENSE_DEFAULT_PLAN)
        self.assertGreater(first['revenue_share_pct'], 0.0)

        events = [
            row for row in subscription_service._revenue_mod.load_transactions()
            if row.get('type') == 'institution_license_binding'
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].get('payment_ref'), payment_ref)

    def test_create_trial_subscription_returns_active_record(self):
        result = subscription_service.create_subscription(
            '100',
            plan='trial',
            org_id=self.org_id,
            actor='user:owner',
        )
        subscription = result['subscription']
        self.assertEqual(result['telegram_id'], '100')
        self.assertEqual(subscription['plan'], 'trial')
        self.assertTrue(subscription['payment_verified'])
        self.assertEqual(subscription['created_by'], 'user:owner')
        self.assertEqual(
            subscription_service.load_subscriptions(self.org_id)['_meta']['service_scope'],
            'institution_owned_subscription_service',
        )

    def test_create_draft_subscription_from_preview_records_a_draft_only(self):
        preview = {
            'preview_id': 'quote_pir_draft',
            'pilot_request_id': 'pir_draft',
            'name': 'Jane Doe',
            'company': 'Acme',
            'email': 'jane@example.com',
            'telegram_handle': '@jane',
            'requested_cadence': 'Weekly brief',
            'requested_offer': 'manual_pilot',
            'review_note': 'Draft the continuation offer without checkout claims',
            'preview_truth_source': 'pilot_intake_review_and_published_plan_table_only',
            'state': 'reviewed',
            'plan_options': [
                {
                    'plan': 'premium-brief-weekly',
                    'price_usd': 2.99,
                    'duration_days': 7,
                    'billing_type': 'recurring',
                },
            ],
        }

        result = subscription_service.create_draft_subscription_from_preview(
            preview,
            org_id=self.org_id,
            actor='user:owner',
        )

        draft = result['draft_subscription']
        summary = subscription_service.subscription_summary(self.org_id)
        payload = subscription_service.load_subscriptions(self.org_id)

        self.assertEqual(result['preview_id'], 'quote_pir_draft')
        self.assertEqual(draft['draft_id'], 'draft_quote_pir_draft')
        self.assertEqual(draft['status'], 'draft')
        self.assertFalse(draft['payment_verified'])
        self.assertEqual(payload['draft_subscriptions']['draft_quote_pir_draft']['preview_id'], 'quote_pir_draft')
        self.assertEqual(summary['draft_subscription_count'], 1)
        self.assertEqual(summary['subscriber_count'], 0)
        self.assertEqual(summary['active_subscription_count'], 0)

    def test_activate_subscription_from_preview_queues_loom_delivery(self):
        preview = {
            'preview_id': 'quote_pir_activate',
            'pilot_request_id': 'pir_activate',
            'name': 'Jane Doe',
            'company': 'Acme',
            'email': 'jane@example.com',
            'telegram_handle': '800',
            'requested_cadence': 'Weekly brief',
            'requested_offer': 'manual_pilot',
            'review_note': 'Activate after captured payment',
            'preview_truth_source': 'pilot_intake_review_and_published_plan_table_only',
            'state': 'reviewed',
            'plan_options': [
                {
                    'plan': 'premium-brief-weekly',
                    'price_usd': 2.99,
                    'duration_days': 7,
                    'billing_type': 'recurring',
                },
            ],
        }

        self._append_tx({
            'type': 'customer_payment',
            'order_id': 'ord-activate',
            'amount': 2.99,
            'client': 'cust-activate',
            'product': 'pilot-weekly',
            'payment_key': 'ref:ref-activate',
            'payment_ref': 'ref-activate',
            'tx_hash': '0xactivate',
            'ts': subscription_service.now_ts(),
        })

        with mock.patch.object(subscription_service, 'run_loom_delivery_job', return_value={
            'job_id': 'loom_sub_activated',
            'delivery_job': {
                'job_id': 'loom_sub_activated',
                'state': 'executing',
                'delivery_status': 'running',
            },
            'run': {
                'run_id': 'ldr_sub_activated',
                'job_id': 'loom_sub_activated',
                'state': 'executed',
                'delivery_status': 'delivered',
                'delivered': True,
                'delivery_ref': 'loom_sub_activated',
            },
            'execution': {'ok': True, 'job_id': 'loom_sub_activated'},
        }):
            result = subscription_service.activate_subscription_from_preview(
                preview,
                telegram_id='800',
                plan='premium-brief-weekly',
                payment_ref='ref-activate',
                org_id=self.org_id,
                actor='user:admin',
            )

        subscription = result['subscription']
        payload = subscription_service.load_subscriptions(self.org_id)
        queue_snapshot = subscription_service.loom_delivery_queue_snapshot(self.org_id)

        self.assertEqual(result['preview_id'], 'quote_pir_activate')
        self.assertEqual(result['telegram_id'], '800')
        self.assertEqual(subscription['plan'], 'premium-brief-weekly')
        self.assertEqual(subscription['status'], 'active')
        self.assertTrue(subscription['payment_verified'])
        self.assertEqual(subscription['activated_from_preview_id'], 'quote_pir_activate')
        self.assertEqual(payload['loom_delivery_jobs']['loom_%s' % subscription['id']]['state'], 'queued')
        self.assertEqual(result['delivery_run']['state'], 'executed')
        self.assertEqual(subscription_service.active_delivery_targets(self.org_id), ['800'])
        self.assertEqual(queue_snapshot['summary']['total_jobs'], 1)
        self.assertEqual(queue_snapshot['summary']['queued_count'], 1)
        self.assertEqual(queue_snapshot['delivery_jobs'][0]['subscription_id'], subscription['id'])

    def test_capture_subscription_from_preview_requires_explicit_payment_evidence(self):
        preview = {
            'preview_id': 'quote_pir_checkout',
            'pilot_request_id': 'pir_checkout',
            'name': 'Jane Doe',
            'company': 'Acme',
            'email': 'jane@example.com',
            'telegram_handle': '800',
            'requested_cadence': 'Weekly brief',
            'requested_offer': 'manual_pilot',
            'review_note': 'Customer-initiated checkout capture',
            'preview_truth_source': 'pilot_intake_review_and_published_plan_table_only',
            'state': 'reviewed',
            'plan_options': [
                {
                    'plan': 'premium-brief-weekly',
                    'price_usd': 2.99,
                    'duration_days': 7,
                    'billing_type': 'recurring',
                },
            ],
        }

        self._append_tx({
            'type': 'customer_payment',
            'order_id': 'ord-checkout',
            'amount': 2.99,
            'client': 'cust-checkout',
            'product': 'pilot-weekly',
            'payment_key': 'ref:ref-checkout',
            'payment_ref': 'ref-checkout',
            'tx_hash': '0xcheckout',
            'ts': subscription_service.now_ts(),
        })

        with mock.patch.object(subscription_service, 'run_loom_delivery_job', return_value={
            'job_id': 'loom_sub_checkout',
            'delivery_job': {
                'job_id': 'loom_sub_checkout',
                'state': 'executed',
                'delivery_status': 'delivered',
            },
            'run': {
                'run_id': 'ldr_sub_checkout',
                'job_id': 'loom_sub_checkout',
                'state': 'executed',
                'delivery_status': 'delivered',
                'delivered': True,
                'delivery_ref': 'loom_sub_checkout',
            },
            'execution': {'ok': True, 'job_id': 'loom_sub_checkout'},
        }):
            result = subscription_service.capture_subscription_from_preview(
                preview,
                telegram_id='800',
                plan='premium-brief-weekly',
                payment_ref='ref-checkout',
                payment_evidence={
                    'order_id': 'ord-checkout',
                    'payment_key': 'ref:ref-checkout',
                    'payment_ref': 'ref-checkout',
                    'tx_hash': '0xcheckout',
                    'amount_usd': 2.99,
                },
                org_id=self.org_id,
                actor='customer:800',
            )

        subscription = result['subscription']
        self.assertEqual(subscription['plan'], 'premium-brief-weekly')
        self.assertTrue(subscription['payment_verified'])
        self.assertEqual(subscription['payment_evidence']['tx_hash'], '0xcheckout')
        self.assertEqual(result['delivery_run']['state'], 'executed')
        self.assertEqual(result['delivery_execution']['ok'], True)
        self.assertEqual(result['delivery_run']['delivery_ref'], 'loom_sub_checkout')

    def test_run_loom_delivery_job_records_executed_run(self):
        payload = subscription_service.load_subscriptions(self.org_id)
        payload['subscribers']['800'] = [{
            'id': 'sub_activated',
            'plan': 'premium-brief-weekly',
            'price_usd': 2.99,
            'started_at': subscription_service.now_ts(),
            'status': 'active',
            'payment_method': 'captured',
            'payment_ref': 'ref-activate',
            'payment_verified': True,
            'payment_verified_at': subscription_service.now_ts(),
            'payment_evidence': {'order_id': 'ord-activate'},
            'email': 'jane@example.com',
            'created_by': 'user:admin',
            'telegram_id': '800',
            'subscriber_id': '800',
            'created_for': '800',
        }]
        payload['loom_delivery_jobs'] = {
            'loom_sub_activated': {
                'job_id': 'loom_sub_activated',
                'subscription_id': 'sub_activated',
                'preview_id': 'quote_pir_activate',
                'telegram_id': '800',
                'company': 'Acme',
                'topics': ['pricing', 'launches'],
                'competitors': ['OpenAI'],
                'plan': 'premium-brief-weekly',
                'state': 'queued',
                'queued_at': '2026-03-25T00:00:00Z',
                'attempts': 0,
            },
        }
        subscription_service.save_subscriptions(payload, self.org_id)

        submitted_payloads = []

        def _run(cmd, capture_output, text, timeout, cwd, env=None):
            if cmd[1:3] == ['service', 'status']:
                return mock.Mock(returncode=0, stdout=json.dumps({'running': True, 'service_status': 'running', 'health': 'healthy', 'transport': 'http'}), stderr='')
            if cmd[1:3] == ['capability', 'show']:
                return mock.Mock(returncode=0, stdout=json.dumps({'enabled': True, 'verification_status': 'verified', 'promotion_state': 'promoted'}), stderr='')
            if cmd[1:3] == ['service', 'submit']:
                submitted_payloads.append(json.loads(cmd[cmd.index('--payload-json') + 1]))
                return mock.Mock(returncode=0, stdout=json.dumps({'job_id': 'loom-job-1'}), stderr='')
            if cmd[1:3] == ['job', 'inspect']:
                return mock.Mock(returncode=0, stdout=json.dumps({'job_status': 'completed', 'job_path': '/tmp/jobs/loom-job-1/job.json', 'worker_status': 'completed'}), stderr='')
            if cmd[1:3] == ['channel', 'send']:
                return mock.Mock(returncode=0, stdout='telegram delivered', stderr='')
            if len(cmd) > 1 and cmd[1].endswith('send_email.py'):
                return mock.Mock(returncode=0, stdout='email delivered', stderr='')
            raise AssertionError(cmd)

        worker_result = {
            'summary': 'fallback summary',
            'skill_output': {'research': 'loom research result'},
        }
        with mock.patch.dict(subscription_service.os.environ, {'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'clawskill.safe-web-research.v0'}, clear=False), mock.patch.object(subscription_service.subprocess, 'run', side_effect=_run), mock.patch.object(subscription_service, '_load_json_file', return_value=worker_result):
            result = subscription_service.run_loom_delivery_job('loom_sub_activated', org_id=self.org_id, actor='user:admin', timeout=5)

        payload = subscription_service.load_subscriptions(self.org_id)
        self.assertEqual(result['run']['state'], 'executed')
        self.assertTrue(result['run']['delivered'])
        self.assertEqual(result['run']['delivery_artifact']['brief_text'], 'loom research result')
        self.assertEqual(result['run']['dispatch_channel'], 'telegram')
        self.assertEqual(len(result['run']['dispatches']), 2)
        self.assertEqual(payload['loom_delivery_jobs']['loom_sub_activated']['state'], 'executed')
        self.assertEqual(payload['loom_delivery_jobs']['loom_sub_activated']['brief_preview'], 'loom research result')
        self.assertEqual(payload['loom_delivery_runs'][0]['state'], 'executed')
        self.assertEqual(payload['loom_delivery_runs'][0]['delivery_ref'], 'loom-job-1')
        self.assertEqual(payload['delivery_log'][-1]['delivery_ref'], 'loom-job-1')
        self.assertEqual(payload['delivery_log'][-1]['dispatch_channel'], 'telegram')
        self.assertEqual(payload['subscribers']['800'][0]['latest_delivery_status'], 'delivered')
        self.assertEqual(payload['subscribers']['800'][0]['latest_delivery_preview'], 'loom research result')
        self.assertEqual(submitted_payloads[0]['topic'], 'Acme pricing launches OpenAI AI market intelligence')
        self.assertEqual(submitted_payloads[0]['url'], 'https://duckduckgo.com/html/?q=Acme+pricing+launches+OpenAI+AI+market+intelligence')
        self.assertIn('Requested cadence', submitted_payloads[0]['prompt'])

    def test_convert_trial_subscription_binds_payment_evidence(self):
        subscription_service.create_subscription('200', plan='trial', org_id=self.org_id)
        self._append_tx({
            'type': 'customer_payment',
            'order_id': 'ord-convert',
            'amount': 2.99,
            'client': 'cust-convert',
            'product': 'pilot-weekly',
            'payment_key': 'ref:ref-convert',
            'payment_ref': 'ref-convert',
            'tx_hash': '0xconvert',
            'ts': subscription_service.now_ts(),
        })

        result = subscription_service.convert_trial_subscription(
            '200',
            'premium-brief-weekly',
            payment_ref='ref-convert',
            confirm_payment=True,
            org_id=self.org_id,
            actor='user:admin',
        )
        subscription = result['subscription']
        self.assertEqual(subscription['plan'], 'premium-brief-weekly')
        self.assertTrue(subscription['payment_verified'])
        self.assertEqual(subscription['payment_evidence']['order_id'], 'ord-convert')
        self.assertTrue(subscription['converted_from_trial'])
        payload = subscription_service.load_subscriptions(self.org_id)
        self.assertEqual(payload['subscribers']['200'][0]['status'], 'converted')
        self.assertEqual(payload['subscribers']['200'][1]['status'], 'active')
        self.assertTrue(payload['subscribers']['200'][1]['converted_from_trial'])

    def test_convert_trial_subscription_requires_active_trial(self):
        subscription_service.create_subscription('205', plan='trial', org_id=self.org_id)
        payload = subscription_service.load_subscriptions(self.org_id)
        payload['subscribers']['205'][0]['status'] = 'cancelled'
        subscription_service.save_subscriptions(payload, self.org_id)

        with self.assertRaisesRegex(LookupError, 'No active trial found'):
            subscription_service.convert_trial_subscription(
                '205',
                'premium-brief-weekly',
                payment_ref='ref-missing',
                confirm_payment=False,
                org_id=self.org_id,
                actor='user:admin',
            )

    def test_check_subscription_and_summary_report_counts(self):
        subscription_service.create_subscription('300', plan='trial', org_id=self.org_id)
        self._append_tx({
            'type': 'customer_payment',
            'order_id': 'ord-summary',
            'amount': 2.99,
            'client': 'cust-summary',
            'product': 'pilot-weekly',
            'payment_key': 'ref:ref-summary',
            'payment_ref': 'ref-summary',
            'tx_hash': '0xsummary',
            'ts': subscription_service.now_ts(),
        })
        subscription_service.create_subscription(
            '301',
            plan='premium-brief-weekly',
            payment_ref='ref-summary',
            confirm_payment=True,
            org_id=self.org_id,
        )

        status = subscription_service.check_subscription('300', org_id=self.org_id)
        summary = subscription_service.subscription_summary(self.org_id)
        self.assertTrue(status['found'])
        self.assertTrue(status['active'])
        self.assertTrue(status['eligible_for_delivery'])
        self.assertEqual(status['subscription_count'], 1)
        self.assertEqual(summary['subscriber_count'], 2)
        self.assertEqual(summary['subscription_count'], 2)
        self.assertEqual(summary['active_subscription_count'], 2)
        self.assertEqual(summary['draft_subscription_count'], 0)
        self.assertEqual(summary['verified_paid_subscription_count'], 1)
        self.assertEqual(summary['external_target_count'], 2)

    def test_verify_subscription_payment_binds_existing_paid_record(self):
        created = subscription_service.create_subscription(
            '300',
            plan='premium-brief-weekly',
            payment_ref='ref-verify',
            org_id=self.org_id,
        )
        self._append_tx({
            'type': 'customer_payment',
            'order_id': 'ord-verify',
            'amount': 2.99,
            'client': 'cust-verify',
            'product': 'pilot-weekly',
            'payment_key': 'ref:ref-verify',
            'payment_ref': 'ref-verify',
            'tx_hash': '0xverify',
            'ts': subscription_service.now_ts(),
        })

        result = subscription_service.verify_subscription_payment(
            '300',
            subscription_id=created['subscription']['id'],
            org_id=self.org_id,
            actor='user:admin',
        )
        subscription = result['subscription']
        self.assertTrue(subscription['payment_verified'])
        self.assertEqual(subscription['payment_evidence']['tx_hash'], '0xverify')
        self.assertEqual(subscription['payment_verified_by'], 'user:admin')

    def test_active_delivery_targets_requires_verified_payment_evidence(self):
        subscription_service.create_subscription(
            '400',
            plan='premium-brief-weekly',
            payment_ref='ref-target',
            org_id=self.org_id,
        )
        self.assertEqual(subscription_service.active_delivery_targets(self.org_id), [])

        self._append_tx({
            'type': 'customer_payment',
            'order_id': 'ord-target',
            'amount': 2.99,
            'client': 'cust-target',
            'product': 'pilot-weekly',
            'payment_key': 'ref:ref-target',
            'payment_ref': 'ref-target',
            'tx_hash': '0xtarget',
            'ts': subscription_service.now_ts(),
        })
        subscription_service.verify_subscription_payment(
            '400',
            payment_ref='ref-target',
            org_id=self.org_id,
            actor='user:admin',
        )
        self.assertEqual(subscription_service.active_delivery_targets(self.org_id), ['400'])

    def test_check_subscription_reports_latest_active_trial(self):
        created = subscription_service.create_subscription(
            '500',
            plan='trial',
            org_id=self.org_id,
            actor='user:owner',
        )

        check = subscription_service.check_subscription('500', org_id=self.org_id)

        self.assertTrue(check['found'])
        self.assertTrue(check['active'])
        self.assertTrue(check['eligible_for_delivery'])
        self.assertEqual(check['subscription_count'], 1)
        self.assertEqual(check['active_count'], 1)
        self.assertEqual(check['latest_subscription']['id'], created['subscription']['id'])

    def test_subscription_summary_tracks_internal_and_external_targets(self):
        subscription_service.create_subscription('600', plan='trial', org_id=self.org_id)
        subscription_service.create_subscription(
            '700',
            plan='premium-brief-weekly',
            payment_ref='ref-summary',
            org_id=self.org_id,
        )
        self._append_tx({
            'type': 'customer_payment',
            'order_id': 'ord-summary',
            'amount': 2.99,
            'client': 'cust-summary',
            'product': 'pilot-weekly',
            'payment_key': 'ref:ref-summary',
            'payment_ref': 'ref-summary',
            'tx_hash': '0xsummary',
            'ts': subscription_service.now_ts(),
        })
        subscription_service.verify_subscription_payment(
            '700',
            payment_ref='ref-summary',
            org_id=self.org_id,
            actor='user:admin',
        )
        payload = subscription_service.load_subscriptions(self.org_id)
        payload['_meta']['internal_test_ids'] = ['600']
        subscription_service.save_subscriptions(payload, self.org_id)

        summary = subscription_service.subscription_summary(self.org_id)

        self.assertEqual(summary['subscriber_count'], 2)
        self.assertEqual(summary['subscription_count'], 2)
        self.assertEqual(summary['active_subscription_count'], 2)
        self.assertEqual(summary['verified_paid_subscription_count'], 1)
        self.assertEqual(summary['internal_test_id_count'], 1)
        self.assertEqual(summary['external_target_count'], 1)


if __name__ == '__main__':
    unittest.main()
