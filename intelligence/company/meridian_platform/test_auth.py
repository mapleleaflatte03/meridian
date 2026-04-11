#!/usr/bin/env python3
"""Tests for simple auth module."""
import hashlib
import os
import sys
import unittest
from unittest.mock import patch

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from auth import (
    github_auth_url, verify_did_assertion, provider_user_id,
    auth_config_summary, _DID_TAG,
)


class TestGitHubAuth(unittest.TestCase):
    def test_auth_url_requires_client_id(self):
        with patch('auth.GITHUB_CLIENT_ID', ''):
            with self.assertRaises(ValueError):
                github_auth_url('http://localhost/callback')

    def test_auth_url_generates_url(self):
        with patch('auth.GITHUB_CLIENT_ID', 'test_client_id'):
            url = github_auth_url('http://localhost/callback', state='test_state')
        self.assertIn('client_id=test_client_id', url)
        self.assertIn('state=test_state', url)
        self.assertIn('scope=read%3Auser', url)


class TestDIDAuth(unittest.TestCase):
    def test_verify_did_requires_fields(self):
        with self.assertRaises(ValueError):
            verify_did_assertion('', 'sig', 'challenge')
        with self.assertRaises(ValueError):
            verify_did_assertion('did:key:123', '', 'challenge')

    def test_verify_did_validates_signature(self):
        did = 'did:key:z6MkpTHR8VNs5xhqFi'
        challenge = 'test_challenge_123'
        # Compute valid signature prefix
        h = hashlib.sha256()
        h.update(_DID_TAG)
        h.update(did.encode())
        h.update(challenge.encode())
        valid_sig = h.hexdigest()[:16] + '_extra_data'

        result = verify_did_assertion(did, valid_sig, challenge)
        self.assertEqual(result['provider'], 'did')
        self.assertEqual(result['provider_id'], did)

    def test_verify_did_rejects_bad_signature(self):
        with self.assertRaises(ValueError):
            verify_did_assertion('did:key:z6MkpTHR', 'bad_signature', 'challenge')


class TestProviderUserId(unittest.TestCase):
    def test_github_user_id(self):
        uid = provider_user_id({
            'provider': 'github',
            'provider_id': '12345',
            'username': 'testuser',
        })
        self.assertEqual(uid, 'user_github_testuser')

    def test_did_user_id(self):
        uid = provider_user_id({
            'provider': 'did',
            'provider_id': 'did:key:z6MkpTHR',
            'username': 'z6MkpTHR',
        })
        self.assertEqual(uid, 'user_did_z6MkpTHR')


class TestAuthConfig(unittest.TestCase):
    def test_config_summary(self):
        with patch('auth.GITHUB_CLIENT_ID', ''), \
             patch('auth.GITHUB_CLIENT_SECRET', ''), \
             patch('auth.AUTH_SECRET', ''):
            summary = auth_config_summary()
        self.assertFalse(summary['github_configured'])
        self.assertTrue(summary['did_enabled'])
        self.assertIn('did', summary['providers'])

    def test_config_with_github(self):
        with patch('auth.GITHUB_CLIENT_ID', 'id'), \
             patch('auth.GITHUB_CLIENT_SECRET', 'secret'), \
             patch('auth.AUTH_SECRET', 'key'):
            summary = auth_config_summary()
        self.assertTrue(summary['github_configured'])
        self.assertIn('github', summary['providers'])
        self.assertIn('api_key', summary['providers'])


if __name__ == '__main__':
    unittest.main()
