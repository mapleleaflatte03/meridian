#!/usr/bin/env python3
"""
Runtime host identity and institution admission primitives.

Live deployments still remain free to admit only the founding institution, but
that truth should come from explicit host/admission state rather than from
implicit defaults scattered across service binders.
"""
from __future__ import annotations

import datetime
import json
import os
import socket


HOST_ROLES = (
    'control_host',
    'institution_host',
    'witness_host',
)

ADMISSION_STATES = (
    'admitted',
    'suspended',
    'revoked',
)


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


class HostIdentity:
    __slots__ = (
        'host_id',
        'label',
        'role',
        'federation_enabled',
        'peer_transport',
        'supported_boundaries',
        'settlement_adapters',
    )

    def __init__(self, host_id, label, role='institution_host',
                 federation_enabled=False, peer_transport='none',
                 supported_boundaries=None, settlement_adapters=None):
        if role not in HOST_ROLES:
            raise ValueError(f'Unknown host role {role!r}. Must be one of {HOST_ROLES}')
        self.host_id = host_id
        self.label = label
        self.role = role
        self.federation_enabled = bool(federation_enabled)
        self.peer_transport = peer_transport or 'none'
        self.supported_boundaries = list(supported_boundaries or [])
        self.settlement_adapters = list(settlement_adapters or [])

    def to_dict(self):
        return {
            'host_id': self.host_id,
            'label': self.label,
            'role': self.role,
            'federation_enabled': self.federation_enabled,
            'peer_transport': self.peer_transport,
            'supported_boundaries': list(self.supported_boundaries),
            'settlement_adapters': list(self.settlement_adapters),
        }


def _default_host_id():
    raw = socket.gethostname().strip().lower() or 'live'
    safe = ''.join(ch if ch.isalnum() else '_' for ch in raw).strip('_') or 'live'
    return f'host_{safe}'


def default_host_identity(*, supported_boundaries=None, label='Meridian Live Host',
                          host_id=None, role='institution_host',
                          federation_enabled=False, peer_transport='none',
                          settlement_adapters=None):
    return HostIdentity(
        host_id=host_id or _default_host_id(),
        label=label,
        role=role,
        federation_enabled=federation_enabled,
        peer_transport=peer_transport,
        supported_boundaries=supported_boundaries,
        settlement_adapters=settlement_adapters or ['internal_ledger'],
    )


def load_host_identity(file_path, *, supported_boundaries=None, fallback_label='Meridian Live Host',
                       fallback_role='institution_host', fallback_federation=False):
    if not file_path or not os.path.exists(file_path):
        return default_host_identity(
            supported_boundaries=supported_boundaries,
            label=fallback_label,
            role=fallback_role,
            federation_enabled=fallback_federation,
        )

    with open(file_path) as f:
        raw = json.load(f)
    return HostIdentity(
        host_id=(raw.get('host_id') or raw.get('id') or _default_host_id()).strip(),
        label=(raw.get('label') or raw.get('name') or fallback_label).strip(),
        role=(raw.get('role') or fallback_role).strip(),
        federation_enabled=raw.get('federation_enabled', fallback_federation),
        peer_transport=(raw.get('peer_transport') or 'none').strip(),
        supported_boundaries=raw.get('supported_boundaries', supported_boundaries or []),
        settlement_adapters=raw.get('settlement_adapters', ['internal_ledger']),
    )


