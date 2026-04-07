#!/usr/bin/env python3
import json
import os
import shutil
import tempfile
import unittest

import pilot_intake


class PilotIntakeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix='pilot-intake-')
        self.org_id = 'org_demo'
        self._store = os.path.join(self._tmp, 'capsules', self.org_id, 'pilot_intake.json')
        self._lock = os.path.join(self._tmp, 'capsules', self.org_id, '.pilot_intake.lock')
        self._orig_capsule_path = pilot_intake.capsule_path
        self._orig_resolve_org_id = pilot_intake.resolve_org_id
        pilot_intake.capsule_path = lambda org_id, filename: os.path.join(
            self._tmp,
            'capsules',
            org_id,
            filename,
        )
        pilot_intake.resolve_org_id = lambda org_id=None: org_id

    def tearDown(self):
        pilot_intake.capsule_path = self._orig_capsule_path
        pilot_intake.resolve_org_id = self._orig_resolve_org_id
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_submit_pilot_request_persists_queue_entry(self):
        result = pilot_intake.submit_pilot_request(
            'Jane Doe',
            'Acme',
            email='jane@example.com',
            requested_cadence='Daily alert',
            competitors='OpenAI, Anthropic',
            topics='pricing, launches',
            notes='Need watchlist coverage',
            source_page='pilot.html',
            org_id=self.org_id,
        )

        self.assertTrue(os.path.exists(self._store))
        self.assertTrue(os.path.exists(self._lock))
        self.assertEqual(result['request']['company'], 'Acme')
        self.assertEqual(result['request']['status'], 'requested')
        self.assertEqual(result['summary']['total_requests'], 1)
        self.assertEqual(result['summary']['requested_count'], 1)
        self.assertEqual(result['summary']['contactable_count'], 1)

        with open(self._store) as f:
            payload = json.load(f)
        self.assertEqual(payload['_meta']['boundary_name'], 'pilot_intake')
        self.assertEqual(payload['requests'][result['request']['request_id']]['contact_channel'], 'email')

        snapshot = pilot_intake.queue_snapshot(self.org_id)
        self.assertEqual(snapshot['summary']['total_requests'], 1)
        self.assertEqual(snapshot['requests'][0]['request_id'], result['request']['request_id'])
        self.assertEqual(snapshot['request_paths']['submit'], '/api/pilot/intake')
        self.assertEqual(snapshot['request_paths']['operator_inspect'], '/api/pilot/intake/operator')
        self.assertEqual(snapshot['requests'][0]['review_state'], 'pending_review')

    def test_operator_acknowledge_marks_request_reviewed_without_fulfillment_claim(self):
        submitted = pilot_intake.submit_pilot_request(
            'Jane Doe',
            'Acme',
            email='jane@example.com',
            org_id=self.org_id,
        )

        result = pilot_intake.acknowledge_pilot_request(
            submitted['request']['request_id'],
            'user_owner',
            org_id=self.org_id,
            note='Reviewed for manual pilot fit',
        )

        self.assertEqual(result['request']['status'], 'reviewed')
        self.assertEqual(result['request']['reviewed_by'], 'user_owner')
        self.assertEqual(result['request']['review_state'], 'acknowledged')
        self.assertTrue(result['request']['operator_acknowledged'])
        self.assertEqual(result['summary']['reviewed_count'], 1)
        self.assertEqual(result['summary']['acknowledged_count'], 1)

        operator_snapshot = pilot_intake.operator_review_snapshot(self.org_id)
        self.assertEqual(operator_snapshot['management_mode'], 'manual_operator_review')
        self.assertEqual(operator_snapshot['operator_review']['review_mode'], 'manual_ack_only')
        self.assertEqual(operator_snapshot['operator_review']['acknowledged_count'], 1)
        self.assertEqual(operator_snapshot['requests'][0]['review_state'], 'acknowledged')

    def test_submit_pilot_request_requires_contact_method(self):
        with self.assertRaisesRegex(ValueError, 'email or telegram_handle is required'):
            pilot_intake.submit_pilot_request(
                'Jane Doe',
                'Acme',
                org_id=self.org_id,
            )


if __name__ == '__main__':
    unittest.main()
