#!/usr/bin/env python3
"""Tests for the InstitutionContext runtime primitive."""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, ROOT)


def _make_org(org_id='org_1', slug='test', name='Test Org', status='active',
              lifecycle_state='active', owner_id='user_1'):
    return {
        'id': org_id, 'slug': slug, 'name': name,
        'status': status, 'lifecycle_state': lifecycle_state,
        'owner_id': owner_id, 'members': [{'user_id': owner_id, 'role': 'owner'}],
    }


class ServiceBoundaryTests(unittest.TestCase):

    def test_valid_boundary_creation(self):
        from institution_context import ServiceBoundary
        b = ServiceBoundary('test', 'session', 'institution_bound', 'desc')
        self.assertEqual(b.name, 'test')
        self.assertEqual(b.identity_model, 'session')
        self.assertEqual(b.scope, 'institution_bound')
        self.assertEqual(b.description, 'desc')

    def test_rejects_invalid_identity_model(self):
        from institution_context import ServiceBoundary
        with self.assertRaises(ValueError):
            ServiceBoundary('test', 'magic_token', 'institution_bound')

    def test_rejects_invalid_scope(self):
        from institution_context import ServiceBoundary
        with self.assertRaises(ValueError):
            ServiceBoundary('test', 'session', 'galactic')

    def test_to_dict(self):
        from institution_context import ServiceBoundary
        b = ServiceBoundary('ws', 'session', 'institution_bound', 'Workspace')
        d = b.to_dict()
        self.assertEqual(d['name'], 'ws')
        self.assertEqual(d['identity_model'], 'session')
        self.assertEqual(d['scope'], 'institution_bound')
        self.assertEqual(d['description'], 'Workspace')

    def test_to_dict_omits_empty_description(self):
        from institution_context import ServiceBoundary
        b = ServiceBoundary('ws', 'session', 'institution_bound')
        d = b.to_dict()
        self.assertNotIn('description', d)

    def test_all_identity_models_accepted(self):
        from institution_context import ServiceBoundary, IDENTITY_MODELS
        for model in IDENTITY_MODELS:
            b = ServiceBoundary('test', model, 'institution_bound')
            self.assertEqual(b.identity_model, model)

    def test_all_scopes_accepted(self):
        from institution_context import ServiceBoundary, BOUNDARY_SCOPES
        for scope in BOUNDARY_SCOPES:
            b = ServiceBoundary('test', 'session', scope)
            self.assertEqual(b.scope, scope)


