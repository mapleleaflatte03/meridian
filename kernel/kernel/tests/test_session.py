#!/usr/bin/env python3
"""Tests for the session primitive."""
import datetime
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
sys.path.insert(0, ROOT)

from session import SessionAuthority, SessionClaims, _b64url_encode, _b64url_decode


class SessionIssueTests(unittest.TestCase):
    def setUp(self):
        self.sa = SessionAuthority(secret='test-secret-key')

    def test_issue_returns_dotted_token(self):
        token = self.sa.issue('org_a', 'user_1', 'owner')
        self.assertIn('.', token)
        parts = token.split('.')
        self.assertEqual(len(parts), 2)

    def test_issue_requires_org_id(self):
        with self.assertRaises(ValueError):
            self.sa.issue('', 'user_1', 'owner')

    def test_issue_requires_user_id(self):
        with self.assertRaises(ValueError):
            self.sa.issue('org_a', '', 'owner')

    def test_issue_requires_role(self):
        with self.assertRaises(ValueError):
            self.sa.issue('org_a', 'user_1', '')

    def test_issue_caps_ttl_at_max(self):
        token = self.sa.issue('org_a', 'user_1', 'owner', ttl_seconds=999999)
        claims = self.sa.validate(token)
        self.assertIsNotNone(claims)
        issued = datetime.datetime.strptime(claims.issued_at, '%Y-%m-%dT%H:%M:%SZ')
        expires = datetime.datetime.strptime(claims.expires_at, '%Y-%m-%dT%H:%M:%SZ')
        delta = (expires - issued).total_seconds()
        self.assertLessEqual(delta, 86400)

    def test_issue_rejects_zero_ttl(self):
        with self.assertRaises(ValueError):
            self.sa.issue('org_a', 'user_1', 'owner', ttl_seconds=0)


class SessionValidateTests(unittest.TestCase):
    def setUp(self):
        self.sa = SessionAuthority(secret='test-secret-key')
        self.token = self.sa.issue('org_a', 'user_1', 'owner')

    def test_validate_returns_claims(self):
        claims = self.sa.validate(self.token)
        self.assertIsNotNone(claims)
        self.assertEqual(claims.org_id, 'org_a')
        self.assertEqual(claims.user_id, 'user_1')
        self.assertEqual(claims.role, 'owner')
        self.assertTrue(claims.session_id.startswith('ses_'))

    def test_validate_rejects_tampered_payload(self):
        parts = self.token.split('.')
        payload_bytes = _b64url_decode(parts[0])
        payload = json.loads(payload_bytes)
        payload['role'] = 'admin'
        tampered_payload = json.dumps(payload, separators=(',', ':')).encode()
        tampered_token = _b64url_encode(tampered_payload) + '.' + parts[1]
        self.assertIsNone(self.sa.validate(tampered_token))

    def test_validate_rejects_tampered_signature(self):
        parts = self.token.split('.')
        tampered = parts[0] + '.' + _b64url_encode(b'fake-signature-here')
        self.assertIsNone(self.sa.validate(tampered))

    def test_validate_rejects_wrong_secret(self):
        other_sa = SessionAuthority(secret='different-key')
        self.assertIsNone(other_sa.validate(self.token))

    def test_validate_rejects_expired_token(self):
        token = self.sa.issue('org_a', 'user_1', 'owner', ttl_seconds=1)
        # Manually expire by patching the payload
        parts = token.split('.')
        payload_bytes = _b64url_decode(parts[0])
        payload = json.loads(payload_bytes)
        past = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        payload['expires_at'] = past
        expired_payload = json.dumps(payload, separators=(',', ':')).encode()
        # Re-sign with correct key to make a validly-signed but expired token
        sig = self.sa._sign(expired_payload)
        expired_token = _b64url_encode(expired_payload) + '.' + _b64url_encode(sig)
        self.assertIsNone(self.sa.validate(expired_token))

    def test_validate_rejects_malformed_input(self):
        self.assertIsNone(self.sa.validate(''))
        self.assertIsNone(self.sa.validate(None))
        self.assertIsNone(self.sa.validate('no-dot-here'))
        self.assertIsNone(self.sa.validate('bad.data'))

    def test_validate_enforces_expected_org_id(self):
        claims = self.sa.validate(self.token, expected_org_id='org_a')
        self.assertIsNotNone(claims)
        self.assertIsNone(self.sa.validate(self.token, expected_org_id='org_b'))


class SessionRevokeTests(unittest.TestCase):
    def setUp(self):
        self.sa = SessionAuthority(secret='test-secret-key')
        self.token = self.sa.issue('org_a', 'user_1', 'owner')
        self.claims = self.sa.validate(self.token)

    def test_revoke_invalidates_token(self):
        self.assertIsNotNone(self.claims)
        self.sa.revoke(self.claims.session_id)
        self.assertIsNone(self.sa.validate(self.token))

    def test_is_revoked_tracks_state(self):
        self.assertFalse(self.sa.is_revoked(self.claims.session_id))
        self.sa.revoke(self.claims.session_id)
        self.assertTrue(self.sa.is_revoked(self.claims.session_id))


