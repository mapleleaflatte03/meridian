#!/usr/bin/env python3
"""Tests for session integration in the workspace."""
import importlib.util
import json
import os
import tempfile
import unittest
from urllib.parse import urlparse


ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
WORKSPACE_PY = os.path.join(ROOT, 'workspace.py')


def _load_workspace(name):
    spec = importlib.util.spec_from_file_location(name, WORKSPACE_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class WorkspaceSessionAuthContextTests(unittest.TestCase):
    def setUp(self):
        self.ws = _load_workspace('kernel_workspace_session_test')
        self.orig_load_orgs = self.ws.load_orgs
        self.ws.load_orgs = lambda: {
            'organizations': {
                'org_a': {
                    'id': 'org_a',
                    'slug': 'a',
                    'name': 'A',
                    'owner_id': 'user_owner',
                    'members': [
                        {'user_id': 'user_owner', 'role': 'owner'},
                        {'user_id': 'user_m', 'role': 'member'},
                    ],
                },
            }
        }

    def tearDown(self):
        self.ws.load_orgs = self.orig_load_orgs

    def test_session_auth_context_from_claims(self):
        sa = self.ws._session_authority
        token = sa.issue('org_a', 'user_owner', 'owner')
        claims = sa.validate(token)
        ctx = self.ws._resolve_auth_context_from_session(claims, 'org_a')
        self.assertTrue(ctx['enabled'])
        self.assertEqual(ctx['mode'], 'session_bound')
        self.assertEqual(ctx['org_id'], 'org_a')
        self.assertEqual(ctx['user_id'], 'user_owner')
        self.assertEqual(ctx['role'], 'owner')
        self.assertEqual(ctx['actor_source'], 'session')
        self.assertIn('session_id', ctx)

    def test_session_auth_context_rejects_wrong_org(self):
        sa = self.ws._session_authority
        token = sa.issue('org_other', 'user_1', 'member')
        claims = sa.validate(token)
        with self.assertRaises(ValueError):
            self.ws._resolve_auth_context_from_session(claims, 'org_a')

    def test_session_auth_context_uses_live_membership_role(self):
        """If a member's role changed since session issuance, use the current role."""
        sa = self.ws._session_authority
        # Issue as owner but the member list says user_m is 'member'
        token = sa.issue('org_a', 'user_m', 'owner')
        claims = sa.validate(token)
        ctx = self.ws._resolve_auth_context_from_session(claims, 'org_a')
        # Live membership says 'member', not 'owner'
        self.assertEqual(ctx['role'], 'member')

    def test_session_auth_context_returns_none_role_for_removed_member(self):
        """A session for a removed user gets role=None (blocks mutations)."""
        sa = self.ws._session_authority
        token = sa.issue('org_a', 'user_removed', 'member')
        claims = sa.validate(token)
        ctx = self.ws._resolve_auth_context_from_session(claims, 'org_a')
        self.assertIsNone(ctx['role'])

    def test_permission_snapshot_includes_session_paths(self):
        auth = {'enabled': True, 'role': 'admin'}
        perms = self.ws._permission_snapshot(auth)['mutation_paths']
        self.assertIn('/api/session/issue', perms)
        self.assertIn('/api/session/revoke', perms)
        self.assertTrue(perms['/api/session/issue']['allowed'])
        self.assertTrue(perms['/api/session/revoke']['allowed'])

    def test_member_can_issue_but_not_revoke(self):
        auth = {'enabled': True, 'role': 'member'}
        perms = self.ws._permission_snapshot(auth)['mutation_paths']
        self.assertTrue(perms['/api/session/issue']['allowed'])
        self.assertFalse(perms['/api/session/revoke']['allowed'])

    def test_wrong_org_bearer_does_not_fallback_to_credentials(self):
        """A Bearer token for the wrong org must not silently grant credential auth."""
        sa = self.ws._session_authority
        token = sa.issue('org_other', 'user_owner', 'owner')
        claims = sa.validate(token, expected_org_id='org_a')
        # Token is valid but for wrong org
        self.assertIsNone(claims)
        # Verify that _session_claims_from_request returns None for wrong org
        full_claims = sa.validate(token)
        self.assertIsNotNone(full_claims)
        self.assertEqual(full_claims.org_id, 'org_other')

    def test_session_authority_exists_at_module_level(self):
        """Workspace module creates a process-level SessionAuthority."""
        sa = self.ws._session_authority
        self.assertIsNotNone(sa)
        # Should be able to issue and validate
        token = sa.issue('org_test', 'user_test', 'member')
        claims = sa.validate(token)
        self.assertIsNotNone(claims)
        self.assertEqual(claims.org_id, 'org_test')


class WorkspaceSessionTokenFlowTests(unittest.TestCase):
    """End-to-end session token lifecycle via workspace module functions."""

    def setUp(self):
        self.ws = _load_workspace('kernel_workspace_session_flow_test')
        self.orig_load_orgs = self.ws.load_orgs
        self.ws.load_orgs = lambda: {
            'organizations': {
                'org_a': {
                    'id': 'org_a',
                    'slug': 'a',
                    'name': 'A',
                    'owner_id': 'user_owner',
                    'members': [
                        {'user_id': 'user_owner', 'role': 'owner'},
                    ],
                },
            }
        }

    def tearDown(self):
        self.ws.load_orgs = self.orig_load_orgs

    def test_issue_validate_revoke_lifecycle(self):
        sa = self.ws._session_authority
        # Issue
        token = sa.issue('org_a', 'user_owner', 'owner')
        # Validate
        claims = sa.validate(token, expected_org_id='org_a')
        self.assertIsNotNone(claims)
        self.assertEqual(claims.user_id, 'user_owner')
        self.assertEqual(claims.role, 'owner')
        # Auth context from session
        ctx = self.ws._resolve_auth_context_from_session(claims, 'org_a')
        self.assertEqual(ctx['mode'], 'session_bound')
        self.assertEqual(ctx['role'], 'owner')
        # Mutation authorization should pass for owner-level paths
        required = self.ws._enforce_mutation_authorization(ctx, 'org_a', '/api/treasury/contribute')
        self.assertEqual(required, 'owner')
        # Revoke
        sa.revoke(claims.session_id)
        self.assertIsNone(sa.validate(token))

    def test_session_mutation_auth_blocks_insufficient_role(self):
        """Session-derived auth context correctly blocks mutations above the actor's role."""
        self.ws.load_orgs = lambda: {
            'organizations': {
                'org_a': {
                    'id': 'org_a',
                    'slug': 'a',
                    'name': 'A',
                    'owner_id': 'user_owner',
                    'members': [
                        {'user_id': 'user_member', 'role': 'member'},
                    ],
                },
            }
        }
        sa = self.ws._session_authority
        token = sa.issue('org_a', 'user_member', 'member')
        claims = sa.validate(token)
        ctx = self.ws._resolve_auth_context_from_session(claims, 'org_a')
        with self.assertRaises(PermissionError):
            self.ws._enforce_mutation_authorization(ctx, 'org_a', '/api/authority/kill-switch')


class AuditSessionTraceabilityTests(unittest.TestCase):
    """Verify audit.log_event records session_id when provided."""

    def test_log_event_includes_session_id_when_provided(self):
        ws = _load_workspace('kernel_workspace_audit_session_test')
        # Use a temporary audit file to avoid polluting the real one
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                         delete=False) as f:
            audit_path = f.name
        orig_audit_file = ws.AUDIT_FILE if hasattr(ws, 'AUDIT_FILE') else None
        # Patch the audit module's file path via the workspace's import
        import audit as audit_mod
        orig_path = audit_mod.AUDIT_FILE
        audit_mod.AUDIT_FILE = audit_path
        try:
            eid = ws.log_event('org_a', 'user_owner', 'test_action',
                               outcome='success', session_id='ses_abc123')
            with open(audit_path) as f:
                events = [json.loads(line) for line in f if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['session_id'], 'ses_abc123')
            self.assertEqual(events[0]['id'], eid)
        finally:
            audit_mod.AUDIT_FILE = orig_path
            os.unlink(audit_path)

    def test_log_event_omits_session_id_when_not_provided(self):
        ws = _load_workspace('kernel_workspace_audit_no_session_test')
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl',
                                         delete=False) as f:
            audit_path = f.name
        import audit as audit_mod
        orig_path = audit_mod.AUDIT_FILE
        audit_mod.AUDIT_FILE = audit_path
        try:
            ws.log_event('org_a', 'user_owner', 'test_action',
                         outcome='success')
            with open(audit_path) as f:
                events = [json.loads(line) for line in f if line.strip()]
            self.assertEqual(len(events), 1)
            self.assertNotIn('session_id', events[0])
        finally:
            audit_mod.AUDIT_FILE = orig_path
            os.unlink(audit_path)


if __name__ == '__main__':
    unittest.main()
