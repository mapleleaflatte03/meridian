#!/usr/bin/env python3
import importlib.util
import json
import pathlib
import shutil
import sys
import tempfile
import types
import unittest
import uuid
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[2]
AUTHORITY_PATH = ROOT / 'kernel' / 'authority.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
LEGACY_QUEUE_PATH = ROOT / 'kernel' / 'authority_queue.json'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


authority = _load_module('kernel_authority_test', AUTHORITY_PATH)
capsule = _load_module('kernel_capsule_test_for_authority', CAPSULE_PATH)


class AuthorityCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_authority_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

        ledger_path = pathlib.Path(capsule.capsule_path(self.org_id, 'ledger.json'))
        ledger = json.loads(ledger_path.read_text())
        ledger['updatedAt'] = '2026-03-21T00:00:00Z'
        ledger['epoch']['started_at'] = '2026-03-21T00:00:00Z'
        ledger['agents'] = {
            'main': {
                'name': 'Manager',
                'role': 'manager',
                'reputation_units': 50,
                'authority_units': 50,
                'probation': False,
                'zero_authority': False,
                'status': 'active',
            },
            'atlas': {
                'name': 'Atlas',
                'role': 'analyst',
                'reputation_units': 50,
                'authority_units': 50,
                'probation': False,
                'zero_authority': False,
                'status': 'active',
            },
        }
        ledger_path.write_text(json.dumps(ledger, indent=2))
        self.legacy_queue_before = LEGACY_QUEUE_PATH.read_text() if LEGACY_QUEUE_PATH.exists() else ''

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def test_request_approval_writes_only_to_capsule_queue(self):
        approval_id = authority.request_approval(
            'atlas',
            'execute',
            'capsule-resource',
            cost_usd=1.0,
            org_id=self.org_id,
        )

        queue_path = pathlib.Path(capsule.capsule_path(self.org_id, 'authority_queue.json'))
        queue = json.loads(queue_path.read_text())
        self.assertIn(approval_id, queue['pending_approvals'])
        current_legacy_queue = LEGACY_QUEUE_PATH.read_text() if LEGACY_QUEUE_PATH.exists() else ''
        self.assertEqual(current_legacy_queue, self.legacy_queue_before)

    def test_check_authority_filters_economy_key_by_org_id(self):
        fake_registry = types.ModuleType('agent_registry')
        fake_registry.load_registry = lambda: {
            'agents': {
                'agent_wrong': {
                    'id': 'agent_wrong',
                    'org_id': 'org_other',
                    'economy_key': 'atlas',
                    'lifecycle_state': 'quarantined',
                },
                'agent_right': {
                    'id': 'agent_right',
                    'org_id': self.org_id,
                    'economy_key': 'atlas',
                    'lifecycle_state': 'active',
                },
            }
        }
        fake_orgs = types.ModuleType('organizations')
        fake_orgs.load_orgs = lambda: {
            'organizations': {
                self.org_id: {'lifecycle_state': 'active'},
                'org_other': {'lifecycle_state': 'active'},
            }
        }

        with mock.patch.dict(sys.modules, {
            'agent_registry': fake_registry,
            'organizations': fake_orgs,
        }, clear=False):
            allowed, reason = authority.check_authority('atlas', 'execute', org_id=self.org_id)

        self.assertTrue(allowed, reason)

    def test_delegation_matches_registry_id_and_economy_key(self):
        ledger_path = pathlib.Path(capsule.capsule_path(self.org_id, 'ledger.json'))
        ledger = json.loads(ledger_path.read_text())
        ledger['agents']['atlas']['zero_authority'] = True
        ledger_path.write_text(json.dumps(ledger, indent=2))

        fake_registry = types.ModuleType('agent_registry')
        fake_registry.load_registry = lambda: {
            'agents': {
                'agent_atlas': {
                    'id': 'agent_atlas',
                    'org_id': self.org_id,
                    'economy_key': 'atlas',
                    'lifecycle_state': 'active',
                }
            }
        }
        fake_orgs = types.ModuleType('organizations')
        fake_orgs.load_orgs = lambda: {
            'organizations': {
                self.org_id: {'lifecycle_state': 'active'},
            }
        }

        authority.delegate('main', 'agent_atlas', ['execute'], org_id=self.org_id)

        with mock.patch.dict(sys.modules, {
            'agent_registry': fake_registry,
            'organizations': fake_orgs,
        }, clear=False):
            allowed, reason = authority.check_authority('atlas', 'execute', org_id=self.org_id)

        self.assertTrue(allowed, reason)
        self.assertIn('Delegated by main', reason)

    def test_missing_org_fails_cleanly(self):
        with self.assertRaises(SystemExit) as ctx:
            authority._load_queue(f'org_missing_{uuid.uuid4().hex[:8]}')
        self.assertIn('is not initialized', str(ctx.exception))

    def test_load_queue_migrates_legacy_queue_for_founding_alias(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = pathlib.Path(tmpdir)
            economy_dir = tmpdir / 'economy'
            economy_dir.mkdir()
            legacy_queue = tmpdir / 'authority_queue.json'
            legacy_payload = {
                'pending_approvals': {'apr_seed': {'status': 'pending'}},
                'delegations': {},
                'kill_switch': {'engaged': False, 'engaged_by': None, 'engaged_at': None, 'reason': ''},
                'updatedAt': '2026-03-21T00:00:00Z',
            }
            legacy_queue.write_text(json.dumps(legacy_payload, indent=2))

            def fake_capsule_path(org_id, filename):
                return str(economy_dir / filename)

            with mock.patch.object(authority, 'ECONOMY_DIR', str(economy_dir)), \
                 mock.patch.object(authority, 'LEGACY_QUEUE_FILE', str(legacy_queue)), \
                 mock.patch.object(authority, 'capsule_path', side_effect=fake_capsule_path):
                queue = authority._load_queue('org_b7d95bae')

            migrated_path = economy_dir / 'authority_queue.json'
            self.assertTrue(migrated_path.exists())
            self.assertEqual(queue['pending_approvals']['apr_seed']['status'], 'pending')


if __name__ == '__main__':
    unittest.main()
