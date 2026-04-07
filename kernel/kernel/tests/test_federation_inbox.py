#!/usr/bin/env python3
import importlib.util
import pathlib
import shutil
import sys
import tempfile
import unittest
import uuid


ROOT = pathlib.Path(__file__).resolve().parents[2]
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
INBOX_PATH = ROOT / 'kernel' / 'federation_inbox.py'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FederationInboxTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory(prefix='meridian-federation-inbox-test-')
        self.root = pathlib.Path(self.tmpdir.name)
        self.economy_dir = self.root / 'economy'
        self.capsules_dir = self.root / 'capsules'
        self.kernel_dir = self.root / 'kernel'
        self.economy_dir.mkdir()
        self.capsules_dir.mkdir()
        self.kernel_dir.mkdir()

        self.orig_capsule_module = sys.modules.get('capsule')
        self.orig_capsule_path = None
        self.orig_capsules_dir = None
        self.orig_economy_dir = None
        self.orig_orgs_file = None
        self.orig_aliases = None

        self.capsule = _load_module(f'kernel_capsule_{uuid.uuid4().hex}', CAPSULE_PATH)
        self.orig_capsule_path = self.capsule.capsule_path
        self.orig_capsules_dir = self.capsule.CAPSULES_DIR
        self.orig_economy_dir = self.capsule.ECONOMY_DIR
        self.orig_orgs_file = self.capsule.ORGS_FILE
        self.orig_aliases = dict(self.capsule._CAPSULE_ALIASES)

        sys.modules['capsule'] = self.capsule
        self.capsule.ECONOMY_DIR = str(self.economy_dir)
        self.capsule.CAPSULES_DIR = str(self.capsules_dir)
        self.capsule.ORGS_FILE = str(self.kernel_dir / 'organizations.json')
        self.capsule._CAPSULE_ALIASES.clear()

        self.inbox = _load_module(f'kernel_federation_inbox_{uuid.uuid4().hex}', INBOX_PATH)

        self.org_a = f'org_inbox_a_{uuid.uuid4().hex[:8]}'
        self.org_b = f'org_inbox_b_{uuid.uuid4().hex[:8]}'
        self.capsule.init_capsule(self.org_a)
        self.capsule.init_capsule(self.org_b)

    def tearDown(self):
        self.capsule.ECONOMY_DIR = self.orig_economy_dir
        self.capsule.CAPSULES_DIR = self.orig_capsules_dir
        self.capsule.ORGS_FILE = self.orig_orgs_file
        self.capsule._CAPSULE_ALIASES.clear()
        self.capsule._CAPSULE_ALIASES.update(self.orig_aliases)
        if self.orig_capsule_module is None:
            sys.modules.pop('capsule', None)
        else:
            sys.modules['capsule'] = self.orig_capsule_module
        self.tmpdir.cleanup()

    def _entry(self, envelope_id, *, message_type='execution_request', state='received',
               receipt_id='rcpt_1', accepted_at='2026-03-22T00:00:00Z',
               processed_at='', payload=None):
        return {
            'envelope_id': envelope_id,
            'source_host_id': 'host_alpha',
            'source_institution_id': self.org_a,
            'target_host_id': 'host_beta',
            'target_institution_id': self.org_a,
            'message_type': message_type,
            'warrant_id': 'war_demo',
            'commitment_id': 'cmt_demo',
            'payload': payload if payload is not None else {'demo': envelope_id},
            'receipt_id': receipt_id,
            'accepted_at': accepted_at,
            'processed_at': processed_at,
            'state': state,
        }

    def test_org_isolation_uses_capsule_scoped_files(self):
        record = self.inbox.upsert_inbox_entry(self.org_a, self._entry('fed_org_a'))
        self.assertEqual(record['envelope_id'], 'fed_org_a')

        org_a_path = pathlib.Path(self.capsule.capsule_path(self.org_a, 'federation_inbox.json'))
        org_b_path = pathlib.Path(self.capsule.capsule_path(self.org_b, 'federation_inbox.json'))

        self.assertTrue(org_a_path.exists())
        self.assertTrue(org_b_path.exists())
        self.assertEqual(self.inbox.load_inbox_entries(self.org_a)[0]['envelope_id'], 'fed_org_a')
        self.assertEqual(self.inbox.load_inbox_entries(self.org_b), [])
        self.assertNotEqual(org_a_path, org_b_path)
        self.assertEqual(self.inbox.summarize_inbox_entries(self.org_b)['total'], 0)

    def test_upsert_is_idempotent_by_envelope_id(self):
        first = self.inbox.upsert_inbox_entry(self.org_a, self._entry('fed_idem'))
        self.assertEqual(first['state'], 'received')

        second = self.inbox.upsert_inbox_entry(
            self.org_a,
            self._entry(
                'fed_idem',
                receipt_id='rcpt_2',
                accepted_at='2026-03-22T00:01:00Z',
                processed_at='2026-03-22T00:02:00Z',
                state='processed',
            ),
        )

        entries = self.inbox.load_inbox_entries(self.org_a)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['envelope_id'], 'fed_idem')
        self.assertEqual(entries[0]['receipt_id'], 'rcpt_2')
        self.assertEqual(entries[0]['state'], 'processed')
        self.assertEqual(entries[0]['processed_at'], '2026-03-22T00:02:00Z')
        self.assertEqual(second['envelope_id'], 'fed_idem')

    def test_summary_counts_by_message_type(self):
        self.inbox.upsert_inbox_entry(self.org_a, self._entry('fed_exec_1', message_type='execution_request'))
        self.inbox.upsert_inbox_entry(self.org_a, self._entry('fed_exec_2', message_type='execution_request'))
        self.inbox.upsert_inbox_entry(self.org_a, self._entry('fed_settle_1', message_type='settlement_notice'))

        summary = self.inbox.summarize_inbox_entries(self.org_a)
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['message_type_counts'], {
            'execution_request': 2,
            'settlement_notice': 1,
        })
        self.assertEqual(summary['received'], 3)
        self.assertEqual(summary['processed'], 0)


if __name__ == '__main__':
    unittest.main()
