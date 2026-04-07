"""
Institution context — runtime primitive for institution-scoped identity.

Every Meridian service or internal boundary operates in the context of an
institution and an identity model. This module provides:

  ServiceBoundary — declares what identity model a boundary uses and whether
                    it supports institution routing.

  InstitutionContext — resolves and validates which institution a process or
                       request acts for. Carries the ServiceBoundary so the
                       full identity/scope/admission answer is available at
                       any point in the request pipeline.

  Runtime-core helpers — expose a machine-readable boundary registry and
                         runtime admission state so deployments can surface
                         honest answers about which boundaries are routable
                         today and how additional institutions would be
                         admitted without cross-org bleed.
"""
import os
import sys

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)
from organizations import load_orgs, get_org

IDENTITY_MODELS = (
    'session',
    'credential',
    'x402_payment',
    'daemon',
    'signed_host_service',
    'none',
)

BOUNDARY_SCOPES = (
    'institution_bound',
    'federation_gateway',
    'founding_service_only',
    'daemon_only',
    'unscoped',
)


class ServiceBoundary:
    __slots__ = ('name', 'identity_model', 'scope', 'description', 'requires_warrant_for_messages')

    def __init__(self, name, identity_model, scope, description='', *, requires_warrant_for_messages=None):
        if identity_model not in IDENTITY_MODELS:
            raise ValueError(
                f'Unknown identity_model {identity_model!r}. '
                f'Must be one of {IDENTITY_MODELS}'
            )
        if scope not in BOUNDARY_SCOPES:
            raise ValueError(
                f'Unknown scope {scope!r}. Must be one of {BOUNDARY_SCOPES}'
            )
        self.name = name
        self.identity_model = identity_model
        self.scope = scope
        self.description = description
        self.requires_warrant_for_messages = dict(requires_warrant_for_messages or {})

    def to_dict(self):
        d = {
            'name': self.name,
            'identity_model': self.identity_model,
            'scope': self.scope,
        }
        if self.description:
            d['description'] = self.description
        return d


class InstitutionContext:
    __slots__ = ('org_id', 'org', 'context_source', 'boundary', '_admitted')

    def __init__(self, org_id, org, context_source, boundary):
        self.org_id = org_id
        self.org = org
        self.context_source = context_source
        self.boundary = boundary
        self._admitted = org_id is not None and org is not None

    @classmethod
    def bind(cls, org_id, org, context_source, boundary):
        ctx = cls(org_id, org, context_source, boundary)
        ctx.validate()
        return ctx

    @classmethod
    def resolve(cls, boundary, configured_org_id=None):
        if configured_org_id:
            org = get_org(configured_org_id)
            if not org:
                raise RuntimeError(
                    f'Configured institution not found: {configured_org_id}'
                )
            return cls.bind(configured_org_id, org, 'configured_org', boundary)

        orgs = load_orgs()
        for oid, org in orgs.get('organizations', {}).items():
            return cls.bind(oid, org, 'founding_default', boundary)

        raise RuntimeError('No institution registered — cannot resolve context')

    @property
    def is_admitted(self):
        return self._admitted

    @property
    def identity_model(self):
        return self.boundary.identity_model

    @property
    def scope(self):
        return self.boundary.scope

    def validate(self):
        if not self._admitted:
            raise RuntimeError('No institution admitted to this context')
        status = self.org.get('status', 'active')
        if status == 'suspended':
            raise RuntimeError(f'Institution {self.org_id} is suspended')
        lifecycle = self.org.get('lifecycle_state', 'active')
        if lifecycle in ('suspended', 'dissolved'):
            raise RuntimeError(f'Institution {self.org_id} is {lifecycle}')
        return True

    def admits_org(self, other_org_id):
        if self.boundary.scope == 'unscoped':
            return False
        return other_org_id == self.org_id

    def reject_cross_org(self, request_org_id):
        if request_org_id and request_org_id != self.org_id:
            raise ValueError(
                f'Request targets institution {request_org_id!r} but this '
                f'process serves {self.org_id!r}'
            )

    def to_dict(self):
        org = self.org or {}
        return {
            'org_id': self.org_id,
            'institution_name': org.get('name', ''),
            'institution_slug': org.get('slug', ''),
            'context_source': self.context_source,
            'identity_model': self.identity_model,
            'boundary_scope': self.scope,
            'boundary_name': self.boundary.name,
            'is_admitted': self.is_admitted,
            'lifecycle_state': org.get('lifecycle_state', ''),
        }


WORKSPACE_BOUNDARY = ServiceBoundary(
    'workspace', 'session', 'institution_bound',
    'Governed workspace — institution-scoped session identity',
)

MCP_SERVICE_BOUNDARY = ServiceBoundary(
    'mcp_service', 'x402_payment', 'founding_service_only',
    'MCP tool server — x402 payment identity, founding institution only',
)

PAYMENT_MONITOR_BOUNDARY = ServiceBoundary(
    'payment_monitor', 'daemon', 'founding_service_only',
    'Payment monitor daemon — no user identity, founding institution only',
)

