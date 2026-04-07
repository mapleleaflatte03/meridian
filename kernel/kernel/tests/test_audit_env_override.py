#!/usr/bin/env python3
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / 'kernel' / 'audit.py'


def _load_audit_module(module_name):
    spec = importlib.util.spec_from_file_location(module_name, AUDIT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditEnvOverrideTests(unittest.TestCase):
    def test_meridian_audit_file_env_redirects_log_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            preview_path = pathlib.Path(tmpdir) / 'audit-preview.jsonl'
            os.environ['MERIDIAN_AUDIT_FILE'] = str(preview_path)
            try:
                audit = _load_audit_module('kernel_audit_env_override_test')
                event_id = audit.log_event(
                    'org_demo',
                    'agent_atlas',
                    'shadow_preview',
                    resource='web_search',
                    outcome='simulated_success',
                    details={'source': 'unit_test'},
                    policy_ref='experimental_preflight_preview',
                )
            finally:
                os.environ.pop('MERIDIAN_AUDIT_FILE', None)

            self.assertTrue(preview_path.exists())
            rows = preview_path.read_text().strip().splitlines()
            self.assertEqual(len(rows), 1)
            event = json.loads(rows[0])
            self.assertEqual(event['id'], event_id)
            self.assertEqual(event['org_id'], 'org_demo')
            self.assertEqual(event['agent_id'], 'agent_atlas')
            self.assertEqual(event['action'], 'shadow_preview')
            self.assertEqual(event['outcome'], 'simulated_success')
            self.assertEqual(event['policy_ref'], 'experimental_preflight_preview')

    def test_log_runtime_cli_respects_env_override_and_shapes_details(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_path = pathlib.Path(tmpdir) / 'audit-runtime.jsonl'
            env = os.environ.copy()
            env['MERIDIAN_AUDIT_FILE'] = str(runtime_path)
            result = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_PATH),
                    'log-runtime',
                    '--org_id', 'org_demo',
                    '--agent_id', 'agent_atlas',
                    '--action', 'research',
                    '--resource', 'web_search',
                    '--outcome', 'success',
                    '--input_hash', 'abc123',
                    '--estimated_cost_usd', '0.05',
                    '--effective_source', 'worker_supervisor',
                    '--effective_stage', 'governed_local_worker',
                    '--reference_stage', 'ok',
                    '--runtime_outcome', 'worker_executed',
                    '--worker_status', 'completed',
                    '--worker_kind', 'python_reference_worker',
                    '--parity_status', 'match',
                    '--runtime_event_id', 'loom.runtime.v1::evt_demo',
                    '--event_schema_version', 'loom.runtime.v1',
                    '--job_id', 'job::demo',
                    '--execution_id', 'execution::demo',
                    '--decision_id', 'decision::demo',
                    '--parity_id', 'parity::demo',
                    '--audit_id', 'audit::demo',
                    '--budget_reservation_id', 'bud_demo',
                    '--budget_reservation_status', 'reserved',
                    '--budget_reservation_reason', 'ok',
                    '--session_id', 'sess_demo',
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            receipt = json.loads(result.stdout.strip())

            self.assertTrue(runtime_path.exists())
            rows = runtime_path.read_text().strip().splitlines()
            self.assertEqual(len(rows), 1)
            event = json.loads(rows[0])
            self.assertEqual(receipt['runtime_event_id'], 'loom.runtime.v1::evt_demo')
            self.assertEqual(receipt['budget_reservation_status'], 'reserved')
            self.assertEqual(event['org_id'], 'org_demo')
            self.assertEqual(event['agent_id'], 'agent_atlas')
            self.assertEqual(event['action'], 'research')
            self.assertEqual(event['resource'], 'web_search')
            self.assertEqual(event['outcome'], 'success')
            self.assertEqual(event['policy_ref'], 'experimental_runtime_rehearsal')
            self.assertEqual(event['session_id'], 'sess_demo')
            self.assertEqual(event['details']['source'], 'loom_runtime_execute')
            self.assertEqual(event['details']['runtime_outcome'], 'worker_executed')
            self.assertEqual(event['details']['worker_status'], 'completed')
            self.assertEqual(event['details']['worker_kind'], 'python_reference_worker')
            self.assertEqual(event['details']['parity_status'], 'match')
            self.assertEqual(event['details']['runtime_event_id'], 'loom.runtime.v1::evt_demo')
            self.assertEqual(event['details']['event_schema_version'], 'loom.runtime.v1')
            self.assertEqual(event['details']['job_id'], 'job::demo')
            self.assertEqual(event['details']['budget_reservation_id'], 'bud_demo')
            self.assertEqual(event['details']['budget_reservation_status'], 'reserved')

    def test_log_runtime_cli_defaults_to_kernel_runtime_audit_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)
            kernel_dir = root / 'kernel'
            kernel_dir.mkdir()
            audit_copy = kernel_dir / 'audit.py'
            audit_copy.write_text(AUDIT_PATH.read_text())
            expected = kernel_dir / 'runtime_audit' / 'loom_runtime_events.jsonl'
            env = os.environ.copy()
            env.pop('MERIDIAN_AUDIT_FILE', None)
            env.pop('MERIDIAN_RUNTIME_AUDIT_FILE', None)
            result = subprocess.run(
                [
                    sys.executable,
                    str(audit_copy),
                    'log-runtime',
                    '--org_id', 'org_demo',
                    '--agent_id', 'agent_atlas',
                    '--action', 'research',
                    '--resource', 'web_search',
                    '--outcome', 'success',
                    '--input_hash', 'def456',
                    '--estimated_cost_usd', '0.05',
                    '--effective_source', 'reference_gate',
                    '--effective_stage', 'ok',
                    '--reference_stage', 'ok',
                    '--runtime_outcome', 'worker_executed',
                    '--worker_status', 'completed',
                    '--worker_kind', 'python_reference_worker',
                    '--parity_status', 'match',
                    '--runtime_event_id', 'loom.runtime.v1::evt_default',
                    '--event_schema_version', 'loom.runtime.v1',
                    '--job_id', 'job::default',
                    '--execution_id', 'execution::default',
                    '--decision_id', 'decision::default',
                    '--parity_id', 'parity::default',
                    '--audit_id', 'audit::default',
                    '--budget_reservation_status', 'committed',
                ],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            receipt = json.loads(result.stdout.strip())

            self.assertTrue(expected.exists())
            rows = expected.read_text().strip().splitlines()
            self.assertEqual(len(rows), 1)
            event = json.loads(rows[0])
            self.assertEqual(receipt['runtime_audit_file'], str(expected))
            self.assertEqual(event['org_id'], 'org_demo')
            self.assertEqual(event['details']['source'], 'loom_runtime_execute')
            self.assertEqual(event['details']['runtime_event_id'], 'loom.runtime.v1::evt_default')
            self.assertEqual(event['details']['budget_reservation_status'], 'committed')

    def test_summarize_runtime_cli_prints_proof_first_human_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_path = pathlib.Path(tmpdir) / 'audit-runtime.jsonl'
            runtime_events = [
                {
                    'id': 'evt_runtime_1',
                    'timestamp': '2026-03-23T00:00:01Z',
                    'org_id': 'org_demo',
                    'agent_id': 'agent_alpha',
                    'actor_type': 'agent',
                    'action': 'research',
                    'resource': 'web_search',
                    'outcome': 'success',
                    'details': {'runtime_event_id': 'loom.runtime.v1::evt_1'},
                    'policy_ref': 'experimental_runtime_rehearsal',
                },
                {
                    'id': 'evt_runtime_2',
                    'timestamp': '2026-03-23T00:00:02Z',
                    'org_id': 'org_demo',
                    'agent_id': 'agent_alpha',
                    'actor_type': 'agent',
                    'action': 'summarize',
                    'resource': 'runtime_audit',
                    'outcome': 'success',
                    'details': {'runtime_event_id': 'loom.runtime.v1::evt_2'},
                    'policy_ref': 'experimental_runtime_rehearsal',
                },
            ]
            runtime_path.write_text('\n'.join(json.dumps(row) for row in runtime_events) + '\n')

            env = os.environ.copy()
            env['MERIDIAN_AUDIT_FILE'] = str(runtime_path)
            env['MERIDIAN_RUNTIME_AUDIT_FILE'] = str(runtime_path)
            result = subprocess.run(
                [
                    sys.executable,
                    str(AUDIT_PATH),
                    'summarize-runtime',
                    '--org_id', 'org_demo',
                    '--limit', '2',
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )

            output = result.stdout.strip().splitlines()
            self.assertEqual(output[0], 'Runtime audit inspection')
            self.assertIn(f'file: {runtime_path}', output[1])
            self.assertIn('org_id: org_demo', output[2])
            self.assertIn('total_events: 2', result.stdout)
            self.assertIn('showing_last: 2', result.stdout)
            self.assertIn('distinct_orgs: 1', result.stdout)
            self.assertIn('distinct_agents: 1', result.stdout)
            self.assertIn('"research": 1', result.stdout)
            self.assertIn('"summarize": 1', result.stdout)
            self.assertIn('Latest proof', result.stdout)
            self.assertIn('evt_runtime_2', result.stdout)
            self.assertIn('Recent events', result.stdout)
            self.assertIn('evt_runtime_1', result.stdout)
            self.assertIn('evt_runtime_2', result.stdout)
            self.assertLess(result.stdout.find('evt_runtime_2'), result.stdout.rfind('evt_runtime_1') + 1000)


if __name__ == '__main__':
    unittest.main()
