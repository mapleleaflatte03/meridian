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
COURT_PATH = ROOT / 'kernel' / 'court.py'
CAPSULE_PATH = ROOT / 'kernel' / 'capsule.py'
LEGACY_RECORDS_PATH = ROOT / 'kernel' / 'court_records.json'
CAPSULES_DIR = ROOT / 'capsules'


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


court = _load_module('kernel_court_test', COURT_PATH)
capsule = _load_module('kernel_capsule_test_for_court', CAPSULE_PATH)


class CourtCapsuleTests(unittest.TestCase):
    def setUp(self):
        self.org_id = f'org_court_test_{uuid.uuid4().hex[:8]}'
        self.capsule_dir = CAPSULES_DIR / self.org_id
        capsule.init_capsule(self.org_id)

        ledger_path = pathlib.Path(capsule.capsule_path(self.org_id, 'ledger.json'))
        ledger = json.loads(ledger_path.read_text())
        ledger['updatedAt'] = '2026-03-21T00:00:00Z'
        ledger['epoch']['started_at'] = '2026-03-21T00:00:00Z'
        ledger['agents'] = {
            'atlas': {
                'name': 'Atlas',
                'role': 'analyst',
                'reputation_units': 50,
                'authority_units': 50,
                'probation': False,
                'zero_authority': False,
                'status': 'active',
            },
            'sentinel': {
                'name': 'Sentinel',
                'role': 'verifier',
                'reputation_units': 35,
                'authority_units': 6,
                'probation': False,
                'zero_authority': False,
                'status': 'active',
            },
        }
        ledger_path.write_text(json.dumps(ledger, indent=2))
        self.legacy_records_before = LEGACY_RECORDS_PATH.read_text() if LEGACY_RECORDS_PATH.exists() else ''

    def tearDown(self):
        shutil.rmtree(self.capsule_dir, ignore_errors=True)

    def _fake_modules(self):
        fake_registry = types.ModuleType('agent_registry')
        fake_registry.record_incident = lambda *_args, **_kwargs: None
        fake_registry.get_agent_by_economy_key = lambda *_args, **_kwargs: None
        fake_registry.load_registry = lambda: {'agents': {}}
        fake_registry.save_registry = lambda *_args, **_kwargs: None

        fake_audit = types.ModuleType('audit')
        fake_audit.log_event = lambda *_args, **_kwargs: None
        return fake_registry, fake_audit

    def test_file_violation_writes_only_to_capsule_records(self):
        fake_registry, fake_audit = self._fake_modules()

        with mock.patch.dict(sys.modules, {
            'agent_registry': fake_registry,
            'audit': fake_audit,
        }, clear=False):
            violation_id = court.file_violation(
                agent_id='atlas',
                org_id=self.org_id,
                violation_type='rejected_output',
                severity=3,
                evidence='capsule scoped violation',
                policy_ref='test',
            )

        records_path = pathlib.Path(capsule.capsule_path(self.org_id, 'court_records.json'))
        records = json.loads(records_path.read_text())
        self.assertIn(violation_id, records['violations'])
        self.assertEqual(records['violations'][violation_id]['org_id'], self.org_id)
        current_legacy_records = LEGACY_RECORDS_PATH.read_text() if LEGACY_RECORDS_PATH.exists() else ''
        self.assertEqual(current_legacy_records, self.legacy_records_before)

    def test_decide_appeal_lifts_capsule_scoped_sanction(self):
        fake_registry, fake_audit = self._fake_modules()

        with mock.patch.dict(sys.modules, {
            'agent_registry': fake_registry,
            'audit': fake_audit,
        }, clear=False):
            violation_id = court.file_violation(
                agent_id='sentinel',
                org_id=self.org_id,
                violation_type='false_confidence',
                severity=5,
                evidence='wrong claim',
                policy_ref='test',
            )
            appeal_id = court.file_appeal(
                violation_id=violation_id,
                agent_id='sentinel',
                grounds='evidence was incorrect',
                org_id=self.org_id,
            )
            court.decide_appeal(
                appeal_id=appeal_id,
                decision='overturned',
                decided_by='main',
                org_id=self.org_id,
            )

        ledger_path = pathlib.Path(capsule.capsule_path(self.org_id, 'ledger.json'))
        ledger = json.loads(ledger_path.read_text())
        self.assertFalse(ledger['agents']['sentinel'].get('zero_authority'))
        self.assertGreaterEqual(ledger['agents']['sentinel']['authority_units'], 1)

        records_path = pathlib.Path(capsule.capsule_path(self.org_id, 'court_records.json'))
        records = json.loads(records_path.read_text())
        self.assertEqual(records['appeals'][appeal_id]['status'], 'overturned')
        self.assertEqual(records['violations'][violation_id]['status'], 'dismissed')

    def test_missing_org_fails_cleanly(self):
        with self.assertRaises(SystemExit) as ctx:
            court._load_records(f'org_missing_{uuid.uuid4().hex[:8]}')
        self.assertIn('is not initialized', str(ctx.exception))

    def test_load_records_migrates_legacy_records_for_founding_alias(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = pathlib.Path(tmpdir)
            economy_dir = tmpdir / 'economy'
            economy_dir.mkdir()
            legacy_records = tmpdir / 'court_records.json'
            legacy_payload = {
                'violations': {'vio_seed': {'status': 'open'}},
                'appeals': {},
                'updatedAt': '2026-03-21T00:00:00Z',
            }
            legacy_records.write_text(json.dumps(legacy_payload, indent=2))

            def fake_capsule_path(org_id, filename):
                return str(economy_dir / filename)

            with mock.patch.object(court, 'ECONOMY_DIR', str(economy_dir)), \
                 mock.patch.object(court, 'LEGACY_RECORDS_FILE', str(legacy_records)), \
                 mock.patch.object(court, 'capsule_path', side_effect=fake_capsule_path):
                records = court._load_records('org_b7d95bae')

            migrated_path = economy_dir / 'court_records.json'
            self.assertTrue(migrated_path.exists())
            self.assertEqual(records['violations']['vio_seed']['status'], 'open')


if __name__ == '__main__':
    unittest.main()