SUBSCRIPTIONS_BOUNDARY = ServiceBoundary(
    'subscriptions', 'session', 'institution_bound',
    'Subscription entitlement state — institution-bound session surface on a founding-locked host',
)

ACCOUNTING_BOUNDARY = ServiceBoundary(
    'accounting', 'session', 'institution_bound',
    'Accounting ledger — institution-bound session surface on a founding-locked host',
)

CLI_BOUNDARY = ServiceBoundary(
    'cli', 'credential', 'institution_bound',
    'CLI tools — credential-based, institution-bound per invocation',
)

FEDERATION_GATEWAY_BOUNDARY = ServiceBoundary(
    'federation_gateway', 'signed_host_service', 'federation_gateway',
    'Cross-host federation gateway — signed host-service identity',
    requires_warrant_for_messages={
        'execution_request': 'federated_execution',
        'commitment_proposal': 'cross_institution_commitment',
        'commitment_acceptance': 'cross_institution_commitment',
        'commitment_breach_notice': 'cross_institution_commitment',
    },
)

SERVICE_BOUNDARIES = {
    boundary.name: boundary for boundary in (
        WORKSPACE_BOUNDARY,
        FEDERATION_GATEWAY_BOUNDARY,
        MCP_SERVICE_BOUNDARY,
        PAYMENT_MONITOR_BOUNDARY,
        SUBSCRIPTIONS_BOUNDARY,
        ACCOUNTING_BOUNDARY,
        CLI_BOUNDARY,
    )
}


def describe_boundary(boundary):
    data = boundary.to_dict()
    data['supports_institution_routing'] = boundary.scope in (
        'institution_bound',
        'federation_gateway',
    )
    data['supports_federation'] = boundary.scope == 'federation_gateway'
    data['requires_admitted_institution'] = boundary.scope not in ('unscoped', 'daemon_only')
    data['requires_warrant'] = bool(boundary.requires_warrant_for_messages)
    data['required_warrant_actions'] = dict(boundary.requires_warrant_for_messages)
    return data


def service_boundary_registry():
    return {
        name: describe_boundary(boundary)
        for name, boundary in SERVICE_BOUNDARIES.items()
    }


def admission_state(context, additional_institutions_allowed=False,
                    second_institution_path='', host_identity=None,
                    admission_registry=None,
                    management_mode='implicit_context',
                    mutation_enabled=False,
                    mutation_disabled_reason=''):
    admitted_org_ids = [context.org_id] if context.is_admitted else []
    admission_source = 'implicit_context'
    host_id = ''
    host_role = ''
    federation_enabled = False
    if host_identity:
        host_id = getattr(host_identity, 'host_id', '') or ''
        host_role = getattr(host_identity, 'role', '') or ''
        federation_enabled = bool(getattr(host_identity, 'federation_enabled', False))
    if admission_registry:
        admitted_org_ids = list(admission_registry.get('admitted_org_ids', admitted_org_ids))
        admission_source = admission_registry.get('source', admission_source)
        if not host_id:
            host_id = admission_registry.get('host_id', '') or ''
    additional_institutions_allowed = bool(
        additional_institutions_allowed or len(admitted_org_ids) > 1
    )
    if not second_institution_path:
        if additional_institutions_allowed:
            second_institution_path = (
                'Admit the institution on this host, then bind a separate process '
                'to that admitted institution via --org-id or credential-scoped '
                'org binding. Shared request-level org hopping remains disallowed.'
            )
        else:
            second_institution_path = (
                'This deployment does not admit additional institutions beyond '
                'the currently bound institution.'
            )
    return {
        'mode': (
            'single_process_per_institution'
            if additional_institutions_allowed else
            'single_institution_deployment'
        ),
        'bound_org_id': context.org_id,
        'admitted_org_ids': admitted_org_ids,
        'additional_institutions_allowed': bool(additional_institutions_allowed),
        'shared_request_routing': False,
        'admission_source': admission_source,
        'host_id': host_id,
        'host_role': host_role,
        'federation_enabled': federation_enabled,
        'second_institution_path': second_institution_path,
        'management_mode': management_mode,
        'mutation_enabled': bool(mutation_enabled),
        'mutation_disabled_reason': (
            '' if mutation_enabled else mutation_disabled_reason
        ),
    }


def runtime_core_snapshot(context, additional_institutions_allowed=False,
                          second_institution_path='', host_identity=None,
                          admission_registry=None,
                          admission_management_mode='implicit_context',
                          admission_mutation_enabled=False,
                          admission_mutation_disabled_reason=''):
    return {
        'institution_context': context.to_dict(),
        'host_identity': host_identity.to_dict() if host_identity else {},
        'current_boundary': describe_boundary(context.boundary),
        'service_registry': service_boundary_registry(),
        'admission': admission_state(
            context,
            additional_institutions_allowed=additional_institutions_allowed,
            second_institution_path=second_institution_path,
            host_identity=host_identity,
            admission_registry=admission_registry,
            management_mode=admission_management_mode,
            mutation_enabled=admission_mutation_enabled,
            mutation_disabled_reason=admission_mutation_disabled_reason,
        ),
    }
