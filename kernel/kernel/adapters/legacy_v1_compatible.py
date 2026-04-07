#!/usr/bin/env python3
"""
Legacy v1-compatible kernel adapter bridge.

This adapter provides backward-compatible kernel hook routing for runtimes
that predate the Loom-native contract interface. Loom is the primary runtime;
this bridge exists for legacy integration paths.
"""
from __future__ import annotations

from audit import log_event
from authority import check_authority
from court import get_restrictions
from metering import record as meter_record
from treasury import check_budget


SUPPORTED_HOOKS = (
    'agent_identity',
    'action_envelope',
    'cost_attribution',
    'approval_hook',
    'audit_emission',
    'sanction_controls',
    'budget_gate',
)


def adapter_proof():
    return {
        'type': 'reference_library',
        'runtime_id': 'legacy_v1_compatible',
        'implemented_hooks': list(SUPPORTED_HOOKS),
        'notes': (
            'Legacy v1-compatible kernel adapter bridge. '
            'Provides backward-compatible hook routing for pre-Loom integration paths.'
        ),
    }


def validate_action_envelope(envelope):
    if not isinstance(envelope, dict):
        raise ValueError('action envelope must be a dict')

    agent_id = (envelope.get('agent_id') or '').strip()
    action_type = (envelope.get('action_type') or '').strip()
    resource = (envelope.get('resource') or '').strip()
    if not agent_id:
        raise ValueError('action envelope requires agent_id')
    if not action_type:
        raise ValueError('action envelope requires action_type')
    if not resource:
        raise ValueError('action envelope requires resource')

    estimated_cost_usd = float(envelope.get('estimated_cost_usd', 0.0) or 0.0)
    if estimated_cost_usd < 0:
        raise ValueError('estimated_cost_usd must be non-negative')

    normalized = dict(envelope)
    normalized['agent_id'] = agent_id
    normalized['action_type'] = action_type
    normalized['resource'] = resource
    normalized['estimated_cost_usd'] = estimated_cost_usd
    normalized.setdefault('run_id', '')
    normalized.setdefault('session_id', '')
    normalized.setdefault('details', {})
    return normalized


def build_action_envelope(agent_id, action_type, resource, estimated_cost_usd=0.0,
                          *, run_id='', session_id='', details=None):
    return validate_action_envelope({
        'agent_id': agent_id,
        'action_type': action_type,
        'resource': resource,
        'estimated_cost_usd': estimated_cost_usd,
        'run_id': run_id,
        'session_id': session_id,
        'details': details or {},
    })


def pre_session_check(org_id, agent_id):
    restrictions = list(get_restrictions(agent_id, org_id=org_id) or [])
    if 'execute' in restrictions or 'remediation_only' in restrictions:
        return {
            'allowed': False,
            'reason': f'Agent {agent_id} is restricted from execute',
            'restrictions': restrictions,
        }
    return {
        'allowed': True,
        'reason': 'ok',
        'restrictions': restrictions,
    }


def pre_action_check(org_id, envelope):
    envelope = validate_action_envelope(envelope)
    session_gate = pre_session_check(org_id, envelope['agent_id'])
    if not session_gate['allowed']:
        return {
            'allowed': False,
            'reason': session_gate['reason'],
            'stage': 'sanction_controls',
            'envelope': envelope,
            'restrictions': session_gate['restrictions'],
        }

    allowed, reason = check_authority(
        envelope['agent_id'],
        envelope['action_type'],
        org_id=org_id,
    )
    if not allowed:
        return {
            'allowed': False,
            'reason': reason,
            'stage': 'approval_hook',
            'envelope': envelope,
            'restrictions': session_gate['restrictions'],
        }

    estimated_cost = envelope['estimated_cost_usd']
    if estimated_cost > 0:
        allowed, reason = check_budget(
            envelope['agent_id'],
            estimated_cost,
            org_id=org_id,
        )
        if not allowed:
            return {
                'allowed': False,
                'reason': reason,
                'stage': 'budget_gate',
                'envelope': envelope,
                'restrictions': session_gate['restrictions'],
            }

    return {
        'allowed': True,
        'reason': 'ok',
        'stage': 'ok',
        'envelope': envelope,
        'restrictions': session_gate['restrictions'],
    }


def post_action_record(org_id, envelope, *, outcome='success', actual_cost_usd=None,
                       metric='runtime_action', quantity=1.0, unit='calls',
                       actor_type='agent'):
    envelope = validate_action_envelope(envelope)
    cost_usd = envelope['estimated_cost_usd'] if actual_cost_usd is None else float(actual_cost_usd)
    if cost_usd < 0:
        raise ValueError('actual_cost_usd must be non-negative')

    details = dict(envelope.get('details') or {})
    details.setdefault('action_type', envelope['action_type'])
    details.setdefault('resource', envelope['resource'])

    meter_id = meter_record(
        org_id,
        envelope['agent_id'],
        metric,
        quantity=quantity,
        unit=unit,
        cost_usd=cost_usd,
        run_id=envelope.get('run_id', ''),
        details=details,
    )
    event_id = log_event(
        org_id,
        envelope['agent_id'],
        envelope['action_type'],
        resource=envelope['resource'],
        outcome=outcome,
        actor_type=actor_type,
        details=details,
        session_id=envelope.get('session_id', ''),
    )
    return {
        'meter_id': meter_id,
        'event_id': event_id,
        'cost_usd': cost_usd,
        'envelope': envelope,
    }