def load_admission_registry(file_path, *, bound_org_id=None, host_identity=None):
    default_registry = {
        'host_id': host_identity.host_id if host_identity else '',
        'source': 'derived_bound_default',
        'institutions': {},
        'admitted_org_ids': [],
    }
    if bound_org_id:
        default_registry['institutions'][bound_org_id] = {
            'org_id': bound_org_id,
            'status': 'admitted',
            'source': 'bound_default',
        }
        default_registry['admitted_org_ids'] = [bound_org_id]

    if not file_path or not os.path.exists(file_path):
        return default_registry

    with open(file_path) as f:
        raw = json.load(f)

    registry = {
        'host_id': (raw.get('host_id') or default_registry['host_id'] or '').strip(),
        'source': 'file',
        'institutions': {},
        'admitted_org_ids': [],
    }
    if host_identity and registry['host_id'] and registry['host_id'] != host_identity.host_id:
        raise RuntimeError(
            f"Admission registry host_id '{registry['host_id']}' does not match runtime host "
            f"'{host_identity.host_id}'"
        )

    institutions = raw.get('institutions')
    if isinstance(institutions, dict):
        for org_id, data in institutions.items():
            org_id = (org_id or '').strip()
            if not org_id:
                continue
            entry = dict(data or {})
            status = (entry.get('status') or 'admitted').strip()
            if status not in ADMISSION_STATES:
                raise RuntimeError(
                    f'Unknown admission status {status!r} for institution {org_id!r}'
                )
            entry['org_id'] = org_id
            entry['status'] = status
            registry['institutions'][org_id] = entry
            if status == 'admitted':
                registry['admitted_org_ids'].append(org_id)
    else:
        for org_id in raw.get('admitted_org_ids', []):
            org_id = (org_id or '').strip()
            if not org_id:
                continue
            registry['institutions'][org_id] = {
                'org_id': org_id,
                'status': 'admitted',
                'source': 'legacy_admitted_org_ids',
            }
            registry['admitted_org_ids'].append(org_id)

    if bound_org_id and not registry['institutions']:
        return default_registry
    return registry


def ensure_org_admitted(bound_org_id, admission_registry):
    if not bound_org_id:
        raise RuntimeError('Cannot validate admission without a bound institution')
    institutions = admission_registry.get('institutions', {})
    if bound_org_id not in institutions:
        raise RuntimeError(f"Institution '{bound_org_id}' is not admitted on this host")
    state = institutions[bound_org_id].get('status', 'admitted')
    if state != 'admitted':
        raise RuntimeError(
            f"Institution '{bound_org_id}' is present on this host but not servable "
            f"(status={state})"
        )
    return True


def save_admission_registry(file_path, registry, *, host_identity=None):
    if not file_path:
        raise RuntimeError('Admission registry file path is required')
    host_id = (
        registry.get('host_id')
        or (getattr(host_identity, 'host_id', '') if host_identity else '')
        or ''
    ).strip()
    if not host_id:
        raise RuntimeError('Admission registry must declare host_id')

    data = {
        'host_id': host_id,
        'institutions': {},
        'updated_at': _now(),
    }
    for org_id, entry in sorted((registry.get('institutions') or {}).items()):
        org_id = (org_id or '').strip()
        if not org_id:
            continue
        normalized = dict(entry or {})
        status = (normalized.get('status') or 'admitted').strip()
        if status not in ADMISSION_STATES:
            raise RuntimeError(
                f'Unknown admission status {status!r} for institution {org_id!r}'
            )
        normalized.pop('org_id', None)
        normalized['status'] = status
        data['institutions'][org_id] = normalized
    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)
    return load_admission_registry(file_path, host_identity=host_identity)


def set_admission_state(file_path, org_id, status, *, bound_org_id=None,
                        host_identity=None, source='workspace_api', details=None):
    org_id = (org_id or '').strip()
    if not org_id:
        raise RuntimeError('org_id is required')
    status = (status or '').strip()
    if status not in ADMISSION_STATES:
        raise RuntimeError(
            f'Unknown admission status {status!r}. Must be one of {ADMISSION_STATES}'
        )
    registry = load_admission_registry(
        file_path,
        bound_org_id=bound_org_id,
        host_identity=host_identity,
    )
    institutions = dict(registry.get('institutions', {}))
    entry = dict(institutions.get(org_id, {}))
    entry.update(details or {})
    entry['org_id'] = org_id
    entry['status'] = status
    entry['source'] = source
    entry['updated_at'] = _now()
    if status == 'admitted':
        entry.setdefault('admitted_at', entry['updated_at'])
    institutions[org_id] = entry
    registry['host_id'] = registry.get('host_id') or getattr(host_identity, 'host_id', '')
    registry['institutions'] = institutions
    return save_admission_registry(file_path, registry, host_identity=host_identity)
