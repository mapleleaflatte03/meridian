#!/usr/bin/env python3
"""Tests for the pluggable storage backend abstraction."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
KERNEL_DIR = os.path.dirname(THIS_DIR)
if KERNEL_DIR not in sys.path:
    sys.path.insert(0, KERNEL_DIR)

from storage_backend import (
    JsonFileBackend,
    RustKvBridgeBackend,
    SqliteBackend,
    create_backend,
)


_RUST_BRIDGE_BIN: str | None = None


def _ensure_rust_bridge_bin() -> str:
    global _RUST_BRIDGE_BIN
    if _RUST_BRIDGE_BIN:
        return _RUST_BRIDGE_BIN
    if shutil.which('cargo') is None:
        raise unittest.SkipTest('cargo is required for rust_kv_bridge backend tests')
    repo_root = os.path.dirname(KERNEL_DIR)
    crate_dir = os.path.join(repo_root, 'kernel-rs-explore')
    bridge_bin = os.path.join(crate_dir, 'target', 'release', 'storage_bridge')
    subprocess.run(
        ['cargo', 'build', '--quiet', '--release', '--bin', 'storage_bridge'],
        cwd=crate_dir,
        check=True,
    )
    if not os.path.exists(bridge_bin):
        raise unittest.SkipTest(f'compiled storage bridge missing at {bridge_bin}')
    _RUST_BRIDGE_BIN = bridge_bin
    return bridge_bin


class BackendContractTests:
    """Shared contract tests run against every backend."""

    def make_backend(self, tmp_dir):
        raise NotImplementedError

    def test_load_returns_default_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.make_backend(tmp)
            default = {'agents': {}}
            result = backend.load('registry.json', default)
            self.assertEqual(result, default)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.make_backend(tmp)
            data = {'agents': {'a1': {'name': 'Atlas', 'role': 'worker'}}}
            backend.save('registry.json', data)
            loaded = backend.load('registry.json', {})
            self.assertEqual(loaded, data)

    def test_save_overwrites_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.make_backend(tmp)
            backend.save('registry.json', {'v': 1})
            backend.save('registry.json', {'v': 2})
            loaded = backend.load('registry.json', {})
            self.assertEqual(loaded, {'v': 2})

    def test_append_creates_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.make_backend(tmp)
            backend.append('audit.jsonl', {'action': 'create', 'ts': 1})
            backend.append('audit.jsonl', {'action': 'delete', 'ts': 2})
            entries = backend.read_log('audit.jsonl')
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]['action'], 'create')
            self.assertEqual(entries[1]['action'], 'delete')

    def test_read_log_empty_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.make_backend(tmp)
            entries = backend.read_log('audit.jsonl')
            self.assertEqual(entries, [])

    def test_read_log_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.make_backend(tmp)
            for i in range(10):
                backend.append('log.jsonl', {'i': i})
            tail = backend.read_log('log.jsonl', tail=3)
            self.assertEqual(len(tail), 3)
            self.assertEqual(tail[0]['i'], 7)
            self.assertEqual(tail[2]['i'], 9)

    def test_exists_returns_correct_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.make_backend(tmp)
            self.assertFalse(backend.exists('registry.json'))
            backend.save('registry.json', {'v': 1})
            self.assertTrue(backend.exists('registry.json'))

    def test_nested_data_structures(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = self.make_backend(tmp)
            data = {
                'nested': {'deep': {'value': [1, 2, 3]}},
                'list': [{'a': 1}, {'b': 2}],
                'null_field': None,
                'bool_field': True,
            }
            backend.save('complex.json', data)
            loaded = backend.load('complex.json', {})
            self.assertEqual(loaded, data)


class TestJsonFileBackend(BackendContractTests, unittest.TestCase):
    def make_backend(self, tmp_dir):
        return JsonFileBackend(tmp_dir)


class TestSqliteBackend(BackendContractTests, unittest.TestCase):
    def make_backend(self, tmp_dir):
        return SqliteBackend(os.path.join(tmp_dir, 'state.db'))


class TestRustKvBridgeBackend(BackendContractTests, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge_bin = _ensure_rust_bridge_bin()

    def make_backend(self, tmp_dir):
        return RustKvBridgeBackend(
            db_path=os.path.join(tmp_dir, 'state.sled'),
            bridge_bin=self.bridge_bin,
        )


class TestCreateBackend(unittest.TestCase):
    def test_create_json_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = create_backend('json', base_dir=tmp)
            self.assertIsInstance(backend, JsonFileBackend)

    def test_create_sqlite_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = create_backend('sqlite', db_path=os.path.join(tmp, 'test.db'))
            self.assertIsInstance(backend, SqliteBackend)

    def test_unknown_backend_raises(self):
        with self.assertRaises(ValueError):
            create_backend('postgres')

    def test_create_rust_kv_bridge_backend(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = create_backend(
                'rust_kv_bridge',
                db_path=os.path.join(tmp, 'state.sled'),
                rust_kv_bridge_bin=_ensure_rust_bridge_bin(),
            )
            self.assertIsInstance(backend, RustKvBridgeBackend)


class TestMigration(unittest.TestCase):
    def test_migrate_json_to_sqlite_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_backend = JsonFileBackend(tmp)
            json_backend.save('registry.json', {'agents': {'a1': {'role': 'worker'}}})
            json_backend.append('audit.jsonl', {'action': 'create'})
            json_backend.append('audit.jsonl', {'action': 'update'})

            db_path = os.path.join(tmp, 'migrated.db')
            sqlite_backend = SqliteBackend(db_path)
            sqlite_backend.migrate_from(json_backend, ['registry.json'], ['audit.jsonl'])

            loaded = sqlite_backend.load('registry.json', {})
            self.assertEqual(loaded, {'agents': {'a1': {'role': 'worker'}}})
            entries = sqlite_backend.read_log('audit.jsonl')
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]['action'], 'create')


class TestConcurrency(unittest.TestCase):
    def test_sqlite_concurrent_appends(self):
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            backend = SqliteBackend(os.path.join(tmp, 'concurrent.db'))
            errors = []

            def append_entries(thread_id, count):
                try:
                    for i in range(count):
                        backend.append('log.jsonl', {'thread': thread_id, 'i': i})
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=append_entries, args=(t, 20)) for t in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [])
            entries = backend.read_log('log.jsonl')
            self.assertEqual(len(entries), 100)


class TestLatencyBaseline(unittest.TestCase):
    """Measure read/write latency to establish KPI baseline.

    These are opt-in benchmarks; they print results but don't assert
    relative performance because fsync latency varies by disk.
    Run manually with: python3 -m unittest tests.test_storage_backend.TestLatencyBaseline -v
    """

    @unittest.skipIf(
        os.environ.get('SKIP_LATENCY_BENCH', '1') == '1',
        'SKIP_LATENCY_BENCH=1 (default); set to 0 to run latency benchmarks',
    )
    def test_json_vs_sqlite_write_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_b = JsonFileBackend(tmp)
            sqlite_b = SqliteBackend(os.path.join(tmp, 'bench.db'))
            data = {'agents': {f'a{i}': {'role': 'worker', 'score': i} for i in range(10)}}
            n = 5

            # JSON writes
            t0 = time.perf_counter()
            for i in range(n):
                json_b.save(f'bench_{i}.json', data)
            json_write_ms = (time.perf_counter() - t0) * 1000

            # SQLite writes
            t0 = time.perf_counter()
            for i in range(n):
                sqlite_b.save(f'bench_{i}.json', data)
            sqlite_write_ms = (time.perf_counter() - t0) * 1000

            # JSON reads
            t0 = time.perf_counter()
            for i in range(n):
                json_b.load(f'bench_{i}.json', {})
            json_read_ms = (time.perf_counter() - t0) * 1000

            # SQLite reads
            t0 = time.perf_counter()
            for i in range(n):
                sqlite_b.load(f'bench_{i}.json', {})
            sqlite_read_ms = (time.perf_counter() - t0) * 1000

            print(f'\n  JSON  write {n}x: {json_write_ms:.1f}ms  read {n}x: {json_read_ms:.1f}ms')
            print(f'  SQLite write {n}x: {sqlite_write_ms:.1f}ms  read {n}x: {sqlite_read_ms:.1f}ms')

            # Both must complete — no assertion on relative speed, just that both work
            self.assertGreater(json_write_ms, 0)
            self.assertGreater(sqlite_write_ms, 0)

    @unittest.skipIf(
        os.environ.get('SKIP_LATENCY_BENCH', '1') == '1',
        'SKIP_LATENCY_BENCH=1 (default); set to 0 to run latency benchmarks',
    )
    def test_append_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_b = JsonFileBackend(tmp)
            sqlite_b = SqliteBackend(os.path.join(tmp, 'bench_log.db'))
            entry = {'action': 'test', 'agent': 'a1', 'ts': 1234567890}

            t0 = time.perf_counter()
            for _ in range(10):
                json_b.append('bench.jsonl', entry)
            json_append_ms = (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            for _ in range(10):
                sqlite_b.append('bench.jsonl', entry)
            sqlite_append_ms = (time.perf_counter() - t0) * 1000

            print(f'\n  JSON  append 10x: {json_append_ms:.1f}ms')
            print(f'  SQLite append 10x: {sqlite_append_ms:.1f}ms')

            self.assertGreater(json_append_ms, 0)
            self.assertGreater(sqlite_append_ms, 0)


if __name__ == '__main__':
    unittest.main()
