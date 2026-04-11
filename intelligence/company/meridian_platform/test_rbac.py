#!/usr/bin/env python3
"""Tests for lightweight RBAC."""
import os
import sys
import unittest

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from rbac import (
    role_level, has_minimum_role, has_capability, get_capabilities,
    get_user_role, enforce_capability, permission_summary,
)


class TestRoleHierarchy(unittest.TestCase):
    def test_role_levels_are_ordered(self):
        self.assertGreater(role_level('owner'), role_level('admin'))
        self.assertGreater(role_level('admin'), role_level('operator'))
        self.assertGreater(role_level('operator'), role_level('member'))
        self.assertGreater(role_level('member'), role_level('viewer'))

    def test_unknown_role_returns_zero(self):
        self.assertEqual(role_level('nonexistent'), 0)

    def test_has_minimum_role_owner_meets_all(self):
        for role in ('owner', 'admin', 'operator', 'member', 'viewer'):
            self.assertTrue(has_minimum_role('owner', role))

    def test_member_does_not_meet_admin(self):
        self.assertFalse(has_minimum_role('member', 'admin'))

    def test_operator_meets_operator(self):
        self.assertTrue(has_minimum_role('operator', 'operator'))

    def test_operator_meets_member(self):
        self.assertTrue(has_minimum_role('operator', 'member'))

    def test_operator_does_not_meet_admin(self):
        self.assertFalse(has_minimum_role('operator', 'admin'))


class TestCapabilities(unittest.TestCase):
    def test_owner_has_treasury_write(self):
        self.assertTrue(has_capability('owner', 'treasury_write'))

    def test_admin_cannot_write_treasury(self):
        self.assertFalse(has_capability('admin', 'treasury_write'))

    def test_operator_can_run_agents(self):
        self.assertTrue(has_capability('operator', 'agent_run'))

    def test_member_cannot_run_agents(self):
        self.assertFalse(has_capability('member', 'agent_run'))

    def test_member_can_vote(self):
        self.assertTrue(has_capability('member', 'vote'))

    def test_viewer_cannot_vote(self):
        self.assertFalse(has_capability('viewer', 'vote'))

    def test_admin_can_admin_court(self):
        self.assertTrue(has_capability('admin', 'court_admin'))

    def test_operator_cannot_admin_court(self):
        self.assertFalse(has_capability('operator', 'court_admin'))


class TestEnforcement(unittest.TestCase):
    def test_enforce_raises_on_missing_capability(self):
        with self.assertRaises(PermissionError):
            enforce_capability('viewer', 'agent_run')

    def test_enforce_passes_on_valid_capability(self):
        enforce_capability('operator', 'agent_run')


class TestUserRole(unittest.TestCase):
    def test_get_user_role_returns_role(self):
        org = {'members': [
            {'user_id': 'u1', 'role': 'admin'},
            {'user_id': 'u2', 'role': 'operator'},
        ]}
        self.assertEqual(get_user_role(org, 'u1'), 'admin')
        self.assertEqual(get_user_role(org, 'u2'), 'operator')
        self.assertIsNone(get_user_role(org, 'u3'))


class TestPermissionSummary(unittest.TestCase):
    def test_summary_has_required_fields(self):
        s = permission_summary('operator')
        self.assertEqual(s['role'], 'operator')
        self.assertEqual(s['level'], 3)
        self.assertTrue(s['can_run_agents'])
        self.assertFalse(s['can_admin_court'])
        self.assertFalse(s['can_write_treasury'])
        self.assertTrue(s['can_vote'])


if __name__ == '__main__':
    unittest.main()
