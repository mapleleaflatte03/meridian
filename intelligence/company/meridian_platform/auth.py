#!/usr/bin/env python3
"""
Simple authentication for Meridian multi-user platform.

Supports:
  1. GitHub OAuth — Exchange code for access token, fetch user profile
  2. DID (Decentralized Identifier) — Verify DID document signatures
  3. API Key — Simple bearer token auth for automated access

Flow:
  1. Client redirects to /api/auth/github or posts DID assertion to /api/auth/did
  2. Server validates identity and returns a Meridian session token
  3. Client uses session token for subsequent requests

Environment:
  MERIDIAN_GITHUB_CLIENT_ID     — GitHub OAuth App client ID
  MERIDIAN_GITHUB_CLIENT_SECRET — GitHub OAuth App client secret
  MERIDIAN_AUTH_SECRET           — HMAC signing key for sessions
"""
import hashlib
import json
import os
import uuid
from urllib import request as urllib_request, error as urllib_error, parse as urllib_parse

GITHUB_CLIENT_ID = (os.environ.get('MERIDIAN_GITHUB_CLIENT_ID') or '').strip()
GITHUB_CLIENT_SECRET = (os.environ.get('MERIDIAN_GITHUB_CLIENT_SECRET') or '').strip()
AUTH_SECRET = (os.environ.get('MERIDIAN_AUTH_SECRET') or '').strip()
GITHUB_AUTHORIZE_URL = 'https://github.com/login/oauth/authorize'
GITHUB_TOKEN_URL = 'https://github.com/login/oauth/access_token'
GITHUB_USER_URL = 'https://api.github.com/user'

_DID_TAG = b'DID_VERIFY_v1\x00'


def github_auth_url(redirect_uri: str, state: str = '') -> str:
    """Generate GitHub OAuth authorization URL."""
    if not GITHUB_CLIENT_ID:
        raise ValueError('MERIDIAN_GITHUB_CLIENT_ID not configured')
    params = {
        'client_id': GITHUB_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'scope': 'read:user user:email',
        'state': state or uuid.uuid4().hex,
    }
    return GITHUB_AUTHORIZE_URL + '?' + urllib_parse.urlencode(params)


def github_exchange_code(code: str) -> dict:
    """Exchange GitHub OAuth code for access token and user profile."""
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise ValueError('GitHub OAuth credentials not configured')

    # Exchange code for access token
    token_data = urllib_parse.urlencode({
        'client_id': GITHUB_CLIENT_ID,
        'client_secret': GITHUB_CLIENT_SECRET,
        'code': code,
    }).encode()
    token_req = urllib_request.Request(
        GITHUB_TOKEN_URL,
        data=token_data,
        headers={'Accept': 'application/json'},
    )
    try:
        with urllib_request.urlopen(token_req, timeout=15) as resp:
            token_response = json.loads(resp.read().decode())
    except (urllib_error.URLError, json.JSONDecodeError) as e:
        raise ValueError(f'GitHub token exchange failed: {e}')

    access_token = token_response.get('access_token')
    if not access_token:
        raise ValueError(
            f'GitHub did not return access token: {token_response.get("error_description", "unknown")}'
        )

    # Fetch user profile
    user_req = urllib_request.Request(
        GITHUB_USER_URL,
        headers={
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
        },
    )
    try:
        with urllib_request.urlopen(user_req, timeout=15) as resp:
            user_profile = json.loads(resp.read().decode())
    except (urllib_error.URLError, json.JSONDecodeError) as e:
        raise ValueError(f'GitHub user fetch failed: {e}')

    return {
        'provider': 'github',
        'provider_id': str(user_profile.get('id', '')),
        'username': user_profile.get('login', ''),
        'display_name': user_profile.get('name', '') or user_profile.get('login', ''),
        'email': user_profile.get('email', ''),
        'avatar_url': user_profile.get('avatar_url', ''),
        'access_token': access_token,
    }


def verify_did_assertion(did: str, signature: str, challenge: str) -> dict:
    """Verify a DID-based identity assertion.

    For MVP, this uses a simplified hash-based verification.
    Production should resolve the DID document and verify the signature
    against the public key.
    """
    if not did or not signature:
        raise ValueError('DID and signature are required')

    # Simplified verification: hash(DID + challenge) must match signature prefix
    h = hashlib.sha256()
    h.update(_DID_TAG)
    h.update(did.encode())
    h.update(challenge.encode())
    expected_prefix = h.hexdigest()[:16]

    if not signature.startswith(expected_prefix):
        raise ValueError('DID signature verification failed')

    return {
        'provider': 'did',
        'provider_id': did,
        'username': did.split(':')[-1][:20] if ':' in did else did[:20],
        'display_name': f'DID:{did[-8:]}',
    }


def provider_user_id(identity: dict) -> str:
    """Generate a Meridian user_id from a provider identity."""
    provider = identity.get('provider', 'unknown')
    provider_id = identity.get('provider_id', '')
    username = identity.get('username', '')
    return f'user_{provider}_{username or provider_id}'


def auth_config_summary() -> dict:
    """Return current auth configuration status."""
    return {
        'github_configured': bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET),
        'did_enabled': True,
        'api_key_enabled': bool(AUTH_SECRET),
        'providers': [
            p for p, enabled in [
                ('github', bool(GITHUB_CLIENT_ID)),
                ('did', True),
                ('api_key', bool(AUTH_SECRET)),
            ] if enabled
        ],
    }
