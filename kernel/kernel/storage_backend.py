#!/usr/bin/env python3
"""Pluggable storage backend abstraction for kernel state.

Provides a uniform interface for loading, saving, and appending state,
with implementations for JSON files (current default) and SQLite
(production-grade alternative with concurrency and atomic transactions).

Usage:
    backend = create_backend('json', base_dir='/path/to/economy')
    backend = create_backend('sqlite', db_path='/path/to/state.db')

    backend.save('registry.json', data)
    data = backend.load('registry.json', default={})
    backend.append('audit.jsonl', entry)
    entries = backend.read_log('audit.jsonl', tail=10)
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
from abc import ABC, abstractmethod
from typing import Any


class StorageBackend(ABC):
    """Abstract storage backend interface."""

    @abstractmethod
    def load(self, key: str, default: Any) -> Any:
        """Load a JSON document by key. Return default if not found."""

    @abstractmethod
    def save(self, key: str, data: Any) -> None:
        """Save a JSON document atomically by key."""

    @abstractmethod
    def append(self, key: str, entry: dict[str, Any]) -> None:
        """Append a JSONL entry to a log identified by key."""

    @abstractmethod
    def read_log(self, key: str, tail: int | None = None) -> list[dict[str, Any]]:
        """Read all (or last N) entries from a log. Return [] if not found."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if a document with the given key exists."""

    def migrate_from(
        self,
        source: StorageBackend,
        document_keys: list[str],
        log_keys: list[str],
    ) -> dict[str, int]:
        """Migrate documents and logs from another backend into this one."""
        stats = {'documents': 0, 'log_entries': 0}
        for key in document_keys:
            if source.exists(key):
                data = source.load(key, None)
                if data is not None:
                    self.save(key, data)
                    stats['documents'] += 1
        for key in log_keys:
            entries = source.read_log(key)
            for entry in entries:
                self.append(key, entry)
            stats['log_entries'] += len(entries)
        return stats


