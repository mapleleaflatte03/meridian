#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import tempfile
import unittest


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


authority = _load_module(os.path.join(PLATFORM_DIR, 'authority.py'), 'meridian_live_authority_capsule_test')
court = _load_module(os.path.join(PLATFORM_DIR, 'court.py'), 'meridian_live_court_capsule_test')


class CapsuleStateMigrationTests(unittest.TestCase):
    def setUp(self):
        self._state_dir = tempfile.mkdtemp(prefix='meridian-live-capsule-test-')
        self._orig_authority_queue = authority.QUEUE_FILE
        self._orig_court_records = court.RECORDS_FILE
        self._orig_authority_default = authority._default_org_id
        self._orig_court_default = court._default_org_id
        self._orig_authority_capsule_path = authority.capsule_path
        self._orig_authority_ensure_capsule = authority.ensure_capsule
        self._orig_court_capsule_path = court.capsule_path
        self._orig_court_ensure_capsule = court.ensure_capsule

        self.org_id = 'org_live'
        self.legacy_queue = os.path.join(self._state_dir, 'authority_queue.json')
        self.legacy_records = os.path.join(self._state_dir, 'court_records.json')
        self.capsules_dir = os.path.join(self._state_dir, 'capsules')

        with open(self.legacy_queue, 'w') as f:
            json.dump({
                'pending_approvals': {'apr1': {'id': 'apr1', 'status': 'pending'}},
                'delegations': {},
                'kill_switch': {'engaged': False, 'engaged_by': None, 'engaged_at': None, 'reason': ''},
                'updatedAt': '2026-03-21T00:00:00Z',
            }, f, indent=2)
        with open(self.legacy_records, 'w') as f:
            json.dump({
                'violations': {'vio1': {'id': 'vio1', 'org_id': self.org_id, 'status': 'open'}},
                'appeals': {},
                'updatedAt': '2026-03-21T00:00:00Z',
            }, f, indent=2)

        authority.QUEUE_FILE = self.legacy_queue
        court.RECORDS_FILE = self.legacy_records
        authority._default_org_id = lambda: self.org_id
        court._default_org_id = lambda: self.org_id
        authority.capsule_path = lambda org_id, filename: os.path.join(self.capsules_dir, org_id or self.org_id, filename)
        authority.ensure_capsule = lambda org_id=None: os.makedirs(os.path.join(self.capsules_dir, org_id or self.org_id), exist_ok=True) or os.path.join(self.capsules_dir, org_id or self.org_id)
        court.capsule_path = lambda org_id, filename: os.path.join(self.capsules_dir, org_id or self.org_id, filename)
        court.ensure_capsule = lambda org_id=None: os.makedirs(os.path.join(self.capsules_dir, org_id or self.org_id), exist_ok=True) or os.path.join(self.capsules_dir, org_id or self.org_id)

    def tearDown(self):
        authority.QUEUE_FILE = self._orig_authority_queue
        court.RECORDS_FILE = self._orig_court_records
        authority._default_org_id = self._orig_authority_default
        court._default_org_id = self._orig_court_default
        authority.capsule_path = self._orig_authority_capsule_path
        authority.ensure_capsule = self._orig_authority_ensure_capsule
        court.capsule_path = self._orig_court_capsule_path
        court.ensure_capsule = self._orig_court_ensure_capsule
        shutil.rmtree(self._state_dir, ignore_errors=True)

    def test_authority_queue_migrates_to_capsule_path(self):
        queue = authority._load_queue(self.org_id)
        self.assertIn('apr1', queue['pending_approvals'])
        capsule_path = os.path.join(self.capsules_dir, self.org_id, 'authority_queue.json')
        self.assertTrue(os.path.exists(capsule_path))

        queue['pending_approvals']['apr2'] = {'id': 'apr2', 'status': 'pending'}
        authority._save_queue(queue, self.org_id)
        with open(capsule_path) as f:
            saved = json.load(f)
        self.assertIn('apr2', saved['pending_approvals'])

    def test_existing_empty_capsule_queue_is_rehydrated_from_legacy(self):
        capsule_path = os.path.join(self.capsules_dir, self.org_id, 'authority_queue.json')
        os.makedirs(os.path.dirname(capsule_path), exist_ok=True)
        with open(capsule_path, 'w') as f:
            json.dump({
                'pending_approvals': {},
                'delegations': {},
                'kill_switch': {'engaged': False, 'engaged_by': None, 'engaged_at': None, 'reason': ''},
                'updatedAt': '2026-03-21T00:00:00Z',
            }, f, indent=2)

        queue = authority._load_queue(self.org_id)
        self.assertIn('apr1', queue['pending_approvals'])

    def test_court_records_migrate_to_capsule_path(self):
        records = court._load_records(self.org_id)
        self.assertIn('vio1', records['violations'])
        capsule_path = os.path.join(self.capsules_dir, self.org_id, 'court_records.json')
        self.assertTrue(os.path.exists(capsule_path))

        records['appeals']['apl1'] = {'id': 'apl1', 'org_id': self.org_id, 'status': 'pending'}
        court._save_records(records, self.org_id)
        with open(capsule_path) as f:
            saved = json.load(f)
        self.assertIn('apl1', saved['appeals'])

    def test_existing_empty_capsule_records_are_rehydrated_from_legacy(self):
        capsule_path = os.path.join(self.capsules_dir, self.org_id, 'court_records.json')
        os.makedirs(os.path.dirname(capsule_path), exist_ok=True)
        with open(capsule_path, 'w') as f:
            json.dump({'violations': {}, 'appeals': {}, 'updatedAt': '2026-03-21T00:00:00Z'}, f, indent=2)

        records = court._load_records(self.org_id)
        self.assertIn('vio1', records['violations'])


if __name__ == '__main__':
    unittest.main()
