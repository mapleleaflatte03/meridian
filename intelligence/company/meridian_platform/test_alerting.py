#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest
from unittest import mock


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

import alerting
import observability_store


class AlertingTests(unittest.TestCase):
    def test_record_slo_alerts_persists_transition_and_dedupes_repeated_snapshots(self):
        evaluation = {
            'policy_name': 'meridian_observability_slo_v1',
            'evaluated_at': '2026-03-25T00:30:00Z',
            'status': 'warning',
            'objectives': [
                {
                    'name': 'audit_freshness',
                    'status': 'warning',
                    'message': 'Latest sample age is 7200s',
                    'metric': 'audit.latest_at',
                    'warning_after_seconds': 3600,
                    'breach_after_seconds': 86400,
                    'observed_seconds': 7200,
                },
                {
                    'name': 'metering_freshness',
                    'status': 'healthy',
                    'message': 'Latest sample age is 60s',
                    'metric': 'metering.latest_at',
                    'warning_after_seconds': 3600,
                    'breach_after_seconds': 86400,
                    'observed_seconds': 60,
                },
            ],
            'alerts': [
                {
                    'objective': 'audit_freshness',
                    'status': 'warning',
                    'message': 'Latest sample age is 7200s',
                },
            ],
            'alert_count': 1,
        }

        with tempfile.TemporaryDirectory() as tmp:
            alert_path = os.path.join(tmp, 'slo_alert_log.jsonl')
            with (
                mock.patch.object(alerting, 'ALERT_LOG_FILE', alert_path),
                mock.patch.object(alerting, '_now', return_value='2026-03-25T00:30:00Z'),
            ):
                first = alerting.record_slo_alerts(evaluation, org_id='org_demo')
                second = alerting.record_slo_alerts(evaluation, org_id='org_demo')

            events = observability_store.query_slo_alert_events(alert_path, org_id='org_demo')
            deliveries = observability_store.query_slo_alert_deliveries(alert_path, org_id='org_demo')
            state = observability_store.get_slo_alert_state(
                alert_path,
                org_id='org_demo',
                policy_name='meridian_observability_slo_v1',
                objective='audit_freshness',
            )

        self.assertEqual(first['event_count'], 1)
        self.assertEqual(first['delivery_count'], 1)
        self.assertEqual(second['event_count'], 0)
        self.assertEqual(second['delivery_count'], 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['state_change'], 'opened')
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]['status'], 'hook_returned_none')
        self.assertFalse(deliveries[0]['delivered'])
        self.assertEqual(state['current_status'], 'warning')

    def test_record_slo_alerts_uses_hook_result_truthfully(self):
        evaluation = {
            'policy_name': 'meridian_observability_slo_v1',
            'evaluated_at': '2026-03-25T00:30:00Z',
            'status': 'breached',
            'objectives': [
                {
                    'name': 'monthly_metering_cost',
                    'status': 'breached',
                    'message': 'Monthly cost over threshold',
                    'metric': 'metering.total_cost_usd',
                    'warning_at_usd': 80.0,
                    'breach_at_usd': 100.0,
                    'observed_usd': 120.0,
                },
            ],
            'alerts': [
                {
                    'objective': 'monthly_metering_cost',
                    'status': 'breached',
                    'message': 'Monthly cost over threshold',
                },
            ],
            'alert_count': 1,
        }

        def hook(event):
            return {
                'status': 'delivered',
                'channel': 'test-hook',
                'alert_event_id': event['id'],
            }

        with tempfile.TemporaryDirectory() as tmp:
            alert_path = os.path.join(tmp, 'slo_alert_log.jsonl')
            with (
                mock.patch.object(alerting, 'ALERT_LOG_FILE', alert_path),
                mock.patch.object(alerting, '_now', return_value='2026-03-25T00:30:00Z'),
            ):
                result = alerting.record_slo_alerts(
                    evaluation,
                    org_id='org_demo',
                    delivery_hook=hook,
                    hook_name='test_hook',
                )

            deliveries = observability_store.query_slo_alert_deliveries(alert_path, org_id='org_demo')

        self.assertEqual(result['event_count'], 1)
        self.assertEqual(result['delivery_count'], 1)
        self.assertEqual(result['hook']['name'], 'test_hook')
        self.assertEqual(deliveries[0]['status'], 'delivered')
        self.assertTrue(deliveries[0]['delivered'])
        self.assertEqual(deliveries[0]['details']['hook_response']['channel'], 'test-hook')

    def test_record_slo_alerts_dry_run_persists_queue_without_invoking_hook(self):
        evaluation = {
            'policy_name': 'meridian_observability_slo_v1',
            'evaluated_at': '2026-03-25T00:45:00Z',
            'status': 'warning',
            'objectives': [
                {
                    'name': 'audit_freshness',
                    'status': 'warning',
                    'message': 'Latest sample age is 7200s',
                    'metric': 'audit.latest_at',
                    'warning_after_seconds': 3600,
                    'breach_after_seconds': 86400,
                    'observed_seconds': 7200,
                },
            ],
            'alerts': [
                {
                    'objective': 'audit_freshness',
                    'status': 'warning',
                    'message': 'Latest sample age is 7200s',
                },
            ],
            'alert_count': 1,
        }
        called = []

        def hook(event):
            called.append(event)
            return {'status': 'delivered'}

        with tempfile.TemporaryDirectory() as tmp:
            alert_path = os.path.join(tmp, 'slo_alert_log.jsonl')
            with (
                mock.patch.object(alerting, 'ALERT_LOG_FILE', alert_path),
                mock.patch.object(alerting, '_now', return_value='2026-03-25T00:45:00Z'),
            ):
                result = alerting.record_slo_alerts(
                    evaluation,
                    org_id='org_demo',
                    delivery_hook=hook,
                    hook_name='test_hook',
                    dry_run=True,
                )
                queue = alerting.alert_queue_snapshot('org_demo')

            deliveries = observability_store.query_slo_alert_deliveries(alert_path, org_id='org_demo')

        self.assertEqual(called, [])
        self.assertEqual(result['delivery_mode'], 'dry_run')
        self.assertEqual(result['hook']['dry_run'], True)
        self.assertEqual(result['delivery_count'], 1)
        self.assertEqual(deliveries[0]['status'], 'dry_run')
        self.assertFalse(deliveries[0]['delivered'])
        self.assertEqual(queue['queue_count'], 1)
        self.assertEqual(queue['pending_delivery_count'], 1)
        self.assertEqual(queue['queue'][0]['delivery_state'], 'dry_run')
        self.assertEqual(queue['queue'][0]['event']['objective'], 'audit_freshness')

    def test_dispatch_queued_alerts_acknowledges_pending_queue_without_claiming_delivery(self):
        evaluation = {
            'policy_name': 'meridian_observability_slo_v1',
            'evaluated_at': '2026-03-25T01:00:00Z',
            'status': 'warning',
            'objectives': [
                {
                    'name': 'audit_freshness',
                    'status': 'warning',
                    'message': 'Latest sample age is 7200s',
                    'metric': 'audit.latest_at',
                    'warning_after_seconds': 3600,
                    'breach_after_seconds': 86400,
                    'observed_seconds': 7200,
                },
            ],
            'alerts': [
                {
                    'objective': 'audit_freshness',
                    'status': 'warning',
                    'message': 'Latest sample age is 7200s',
                },
            ],
            'alert_count': 1,
        }

        with tempfile.TemporaryDirectory() as tmp:
            alert_path = os.path.join(tmp, 'slo_alert_log.jsonl')
            with (
                mock.patch.object(alerting, 'ALERT_LOG_FILE', alert_path),
                mock.patch.object(alerting, '_now', return_value='2026-03-25T01:00:00Z'),
            ):
                alerting.record_slo_alerts(evaluation, org_id='org_demo')
                result = alerting.dispatch_queued_alerts('org_demo')
                queue = alerting.alert_queue_snapshot('org_demo')

            dispatches = observability_store.query_slo_alert_dispatches(alert_path, org_id='org_demo')

        self.assertEqual(result['dispatch_mode'], 'inspect_only')
        self.assertEqual(result['dispatched_count'], 1)
        self.assertEqual(result['acknowledged_count'], 1)
        self.assertEqual(result['pending_delivery_count'], 1)
        self.assertEqual(len(dispatches), 1)
        self.assertEqual(dispatches[0]['status'], 'acknowledged_pending')
        self.assertTrue(dispatches[0]['acknowledged'])
        self.assertEqual(queue['queue_count'], 1)
        self.assertEqual(queue['pending_delivery_count'], 1)
        self.assertEqual(queue['acknowledged_count'], 1)
        self.assertEqual(queue['queue'][0]['dispatch_state'], 'acknowledged_pending')
        self.assertEqual(queue['queue'][0]['dispatch_attempt_count'], 1)

    def test_alert_queue_ignores_historical_active_events_after_resolution(self):
        warning_evaluation = {
            'policy_name': 'meridian_observability_slo_v1',
            'evaluated_at': '2026-03-25T01:00:00Z',
            'status': 'warning',
            'objectives': [
                {
                    'name': 'audit_freshness',
                    'status': 'warning',
                    'message': 'Latest sample age is 7200s',
                    'metric': 'audit.latest_at',
                    'warning_after_seconds': 3600,
                    'breach_after_seconds': 86400,
                    'observed_seconds': 7200,
                },
            ],
            'alerts': [
                {
                    'objective': 'audit_freshness',
                    'status': 'warning',
                    'message': 'Latest sample age is 7200s',
                },
            ],
            'alert_count': 1,
        }
        healthy_evaluation = {
            'policy_name': 'meridian_observability_slo_v1',
            'evaluated_at': '2026-03-25T01:05:00Z',
            'status': 'healthy',
            'objectives': [
                {
                    'name': 'audit_freshness',
                    'status': 'healthy',
                    'message': 'Latest sample age is 60s',
                    'metric': 'audit.latest_at',
                    'warning_after_seconds': 3600,
                    'breach_after_seconds': 86400,
                    'observed_seconds': 60,
                },
            ],
            'alerts': [],
            'alert_count': 0,
        }

        with tempfile.TemporaryDirectory() as tmp:
            alert_path = os.path.join(tmp, 'slo_alert_log.jsonl')
            with mock.patch.object(alerting, 'ALERT_LOG_FILE', alert_path):
                alerting.record_slo_alerts(warning_evaluation, org_id='org_demo')
                alerting.record_slo_alerts(healthy_evaluation, org_id='org_demo')
                queue = alerting.alert_queue_snapshot('org_demo')
                surface = alerting.alert_surface_snapshot('org_demo')

        self.assertEqual(queue['queue_count'], 0)
        self.assertEqual(queue['pending_delivery_count'], 0)
        self.assertEqual(surface['active_alert_count'], 0)
        self.assertEqual(surface['queue_count'], 0)


if __name__ == '__main__':
    unittest.main()