class JsonFileBackend(StorageBackend):
    """File-backed JSON storage (current kernel default)."""

    def __init__(self, base_dir: str) -> None:
        self._base_dir = base_dir

    def _path(self, key: str) -> str:
        return os.path.join(self._base_dir, key)

    def load(self, key: str, default: Any) -> Any:
        path = self._path(key)
        if not os.path.exists(path):
            return default
        try:
            with open(path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def save(self, key: str, data: Any) -> None:
        path = self._path(key)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        tmp_path = f'{path}.tmp.{os.getpid()}'
        try:
            with open(tmp_path, 'w') as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def append(self, key: str, entry: dict[str, Any]) -> None:
        path = self._path(key)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
            f.flush()
            os.fsync(f.fileno())

    def read_log(self, key: str, tail: int | None = None) -> list[dict[str, Any]]:
        path = self._path(key)
        if not os.path.exists(path):
            return []
        entries: list[dict[str, Any]] = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if tail is not None and tail > 0:
            entries = entries[-tail:]
        return entries

    def exists(self, key: str) -> bool:
        return os.path.exists(self._path(key))


class SqliteBackend(StorageBackend):
    """SQLite-backed storage with WAL mode for concurrent reads.

    Documents are stored as JSON text in a key-value table.
    Logs are stored as rows with auto-incrementing rowid for ordering.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, timeout=10.0)
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA busy_timeout=5000')
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        with self._init_lock:
            conn = self._conn()
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at REAL NOT NULL DEFAULT (julianday('now'))
                );
                CREATE TABLE IF NOT EXISTS log_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at REAL NOT NULL DEFAULT (julianday('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_log_key ON log_entries(key);
            ''')
            conn.commit()

    def load(self, key: str, default: Any) -> Any:
        conn = self._conn()
        row = conn.execute(
            'SELECT data FROM documents WHERE key = ?', (key,)
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return default

    def save(self, key: str, data: Any) -> None:
        conn = self._conn()
        serialized = json.dumps(data)
        conn.execute(
            'INSERT OR REPLACE INTO documents (key, data, updated_at) VALUES (?, ?, julianday(\'now\'))',
            (key, serialized),
        )
        conn.commit()

    def append(self, key: str, entry: dict[str, Any]) -> None:
        conn = self._conn()
        serialized = json.dumps(entry)
        conn.execute(
            'INSERT INTO log_entries (key, data) VALUES (?, ?)',
            (key, serialized),
        )
        conn.commit()

    def read_log(self, key: str, tail: int | None = None) -> list[dict[str, Any]]:
        conn = self._conn()
        if tail is not None and tail > 0:
            rows = conn.execute(
                'SELECT data FROM (SELECT data, id FROM log_entries WHERE key = ? ORDER BY id DESC LIMIT ?) ORDER BY id ASC',
                (key, tail),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT data FROM log_entries WHERE key = ? ORDER BY id ASC',
                (key,),
            ).fetchall()
        entries: list[dict[str, Any]] = []
        for (raw,) in rows:
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return entries

    def exists(self, key: str) -> bool:
        conn = self._conn()
        row = conn.execute(
            'SELECT 1 FROM documents WHERE key = ? LIMIT 1', (key,)
        ).fetchone()
        return row is not None


def _default_rust_kv_bridge_bin() -> str:
    env_path = os.environ.get('MERIDIAN_KERNEL_RUST_KV_BRIDGE_BIN')
    if env_path:
        return env_path
    kernel_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(kernel_dir)
    candidates = [
        os.path.join(repo_root, 'kernel-rs-explore', 'target', 'release', 'storage_bridge'),
        os.path.join(repo_root, 'kernel-rs-explore', 'target', 'debug', 'storage_bridge'),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        'rust_kv_bridge binary not found; run '
        '"cargo build --release --bin storage_bridge" in kernel-rs-explore '
        'or set MERIDIAN_KERNEL_RUST_KV_BRIDGE_BIN'
    )


class RustKvBridgeBackend(StorageBackend):
    """Rust KV bridge backend via kernel-rs-explore/storage_bridge."""

    def __init__(
        self,
        db_path: str,
        bridge_bin: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._db_path = db_path
        self._bridge_bin = bridge_bin or _default_rust_kv_bridge_bin()
        self._timeout_seconds = timeout_seconds
        if not os.path.exists(self._bridge_bin):
            raise FileNotFoundError(f'rust_kv_bridge binary not found: {self._bridge_bin}')

    def _run(self, operation: str, *args: str) -> Any:
        cmd = [self._bridge_bin, '--db-path', self._db_path, operation, *args]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
            check=False,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            raise RuntimeError(f'rust_kv_bridge {operation} failed: {stderr or proc.stdout.strip()}')
        raw = proc.stdout.strip()
        if not raw:
            return None
        return json.loads(raw)

    def load(self, key: str, default: Any) -> Any:
        value = self._run('load', '--key', key)
        return default if value is None else value

    def save(self, key: str, data: Any) -> None:
        self._run('save', '--key', key, '--json', json.dumps(data, sort_keys=True))

    def append(self, key: str, entry: dict[str, Any]) -> None:
        self._run('append', '--key', key, '--json', json.dumps(entry, sort_keys=True))

    def read_log(self, key: str, tail: int | None = None) -> list[dict[str, Any]]:
        args = ['--key', key]
        if tail is not None and tail > 0:
            args.extend(['--tail', str(tail)])
        value = self._run('read-log', *args)
        if isinstance(value, list):
            return [entry for entry in value if isinstance(entry, dict)]
        return []

    def exists(self, key: str) -> bool:
        value = self._run('exists', '--key', key)
        return bool(value)


def create_backend(
    backend_type: str,
    *,
    base_dir: str | None = None,
    db_path: str | None = None,
    rust_kv_bridge_bin: str | None = None,
) -> StorageBackend:
    """Factory function for storage backends.

    Args:
        backend_type: 'json', 'sqlite', or 'rust_kv_bridge'
        base_dir: Required for 'json' backend
        db_path: Required for 'sqlite' and 'rust_kv_bridge' backends
    """
    if backend_type == 'json':
        if base_dir is None:
            raise ValueError('base_dir is required for json backend')
        return JsonFileBackend(base_dir)
    if backend_type == 'sqlite':
        if db_path is None:
            raise ValueError('db_path is required for sqlite backend')
        return SqliteBackend(db_path)
    if backend_type in {'rust_kv_bridge', 'rust-kv', 'rust_kv'}:
        if db_path is None:
            raise ValueError('db_path is required for rust_kv_bridge backend')
        return RustKvBridgeBackend(db_path=db_path, bridge_bin=rust_kv_bridge_bin)
    raise ValueError(
        f'unknown backend type: {backend_type!r}; supported: json, sqlite, rust_kv_bridge'
    )
