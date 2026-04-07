#!/usr/bin/env python3
import json
import os
import tempfile
import unittest
from unittest import mock

import organizations
import organizations_store


class TestOrganizations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig_orgs_file = organizations.ORGS_FILE
        organizations.ORGS_FILE = os.path.join(self.tmp.name, 'organizations.json')

    def tearDown(self):
        organizations.ORGS_FILE = self.orig_orgs_file
        self.tmp.cleanup()

    @mock.patch('uuid.uuid4')
    def test_create_org(self, mock_uuid):
        mock_uuid.return_value.hex = '1234567890abcdef'
        org_id = organizations.create_org('Acme Corp', 'user_123', plan='pro')

        self.assertEqual(org_id, 'org_12345678')

        org = organizations.get_org(org_id)
        self.assertIsNotNone(org)
        self.assertEqual(org['name'], 'Acme Corp')
        self.assertEqual(org['slug'], 'acme-corp')
        self.assertEqual(org['owner_id'], 'user_123')
        self.assertEqual(org['plan'], 'pro')
        self.assertEqual(org['status'], 'active')
        self.assertEqual(len(org['members']), 1)
        self.assertEqual(org['members'][0]['user_id'], 'user_123')
        self.assertEqual(org['members'][0]['role'], 'owner')

    @mock.patch('uuid.uuid4')
    def test_create_org_duplicate_slug(self, mock_uuid):
        mock_uuid.return_value.hex = '11111111'
        organizations.create_org('Acme Corp', 'user_123')

        mock_uuid.return_value.hex = '22222222'
        org_id_2 = organizations.create_org('Acme Corp', 'user_456')

        org2 = organizations.get_org(org_id_2)
        self.assertEqual(org2['slug'], 'acme-corp-2222')

    def test_get_org(self):
        org_id = organizations.create_org('Test Org', 'user_1')
        org = organizations.get_org(org_id)
        self.assertIsNotNone(org)
        self.assertEqual(org['name'], 'Test Org')

        not_found = organizations.get_org('org_does_not_exist')
        self.assertIsNone(not_found)

    def test_list_orgs(self):
        organizations.create_org('Org 1', 'user_1', plan='free')
        organizations.create_org('Org 2', 'user_2', plan='pro')

        orgs = organizations.list_orgs()
        self.assertEqual(len(orgs), 2)

        orgs[0]['status'] = 'suspended'
        organizations.save_orgs({'organizations': {o['id']: o for o in orgs}, 'updatedAt': organizations._now()})

        active_orgs = organizations.list_orgs(status_filter='active')
        self.assertEqual(len(active_orgs), 1)
        self.assertEqual(active_orgs[0]['name'], 'Org 2')

    def test_add_member(self):
        org_id = organizations.create_org('Org 1', 'user_1')

        organizations.add_member(org_id, 'user_2', role='admin')
        org = organizations.get_org(org_id)

        self.assertEqual(len(org['members']), 2)
        admin_member = next(m for m in org['members'] if m['user_id'] == 'user_2')
        self.assertEqual(admin_member['role'], 'admin')

        # Add duplicate member, should update role
        organizations.add_member(org_id, 'user_2', role='viewer')
        org = organizations.get_org(org_id)
        self.assertEqual(len(org['members']), 2)
        viewer_member = next(m for m in org['members'] if m['user_id'] == 'user_2')
        self.assertEqual(viewer_member['role'], 'viewer')

        with self.assertRaises(ValueError):
            organizations.add_member(org_id, 'user_3', role='invalid_role')

        with self.assertRaises(ValueError):
            organizations.add_member('invalid_org', 'user_3', role='member')

    def test_update_org(self):
        org_id = organizations.create_org('Org 1', 'user_1', plan='free')

        organizations.update_org(org_id, name='New Name', plan='pro', status='suspended')

        org = organizations.get_org(org_id)
        self.assertEqual(org['name'], 'New Name')
        self.assertEqual(org['plan'], 'pro')
        self.assertEqual(org['status'], 'suspended')

        with self.assertRaises(ValueError):
            organizations.update_org(org_id, plan='invalid_plan')

        with self.assertRaises(ValueError):
            organizations.update_org(org_id, status='invalid_status')

        with self.assertRaises(ValueError):
            organizations.update_org('invalid_org', name='name')

    def test_get_org_for_user(self):
        org_id_1 = organizations.create_org('Org 1', 'user_1')
        org_id_2 = organizations.create_org('Org 2', 'user_2')
        organizations.add_member(org_id_2, 'user_1')

        # Suspend org 1
        organizations.update_org(org_id_1, status='suspended')

        # Should return active org 2 since org 1 is suspended
        org = organizations.get_org_for_user('user_1')
        self.assertIsNotNone(org)
        self.assertEqual(org['id'], org_id_2)

        org = organizations.get_org_for_user('user_3')
        self.assertIsNone(org)

    def test_set_charter(self):
        org_id = organizations.create_org('Org 1', 'user_1')

        organizations.set_charter(org_id, 'New Charter Text')
        org = organizations.get_org(org_id)
        self.assertEqual(org['charter'], 'New Charter Text')

        with self.assertRaises(ValueError):
            organizations.set_charter('invalid_org', 'text')

    def test_set_policy_defaults(self):
        org_id = organizations.create_org('Org 1', 'user_1')

        organizations.set_policy_defaults(org_id, max_budget_per_agent_usd=50.0, auto_sanctions_enabled=False)
        org = organizations.get_org(org_id)

        self.assertEqual(org['policy_defaults']['max_budget_per_agent_usd'], 50.0)
        self.assertFalse(org['policy_defaults']['auto_sanctions_enabled'])
        # Should retain original defaults for unprovided keys
        self.assertEqual(org['policy_defaults']['require_approval_above_usd'], 5.0)

        with self.assertRaises(ValueError):
            organizations.set_policy_defaults('invalid_org', max_budget_per_agent_usd=50.0)

    def test_transition_lifecycle(self):
        org_id = organizations.create_org('Org 1', 'user_1')
        # newly created orgs start in 'active'
        org = organizations.get_org(org_id)
        self.assertEqual(org['lifecycle_state'], 'active')

        # Test valid transition active -> suspended
        organizations.transition_lifecycle(org_id, 'suspended')
        self.assertEqual(organizations.get_org(org_id)['lifecycle_state'], 'suspended')

        # Test valid transition suspended -> dissolved
        organizations.transition_lifecycle(org_id, 'dissolved')
        self.assertEqual(organizations.get_org(org_id)['lifecycle_state'], 'dissolved')

        # Test invalid transition dissolved -> active
        with self.assertRaises(ValueError):
            organizations.transition_lifecycle(org_id, 'active')

        with self.assertRaises(ValueError):
            organizations.transition_lifecycle(org_id, 'invalid_state')

        with self.assertRaises(ValueError):
            organizations.transition_lifecycle('invalid_org', 'suspended')

    @mock.patch('uuid.uuid4')
    def test_sqlite_mirror_survives_missing_json_file(self, mock_uuid):
        mock_uuid.return_value.hex = '1234567890abcdef'
        org_id = organizations.create_org('Acme Corp', 'user_123', plan='pro')

        db_path = organizations_store.db_path_for_file(organizations.ORGS_FILE)
        self.assertTrue(os.path.exists(db_path))

        os.remove(organizations.ORGS_FILE)
        reloaded = organizations.get_org(org_id)

        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded['id'], org_id)
        self.assertEqual(reloaded['name'], 'Acme Corp')
        self.assertEqual(reloaded['plan'], 'pro')

if __name__ == '__main__':
    unittest.main()