class SessionClaimsTests(unittest.TestCase):
    def test_to_dict_roundtrips(self):
        claims = SessionClaims(
            session_id='ses_abc',
            org_id='org_a',
            user_id='user_1',
            role='owner',
            issued_at='2026-03-21T00:00:00Z',
            expires_at='2026-03-21T01:00:00Z',
        )
        d = claims.to_dict()
        self.assertEqual(d['session_id'], 'ses_abc')
        self.assertEqual(d['org_id'], 'org_a')
        self.assertEqual(d['role'], 'owner')

    def test_is_expired_returns_true_for_past(self):
        past = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        claims = SessionClaims('ses_a', 'org_a', 'user_1', 'owner',
                               '2026-01-01T00:00:00Z', past)
        self.assertTrue(claims.is_expired)

    def test_is_expired_returns_false_for_future(self):
        future = (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        claims = SessionClaims('ses_a', 'org_a', 'user_1', 'owner',
                               '2026-01-01T00:00:00Z', future)
        self.assertFalse(claims.is_expired)


class SessionRevocationPersistenceTests(unittest.TestCase):
    def test_revocation_persists_across_reload(self):
        """With revocation_file, revoked sessions stay revoked after reload."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.revocations',
                                         delete=False) as f:
            revocation_path = f.name
        try:
            sa1 = SessionAuthority(secret='persist-key', revocation_file=revocation_path)
            token = sa1.issue('org_a', 'user_1', 'owner')
            claims = sa1.validate(token)
            sa1.revoke(claims.session_id)
            self.assertIsNone(sa1.validate(token))

            # Reload with same key and file
            sa2 = SessionAuthority(secret='persist-key', revocation_file=revocation_path)
            self.assertIsNone(sa2.validate(token))
            self.assertTrue(sa2.is_revoked(claims.session_id))
        finally:
            os.unlink(revocation_path)

    def test_no_revocation_file_means_in_memory_only(self):
        """Without revocation_file, revocations are lost on reload."""
        sa1 = SessionAuthority(secret='ephemeral-test')
        token = sa1.issue('org_a', 'user_1', 'owner')
        claims = sa1.validate(token)
        sa1.revoke(claims.session_id)
        self.assertIsNone(sa1.validate(token))

        # New instance with same key — revocation is lost
        sa2 = SessionAuthority(secret='ephemeral-test')
        self.assertIsNotNone(sa2.validate(token))
        self.assertFalse(sa2.is_revoked(claims.session_id))

    def test_revocation_file_created_on_first_revoke(self):
        """File is created lazily on first revoke, not on init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            revocation_path = os.path.join(tmpdir, 'revocations')
            sa = SessionAuthority(secret='test-key', revocation_file=revocation_path)
            self.assertFalse(os.path.exists(revocation_path))
            token = sa.issue('org_a', 'user_1', 'owner')
            claims = sa.validate(token)
            sa.revoke(claims.session_id)
            self.assertTrue(os.path.exists(revocation_path))

    def test_multiple_revocations_all_persist(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.revocations',
                                         delete=False) as f:
            revocation_path = f.name
        try:
            sa1 = SessionAuthority(secret='multi-key', revocation_file=revocation_path)
            tokens = []
            session_ids = []
            for i in range(3):
                token = sa1.issue('org_a', f'user_{i}', 'member')
                claims = sa1.validate(token)
                tokens.append(token)
                session_ids.append(claims.session_id)
                sa1.revoke(claims.session_id)

            # Reload — all three should still be revoked
            sa2 = SessionAuthority(secret='multi-key', revocation_file=revocation_path)
            for token in tokens:
                self.assertIsNone(sa2.validate(token))
            for sid in session_ids:
                self.assertTrue(sa2.is_revoked(sid))
        finally:
            os.unlink(revocation_path)


class SessionAuthorityAutoKeyTests(unittest.TestCase):
    def test_auto_generated_key_works(self):
        """SessionAuthority without explicit secret uses per-process random key."""
        old = os.environ.pop('MERIDIAN_SESSION_SECRET', None)
        try:
            sa = SessionAuthority()
            token = sa.issue('org_a', 'user_1', 'member')
            claims = sa.validate(token)
            self.assertIsNotNone(claims)
            self.assertEqual(claims.org_id, 'org_a')
        finally:
            if old is not None:
                os.environ['MERIDIAN_SESSION_SECRET'] = old


if __name__ == '__main__':
    unittest.main()
