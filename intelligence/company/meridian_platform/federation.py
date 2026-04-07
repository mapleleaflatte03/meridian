#!/usr/bin/env python3
"""
Federation gateway primitives for Meridian live runtime.

The live deployment still defaults to a founding-only institution host.
This module keeps the federation contract honest so workspace/status can
surface whether host-service federation is enabled without pretending the
deployment already routes multiple institutions.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
import uuid


TRUST_STATES = (
    'trusted',
    'suspended',
    'revoked',
)

DEFAULT_TTL_SECONDS = 300
MAX_TTL_SECONDS = 3600


def _now():
    return datetime.datetime.utcnow()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64url_decode(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)


def _canonical_payload_bytes(payload) -> bytes:
    if payload is None:
        return b''
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode('utf-8')
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _payload_hash(payload) -> str:
    return hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest()


class FederationError(RuntimeError):
    """Base class for federation gateway failures."""


class FederationUnavailable(FederationError):
    """The host has not enabled federation for this boundary."""


class FederationValidationError(FederationError):
    """Envelope or peer identity failed validation."""


class FederationReplayError(FederationValidationError):
    """Envelope nonce was already consumed."""


class FederationDeliveryError(FederationError):
    """Outbound delivery to a trusted peer failed."""

    def __init__(self, message, *, peer_host_id='', envelope='',
                 claims=None, response=None):
        super().__init__(message)
        self.peer_host_id = peer_host_id
        self.envelope = envelope
        self.claims = claims
        self.response = response


class FederationPeer:
    __slots__ = (
        'host_id',
        'label',
        'transport',
        'endpoint_url',
        'trust_state',
        'shared_secret',
        'admitted_org_ids',
        'capability_snapshot',
        'last_refreshed_at',
    )

    def __init__(self, host_id, label='', transport='https', endpoint_url='',
                 trust_state='trusted', shared_secret='', admitted_org_ids=None,
                 capability_snapshot=None, last_refreshed_at=''):
        if trust_state not in TRUST_STATES:
            raise ValueError(
                f'Unknown trust_state {trust_state!r}. Must be one of {TRUST_STATES}'
            )
        self.host_id = host_id
        self.label = label or host_id
        self.transport = transport or 'https'
        self.endpoint_url = endpoint_url.rstrip('/')
        self.trust_state = trust_state
        self.shared_secret = shared_secret or ''
        self.admitted_org_ids = list(admitted_org_ids or [])
        self.capability_snapshot = dict(capability_snapshot or {})
        self.last_refreshed_at = (last_refreshed_at or '').strip()

    def to_dict(self, redact_secret=True):
        data = {
            'host_id': self.host_id,
            'label': self.label,
            'transport': self.transport,
            'endpoint_url': self.endpoint_url,
            'trust_state': self.trust_state,
            'admitted_org_ids': list(self.admitted_org_ids),
            'capability_snapshot': dict(self.capability_snapshot),
            'last_refreshed_at': self.last_refreshed_at,
        }
        if not redact_secret:
            data['shared_secret'] = self.shared_secret
        return data

    @property
    def receive_url(self):
        if not self.endpoint_url:
            return ''
        return self.endpoint_url + '/api/federation/receive'

    @property
    def manifest_url(self):
        if not self.endpoint_url:
            return ''
        return self.endpoint_url + '/api/federation/manifest'


def _normalize_host_id(host_id, *, field_name='host_id'):
    host_id = (host_id or '').strip()
    if not host_id:
        raise RuntimeError(f'{field_name} is required')
    return host_id


def _normalize_peer_org_ids(admitted_org_ids):
    normalized = []
    for org_id in admitted_org_ids or []:
        org_id = (org_id or '').strip()
        if org_id and org_id not in normalized:
            normalized.append(org_id)
    return normalized


def _peer_view(raw_peer):
    if isinstance(raw_peer, FederationPeer):
        return raw_peer.to_dict(), raw_peer.trust_state, raw_peer.receive_url
    data = dict(raw_peer or {})
    endpoint_url = (data.get('endpoint_url') or data.get('base_url') or '').rstrip('/')
    receive_url = endpoint_url + '/api/federation/receive' if endpoint_url else ''
    return data, (data.get('trust_state') or '').strip(), receive_url


class ReplayStore:
    """Replay protection store for federation envelope nonces."""

    def __init__(self, file_path=None):
        self.file_path = file_path
        self._seen = set()
        if self.file_path and os.path.exists(self.file_path):
            with open(self.file_path) as f:
                for line in f:
                    key = line.strip()
                    if key:
                        self._seen.add(key)

    @property
    def mode(self):
        return 'file_backed' if self.file_path else 'memory_only'

    def has(self, key):
        return key in self._seen

    def record(self, key):
        if key in self._seen:
            return False
        self._seen.add(key)
        if self.file_path:
            with open(self.file_path, 'a') as f:
                f.write(key + '\n')
        return True

    def snapshot(self):
        return {
            'mode': self.mode,
            'entries': len(self._seen),
        }


class FederationEnvelopeClaims:
    __slots__ = (
        'envelope_id',
        'source_host_id',
        'source_institution_id',
        'target_host_id',
        'target_institution_id',
        'actor_type',
        'actor_id',
        'session_id',
        'boundary_name',
        'identity_model',
        'message_type',
        'payload_hash',
        'issued_at',
        'expires_at',
        'nonce',
        'algorithm',
        'warrant_id',
        'commitment_id',
    )

    def __init__(self, **kwargs):
        for name in self.__slots__:
            setattr(self, name, kwargs.get(name, ''))

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__slots__}

    @property
    def replay_key(self):
        return f'{self.source_host_id}:{self.nonce}'

    @property
    def is_expired(self):
        try:
            expires = datetime.datetime.strptime(self.expires_at, '%Y-%m-%dT%H:%M:%SZ')
        except (ValueError, TypeError):
            return True
        return _now() >= expires


def load_peer_registry(file_path, *, host_identity=None):
    registry = {
        'host_id': getattr(host_identity, 'host_id', '') or '',
        'source': 'none',
        'peers': {},
        'trusted_peer_ids': [],
    }
    if not file_path or not os.path.exists(file_path):
        return registry

    with open(file_path) as f:
        raw = json.load(f)

    registry['source'] = 'file'
    registry['host_id'] = (raw.get('host_id') or registry['host_id'] or '').strip()
    if host_identity and registry['host_id'] and registry['host_id'] != host_identity.host_id:
        raise RuntimeError(
            f"Peer registry host_id '{registry['host_id']}' does not match runtime host "
            f"'{host_identity.host_id}'"
        )

    peers = raw.get('peers', {})
    if isinstance(peers, list):
        peers = {entry.get('host_id', ''): entry for entry in peers}
    if not isinstance(peers, dict):
        raise RuntimeError('Federation peer registry must contain a peers dict or list')

    for host_id, data in peers.items():
        host_id = (host_id or data.get('host_id') or '').strip()
        if not host_id:
            continue
        entry = FederationPeer(
            host_id=host_id,
            label=(data.get('label') or data.get('name') or host_id).strip(),
            transport=(data.get('transport') or 'https').strip(),
            endpoint_url=(data.get('endpoint_url') or data.get('base_url') or '').strip(),
            trust_state=(data.get('trust_state') or 'trusted').strip(),
            shared_secret=(data.get('shared_secret') or '').strip(),
            admitted_org_ids=data.get('admitted_org_ids', []),
            capability_snapshot=data.get('capability_snapshot', {}),
            last_refreshed_at=data.get('last_refreshed_at', ''),
        )
        if entry.trust_state == 'trusted' and not entry.shared_secret:
            raise RuntimeError(
                f"Trusted peer '{host_id}' must declare shared_secret for HMAC verification"
            )
        registry['peers'][host_id] = entry
        if entry.trust_state == 'trusted':
            registry['trusted_peer_ids'].append(host_id)
    return registry


def save_peer_registry(file_path, registry, *, host_identity=None):
    if not file_path:
        raise RuntimeError('Federation peer registry file path is required')
    host_id = (
        registry.get('host_id')
        or (getattr(host_identity, 'host_id', '') if host_identity else '')
        or ''
    ).strip()
    if not host_id:
        raise RuntimeError('Federation peer registry must declare host_id')
    if host_identity and host_id != host_identity.host_id:
        raise RuntimeError(
            f"Peer registry host_id '{host_id}' does not match runtime host "
            f"'{host_identity.host_id}'"
        )

    peers_out = {}
    for peer_host_id, raw_entry in sorted((registry.get('peers') or {}).items()):
        if isinstance(raw_entry, FederationPeer):
            entry = raw_entry
        else:
            data = dict(raw_entry or {})
            entry = FederationPeer(
                host_id=(data.get('host_id') or peer_host_id or '').strip(),
                label=(data.get('label') or data.get('name') or peer_host_id).strip(),
                transport=(data.get('transport') or 'https').strip(),
                endpoint_url=(data.get('endpoint_url') or data.get('base_url') or '').strip(),
                trust_state=(data.get('trust_state') or 'trusted').strip(),
                shared_secret=(data.get('shared_secret') or '').strip(),
                admitted_org_ids=_normalize_peer_org_ids(data.get('admitted_org_ids', [])),
                capability_snapshot=data.get('capability_snapshot', {}),
                last_refreshed_at=data.get('last_refreshed_at', ''),
            )
        if entry.host_id == host_id:
            raise RuntimeError('Peer registry cannot declare the current host as a trusted peer')
        if entry.trust_state == 'trusted' and not entry.shared_secret:
            raise RuntimeError(
                f"Trusted peer '{entry.host_id}' must declare shared_secret for HMAC verification"
            )
        peer_data = entry.to_dict(redact_secret=False)
        peer_data['admitted_org_ids'] = _normalize_peer_org_ids(peer_data.get('admitted_org_ids', []))
        peers_out[entry.host_id] = peer_data

    parent = os.path.dirname(file_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump({
            'host_id': host_id,
            'updated_at': _now().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'peers': peers_out,
        }, f, indent=2, sort_keys=True)
    return load_peer_registry(file_path, host_identity=host_identity)


def upsert_peer_registry_entry(file_path, peer_host_id, *, host_identity=None,
                               label=None, transport=None, endpoint_url=None,
                               trust_state=None, shared_secret=None,
                               admitted_org_ids=None):
    peer_host_id = _normalize_host_id(peer_host_id, field_name='peer_host_id')
    if host_identity and peer_host_id == host_identity.host_id:
        raise PermissionError('Cannot register the current host as its own federation peer')

    registry = load_peer_registry(file_path, host_identity=host_identity)
    existing = registry.get('peers', {}).get(peer_host_id)
    next_trust_state = (trust_state or (existing.trust_state if existing else 'trusted')).strip()
    next_entry = FederationPeer(
        host_id=peer_host_id,
        label=(
            label.strip() if isinstance(label, str) and label.strip()
            else (existing.label if existing else peer_host_id)
        ),
        transport=(
            transport.strip() if isinstance(transport, str) and transport.strip()
            else (existing.transport if existing else 'https')
        ),
        endpoint_url=(
            endpoint_url.strip() if isinstance(endpoint_url, str)
            else (existing.endpoint_url if existing else '')
        ),
        trust_state=next_trust_state,
        shared_secret=(
            shared_secret.strip() if isinstance(shared_secret, str)
            else (existing.shared_secret if existing else '')
        ),
        admitted_org_ids=(
            _normalize_peer_org_ids(admitted_org_ids)
            if admitted_org_ids is not None else
            _normalize_peer_org_ids(existing.admitted_org_ids if existing else [])
        ),
        capability_snapshot=(
            dict(existing.capability_snapshot) if existing else {}
        ),
        last_refreshed_at=(
            existing.last_refreshed_at if existing else ''
        ),
    )
    registry.setdefault('peers', {})[peer_host_id] = next_entry
    return save_peer_registry(file_path, registry, host_identity=host_identity)


def set_peer_trust_state(file_path, peer_host_id, trust_state, *, host_identity=None):
    peer_host_id = _normalize_host_id(peer_host_id, field_name='peer_host_id')
    trust_state = (trust_state or '').strip()
    if trust_state not in TRUST_STATES:
        raise RuntimeError(
            f'Unknown trust_state {trust_state!r}. Must be one of {TRUST_STATES}'
        )
    registry = load_peer_registry(file_path, host_identity=host_identity)
    existing = registry.get('peers', {}).get(peer_host_id)
    if not existing:
        raise LookupError(f"Peer host '{peer_host_id}' is not in peer registry")
    registry.setdefault('peers', {})[peer_host_id] = FederationPeer(
        host_id=existing.host_id,
        label=existing.label,
        transport=existing.transport,
        endpoint_url=existing.endpoint_url,
        trust_state=trust_state,
        shared_secret=existing.shared_secret,
        admitted_org_ids=existing.admitted_org_ids,
        capability_snapshot=existing.capability_snapshot,
        last_refreshed_at=existing.last_refreshed_at,
    )
    return save_peer_registry(file_path, registry, host_identity=host_identity)


def refresh_peer_registry_entry(file_path, peer_host_id, *, host_identity=None,
                                http_get=None, target_org_id=None):
    peer_host_id = _normalize_host_id(peer_host_id, field_name='peer_host_id')
    if host_identity is None:
        raise RuntimeError('host_identity is required to refresh federation peer capabilities')
    registry = load_peer_registry(file_path, host_identity=host_identity)
    existing = registry.get('peers', {}).get(peer_host_id)
    if not existing:
        raise LookupError(f"Peer host '{peer_host_id}' is not in peer registry")
    authority = FederationAuthority(
        host_identity,
        peer_registry=registry,
    )
    peer, manifest = authority.fetch_peer_manifest(peer_host_id, http_get=http_get)
    manifest = authority._validate_peer_manifest(
        peer,
        manifest,
        target_institution_id=(target_org_id or '').strip(),
    )
    registry.setdefault('peers', {})[peer_host_id] = FederationPeer(
        host_id=existing.host_id,
        label=existing.label,
        transport=existing.transport,
        endpoint_url=existing.endpoint_url,
        trust_state=existing.trust_state,
        shared_secret=existing.shared_secret,
        admitted_org_ids=existing.admitted_org_ids,
        capability_snapshot=dict(manifest),
        last_refreshed_at=_now().strftime('%Y-%m-%dT%H:%M:%SZ'),
    )
    return save_peer_registry(file_path, registry, host_identity=host_identity)


class FederationAuthority:
    """Host-service signer / verifier for federation envelopes."""

    def __init__(self, host_identity, *, signing_secret=None,
                 peer_registry=None, replay_store=None):
        self.host_identity = host_identity
        self._signing_secret = (
            signing_secret.encode('utf-8')
            if isinstance(signing_secret, str) else
            signing_secret
        )
        self.peer_registry = peer_registry or {
            'source': 'none',
            'host_id': getattr(host_identity, 'host_id', '') or '',
            'peers': {},
            'trusted_peer_ids': [],
        }
        self.replay_store = replay_store or ReplayStore()

    def _enabled_state(self):
        if not getattr(self.host_identity, 'federation_enabled', False):
            return False, 'host_federation_disabled'
        if not self._signing_secret:
            return False, 'signing_secret_missing'
        if (getattr(self.host_identity, 'peer_transport', '') or 'none') == 'none':
            return False, 'peer_transport_none'
        return True, ''

    def ensure_enabled(self):
        enabled, reason = self._enabled_state()
        if not enabled:
            raise FederationUnavailable(
                f'Federation gateway is disabled on host {self.host_identity.host_id} '
                f'({reason})'
            )
        return True

    def _sign(self, payload_bytes):
        return hmac.new(self._signing_secret, payload_bytes, hashlib.sha256).digest()

    def _verification_secret_for_source(self, source_host_id):
        if source_host_id == self.host_identity.host_id:
            if not self._signing_secret:
                raise FederationValidationError('Local federation signing secret is not configured')
            return self._signing_secret
        peer = self.peer_registry.get('peers', {}).get(source_host_id)
        if not peer:
            raise FederationValidationError(f"Source host '{source_host_id}' is not in peer registry")
        if peer.trust_state != 'trusted':
            raise FederationValidationError(
                f"Source host '{source_host_id}' is not trusted (state={peer.trust_state})"
            )
        if not peer.shared_secret:
            raise FederationValidationError(
                f"Trusted peer '{source_host_id}' does not declare a verification secret"
            )
        return peer.shared_secret.encode('utf-8')

    def issue(self, source_institution_id, target_host_id, target_institution_id,
              message_type, payload=None, *, actor_type='host_service',
              actor_id='', session_id='', boundary_name='federation_gateway',
              ttl_seconds=None, warrant_id='', commitment_id=''):
        self.ensure_enabled()
        if not source_institution_id:
            raise ValueError('source_institution_id is required')
        if not target_host_id:
            raise ValueError('target_host_id is required')
        if not target_institution_id:
            raise ValueError('target_institution_id is required')
        if not message_type:
            raise ValueError('message_type is required')

        ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS
        if ttl > MAX_TTL_SECONDS:
            ttl = MAX_TTL_SECONDS
        if ttl <= 0:
            raise ValueError('ttl_seconds must be positive')

        now = _now()
        payload_obj = {
            'envelope_id': f'fed_{uuid.uuid4().hex[:12]}',
            'source_host_id': self.host_identity.host_id,
            'source_institution_id': source_institution_id,
            'target_host_id': target_host_id,
            'target_institution_id': target_institution_id,
            'actor_type': actor_type or 'host_service',
            'actor_id': actor_id or f'host_service:{self.host_identity.host_id}',
            'session_id': session_id or '',
            'boundary_name': boundary_name or 'federation_gateway',
            'identity_model': 'signed_host_service',
            'message_type': message_type,
            'payload_hash': _payload_hash(payload),
            'issued_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'expires_at': (now + datetime.timedelta(seconds=ttl)).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'nonce': f'nonce_{uuid.uuid4().hex[:12]}',
            'algorithm': 'hmac_sha256',
            'warrant_id': warrant_id or '',
            'commitment_id': commitment_id or '',
        }
        payload_bytes = json.dumps(payload_obj, separators=(',', ':')).encode('utf-8')
        signature = self._sign(payload_bytes)
        return _b64url_encode(payload_bytes) + '.' + _b64url_encode(signature)

    def validate(self, envelope, *, payload=None, expected_target_host_id=None,
                 expected_target_org_id=None, expected_boundary_name=None,
                 reject_replay=False):
        if not envelope or '.' not in envelope:
            raise FederationValidationError('Invalid federation envelope format')

        body_b64, signature_b64 = envelope.split('.', 1)
        try:
            payload_bytes = _b64url_decode(body_b64)
            signature = _b64url_decode(signature_b64)
            body = json.loads(payload_bytes)
        except Exception as exc:
            raise FederationValidationError(f'Envelope decode failed: {exc}') from exc

        required = (
            'envelope_id',
            'source_host_id',
            'source_institution_id',
            'target_host_id',
            'target_institution_id',
            'actor_type',
            'actor_id',
            'boundary_name',
            'identity_model',
            'message_type',
            'payload_hash',
            'issued_at',
            'expires_at',
            'nonce',
            'algorithm',
        )
        missing = [field for field in required if not body.get(field)]
        if missing:
            raise FederationValidationError(
                f'Envelope payload missing required fields: {", ".join(missing)}'
            )
        if body.get('identity_model') != 'signed_host_service':
            raise FederationValidationError('Envelope identity_model must be signed_host_service')
        if body.get('algorithm') != 'hmac_sha256':
            raise FederationValidationError('Envelope algorithm must be hmac_sha256')

        source_peer = self.peer_registry.get('peers', {}).get(body['source_host_id'])
        if (
            source_peer
            and source_peer.trust_state == 'suspended'
            and body.get('message_type') in ('case_notice', 'court_notice')
        ):
            if not source_peer.shared_secret:
                raise FederationValidationError(
                    f"Suspended peer '{body['source_host_id']}' does not declare a verification secret"
                )
            secret = source_peer.shared_secret.encode('utf-8')
        else:
            secret = self._verification_secret_for_source(body['source_host_id'])
        expected_sig = hmac.new(secret, payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_sig):
            raise FederationValidationError('Envelope signature verification failed')

        claims = FederationEnvelopeClaims(**body)
        if claims.is_expired:
            raise FederationValidationError('Envelope is expired')
        if expected_target_host_id and claims.target_host_id != expected_target_host_id:
            raise FederationValidationError(
                f"Envelope targets host '{claims.target_host_id}', not '{expected_target_host_id}'"
            )
        if expected_target_org_id and claims.target_institution_id != expected_target_org_id:
            raise FederationValidationError(
                f"Envelope targets institution '{claims.target_institution_id}', not "
                f"'{expected_target_org_id}'"
            )
        if expected_boundary_name and claims.boundary_name != expected_boundary_name:
            raise FederationValidationError(
                f"Envelope boundary '{claims.boundary_name}' does not match expected "
                f"'{expected_boundary_name}'"
            )
        if payload is not None and claims.payload_hash != _payload_hash(payload):
            raise FederationValidationError('Envelope payload hash does not match supplied payload')

        source_peer = self.peer_registry.get('peers', {}).get(claims.source_host_id)
        if source_peer and source_peer.admitted_org_ids:
            if claims.source_institution_id not in source_peer.admitted_org_ids:
                raise FederationValidationError(
                    f"Envelope source institution '{claims.source_institution_id}' is not admitted "
                    f"for peer '{claims.source_host_id}'"
                )

        if reject_replay and self.replay_store.has(claims.replay_key):
            raise FederationReplayError(
                f"Envelope nonce already consumed for source host '{claims.source_host_id}'"
            )
        return claims

    def accept(self, envelope, *, payload=None, expected_target_host_id=None,
               expected_target_org_id=None, expected_boundary_name='federation_gateway'):
        self.ensure_enabled()
        claims = self.validate(
            envelope,
            payload=payload,
            expected_target_host_id=expected_target_host_id,
            expected_target_org_id=expected_target_org_id,
            expected_boundary_name=expected_boundary_name,
            reject_replay=True,
        )
        self.replay_store.record(claims.replay_key)
        return claims

    def deliver(self, peer_host_id, source_institution_id, target_institution_id,
                message_type, payload=None, *, actor_type='host_service',
                actor_id='', session_id='', warrant_id='', commitment_id='',
                ttl_seconds=None, http_post=None, http_get=None):
        self.ensure_enabled()
        peer = self.peer_registry.get('peers', {}).get(peer_host_id)
        if not peer:
            raise FederationDeliveryError(f"Peer host '{peer_host_id}' is not in peer registry")
        if peer.trust_state != 'trusted':
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' is not trusted (state={peer.trust_state})"
            )
        if not peer.receive_url:
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' does not declare endpoint_url"
            )
        manifest = self.preflight_delivery(
            peer_host_id,
            target_institution_id,
            http_get=http_get,
        )
        envelope = self.issue(
            source_institution_id,
            peer.host_id,
            target_institution_id,
            message_type,
            payload=payload,
            actor_type=actor_type,
            actor_id=actor_id,
            session_id=session_id,
            ttl_seconds=ttl_seconds,
            warrant_id=warrant_id,
            commitment_id=commitment_id,
        )
        claims = self.validate(
            envelope,
            payload=payload,
            expected_target_host_id=peer.host_id,
            expected_target_org_id=target_institution_id,
            expected_boundary_name='federation_gateway',
        )
        sender = http_post or _default_http_post_json
        try:
            response = sender(peer.receive_url, {
                'envelope': envelope,
                'payload': payload,
            })
        except FederationError as exc:
            raise FederationDeliveryError(
                str(exc),
                peer_host_id=peer.host_id,
                envelope=envelope,
                claims=claims,
            ) from exc
        except Exception as exc:
            raise FederationDeliveryError(
                f"Failed delivering federation envelope to '{peer.host_id}': {exc}",
                peer_host_id=peer.host_id,
                envelope=envelope,
                claims=claims,
            ) from exc
        receipt = self._validate_delivery_receipt(
            response,
            peer_host_id=peer.host_id,
            target_institution_id=target_institution_id,
            claims=claims,
        )
        return {
            'peer': peer.to_dict(),
            'peer_manifest': manifest,
            'envelope': envelope,
            'claims': claims.to_dict(),
            'receipt': receipt,
            'response': response,
        }

    def fetch_peer_manifest(self, peer_host_id, *, http_get=None):
        peer = self.peer_registry.get('peers', {}).get(peer_host_id)
        if not peer:
            raise FederationDeliveryError(f"Peer host '{peer_host_id}' is not in peer registry")
        if peer.trust_state != 'trusted':
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' is not trusted (state={peer.trust_state})"
            )
        if not peer.manifest_url:
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' does not declare endpoint_url"
            )
        getter = http_get or _default_http_get_json
        try:
            manifest = getter(peer.manifest_url)
        except FederationError as exc:
            raise FederationDeliveryError(
                str(exc),
                peer_host_id=peer.host_id,
            ) from exc
        except Exception as exc:
            raise FederationDeliveryError(
                f"Failed fetching federation manifest from '{peer.host_id}': {exc}",
                peer_host_id=peer.host_id,
            ) from exc
        if not isinstance(manifest, dict):
            raise FederationDeliveryError(
                f"Peer host '{peer.host_id}' returned a non-object federation manifest",
                peer_host_id=peer.host_id,
                response=manifest,
            )
        return peer, manifest

    def _validate_peer_manifest(self, peer, manifest, *, target_institution_id=''):
        host_identity = manifest.get('host_identity', {}) or {}
        if host_identity.get('host_id') != peer.host_id:
            raise FederationDeliveryError(
                f"Peer manifest host_id '{host_identity.get('host_id', '')}' does not match "
                f"trusted peer '{peer.host_id}'",
                peer_host_id=peer.host_id,
                response=manifest,
            )

        federation = manifest.get('federation', {}) or {}
        if federation.get('boundary_name') != 'federation_gateway':
            raise FederationDeliveryError(
                f"Peer host '{peer.host_id}' does not surface federation_gateway boundary truth",
                peer_host_id=peer.host_id,
                response=manifest,
            )
        if federation.get('identity_model') != 'signed_host_service':
            raise FederationDeliveryError(
                f"Peer host '{peer.host_id}' federation identity model is "
                f"{federation.get('identity_model', '')!r}, not 'signed_host_service'",
                peer_host_id=peer.host_id,
                response=manifest,
            )
        if not federation.get('enabled'):
            raise FederationDeliveryError(
                f"Peer host '{peer.host_id}' federation gateway is not enabled",
                peer_host_id=peer.host_id,
                response=manifest,
            )

        service_registry = manifest.get('service_registry', {}) or {}
        gateway = service_registry.get('federation_gateway', {}) or {}
        if not gateway:
            raise FederationDeliveryError(
                f"Peer host '{peer.host_id}' manifest does not declare federation_gateway service",
                peer_host_id=peer.host_id,
                response=manifest,
            )
        if not gateway.get('supports_institution_routing'):
            raise FederationDeliveryError(
                f"Peer host '{peer.host_id}' does not advertise institution-routable federation gateway",
                peer_host_id=peer.host_id,
                response=manifest,
            )

        if peer.admitted_org_ids and target_institution_id not in peer.admitted_org_ids:
            raise FederationDeliveryError(
                f"Peer host '{peer.host_id}' registry does not admit target institution "
                f"'{target_institution_id}'",
                peer_host_id=peer.host_id,
                response=manifest,
            )

        admission = manifest.get('admission', {}) or {}
        admitted_org_ids = list(admission.get('admitted_org_ids', []) or [])
        if target_institution_id and admitted_org_ids and target_institution_id not in admitted_org_ids:
            raise FederationDeliveryError(
                f"Peer host '{peer.host_id}' manifest does not admit target institution "
                f"'{target_institution_id}'",
                peer_host_id=peer.host_id,
                response=manifest,
            )
        return manifest

    def _validate_delivery_receipt(self, response, *, peer_host_id='',
                                   target_institution_id='', claims=None):
        if not isinstance(response, dict):
            return {}
        receipt = response.get('receipt') or {}
        if not receipt:
            return {}
        if not isinstance(receipt, dict):
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' returned a non-object delivery receipt",
                peer_host_id=peer_host_id,
                claims=claims,
                response=response,
            )
        required = (
            'receipt_id',
            'envelope_id',
            'receiver_host_id',
            'receiver_institution_id',
        )
        missing = [field for field in required if not receipt.get(field)]
        if missing:
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' returned an incomplete delivery receipt: "
                f"{', '.join(missing)}",
                peer_host_id=peer_host_id,
                claims=claims,
                response=response,
            )
        if claims and receipt.get('envelope_id') != claims.envelope_id:
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' returned receipt for envelope "
                f"'{receipt.get('envelope_id', '')}', not '{claims.envelope_id}'",
                peer_host_id=peer_host_id,
                claims=claims,
                response=response,
            )
        if peer_host_id and receipt.get('receiver_host_id') != peer_host_id:
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' returned receipt receiver_host_id "
                f"{receipt.get('receiver_host_id', '')!r}",
                peer_host_id=peer_host_id,
                claims=claims,
                response=response,
            )
        if target_institution_id and receipt.get('receiver_institution_id') != target_institution_id:
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' returned receipt receiver_institution_id "
                f"{receipt.get('receiver_institution_id', '')!r}, not "
                f"'{target_institution_id}'",
                peer_host_id=peer_host_id,
                claims=claims,
                response=response,
            )
        if receipt.get('identity_model') and receipt.get('identity_model') != 'signed_host_service':
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' returned receipt identity_model "
                f"{receipt.get('identity_model', '')!r}, not 'signed_host_service'",
                peer_host_id=peer_host_id,
                claims=claims,
                response=response,
            )
        if claims and receipt.get('boundary_name') and receipt.get('boundary_name') != claims.boundary_name:
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' returned receipt boundary "
                f"{receipt.get('boundary_name', '')!r}, not '{claims.boundary_name}'",
                peer_host_id=peer_host_id,
                claims=claims,
                response=response,
            )
        if claims and receipt.get('message_type') and receipt.get('message_type') != claims.message_type:
            raise FederationDeliveryError(
                f"Peer host '{peer_host_id}' returned receipt message_type "
                f"{receipt.get('message_type', '')!r}, not '{claims.message_type}'",
                peer_host_id=peer_host_id,
                claims=claims,
                response=response,
            )
        return dict(receipt)

    def preflight_delivery(self, peer_host_id, target_institution_id, *, http_get=None):
        peer, manifest = self.fetch_peer_manifest(peer_host_id, http_get=http_get)
        return self._validate_peer_manifest(
            peer,
            manifest,
            target_institution_id=target_institution_id,
        )

    def snapshot(self, *, bound_org_id='', admission_registry=None):
        enabled, reason = self._enabled_state()
        peers = self.peer_registry.get('peers', {})
        peer_views = [
            _peer_view(peers[host_id])
            for host_id in sorted(peers)
        ]
        all_peers = [
            peer_data
            for peer_data, _trust_state, _receive_url in peer_views
        ]
        trusted_peers = [
            peer_data
            for peer_data, trust_state, _receive_url in peer_views
            if trust_state == 'trusted'
        ]
        return {
            'enabled': enabled,
            'disabled_reason': '' if enabled else reason,
            'host_id': self.host_identity.host_id,
            'bound_org_id': bound_org_id,
            'identity_model': 'signed_host_service',
            'boundary_name': 'federation_gateway',
            'peer_transport': self.host_identity.peer_transport,
            'send_enabled': enabled and any(
                trust_state == 'trusted' and receive_url
                for _peer_data, trust_state, receive_url in peer_views
            ),
            'registry_source': self.peer_registry.get('source', 'none'),
            'peer_count': len(trusted_peers),
            'all_peer_count': len(all_peers),
            'trusted_peer_ids': list(self.peer_registry.get('trusted_peer_ids', [])),
            'peers': all_peers,
            'trusted_peers': trusted_peers,
            'admitted_org_ids': list((admission_registry or {}).get('admitted_org_ids', [])),
            'replay_protection': self.replay_store.snapshot(),
            'signing': {
                'algorithm': 'hmac_sha256',
                'configured': bool(self._signing_secret),
            },
        }


def _default_http_post_json(url, data):
    body = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read().decode('utf-8')
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise FederationDeliveryError(
            f'Peer returned HTTP {exc.code}: {detail or exc.reason}'
        ) from exc


def _default_http_get_json(url):
    req = urllib.request.Request(url, method='GET')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = resp.read().decode('utf-8')
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise FederationDeliveryError(
            f'Peer returned HTTP {exc.code}: {detail or exc.reason}'
        ) from exc