class InstitutionContextCreationTests(unittest.TestCase):

    def test_bind_active_org(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'configured_org', WORKSPACE_BOUNDARY)
        self.assertTrue(ctx.is_admitted)
        self.assertEqual(ctx.org_id, 'org_1')
        self.assertEqual(ctx.context_source, 'configured_org')
        self.assertEqual(ctx.identity_model, 'session')
        self.assertEqual(ctx.scope, 'institution_bound')

    def test_bind_rejects_none_org_id(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        with self.assertRaises(RuntimeError):
            InstitutionContext.bind(None, None, 'test', WORKSPACE_BOUNDARY)

    def test_bind_rejects_none_org_record(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        with self.assertRaises(RuntimeError):
            InstitutionContext.bind('org_1', None, 'test', WORKSPACE_BOUNDARY)

    def test_bind_rejects_suspended_org(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org(status='suspended')
        with self.assertRaises(RuntimeError) as cm:
            InstitutionContext.bind('org_1', org, 'test', WORKSPACE_BOUNDARY)
        self.assertIn('suspended', str(cm.exception))

    def test_bind_rejects_dissolved_org(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org(lifecycle_state='dissolved')
        with self.assertRaises(RuntimeError) as cm:
            InstitutionContext.bind('org_1', org, 'test', WORKSPACE_BOUNDARY)
        self.assertIn('dissolved', str(cm.exception))

    def test_bind_rejects_lifecycle_suspended_org(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org(lifecycle_state='suspended')
        with self.assertRaises(RuntimeError) as cm:
            InstitutionContext.bind('org_1', org, 'test', WORKSPACE_BOUNDARY)
        self.assertIn('suspended', str(cm.exception))


class InstitutionContextAdmissionTests(unittest.TestCase):

    def test_admits_own_org(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'test', WORKSPACE_BOUNDARY)
        self.assertTrue(ctx.admits_org('org_1'))

    def test_rejects_different_org(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'test', WORKSPACE_BOUNDARY)
        self.assertFalse(ctx.admits_org('org_other'))

    def test_founding_service_admits_only_bound_org(self):
        from institution_context import InstitutionContext, MCP_SERVICE_BOUNDARY
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'test', MCP_SERVICE_BOUNDARY)
        self.assertTrue(ctx.admits_org('org_1'))
        self.assertFalse(ctx.admits_org('org_other'))

    def test_unscoped_admits_nobody(self):
        from institution_context import InstitutionContext, ServiceBoundary
        boundary = ServiceBoundary('internal', 'daemon', 'unscoped')
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'test', boundary)
        self.assertFalse(ctx.admits_org('org_1'))
        self.assertFalse(ctx.admits_org('org_other'))


class InstitutionContextCrossOrgTests(unittest.TestCase):

    def test_reject_cross_org_raises_for_different_org(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'test', WORKSPACE_BOUNDARY)
        with self.assertRaises(ValueError) as cm:
            ctx.reject_cross_org('org_other')
        self.assertIn('org_other', str(cm.exception))
        self.assertIn('org_1', str(cm.exception))

    def test_reject_cross_org_passes_for_same_org(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'test', WORKSPACE_BOUNDARY)
        ctx.reject_cross_org('org_1')  # should not raise

    def test_reject_cross_org_passes_for_none(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'test', WORKSPACE_BOUNDARY)
        ctx.reject_cross_org(None)  # should not raise


class InstitutionContextSerializationTests(unittest.TestCase):

    def test_to_dict_contains_all_fields(self):
        from institution_context import InstitutionContext, WORKSPACE_BOUNDARY
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'configured_org', WORKSPACE_BOUNDARY)
        d = ctx.to_dict()
        self.assertEqual(d['org_id'], 'org_1')
        self.assertEqual(d['institution_name'], 'Test Org')
        self.assertEqual(d['institution_slug'], 'test')
        self.assertEqual(d['context_source'], 'configured_org')
        self.assertEqual(d['identity_model'], 'session')
        self.assertEqual(d['boundary_scope'], 'institution_bound')
        self.assertEqual(d['boundary_name'], 'workspace')
        self.assertTrue(d['is_admitted'])
        self.assertEqual(d['lifecycle_state'], 'active')

    def test_describe_boundary_marks_routable(self):
        from institution_context import describe_boundary, WORKSPACE_BOUNDARY
        d = describe_boundary(WORKSPACE_BOUNDARY)
        self.assertTrue(d['supports_institution_routing'])
        self.assertTrue(d['requires_admitted_institution'])

    def test_service_boundary_registry_contains_known_boundaries(self):
        from institution_context import service_boundary_registry
        registry = service_boundary_registry()
        self.assertIn('workspace', registry)
        self.assertIn('mcp_service', registry)
        self.assertIn('payment_monitor', registry)
        self.assertIn('subscriptions', registry)
        self.assertIn('accounting', registry)
        self.assertIn('cli', registry)
        self.assertTrue(registry['workspace']['supports_institution_routing'])
        self.assertFalse(registry['mcp_service']['supports_institution_routing'])
        self.assertTrue(registry['subscriptions']['supports_institution_routing'])
        self.assertTrue(registry['accounting']['supports_institution_routing'])
        self.assertEqual(registry['subscriptions']['identity_model'], 'session')
        self.assertEqual(registry['accounting']['identity_model'], 'session')

    def test_runtime_core_snapshot_for_process_bound_admission(self):
        from institution_context import (
            InstitutionContext,
            WORKSPACE_BOUNDARY,
            runtime_core_snapshot,
        )
        from runtime_host import default_host_identity
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'configured_org', WORKSPACE_BOUNDARY)
        host = default_host_identity(host_id='host_alpha', federation_enabled=True)
        snap = runtime_core_snapshot(
            ctx,
            additional_institutions_allowed=True,
            host_identity=host,
            admission_registry={
                'source': 'file',
                'host_id': 'host_alpha',
                'institutions': {
                    'org_1': {'status': 'admitted'},
                    'org_2': {'status': 'admitted'},
                },
                'admitted_org_ids': ['org_1', 'org_2'],
            },
        )
        self.assertEqual(snap['institution_context']['org_id'], 'org_1')
        self.assertEqual(snap['host_identity']['host_id'], 'host_alpha')
        self.assertEqual(snap['current_boundary']['name'], 'workspace')
        self.assertEqual(snap['admission']['mode'], 'single_process_per_institution')
        self.assertTrue(snap['admission']['additional_institutions_allowed'])
        self.assertEqual(snap['admission']['host_id'], 'host_alpha')
        self.assertEqual(snap['admission']['admission_source'], 'file')
        self.assertEqual(snap['admission']['admitted_org_ids'], ['org_1', 'org_2'])

    def test_runtime_core_snapshot_for_single_institution_deployment(self):
        from institution_context import (
            InstitutionContext,
            MCP_SERVICE_BOUNDARY,
            runtime_core_snapshot,
        )
        from runtime_host import default_host_identity
        org = _make_org()
        ctx = InstitutionContext.bind('org_1', org, 'founding_default', MCP_SERVICE_BOUNDARY)
        host = default_host_identity(host_id='host_live')
        snap = runtime_core_snapshot(
            ctx,
            host_identity=host,
            admission_registry={
                'source': 'derived_bound_default',
                'host_id': 'host_live',
                'institutions': {'org_1': {'status': 'admitted'}},
                'admitted_org_ids': ['org_1'],
            },
        )
        self.assertEqual(snap['admission']['mode'], 'single_institution_deployment')
        self.assertFalse(snap['admission']['additional_institutions_allowed'])
        self.assertIn('does not admit additional institutions', snap['admission']['second_institution_path'])
        self.assertEqual(snap['admission']['host_id'], 'host_live')
        self.assertTrue(snap['service_registry']['payment_monitor']['requires_admitted_institution'])


class InstitutionContextResolveTests(unittest.TestCase):
    """Tests for InstitutionContext.resolve() which loads from the org registry."""

    def setUp(self):
        import institution_context as mod
        self._orig_load_orgs = mod.load_orgs
        self._orig_get_org = mod.get_org

    def tearDown(self):
        import institution_context as mod
        mod.load_orgs = self._orig_load_orgs
        mod.get_org = self._orig_get_org

    def test_resolve_with_configured_org_id(self):
        import institution_context as mod
        org = _make_org()
        mod.get_org = lambda oid: org if oid == 'org_1' else None
        ctx = mod.InstitutionContext.resolve(mod.WORKSPACE_BOUNDARY, configured_org_id='org_1')
        self.assertEqual(ctx.org_id, 'org_1')
        self.assertEqual(ctx.context_source, 'configured_org')

    def test_resolve_configured_org_not_found(self):
        import institution_context as mod
        mod.get_org = lambda oid: None
        with self.assertRaises(RuntimeError) as cm:
            mod.InstitutionContext.resolve(mod.WORKSPACE_BOUNDARY, configured_org_id='org_missing')
        self.assertIn('not found', str(cm.exception))

    def test_resolve_founding_default(self):
        import institution_context as mod
        org = _make_org()
        mod.load_orgs = lambda: {'organizations': {'org_1': org}}
        ctx = mod.InstitutionContext.resolve(mod.WORKSPACE_BOUNDARY)
        self.assertEqual(ctx.org_id, 'org_1')
        self.assertEqual(ctx.context_source, 'founding_default')

    def test_resolve_no_orgs_raises(self):
        import institution_context as mod
        mod.load_orgs = lambda: {'organizations': {}}
        with self.assertRaises(RuntimeError) as cm:
            mod.InstitutionContext.resolve(mod.WORKSPACE_BOUNDARY)
        self.assertIn('No institution registered', str(cm.exception))


class PredefinedBoundaryTests(unittest.TestCase):
    """Verify the predefined boundary declarations have correct values."""

    def test_workspace_boundary(self):
        from institution_context import WORKSPACE_BOUNDARY
        self.assertEqual(WORKSPACE_BOUNDARY.identity_model, 'session')
        self.assertEqual(WORKSPACE_BOUNDARY.scope, 'institution_bound')

    def test_mcp_service_boundary(self):
        from institution_context import MCP_SERVICE_BOUNDARY
        self.assertEqual(MCP_SERVICE_BOUNDARY.identity_model, 'x402_payment')
        self.assertEqual(MCP_SERVICE_BOUNDARY.scope, 'founding_service_only')

    def test_payment_monitor_boundary(self):
        from institution_context import PAYMENT_MONITOR_BOUNDARY
        self.assertEqual(PAYMENT_MONITOR_BOUNDARY.identity_model, 'daemon')
        self.assertEqual(PAYMENT_MONITOR_BOUNDARY.scope, 'founding_service_only')

    def test_subscriptions_boundary(self):
        from institution_context import SUBSCRIPTIONS_BOUNDARY
        self.assertEqual(SUBSCRIPTIONS_BOUNDARY.identity_model, 'session')
        self.assertEqual(SUBSCRIPTIONS_BOUNDARY.scope, 'institution_bound')

    def test_accounting_boundary(self):
        from institution_context import ACCOUNTING_BOUNDARY
        self.assertEqual(ACCOUNTING_BOUNDARY.identity_model, 'session')
        self.assertEqual(ACCOUNTING_BOUNDARY.scope, 'institution_bound')

    def test_cli_boundary(self):
        from institution_context import CLI_BOUNDARY
        self.assertEqual(CLI_BOUNDARY.identity_model, 'credential')
        self.assertEqual(CLI_BOUNDARY.scope, 'institution_bound')


if __name__ == '__main__':
    unittest.main()
