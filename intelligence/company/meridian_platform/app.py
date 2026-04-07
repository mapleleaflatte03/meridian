#!/usr/bin/env python3
"""Technical backbone for the Meridian public intelligence surface.

This module keeps the obvious surface contract for the live workspace together:
- public GET/POST routes for the intelligence surface
- the runtime service boundaries, including the MCP service boundary
- the mutation-role map enforced by the workspace handler
"""

PUBLIC_SURFACE_GET_ROUTES = (
    ('/', 'Dashboard HTML'),
    ('/api/status', 'Full system snapshot'),
    ('/api/context', 'Bound institution/runtime context'),
    ('/api/runtimes', 'Runtime registry with contract compliance and binding usage'),
    ('/api/institution/template', 'Institution template contract for constitutional deployments'),
    ('/api/institution/license/catalog', 'Institution-license catalog with pricing and boundary notes'),
    ('/api/subscriptions', 'Subscription service state'),
    ('/api/pilot/intake', 'Public pilot intake queue snapshot'),
    ('/api/federation/manifest', 'Public host federation manifest'),
    ('/api/runtime-proof', 'Public live Loom runtime proof receipt'),
    ('/api/runtime-proof-contract', 'Public bounded Loom surface-proof contract'),
    ('/api/kernel-proof-bundle', 'Public kernel reference proof bundle with live host receipts'),
)

PUBLIC_SURFACE_POST_ROUTES = (
    ('/api/pilot/intake', 'Public pilot intake submission with optional checkout preview publication'),
    ('/api/subscriptions/checkout-capture', 'Customer-initiated captured checkout activation with payment-evidence validation'),
    ('/api/institution/license/checkout-capture', 'Customer-initiated institution-license capture with payment-evidence validation'),
    ('/api/federation/receive', 'Inbound federation envelope validation/receipt'),
)

PUBLIC_UNAUTHENTICATED_PATHS = tuple(dict.fromkeys(
    ['/api/session/validate']
    + [path for path, _label in PUBLIC_SURFACE_GET_ROUTES if path.startswith('/api/')]
    + [path for path, _label in PUBLIC_SURFACE_POST_ROUTES if path.startswith('/api/')]
))

PUBLIC_UNAUTHENTICATED_PREFIXES = (
    '/api/runtimes/',
)

SUPPORTED_RUNTIME_BOUNDARIES = (
    'workspace',
    'cli',
    'federation_gateway',
    'mcp_service',
    'payment_monitor',
    'subscriptions',
    'accounting',
)

WORKSPACE_MUTATION_ROLE_REQUIREMENTS = {
    '/api/agents/update': 'admin',
    '/api/agents/budget': 'admin',
    '/api/agents/scopes': 'admin',
    '/api/agents/risk': 'admin',
    '/api/agents/lifecycle': 'admin',
    '/api/agents/incident': 'admin',
    '/api/agents/sync-economy': 'admin',
    '/api/authority/kill-switch': 'admin',
    '/api/authority/approve': 'admin',
    '/api/authority/request': 'member',
    '/api/authority/delegate': 'admin',
    '/api/authority/revoke': 'admin',
    '/api/court/file': 'member',
    '/api/court/resolve': 'admin',
    '/api/court/appeal': 'member',
    '/api/court/decide-appeal': 'admin',
    '/api/court/auto-review': 'admin',
    '/api/court/remediate': 'admin',
    '/api/warrants/issue': 'admin',
    '/api/warrants/approve': 'admin',
    '/api/warrants/stay': 'admin',
    '/api/warrants/revoke': 'admin',
    '/api/commitments/propose': 'admin',
    '/api/commitments/accept': 'admin',
    '/api/commitments/reject': 'admin',
    '/api/commitments/breach': 'admin',
    '/api/commitments/settle': 'admin',
    '/api/cases/open': 'admin',
    '/api/cases/stay': 'admin',
    '/api/cases/resolve': 'admin',
    '/api/federation/execution-jobs/execute': 'admin',
    '/api/treasury/contribute': 'owner',
    '/api/treasury/reserve-floor': 'owner',
    '/api/treasury/settlement-adapters/preflight': 'member',
    '/api/treasury/payout-plan-approval-candidate-queue/promote': 'admin',
    '/api/subscriptions/add': 'admin',
    '/api/subscriptions/draft-from-preview': 'admin',
    '/api/subscriptions/activate-from-preview': 'admin',
    '/api/subscriptions/loom-delivery-jobs/run': 'admin',
    '/api/subscriptions/convert': 'admin',
    '/api/subscriptions/verify-payment': 'admin',
    '/api/subscriptions/remove': 'admin',
    '/api/subscriptions/set-email': 'admin',
    '/api/subscriptions/record-delivery': 'admin',
    '/api/alerts/dispatch': 'admin',
    '/api/accounting/expense': 'owner',
    '/api/accounting/reimburse': 'owner',
    '/api/accounting/draw': 'owner',
    '/api/payouts/propose': 'member',
    '/api/payouts/submit': 'member',
    '/api/payouts/review': 'admin',
    '/api/payouts/approve': 'owner',
    '/api/payouts/open-dispute-window': 'owner',
    '/api/payouts/reject': 'admin',
    '/api/payouts/cancel': 'member',
    '/api/payouts/execute': 'owner',
    '/api/admission/admit': 'owner',
    '/api/admission/suspend': 'owner',
    '/api/admission/revoke': 'owner',
    '/api/federation/handoff-preview-queue/acknowledge': 'admin',
    '/api/federation/handoff-dispatch-queue/run': 'admin',
    '/api/federation/send': 'admin',
    '/api/federation/peers/upsert': 'owner',
    '/api/federation/peers/refresh': 'owner',
    '/api/federation/peers/suspend': 'owner',
    '/api/federation/peers/revoke': 'owner',
    '/api/institution/charter': 'admin',
    '/api/institution/lifecycle': 'owner',
    '/api/session/issue': 'member',
    '/api/session/revoke': 'admin',
}


def is_workspace_protected_path(path):
    return (
        (path == '/' or path.startswith('/workspace') or path.startswith('/api/'))
        and path not in PUBLIC_UNAUTHENTICATED_PATHS
        and not any(path.startswith(prefix) for prefix in PUBLIC_UNAUTHENTICATED_PREFIXES)
    )


def required_mutation_role(path):
    return WORKSPACE_MUTATION_ROLE_REQUIREMENTS.get(path, 'admin')
