#!/usr/bin/env python3
import json
import pathlib
import tempfile
import unittest
from unittest import mock

import memory_graph


class MemoryGraphTemporalTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory(prefix='memory-graph-temporal-')
        self._graph_file = pathlib.Path(self._tmpdir.name) / 'memory_graph.json'
        self._patch_path = mock.patch(
            'memory_graph._graph_path',
            side_effect=lambda org_id=None: str(self._graph_file),
        )
        self._patch_path.start()

    def tearDown(self):
        self._patch_path.stop()
        self._tmpdir.cleanup()

    def test_temporal_query_returns_events_and_verifiable_proof(self):
        memory_graph.append_node(
            key='fact',
            value={'value': 'A', 'agent_id': 'agent_atlas'},
            org_id='org_test',
            agent_id='agent_atlas',
            timestamp='2026-04-08T10:00:00Z',
        )
        memory_graph.append_node(
            key='fact',
            value={'value': 'B', 'agent_id': 'agent_atlas'},
            org_id='org_test',
            agent_id='agent_atlas',
            timestamp='2026-04-08T10:05:00Z',
        )

        payload = memory_graph.temporal_query_with_proof(
            org_id='org_test',
            agent_id='agent_atlas',
            start_ts='2026-04-08T10:00:00Z',
            end_ts='2026-04-08T10:10:00Z',
        )

        self.assertEqual(len(payload['events']), 2)
        self.assertTrue(payload['proof']['chain_valid'])
        self.assertEqual(payload['proof']['selected_count'], 2)
        self.assertRegex(payload['proof']['head_hash'], r'^[0-9a-f]{64}$')

    def test_temporal_query_rejects_integrity_mismatch(self):
        memory_graph.append_node(
            key='fact',
            value={'value': 'A', 'agent_id': 'agent_atlas'},
            org_id='org_test',
            agent_id='agent_atlas',
            timestamp='2026-04-08T10:00:00Z',
        )
        content = json.loads(self._graph_file.read_text(encoding='utf-8'))
        content['nodes'][0]['value']['value'] = 'tampered'
        self._graph_file.write_text(json.dumps(content, indent=2), encoding='utf-8')

        with self.assertRaisesRegex(ValueError, 'memory_integrity_mismatch:'):
            memory_graph.temporal_query_with_proof(org_id='org_test')


if __name__ == '__main__':
    unittest.main()
