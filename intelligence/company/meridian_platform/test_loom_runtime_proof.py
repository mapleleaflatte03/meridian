#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import unittest
from unittest import mock


THIS_DIR = pathlib.Path(__file__).resolve().parent
MODULE_PATH = THIS_DIR / 'loom_runtime_proof.py'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


proof = _load_module('loom_runtime_proof_test', MODULE_PATH)


class LoomRuntimeProofTests(unittest.TestCase):
    def test_parse_loom_health_extracts_structured_runtime_state(self):
        output = json.dumps({
            'status': 'healthy',
            'checks': [
                {'level': 'OK', 'label': 'agent_runtime', 'detail': 'profiles=7 agents=leviathann,atlas,quill memory_ready=7/7 session_ready=7/7'},
                {'level': 'OK', 'label': 'channel_runtime', 'detail': 'total=2 enabled=2 ingress=0 delivery_path=/tmp inbox_path=/tmp channels=web_api,telegram'},
                {'level': 'OK', 'label': 'session_provenance', 'detail': 'total=3 sessions=telegram:founder,web_api:owner,web_api:demo'},
            ],
        })
        parsed = proof.parse_loom_health(output)

        self.assertTrue(parsed['health_ok'])
        self.assertEqual(parsed['status'], 'healthy')
        self.assertTrue(parsed['telegram']['ok'])
        self.assertEqual(parsed['agent_count'], 3)
        self.assertEqual(parsed['agents'][0]['handle'], 'leviathann')
        self.assertEqual(parsed['session_total'], 3)
        self.assertEqual(parsed['session_runtime']['active_count'], 3)
        self.assertEqual(parsed['session_runtime']['archived_count'], 0)
        self.assertEqual(parsed['channel_runtime']['channel_ids'], ['web_api', 'telegram'])

    def test_map_governed_agents_uses_runtime_binding_truth(self):
        agents = [
            {
                'id': 'agent_main',
                'org_id': 'org_1',
                'name': 'Leviathann',
                'economy_key': 'main',
                'runtime_binding': {'runtime_id': 'loom_native'},
            },
            {
                'id': 'agent_writer',
                'org_id': 'org_1',
                'name': 'Release Writer',
                'economy_key': '',
                'runtime_binding': {'runtime_id': 'loom_native'},
            },
        ]

        mapped = proof.map_governed_agents_to_loom_handles(agents)
        self.assertEqual(mapped[0]['loom_handle'], 'main')
        self.assertEqual(mapped[0]['handle_source'], 'economy_key')
        self.assertEqual(mapped[0]['economy_key'], 'main')
        self.assertEqual(mapped[1]['loom_handle'], 'release_writer')
        self.assertEqual(mapped[1]['handle_source'], 'name')
        self.assertTrue(mapped[0]['has_loom_handle'])
        self.assertEqual(mapped[0]['runtime_binding']['runtime_id'], 'loom_native')

    def test_map_governed_agents_prefers_runtime_handle_alias_when_present(self):
        agents = [
            {
                'id': 'agent_main',
                'org_id': 'org_1',
                'name': 'Leviathann',
                'economy_key': 'main',
                'runtime_binding': {'runtime_id': 'loom_native'},
            }
        ]

        mapped = proof.map_governed_agents_to_loom_handles(agents, runtime_handles=['leviathann', 'atlas'])
        self.assertEqual(mapped[0]['loom_handle'], 'leviathann')
        self.assertEqual(mapped[0]['economy_key'], 'main')
        self.assertEqual(mapped[0]['handle_source'], 'runtime_match')
        self.assertEqual(mapped[0]['handle_candidates'], ['main', 'leviathann', 'agent_main'])

    def test_collect_loom_runtime_proof_combines_health_and_registry_truth(self):
        service_status = json.dumps({
            'running': True,
            'service_status': 'running',
            'health': 'healthy',
            'transport': 'socket+http',
        })
        memory_status = json.dumps({
            'agent_count': 1,
            'total_entries': 2,
            'total_bytes': 128,
            'agents': [{'agent_id': 'atlas', 'entry_count': 2, 'categories': ['general'], 'total_bytes': 128}],
        })
        context_status = json.dumps({
            'layer_count': 12,
            'section_count': 6,
            'mutable_count': 4,
            'sections': ['agents', 'heartbeat', 'memory', 'soul', 'tools', 'user'],
        })

        def fake_run(command, timeout):
            if 'service' in command:
                return {
                    'command': list(command),
                    'ok': True,
                    'returncode': 0,
                    'stdout': service_status,
                    'stderr': '',
                }
            if 'memory' in command:
                return {
                    'command': list(command),
                    'ok': True,
                    'returncode': 0,
                    'stdout': memory_status,
                    'stderr': '',
                }
            if 'context' in command:
                return {
                    'command': list(command),
                    'ok': True,
                    'returncode': 0,
                    'stdout': context_status,
                    'stderr': '',
                }
            raise AssertionError(f'unexpected command: {command}')

        with mock.patch.object(proof, 'load_registry', return_value={
            'agents': {
                'agent_main': {
                    'id': 'agent_main',
                    'org_id': 'org_1',
                    'name': 'Leviathann',
                    'economy_key': 'main',
                    'runtime_binding': {'runtime_id': 'loom_native'},
                },
                'agent_atlas': {
                    'id': 'agent_atlas',
                    'org_id': 'org_1',
                    'name': 'Atlas',
                    'economy_key': 'atlas',
                    'runtime_binding': {'runtime_id': 'loom_native'},
                },
            }
        }), mock.patch.object(proof, '_run_command', side_effect=fake_run):
            result = proof.collect_loom_runtime_proof(
                health_output=json.dumps({
                    'status': 'healthy',
                    'checks': [
                        {'level': 'OK', 'label': 'agent_runtime', 'detail': 'profiles=7 agents=leviathann,atlas,sentinel memory_ready=7/7 session_ready=7/7'},
                        {'level': 'OK', 'label': 'channel_runtime', 'detail': 'total=2 enabled=2 ingress=0 active_deliveries=4 archived_deliveries=1 delivery_path=/tmp inbox_path=/tmp channels=web_api,telegram'},
                        {'level': 'OK', 'label': 'session_provenance', 'detail': 'total=3 active=2 archived=1 sessions=web_api:owner,telegram:founder'},
                    ],
                }),
                include_service_probe=True,
                service_probe_command=['loom', 'service', 'status', '--format', 'json'],
            )

        self.assertEqual(result['proof_type'], 'live_single_host_loom_deployment')
        self.assertTrue(result['health']['health_ok'])
        self.assertEqual(result['governed_agents'][0]['loom_handle'], 'leviathann')
        self.assertEqual(result['governed_agents'][0]['economy_key'], 'main')
        self.assertEqual(result['handle_overlap'], ['atlas', 'leviathann'])
        self.assertEqual(result['handle_gap'], [])
        self.assertEqual(result['deployment_truth']['scope'], 'single_host')
        self.assertFalse(result['deployment_truth']['generic_runtime_claim'])
        self.assertEqual(result['runtime_id'], 'loom_native')
        self.assertTrue(result['memory_context']['checked'])
        self.assertTrue(result['memory_context']['memory_ok'])
        self.assertTrue(result['memory_context']['context_ok'])
        self.assertEqual(result['memory_context']['memory']['total_entries'], 2)
        self.assertEqual(result['memory_context']['context']['section_count'], 6)
        self.assertEqual(result['health']['session_runtime']['active_count'], 2)
        self.assertEqual(result['health']['session_runtime']['archived_count'], 1)
        self.assertEqual(result['health']['channel_runtime']['active_delivery_count'], 4)
        self.assertEqual(result['health']['channel_runtime']['archived_delivery_count'], 1)

    def test_public_receipt_filters_runtime_proof_for_public_route(self):
        receipt = proof.public_loom_runtime_receipt({
            'runtime_id': 'loom_native',
            'proof_type': 'live_single_host_loom_deployment',
            'checked_at': '2026-03-22T00:00:00Z',
            'deployment_truth': {'scope': 'single_host', 'generic_runtime_claim': False},
            'health': {
                'status': 'healthy',
                'health_ok': True,
                'telegram': {'ok': True},
                'agent_count': 2,
                'agents': [{'handle': 'leviathann'}, {'handle': 'atlas'}],
                'heartbeat': {'interval': None, 'primary_agent': None},
                'session_total': 0,
                'session_runtime': {'total_count': 6, 'active_count': 4, 'archived_count': 2},
                'channel_runtime': {'total_count': 2, 'enabled_count': 2, 'ingress_count': 16, 'active_delivery_count': 13, 'archived_delivery_count': 16},
            },
            'service_probe': {'checked': True, 'ok': True, 'output': 'service running', 'service_status': 'running', 'health': 'healthy', 'transport': 'socket+http'},
            'memory_context': {
                'checked': True,
                'memory_ok': True,
                'context_ok': True,
                'memory': {'total_entries': 2},
                'context': {'section_count': 6},
            },
            'governed_agents': [
                {
                    'agent_id': 'agent_main',
                    'agent_name': 'Leviathann',
                    'org_id': 'org_1',
                    'role': 'manager',
                    'loom_handle': 'leviathann',
                    'economy_key': 'main',
                    'handle_candidates': ['main', 'leviathann', 'agent_main'],
                    'handle_source': 'runtime_match',
                    'runtime_binding': {
                        'runtime_id': 'loom_native',
                        'runtime_registered': True,
                        'registration_status': 'registered',
                        'bound_org_id': 'org_1',
                    },
                }
            ],
            'handle_overlap': ['leviathann'],
            'handle_gap': [],
        }, bound_org_id='org_1')

        self.assertEqual(receipt['runtime_id'], 'loom_native')
        self.assertTrue(receipt['runtime_health']['health_ok'])
        self.assertTrue(receipt['runtime_health']['service_probe_ok'])
        self.assertEqual(receipt['constitutional_model']['kernel']['count'], 5)
        self.assertEqual(receipt['constitutional_model']['platform']['count'], 6)
        self.assertEqual(receipt['constitutional_model']['platform']['primitives'][-1], 'Commitment')
        self.assertEqual(receipt['service_probe']['status'], 'running')
        self.assertEqual(receipt['runtime_surfaces']['session_provenance']['active_count'], 4)
        self.assertEqual(receipt['runtime_surfaces']['channel_runtime']['archived_delivery_count'], 16)
        self.assertTrue(receipt['memory_context']['checked'])
        self.assertTrue(receipt['memory_context']['memory_ok'])
        self.assertTrue(receipt['memory_context']['context_ok'])
        self.assertEqual(receipt['health']['agent_handles'], ['leviathann', 'atlas'])
        self.assertEqual(receipt['governed_agents'][0]['runtime_binding']['runtime_id'], 'loom_native')
        self.assertEqual(receipt['governed_agents'][0]['economy_key'], 'main')
        self.assertEqual(receipt['governed_agents'][0]['loom_handle'], 'leviathann')

    def test_public_receipt_falls_back_to_service_probe_when_health_probe_is_unknown(self):
        receipt = proof.public_loom_runtime_receipt({
            'runtime_id': 'loom_native',
            'proof_type': 'live_single_host_loom_deployment',
            'checked_at': '2026-03-31T00:00:00Z',
            'deployment_truth': {'scope': 'single_host', 'generic_runtime_claim': False},
            'health': {
                'status': 'unknown',
                'health_ok': False,
                'telegram': {'ok': False},
                'agent_count': 0,
                'agents': [],
                'heartbeat': {'interval': None, 'primary_agent': None},
                'session_total': 0,
                'session_runtime': {'total_count': 0, 'active_count': 0, 'archived_count': 0},
                'channel_runtime': {'total_count': 0, 'enabled_count': 0, 'ingress_count': 0, 'active_delivery_count': 0, 'archived_delivery_count': 0},
            },
            'service_probe': {
                'checked': True,
                'ok': True,
                'output': 'service running',
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
            },
            'memory_context': {'checked': False, 'memory_ok': False, 'context_ok': False},
            'governed_agents': [],
            'handle_overlap': [],
            'handle_gap': [],
        }, bound_org_id='org_1')

        self.assertEqual(receipt['runtime_health']['status'], 'healthy')
        self.assertEqual(receipt['runtime_health']['source_status'], 'unknown')
        self.assertTrue(receipt['runtime_health']['health_ok'])
        self.assertEqual(receipt['health']['status'], 'healthy')
        self.assertTrue(receipt['health']['health_ok'])

    def test_public_receipt_normalizes_degraded_source_when_runtime_checks_are_green(self):
        receipt = proof.public_loom_runtime_receipt({
            'runtime_id': 'loom_native',
            'proof_type': 'live_single_host_loom_deployment',
            'checked_at': '2026-04-06T00:00:00Z',
            'deployment_truth': {'scope': 'single_host', 'generic_runtime_claim': False},
            'health': {
                'status': 'degraded',
                'health_ok': True,
                'telegram': {'ok': True},
                'agent_count': 7,
                'agents': [{'handle': 'leviathann'}],
                'heartbeat': {'interval': '15s', 'primary_agent': 'leviathann'},
                'session_total': 144,
                'session_runtime': {'total_count': 144, 'active_count': 144, 'archived_count': 0},
                'channel_runtime': {'total_count': 3, 'enabled_count': 3, 'ingress_count': 0, 'active_delivery_count': 0, 'archived_delivery_count': 0},
            },
            'service_probe': {
                'checked': True,
                'ok': True,
                'output': 'service running',
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
            },
            'memory_context': {'checked': False, 'memory_ok': False, 'context_ok': False},
            'governed_agents': [],
            'handle_overlap': [],
            'handle_gap': [],
        }, bound_org_id='org_1')

        self.assertEqual(receipt['runtime_health']['source_status'], 'degraded')
        self.assertEqual(receipt['runtime_health']['status'], 'healthy')
        self.assertEqual(receipt['health']['status'], 'healthy')

    def test_public_surface_contract_binds_omni_channel_and_memory_claims(self):
        contract = proof.public_loom_surface_contract_receipt({
            'runtime_id': 'loom_native',
            'checked_at': '2026-03-30T18:00:00Z',
            'deployment_truth': {'scope': 'single_host', 'generic_runtime_claim': False},
            'health': {
                'telegram': {'ok': True},
                'session_runtime': {'total_count': 8, 'active_count': 6},
                'channel_runtime': {
                    'total_count': 2,
                    'enabled_count': 2,
                    'ingress_count': 170,
                    'active_delivery_count': 137,
                    'archived_delivery_count': 28,
                    'channel_ids': ['web_api', 'telegram'],
                },
            },
            'service_probe': {'ok': True, 'transport': 'socket+http'},
            'memory_context': {
                'checked': True,
                'memory_ok': True,
                'context_ok': True,
                'memory': {
                    'agent_count': 2,
                    'total_entries': 0,
                    'total_bytes': 0,
                    'policy': {
                        'agent_isolation': True,
                        'max_entries_per_agent': 500,
                        'retention_days': 365,
                    },
                },
                'context': {
                    'layer_count': 33,
                    'section_count': 6,
                    'mutable_count': 28,
                    'sections': ['agents', 'heartbeat', 'memory', 'soul', 'tools', 'user'],
                },
            },
        }, bound_org_id='org_48b05c21')

        self.assertEqual(contract['proof_type'], 'bounded_live_surface_contract')
        self.assertEqual(contract['contract_version'], 1)
        self.assertEqual(contract['surface_contract']['surfaces']['omni_channel_presence']['status'], 'bounded_proven')
        self.assertEqual(contract['surface_contract']['surfaces']['persistent_memory']['status'], 'bounded_proven')
        self.assertEqual(
            contract['surface_contract']['surfaces']['omni_channel_presence']['evidence']['channel_ids'],
            ['web_api', 'telegram'],
        )
        self.assertTrue(
            contract['surface_contract']['surfaces']['persistent_memory']['evidence']['agent_isolation']
        )
        self.assertIn(
            'email delivery',
            contract['surface_contract']['surfaces']['omni_channel_presence']['not_claimed'],
        )

    def test_runtime_proof_contract_fields_are_non_null(self):
        receipt = proof.public_loom_runtime_receipt({
            'runtime_id': 'loom_native',
            'proof_type': 'live_single_host_loom_deployment',
            'checked_at': '2026-04-05T00:00:00Z',
            'deployment_truth': {'scope': 'single_host', 'generic_runtime_claim': False},
            'health': {
                'status': 'healthy',
                'health_ok': True,
                'telegram': {'ok': True},
                'agent_count': 1,
                'agents': [{'handle': 'leviathann'}],
                'heartbeat': {'interval': '30m', 'primary_agent': 'leviathann'},
                'session_total': 2,
                'session_runtime': {'total_count': 2, 'active_count': 2, 'archived_count': 0},
                'channel_runtime': {
                    'total_count': 2,
                    'enabled_count': 2,
                    'ingress_count': 11,
                    'active_delivery_count': 5,
                    'archived_delivery_count': 1,
                    'channel_ids': ['web_api', 'telegram'],
                },
            },
            'service_probe': {
                'checked': True,
                'ok': True,
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
                'output': 'running',
            },
            'memory_context': {
                'checked': True,
                'memory_ok': True,
                'context_ok': True,
                'memory': {'total_entries': 0},
                'context': {'section_count': 6},
            },
            'governed_agents': [],
            'handle_overlap': ['leviathann'],
            'handle_gap': [],
        }, bound_org_id='org_founding')

        contract = receipt['runtime_proof_contract']
        self.assertEqual(contract['version'], 'runtime_proof_contract_v1')
        self.assertNotEqual(contract['runtime_proof_status'], '')
        self.assertNotEqual(contract['channel_surface_status'], '')
        self.assertNotEqual(contract['memory_surface_status'], '')
        self.assertNotEqual(contract['proof_chain_status'], '')
        self.assertNotEqual(contract['proof_path'], '')
        self.assertIsNotNone(contract.get('runtime_proof_status'))
        self.assertIsNotNone(contract.get('channel_surface_status'))
        self.assertIsNotNone(contract.get('memory_surface_status'))
        self.assertIsNotNone(contract.get('proof_chain_status'))
        self.assertIsNotNone(contract.get('proof_path'))


if __name__ == '__main__':
    unittest.main()
