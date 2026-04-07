#!/usr/bin/env python3
"""SQLite-backed mirror for Meridian owner accounting state."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any


def db_path_for_owner_ledger(owner_ledger_path: str) -> str:
    directory = os.path.dirname(os.path.abspath(owner_ledger_path))
    return os.path.join(directory, 'accounting.db')


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_ledger (
            org_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            owner TEXT NOT NULL,
            created_at TEXT NOT NULL,
            capital_contributed_usd REAL NOT NULL,
            expenses_paid_usd REAL NOT NULL,
            reimbursements_received_usd REAL NOT NULL,
            draws_taken_usd REAL NOT NULL,
            entries_json TEXT NOT NULL,
            meta_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS accounting_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            type TEXT NOT NULL,
            amount_usd REAL,
            note TEXT,
            by_actor TEXT,
            payload_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_accounting_tx_org_time '
        'ON accounting_transactions(org_id, timestamp DESC, id DESC)'
    )


def _default_owner_ledger(org_id: str | None = None) -> dict[str, Any]:
    return {
        'version': 1,
        'owner': 'Son Nguyen The',
        'created_at': '',
        'capital_contributed_usd': 0.0,
        'expenses_paid_usd': 0.0,
        'reimbursements_received_usd': 0.0,
        'draws_taken_usd': 0.0,
        'entries': [],
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': org_id or '',
            'boundary_name': 'accounting',
            'identity_model': 'session',
            'storage_model': 'capsule_owned_owner_ledger',
        },
    }


def _normalize_owner_ledger(payload: dict[str, Any] | None, org_id: str | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    normalized = dict(_default_owner_ledger(org_id))
    normalized.update(payload)
    normalized.setdefault('entries', [])
    if not isinstance(normalized['entries'], list):
        normalized['entries'] = list(normalized['entries'])
    normalized.setdefault('_meta', {})
    normalized['_meta']['service_scope'] = 'institution_owned_service'
    normalized['_meta']['bound_org_id'] = org_id or normalized['_meta'].get('bound_org_id', '')
    normalized['_meta']['boundary_name'] = 'accounting'
    normalized['_meta']['identity_model'] = 'session'
    normalized['_meta']['storage_model'] = 'capsule_owned_owner_ledger'
    return normalized


def _row_to_owner_ledger(row: sqlite3.Row) -> dict[str, Any]:
    payload = {
        'version': row['version'],
        'owner': row['owner'],
        'created_at': row['created_at'],
        'capital_contributed_usd': float(row['capital_contributed_usd'] or 0.0),
        'expenses_paid_usd': float(row['expenses_paid_usd'] or 0.0),
        'reimbursements_received_usd': float(row['reimbursements_received_usd'] or 0.0),
        'draws_taken_usd': float(row['draws_taken_usd'] or 0.0),
        'entries': json.loads(row['entries_json'] or '[]'),
        '_meta': json.loads(row['meta_json'] or '{}'),
    }
    if not isinstance(payload['entries'], list):
        payload['entries'] = []
    if not isinstance(payload['_meta'], dict):
        payload['_meta'] = {}
    return _normalize_owner_ledger(payload, payload['_meta'].get('bound_org_id'))


def _upsert_owner_ledger(conn: sqlite3.Connection, payload: dict[str, Any], updated_at: str, org_id: str) -> None:
    conn.execute(
        """
        INSERT INTO owner_ledger (
            org_id, version, owner, created_at, capital_contributed_usd,
            expenses_paid_usd, reimbursements_received_usd, draws_taken_usd,
            entries_json, meta_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(org_id) DO UPDATE SET
            version=excluded.version,
            owner=excluded.owner,
            created_at=excluded.created_at,
            capital_contributed_usd=excluded.capital_contributed_usd,
            expenses_paid_usd=excluded.expenses_paid_usd,
            reimbursements_received_usd=excluded.reimbursements_received_usd,
            draws_taken_usd=excluded.draws_taken_usd,
            entries_json=excluded.entries_json,
            meta_json=excluded.meta_json,
            updated_at=excluded.updated_at
        """,
        (
            org_id,
            int(payload.get('version', 1) or 1),
            payload.get('owner', ''),
            payload.get('created_at', updated_at),
            float(payload.get('capital_contributed_usd', 0.0) or 0.0),
            float(payload.get('expenses_paid_usd', 0.0) or 0.0),
            float(payload.get('reimbursements_received_usd', 0.0) or 0.0),
            float(payload.get('draws_taken_usd', 0.0) or 0.0),
            json.dumps(payload.get('entries') or [], sort_keys=True),
            json.dumps(payload.get('_meta') or {}, sort_keys=True),
            updated_at,
        ),
    )


def _write_json_atomic(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    tmp_path = f'{path}.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(payload, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def load_owner_ledger_state(owner_ledger_path: str, org_id: str | None = None) -> dict[str, Any]:
    db_path = db_path_for_owner_ledger(owner_ledger_path)
    if os.path.exists(db_path):
        try:
            with _connect(db_path) as conn:
                _ensure_schema(conn)
                if org_id:
                    row = conn.execute(
                        'SELECT * FROM owner_ledger WHERE org_id = ?',
                        (org_id,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        'SELECT * FROM owner_ledger ORDER BY updated_at DESC LIMIT 1',
                    ).fetchone()
            if row is not None:
                payload = _row_to_owner_ledger(row)
                if not os.path.exists(owner_ledger_path):
                    _write_json_atomic(owner_ledger_path, payload)
                return payload
        except sqlite3.Error:
            pass

    if os.path.exists(owner_ledger_path):
        try:
            with open(owner_ledger_path) as f:
                payload = json.load(f)
            payload = _normalize_owner_ledger(payload, org_id)
            save_owner_ledger_state(owner_ledger_path, payload, org_id=org_id)
            return payload
        except (OSError, json.JSONDecodeError, sqlite3.Error):
            pass

    return _normalize_owner_ledger({}, org_id)


def save_owner_ledger_state(
    owner_ledger_path: str,
    payload: dict[str, Any],
    *,
    org_id: str | None = None,
) -> dict[str, Any]:
    normalized = _normalize_owner_ledger(payload, org_id)
    db_org_id = org_id or normalized['_meta'].get('bound_org_id', '') or ''
    updated_at = normalized.get('updated_at') or normalized.get('updatedAt') or ''
    _write_json_atomic(owner_ledger_path, normalized)
    db_path = db_path_for_owner_ledger(owner_ledger_path)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        _upsert_owner_ledger(conn, normalized, updated_at, db_org_id)
        conn.commit()
    return normalized


def append_transaction(
    transactions_path: str,
    entry: dict[str, Any],
    *,
    org_id: str | None = None,
) -> dict[str, Any]:
    normalized = dict(entry)
    normalized.setdefault('ts', '')
    if not normalized['ts']:
        normalized['ts'] = normalized.get('timestamp', '') or ''
    db_org_id = org_id or normalized.get('org_id', '') or ''
    directory = os.path.dirname(transactions_path) or '.'
    os.makedirs(directory, exist_ok=True)
    with open(transactions_path, 'a') as f:
        f.write(json.dumps(normalized) + '\n')
        f.flush()
        os.fsync(f.fileno())

    db_path = db_path_for_owner_ledger(transactions_path)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO accounting_transactions (
                org_id, timestamp, type, amount_usd, note, by_actor, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                db_org_id,
                normalized.get('ts', ''),
                normalized.get('type', ''),
                normalized.get('amount_usd'),
                normalized.get('note', ''),
                normalized.get('by', ''),
                json.dumps(normalized, sort_keys=True),
            ),
        )
        conn.commit()
    return normalized


def db_status_for_owner_ledger(owner_ledger_path: str, org_id: str | None = None) -> dict[str, Any]:
    db_path = db_path_for_owner_ledger(owner_ledger_path)
    snapshot = {
        'path': db_path,
        'status': 'absent',
        'reason': 'sqlite accounting mirror has not been initialized yet',
    }
    if not os.path.exists(db_path):
        return snapshot
    try:
        with _connect(db_path) as conn:
            _ensure_schema(conn)
            ledger_count = conn.execute('SELECT COUNT(*) FROM owner_ledger').fetchone()[0]
            tx_count = conn.execute('SELECT COUNT(*) FROM accounting_transactions').fetchone()[0]
            if org_id:
                row = conn.execute(
                    'SELECT updated_at FROM owner_ledger WHERE org_id = ?',
                    (org_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    'SELECT updated_at FROM owner_ledger ORDER BY updated_at DESC LIMIT 1',
                ).fetchone()
        snapshot.update({
            'status': 'present',
            'reason': '',
            'size_bytes': os.path.getsize(db_path),
            'owner_ledger_rows': int(ledger_count or 0),
            'transaction_rows': int(tx_count or 0),
            'updated_at': row['updated_at'] if row and row['updated_at'] else '',
        })
    except sqlite3.Error as exc:
        snapshot.update({
            'status': 'degraded',
            'reason': str(exc),
        })
    return snapshot
