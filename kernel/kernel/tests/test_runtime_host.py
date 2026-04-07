#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, ROOT)


class RuntimeHostTests(unittest.TestCase):
    def test_default_host_identity_is_institution_host(self):
        from runtime_host import default_host_identity
        host = default_host_identity(supported_boundaries=['workspace'])
        self.assertEqual(host.role, 'institution_host')
        self.assertIn('workspace', host.supported_boundaries)
        self.assertFalse(host.federation_enabled)
        self.assertEqual(host.settlement_adapters, ['internal_ledger'])
        self.assertTrue(host.host_id.startswith('host_'))

    def test_load_host_identity_from_file(self):
        from runtime_host import load_host_identity
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'host_identity.json')
            with open(path, 'w') as f:
                json.dump({
                    'host_id': 'host_alpha',
                    'label': 'Alpha Host',
                    'role': 'control_host',
                    'federation_enabled': True,
                    'peer_transport': 'https',
                    'supported_boundaries': ['workspace', 'cli'],
                    'settlement_adapters': ['base_usdc_x402'],
                }, f)
            host = load_host_identity(path)
        self.assertEqual(host.host_id, 'host_alpha')
        self.assertEqual(host.role, 'control_host')
        self.assertTrue(host.federation_enabled)
        self.assertEqual(host.peer_transport, 'https')

    def test_load_admission_registry_defaults_to_bound_org(self):
        from runtime_host import load_admission_registry, default_host_identity
        host = default_host_identity()
        registry = load_admission_registry('/tmp/missing-admissions.json', bound_org_id='org_a', host_identity=host)
        self.assertEqual(registry['source'], 'derived_bound_default')
        self.assertEqual(registry['admitted_org_ids'], ['org_a'])

    def test_load_admission_registry_reads_file(self):
        from runtime_host import load_admission_registry, default_host_identity
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'institution_admissions.json')
            with open(path, 'w') as f:
                json.dump({
                    'host_id': 'host_alpha',
                    'institutions': {
                        'org_a': {'status': 'admitted'},
                        'org_b': {'status': 'suspended'},
                    },
                }, f)
            host = default_host_identity(host_id='host_alpha')
            registry = load_admission_registry(path, bound_org_id='org_a', host_identity=host)
        self.assertEqual(registry['source'], 'file')
        self.assertEqual(registry['admitted_org_ids'], ['org_a'])
        self.assertEqual(registry['institutions']['org_b']['status'], 'suspended')

    def test_load_admission_registry_rejects_host_mismatch(self):
        from runtime_host import load_admission_registry, default_host_identity
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'institution_admissions.json')
            with open(path, 'w') as f:
                json.dump({'host_id': 'host_beta', 'admitted_org_ids': ['org_a']}, f)
            host = default_host_identity(host_id='host_alpha')
            with self.assertRaises(RuntimeError):
                load_admission_registry(path, bound_org_id='org_a', host_identity=host)

    def test_ensure_org_admitted_accepts_admitted_org(self):
        from runtime_host import ensure_org_admitted
        self.assertTrue(ensure_org_admitted('org_a', {
            'institutions': {'org_a': {'status': 'admitted'}},
        }))

    def test_ensure_org_admitted_rejects_missing_org(self):
        from runtime_host import ensure_org_admitted
        with self.assertRaises(RuntimeError):
            ensure_org_admitted('org_a', {'institutions': {}})

    def test_ensure_org_admitted_rejects_non_servable_org(self):
        from runtime_host import ensure_org_admitted
        with self.assertRaises(RuntimeError):
            ensure_org_admitted('org_a', {'institutions': {'org_a': {'status': 'suspended'}}})

    def test_set_admission_state_persists_registry(self):
        from runtime_host import default_host_identity, set_admission_state
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'institution_admissions.json')
            host = default_host_identity(host_id='host_alpha')
            registry = set_admission_state(
                path,
                'org_b',
                'admitted',
                bound_org_id='org_a',
                host_identity=host,
                details={'updated_by': 'user_owner'},
            )
            self.assertEqual(registry['host_id'], 'host_alpha')
            self.assertEqual(sorted(registry['admitted_org_ids']), ['org_a', 'org_b'])
            self.assertEqual(registry['institutions']['org_b']['status'], 'admitted')
            self.assertEqual(registry['institutions']['org_b']['updated_by'], 'user_owner')

    def test_set_admission_state_rejects_invalid_status(self):
        from runtime_host import default_host_identity, set_admission_state
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                set_admission_state(
                    os.path.join(tmp, 'institution_admissions.json'),
                    'org_b',
                    'unknown',
                    host_identity=default_host_identity(host_id='host_alpha'),
                )

    def test_set_admission_state_materializes_file_from_bound_org(self):
        from runtime_host import default_host_identity, set_admission_state

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'institution_admissions.json')
            host = default_host_identity(host_id='host_alpha')
            registry = set_admission_state(
                path,
                'org_b',
                'admitted',
                bound_org_id='org_a',
                host_identity=host,
            )
            self.assertEqual(registry['source'], 'file')
            self.assertEqual(registry['admitted_org_ids'], ['org_a', 'org_b'])
            self.assertEqual(registry['institutions']['org_b']['status'], 'admitted')

    def test_set_admission_state_updates_existing_entry(self):
        from runtime_host import default_host_identity, set_admission_state

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'institution_admissions.json')
            host = default_host_identity(host_id='host_alpha')
            set_admission_state(path, 'org_a', 'admitted', host_identity=host)
            registry = set_admission_state(path, 'org_a', 'suspended', host_identity=host)
            self.assertEqual(registry['institutions']['org_a']['status'], 'suspended')
            self.assertEqual(registry['admitted_org_ids'], [])


if __name__ == '__main__':
    unittest.main()
