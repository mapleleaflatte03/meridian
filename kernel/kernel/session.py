#!/usr/bin/env python3
"""
Session primitive for Meridian Kernel.

Issues, validates, and revokes HMAC-signed session tokens that bind an
authenticated actor to exactly one institution for a bounded duration.

A session token separates credential bootstrap (proving identity via
Basic auth or other credential) from active session identity (bounded
authorization carried per-request).  Each session is bound to one
org_id and one user_id.  Multi-org switching requires issuing a new
session against a different institution.

Token format:
    base64url(payload_json) "." base64url(hmac_sha256(payload_json, key))

Payload fields:
    session_id, org_id, user_id, role, issued_at, expires_at

Usage:
    from session import SessionAuthority

    sa = SessionAuthority(secret='...',       # or auto-generated
                          revocation_file='/path/to/revocations')
    token = sa.issue('org_a', 'user_1', 'owner', ttl_seconds=3600)
    result = sa.validate(token)              # -> SessionClaims or None
    sa.revoke(result.session_id)
"""
import base64
import datetime
import hashlib
import hmac
import json
import os
import uuid


def _now():
    return datetime.datetime.utcnow()


def _now_ts():
    return _now().strftime('%Y-%m-%dT%H:%M:%SZ')


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64url_decode(s: str) -> bytes:
    padding = 4 - (len(s) % 4)
    if padding != 4:
        s += '=' * padding
    return base64.urlsafe_b64decode(s)


class SessionClaims:
    """Validated session identity."""

    __slots__ = ('session_id', 'org_id', 'user_id', 'role',
                 'issued_at', 'expires_at')

    def __init__(self, session_id, org_id, user_id, role,
                 issued_at, expires_at):
        self.session_id = session_id
        self.org_id = org_id
        self.user_id = user_id
        self.role = role
        self.issued_at = issued_at
        self.expires_at = expires_at

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'org_id': self.org_id,
            'user_id': self.user_id,
            'role': self.role,
            'issued_at': self.issued_at,
            'expires_at': self.expires_at,
        }

    @property
    def is_expired(self):
        try:
            exp = datetime.datetime.strptime(self.expires_at,
                                             '%Y-%m-%dT%H:%M:%SZ')
            return _now() >= exp
        except (ValueError, TypeError):
            return True


DEFAULT_TTL_SECONDS = 3600  # 1 hour
MAX_TTL_SECONDS = 86400     # 24 hours


class SessionAuthority:
    """Issues, validates, and revokes session tokens.

    The secret key is used to HMAC-sign tokens.  If not provided, a
    per-process random key is generated (safe for single-process
    deployments; tokens won't survive restarts).

    Revocation persistence:
        If revocation_file is provided, revoked session IDs are persisted
        to disk (one per line, append-only).  On init, existing entries are
        loaded.  When the signing key is ephemeral (auto-generated), file
        persistence is unnecessary since all tokens die on restart anyway.
        When the signing key is persistent (MERIDIAN_SESSION_SECRET),
        callers should also provide a revocation_file so that revocations
        survive restarts alongside the tokens they govern.
    """

    def __init__(self, secret=None, revocation_file=None):
        if secret:
            self._key = secret.encode('utf-8') if isinstance(secret, str) else secret
        else:
            env_secret = os.environ.get('MERIDIAN_SESSION_SECRET', '').strip()
            if env_secret:
                self._key = env_secret.encode('utf-8')
            else:
                self._key = os.urandom(32)
        self._revocation_file = revocation_file
        self._revoked = set()
        if self._revocation_file and os.path.exists(self._revocation_file):
            with open(self._revocation_file) as f:
                for line in f:
                    sid = line.strip()
                    if sid:
                        self._revoked.add(sid)

    def _sign(self, payload_bytes: bytes) -> bytes:
        return hmac.new(self._key, payload_bytes, hashlib.sha256).digest()

    def issue(self, org_id, user_id, role, ttl_seconds=None):
        """Issue a signed session token.

        Returns the token string.  Raises ValueError for invalid inputs.
        """
        if not org_id:
            raise ValueError('org_id is required')
        if not user_id:
            raise ValueError('user_id is required')
        if not role:
            raise ValueError('role is required')

        ttl = ttl_seconds if ttl_seconds is not None else DEFAULT_TTL_SECONDS
        if ttl > MAX_TTL_SECONDS:
            ttl = MAX_TTL_SECONDS
        if ttl <= 0:
            raise ValueError('ttl_seconds must be positive')

        now = _now()
        payload = {
            'session_id': f'ses_{uuid.uuid4().hex[:12]}',
            'org_id': org_id,
            'user_id': user_id,
            'role': role,
            'issued_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
            'expires_at': (now + datetime.timedelta(seconds=ttl)).strftime(
                '%Y-%m-%dT%H:%M:%SZ'),
        }
        payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        signature = self._sign(payload_bytes)
        return _b64url_encode(payload_bytes) + '.' + _b64url_encode(signature)

    def validate(self, token, expected_org_id=None):
        """Validate a session token.

        Returns SessionClaims on success, None on any failure (expired,
        revoked, tampered, malformed).

        If expected_org_id is provided, the token's org_id must match.
        """
        if not token or '.' not in token:
            return None

        parts = token.split('.', 1)
        if len(parts) != 2:
            return None

        try:
            payload_bytes = _b64url_decode(parts[0])
            provided_sig = _b64url_decode(parts[1])
        except Exception:
            return None

        expected_sig = self._sign(payload_bytes)
        if not hmac.compare_digest(provided_sig, expected_sig):
            return None

        try:
            payload = json.loads(payload_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

        required_fields = ('session_id', 'org_id', 'user_id', 'role',
                           'issued_at', 'expires_at')
        if not all(payload.get(f) for f in required_fields):
            return None

        claims = SessionClaims(
            session_id=payload['session_id'],
            org_id=payload['org_id'],
            user_id=payload['user_id'],
            role=payload['role'],
            issued_at=payload['issued_at'],
            expires_at=payload['expires_at'],
        )

        if claims.is_expired:
            return None

        if claims.session_id in self._revoked:
            return None

        if expected_org_id and claims.org_id != expected_org_id:
            return None

        return claims

    def revoke(self, session_id):
        """Revoke a session by ID.  Future validate() calls will reject it.

        If a revocation_file was configured, the revocation is persisted
        so it survives process restarts.
        """
        if not session_id:
            return
        self._revoked.add(session_id)
        if self._revocation_file:
            with open(self._revocation_file, 'a') as f:
                f.write(session_id + '\n')

    def is_revoked(self, session_id):
        return session_id in self._revoked
