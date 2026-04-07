#!/usr/bin/env python3
import json
import os
import shutil
import tempfile
import unittest

import capsule
import subscription_preview_queue


class SubscriptionPreviewQueueTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='subscription-preview-queue-')
        self.org_id = 'org_demo'
        self._store = os.path.join(self._tmp, 'capsules', self.org_id, 'subscription_preview_queue.json')
        self._lock = os.path.join(self._tmp, 'capsules', self.org_id, '.subscription_preview_queue.lock')
        self._orig_capsule_path = capsule.capsule_path
        capsule.capsule_path = lambda org_id, filename: os.path.join(
            self._tmp,
            'capsules',
            org_id,
            filename,
        )

    def tearDown(self):
        capsule.capsule_path = self._orig_capsule_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_queue_preview_from_pilot_request_is_persisted_and_read_only_to_inspect(self):
        request = {
            'request_id': 'pir_demo',
            'name': 'Jane Doe',
            'company': 'Acme',
            'email': 'jane@example.com',
            'telegram_handle': '@jane',
            'requested_cadence': 'Weekly brief',
            'requested_offer': 'manual_pilot',
            'competitors': ['OpenAI', 'Anthropic'],
            'topics': ['pricing', 'launches'],
            'reviewed_by': 'user_owner',
            'review_note': 'Useful enough to preview the continuation path',
            'reviewed_at': '2026-03-25T00:00:00Z',
        }

        result = subscription_preview_queue.queue_subscription_preview(
            request,
            org_id=self.org_id,
            by='user_owner',
            note='Pilot review complete',
        )

        self.assertTrue(os.path.exists(self._store))
        self.assertTrue(os.path.exists(self._lock))
        self.assertEqual(result['preview']['preview_id'], 'quote_pir_demo')
        self.assertFalse(result['preview']['checkout_claimed'])
        self.assertFalse(result['preview']['payment_capture_claimed'])
        self.assertEqual(result['summary']['total_previews'], 1)
        self.assertEqual(result['summary']['reviewed_count'], 1)
        self.assertGreater(len(result['preview']['plan_options']), 0)

        with open(self._store) as f:
            payload = json.load(f)
        self.assertEqual(payload['_meta']['boundary_name'], 'subscription_preview_queue')
        self.assertEqual(payload['subscription_previews']['quote_pir_demo']['pilot_request_id'], 'pir_demo')

        with open(self._store) as f:
            before = f.read()
        snap = subscription_preview_queue.subscription_preview_queue_snapshot(self.org_id)
        with open(self._store) as f:
            after = f.read()

        self.assertEqual(before, after)
        self.assertEqual(snap['summary']['total_previews'], 1)
        self.assertEqual(snap['queue_paths']['inspect'], '/api/subscriptions/preview-queue')
        self.assertEqual(snap['queue_paths']['checkout_capture'], '/api/subscriptions/checkout-capture')
        self.assertEqual(len(snap['subscription_previews']), 1)
        self.assertEqual(snap['subscription_previews'][0]['preview_id'], 'quote_pir_demo')

    def test_mark_preview_drafted_surfaces_draft_status_without_checkout(self):
        request = {
            'request_id': 'pir_draft_queue',
            'name': 'Jane Doe',
            'company': 'Acme',
            'reviewed_by': 'user_owner',
        }
        queued = subscription_preview_queue.queue_subscription_preview(
            request,
            org_id=self.org_id,
            by='user_owner',
            note='Draft the continuation offer',
        )

        updated = subscription_preview_queue.mark_preview_drafted(
            queued['preview']['preview_id'],
            'draft_quote_pir_draft_queue',
            org_id=self.org_id,
            by='user_owner',
        )
        snapshot = subscription_preview_queue.subscription_preview_queue_snapshot(self.org_id)

        self.assertEqual(updated['preview']['draft_subscription_id'], 'draft_quote_pir_draft_queue')
        self.assertEqual(updated['preview']['draft_state'], 'draft_created')
        self.assertEqual(updated['summary']['drafted_count'], 1)
        self.assertEqual(snapshot['summary']['drafted_count'], 1)
        self.assertEqual(snapshot['subscription_previews'][0]['draft_subscription_id'], 'draft_quote_pir_draft_queue')
        self.assertFalse(snapshot['subscription_previews'][0]['checkout_claimed'])
        self.assertFalse(snapshot['subscription_previews'][0]['payment_capture_claimed'])

    def test_queue_preview_upserts_same_request_id(self):
        request = {
            'request_id': 'pir_repeat',
            'name': 'Jane Doe',
            'company': 'Acme',
            'reviewed_by': 'user_owner',
        }
        first = subscription_preview_queue.queue_subscription_preview(request, org_id=self.org_id, by='user_owner')
        second = subscription_preview_queue.queue_subscription_preview(
            {**request, 'review_note': 'Updated review note'},
            org_id=self.org_id,
            by='user_owner',
            note='Updated review note',
        )

        self.assertEqual(first['preview']['preview_id'], second['preview']['preview_id'])
        self.assertEqual(second['summary']['total_previews'], 1)
        self.assertEqual(second['preview']['review_note'], 'Updated review note')


if __name__ == '__main__':
    unittest.main()
