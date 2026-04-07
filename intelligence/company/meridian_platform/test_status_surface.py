#!/usr/bin/env python3
import importlib.util
import datetime
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock


THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

STATUS_PATH = os.path.join(THIS_DIR, 'status_surface.py')
SPEC = importlib.util.spec_from_file_location('meridian_status_surface', STATUS_PATH)
status_surface = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(status_surface)

import alerting
import accounting_store
import audit
import cases_store
import metering
import observability_store
import organizations
import slo_policy


class StatusSurfaceTests(unittest.TestCase):
    def test_persistence_snapshot_exposes_concrete_file_backed_seams(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs_path = os.path.join(tmp, 'organizations.json')
            audit_path = os.path.join(tmp, 'audit_log.jsonl')
            with (
                mock.patch.object(organizations, 'ORGS_FILE', orgs_path),
                mock.patch.object(audit, 'AUDIT_FILE', audit_path),
                mock.patch.object(
                    status_surface,
                    '_safe_capsule_path',
                    side_effect=lambda org_id, filename: os.path.join(tmp, 'capsules', org_id, filename),
                ),
            ):
                snapshot = status_surface.persistence_snapshot('org_founding')

        self.assertEqual(snapshot['backend'], 'file-backed-jsonl')
        self.assertEqual(snapshot['db']['status'], 'absent')
        seam_names = {os.path.basename(seam['path']) for seam in snapshot['seams']}
        seam_owners = {seam['owner'] for seam in snapshot['seams']}
        self.assertIn('audit_log.jsonl', seam_names)
        self.assertIn('metering.jsonl', seam_names)
        self.assertIn('organizations.db', seam_names)
        self.assertIn('accounting.db', seam_names)
        self.assertIn('cases.db', seam_names)
        self.assertIn('pilot_intake.json', seam_names)
        self.assertIn('subscription_preview_queue.json', seam_names)
        self.assertIn('accounting_service.py', seam_owners)
        self.assertIn('accounting_store.py', seam_owners)
        self.assertIn('cases_store.py', seam_owners)
        self.assertIn('pilot_intake.py', seam_owners)
        self.assertIn('subscription_preview_queue.py', seam_owners)

    def test_observability_snapshot_summarizes_file_backed_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = datetime.datetime.utcnow().replace(microsecond=0)
            audit_ts = (now - datetime.timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ')
            metering_ts = (now - datetime.timedelta(minutes=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
            orgs_path = os.path.join(tmp, 'organizations.json')
            audit_path = os.path.join(tmp, 'audit_log.jsonl')
            metering_path = os.path.join(tmp, 'metering.jsonl')
            alert_path = os.path.join(tmp, 'slo_alert_log.jsonl')
            with open(audit_path, 'w') as f:
                f.write(json.dumps({
                    'org_id': 'org_founding',
                    'agent_id': 'agent_main',
                    'action': 'status_check',
                    'outcome': 'success',
                    'timestamp': audit_ts,
                }) + '\n')
            with open(metering_path, 'w') as f:
                f.write(json.dumps({
                    'org_id': 'org_founding',
                    'agent_id': 'agent_main',
                    'metric': 'mcp_tool_call',
                    'quantity': 1,
                    'unit': 'calls',
                    'cost_usd': 1.25,
                    'timestamp': metering_ts,
                }) + '\n')
            with (
                mock.patch.object(organizations, 'ORGS_FILE', orgs_path),
                mock.patch.object(audit, 'AUDIT_FILE', audit_path),
                mock.patch.object(metering, 'METERING_FILE', metering_path),
                mock.patch.object(alerting, 'ALERT_LOG_FILE', alert_path),
                mock.patch.object(status_surface, '_utc_now', return_value=now),
                mock.patch.object(slo_policy, '_now', return_value=now),
            ):
                snapshot = status_surface.observability_snapshot('org_founding')

        self.assertEqual(snapshot['backend'], 'file-backed-jsonl')
        self.assertEqual(snapshot['metrics']['audit']['total_events'], 1)
        self.assertEqual(snapshot['metrics']['metering']['total_cost_usd'], 1.25)
        self.assertEqual(snapshot['slo']['status'], 'healthy')
        self.assertEqual(snapshot['slo']['policy_name'], 'meridian_observability_slo_v1')
        self.assertEqual(snapshot['metrics']['metering']['latest_metric'], 'mcp_tool_call')
        self.assertEqual(snapshot['alerting']['event_count'], 0)
        self.assertEqual(snapshot['alert_log']['event_count'], 0)
        self.assertEqual(snapshot['alert_queue']['queue_count'], 0)

    def test_observability_snapshot_emits_heartbeat_when_feeds_are_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs_path = os.path.join(tmp, 'organizations.json')
            audit_path = os.path.join(tmp, 'audit_log.jsonl')
            metering_path = os.path.join(tmp, 'metering.jsonl')
            alert_path = os.path.join(tmp, 'slo_alert_log.jsonl')
            with open(audit_path, 'w') as f:
                f.write(json.dumps({
                    'org_id': 'org_founding',
                    'agent_id': 'agent_main',
                    'action': 'status_check',
                    'outcome': 'success',
                    'timestamp': '2026-03-24T20:00:00Z',
                }) + '\n')
            with open(metering_path, 'w') as f:
                f.write(json.dumps({
                    'org_id': 'org_founding',
                    'agent_id': 'agent_main',
                    'metric': 'mcp_tool_call',
                    'quantity': 1,
                    'unit': 'calls',
                    'cost_usd': 0.0,
                    'timestamp': '2026-03-24T20:00:00Z',
                }) + '\n')
            with (
                mock.patch.object(organizations, 'ORGS_FILE', orgs_path),
                mock.patch.object(audit, 'AUDIT_FILE', audit_path),
                mock.patch.object(metering, 'METERING_FILE', metering_path),
                mock.patch.object(alerting, 'ALERT_LOG_FILE', alert_path),
                mock.patch.object(audit, '_now', return_value='2026-03-25T00:30:00Z'),
                mock.patch.object(metering, '_now', return_value='2026-03-25T00:30:00Z'),
                mock.patch.object(status_surface, '_utc_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)),
                mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)),
            ):
                snapshot = status_surface.observability_snapshot('org_founding')

        self.assertEqual(snapshot['metrics']['audit']['latest_action'], 'poge_status_heartbeat')
        self.assertEqual(snapshot['metrics']['metering']['latest_metric'], 'observability_status_heartbeat')
        self.assertEqual(snapshot['slo']['status'], 'healthy')

    def test_sqlite_observability_mirror_supports_queries_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs_path = os.path.join(tmp, 'organizations.json')
            audit_path = os.path.join(tmp, 'audit_log.jsonl')
            metering_path = os.path.join(tmp, 'metering.jsonl')
            with (
                mock.patch.object(organizations, 'ORGS_FILE', orgs_path),
                mock.patch.object(audit, 'AUDIT_FILE', audit_path),
                mock.patch.object(metering, 'METERING_FILE', metering_path),
                mock.patch.object(audit, '_now', return_value='2026-03-25T00:30:00Z'),
                mock.patch.object(metering, '_now', return_value='2026-03-25T00:30:00Z'),
            ):
                audit.log_event(
                    'org_founding',
                    'agent_main',
                    'status_check',
                    resource='workspace',
                    outcome='success',
                    details={'surface': 'status'},
                )
                metering.record(
                    'org_founding',
                    'agent_main',
                    'mcp_tool_call',
                    quantity=2,
                    unit='calls',
                    cost_usd=1.25,
                    run_id='run_1',
                    details={'surface': 'status'},
                )

            db_path = observability_store.db_path_for_log(audit_path)
            self.assertTrue(os.path.exists(db_path))
            with sqlite3.connect(db_path) as conn:
                audit_count = conn.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]
                meter_count = conn.execute('SELECT COUNT(*) FROM metering_events').fetchone()[0]
            self.assertEqual(audit_count, 1)
            self.assertEqual(meter_count, 1)

            alert_path = os.path.join(tmp, 'slo_alert_log.jsonl')
            with (
                mock.patch.object(organizations, 'ORGS_FILE', orgs_path),
                mock.patch.object(audit, 'AUDIT_FILE', audit_path),
                mock.patch.object(metering, 'METERING_FILE', metering_path),
                mock.patch.object(alerting, 'ALERT_LOG_FILE', alert_path),
                mock.patch.object(status_surface, '_utc_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)),
                mock.patch.object(slo_policy, '_now', return_value=datetime.datetime(2026, 3, 25, 0, 30, 0)),
            ):
                snapshot = status_surface.observability_snapshot('org_founding')
                metrics_text = status_surface.observability_metrics_text('org_founding')

        self.assertIn('sqlite-observability', snapshot['backend'])
        self.assertEqual(snapshot['db']['status'], 'present')
        self.assertEqual(snapshot['export']['route'], '/metrics')
        self.assertEqual(snapshot['slo']['status'], 'healthy')
        self.assertIn('meridian_audit_events_total{org_id="org_founding"} 1', metrics_text)
        self.assertIn('meridian_metering_cost_usd_total{org_id="org_founding"} 1.2500', metrics_text)
        self.assertIn('meridian_slo_overall_status{org_id="org_founding"} 1', metrics_text)

    def test_accounting_sqlite_mirror_surfaces_in_persistence_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs_path = os.path.join(tmp, 'organizations.json')
            audit_path = os.path.join(tmp, 'audit_log.jsonl')
            owner_path = os.path.join(tmp, 'owner_ledger.json')
            accounting_store.save_owner_ledger_state(
                owner_path,
                {
                    'owner': 'Son Nguyen The',
                    'capital_contributed_usd': 3.0,
                    'expenses_paid_usd': 1.0,
                    'reimbursements_received_usd': 0.25,
                    'draws_taken_usd': 0.0,
                    'entries': [],
                    '_meta': {'bound_org_id': 'org_founding'},
                },
                org_id='org_founding',
            )
            with (
                mock.patch.object(organizations, 'ORGS_FILE', orgs_path),
                mock.patch.object(audit, 'AUDIT_FILE', audit_path),
                mock.patch.object(status_surface, '_safe_capsule_path', side_effect=lambda org_id, filename: owner_path if filename == 'owner_ledger.json' else ''),
            ):
                snapshot = status_surface.persistence_snapshot('org_founding')

        self.assertEqual(snapshot['db']['accounting']['status'], 'present')
        self.assertIn('sqlite-accounting', snapshot['backend'])

    def test_cases_sqlite_mirror_surfaces_in_persistence_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs_path = os.path.join(tmp, 'organizations.json')
            audit_path = os.path.join(tmp, 'audit_log.jsonl')
            cases_path = os.path.join(tmp, 'cases.json')
            cases_store.save_case_store(
                cases_path,
                {
                    'cases': {
                        'case_demo': {
                            'case_id': 'case_demo',
                            'institution_id': 'org_founding',
                            'source_institution_id': 'org_founding',
                            'target_host_id': 'host_peer',
                            'target_institution_id': 'org_peer',
                            'claim_type': 'misrouted_execution',
                            'linked_commitment_id': 'cmt_demo',
                            'linked_warrant_id': 'war_demo',
                            'evidence_refs': [],
                            'status': 'open',
                            'opened_by': 'user_owner',
                            'opened_at': '2026-03-25T00:00:00Z',
                            'updated_at': '2026-03-25T00:00:00Z',
                            'reviewed_by': '',
                            'reviewed_at': '',
                            'review_note': '',
                            'resolution': '',
                            'note': 'demo',
                            'metadata': {},
                        }
                    },
                    'updatedAt': '2026-03-25T00:00:00Z',
                },
                org_id='org_founding',
            )
            with (
                mock.patch.object(organizations, 'ORGS_FILE', orgs_path),
                mock.patch.object(audit, 'AUDIT_FILE', audit_path),
                mock.patch.object(status_surface, '_safe_capsule_path', side_effect=lambda org_id, filename: cases_path if filename == 'cases.json' else ''),
            ):
                snapshot = status_surface.persistence_snapshot('org_founding')

        self.assertEqual(snapshot['db']['cases']['status'], 'present')
        self.assertIn('sqlite-cases', snapshot['backend'])

    def test_organizations_sqlite_mirror_surfaces_in_persistence_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            orgs_path = os.path.join(tmp, 'organizations.json')
            audit_path = os.path.join(tmp, 'audit_log.jsonl')
            with (
                mock.patch.object(organizations, 'ORGS_FILE', orgs_path),
                mock.patch.object(audit, 'AUDIT_FILE', audit_path),
            ):
                organizations.create_org('Acme Corp', 'user_123', plan='pro')
                snapshot = status_surface.persistence_snapshot('org_founding')

        self.assertEqual(snapshot['db']['organizations']['status'], 'present')
        self.assertTrue(snapshot['backend'].startswith('sqlite-organizations'))


if __name__ == '__main__':
    unittest.main()
