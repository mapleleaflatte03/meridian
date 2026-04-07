#!/usr/bin/env python3
"""SQLite-backed mirror for Meridian case records."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any


def db_path_for_cases_file(cases_path: str) -> str:
    directory = os.path.dirname(os.path.abspath(cases_path))
    return os.path.join(directory, 'cases.db')


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
        CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            institution_id TEXT NOT NULL,
            source_institution_id TEXT,
            target_host_id TEXT,
            target_institution_id TEXT,
            claim_type TEXT NOT NULL,
            linked_commitment_id TEXT,
            linked_warrant_id TEXT,
            evidence_refs_json TEXT NOT NULL,
            status TEXT NOT NULL,
            opened_by TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reviewed_by TEXT,
            reviewed_at TEXT,
            review_note TEXT,
            resolution TEXT,
            note TEXT,
            metadata_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_cases_institution_status_opened '        'ON cases(institution_id, status, opened_at DESC)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_cases_commitment '        'ON cases(institution_id, linked_commitment_id, status)'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_cases_peer '        'ON cases(institution_id, target_host_id, status)'
    )


def _default_store() -> dict[str, Any]:
    return {
        'cases': {},
        'updatedAt': '',
        'states': ['open', 'stayed', 'resolved'],
        'claim_types': [
            'non_delivery',
            'fraudulent_proof',
            'breach_of_commitment',
            'invalid_settlement_notice',
            'misrouted_execution',
        ],
    }


def _normalize_record(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        record = {}
    normalized = dict(record)
    normalized.setdefault('case_id', '')
    normalized.setdefault('institution_id', '')
    normalized.setdefault('source_institution_id', '')
    normalized.setdefault('target_host_id', '')
    normalized.setdefault('target_institution_id', '')
    normalized.setdefault('claim_type', '')
    normalized.setdefault('linked_commitment_id', '')
    normalized.setdefault('linked_warrant_id', '')
    normalized.setdefault('evidence_refs', [])
    if not isinstance(normalized['evidence_refs'], list):
        normalized['evidence_refs'] = list(normalized['evidence_refs'])
    normalized.setdefault('status', 'open')
    normalized.setdefault('opened_by', '')
    normalized.setdefault('opened_at', '')
    normalized.setdefault('updated_at', normalized.get('opened_at', ''))
    normalized.setdefault('reviewed_by', '')
    normalized.setdefault('reviewed_at', '')
    normalized.setdefault('review_note', '')
    normalized.setdefault('resolution', '')
    normalized.setdefault('note', '')
    normalized.setdefault('metadata', {})
    if not isinstance(normalized['metadata'], dict):
        normalized['metadata'] = {}
    return normalized


def _record_to_row(record: dict[str, Any], org_id: str | None) -> tuple[Any, ...]:
    normalized = _normalize_record(record)
    institution_id = normalized.get('institution_id') or org_id or ''
    return (
        normalized.get('case_id', ''),
        institution_id,
        normalized.get('source_institution_id', ''),
        normalized.get('target_host_id', ''),
        normalized.get('target_institution_id', ''),
        normalized.get('claim_type', ''),
        normalized.get('linked_commitment_id', ''),
        normalized.get('linked_warrant_id', ''),
        json.dumps(normalized.get('evidence_refs') or [], sort_keys=True),
        normalized.get('status', 'open'),
        normalized.get('opened_by', ''),
        normalized.get('opened_at', ''),
        normalized.get('updated_at', normalized.get('opened_at', '')),
        normalized.get('reviewed_by', ''),
        normalized.get('reviewed_at', ''),
        normalized.get('review_note', ''),
        normalized.get('resolution', ''),
        normalized.get('note', ''),
        json.dumps(normalized.get('metadata') or {}, sort_keys=True),
    )


def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return _normalize_record({
        'case_id': row['case_id'],
        'institution_id': row['institution_id'],
        'source_institution_id': row['source_institution_id'],
        'target_host_id': row['target_host_id'],
        'target_institution_id': row['target_institution_id'],
        'claim_type': row['claim_type'],
        'linked_commitment_id': row['linked_commitment_id'],
        'linked_warrant_id': row['linked_warrant_id'],
        'evidence_refs': json.loads(row['evidence_refs_json'] or '[]'),
        'status': row['status'],
        'opened_by': row['opened_by'],
        'opened_at': row['opened_at'],
        'updated_at': row['updated_at'],
        'reviewed_by': row['reviewed_by'],
        'reviewed_at': row['reviewed_at'],
        'review_note': row['review_note'],
        'resolution': row['resolution'],
        'note': row['note'],
        'metadata': json.loads(row['metadata_json'] or '{}'),
    })


def _upsert_record(conn: sqlite3.Connection, record: dict[str, Any], org_id: str | None) -> None:
    conn.execute(
        """
        INSERT INTO cases (
            case_id, institution_id, source_institution_id, target_host_id,
            target_institution_id, claim_type, linked_commitment_id,
            linked_warrant_id, evidence_refs_json, status, opened_by,
            opened_at, updated_at, reviewed_by, reviewed_at, review_note,
            resolution, note, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(case_id) DO UPDATE SET
            institution_id=excluded.institution_id,
            source_institution_id=excluded.source_institution_id,
            target_host_id=excluded.target_host_id,
            target_institution_id=excluded.target_institution_id,
            claim_type=excluded.claim_type,
            linked_commitment_id=excluded.linked_commitment_id,
            linked_warrant_id=excluded.linked_warrant_id,
            evidence_refs_json=excluded.evidence_refs_json,
            status=excluded.status,
            opened_by=excluded.opened_by,
            opened_at=excluded.opened_at,
            updated_at=excluded.updated_at,
            reviewed_by=excluded.reviewed_by,
            reviewed_at=excluded.reviewed_at,
            review_note=excluded.review_note,
            resolution=excluded.resolution,
            note=excluded.note,
            metadata_json=excluded.metadata_json
        """,
        _record_to_row(record, org_id),
    )


def _write_json_atomic(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    tmp_path = f'{path}.tmp'
    with open(tmp_path, 'w') as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def load_case_store(cases_path: str, org_id: str | None = None) -> dict[str, Any]:
    db_path = db_path_for_cases_file(cases_path)
    if os.path.exists(db_path):
        try:
            with _connect(db_path) as conn:
                _ensure_schema(conn)
                if org_id:
                    rows = conn.execute(
                        'SELECT * FROM cases WHERE institution_id = ? ORDER BY opened_at DESC',
                        (org_id,),
                    ).fetchall()
                else:
                    rows = conn.execute('SELECT * FROM cases ORDER BY opened_at DESC').fetchall()
            return {
                'cases': {row['case_id']: _row_to_record(row) for row in rows},
                'updatedAt': max((row['updated_at'] for row in rows), default=''),
                'states': ['open', 'stayed', 'resolved'],
                'claim_types': [
                    'non_delivery',
                    'fraudulent_proof',
                    'breach_of_commitment',
                    'invalid_settlement_notice',
                    'misrouted_execution',
                ],
            }
        except sqlite3.Error:
            pass

    if os.path.exists(cases_path):
        try:
            with open(cases_path) as f:
                payload = json.load(f)
            payload = _normalize_store(payload)
            save_case_store(cases_path, payload, org_id=org_id)
            return payload
        except (OSError, json.JSONDecodeError, sqlite3.Error):
            pass

    return _default_store()


def _normalize_store(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    normalized = dict(_default_store())
    normalized.update(payload)
    normalized.setdefault('cases', {})
    if not isinstance(normalized['cases'], dict):
        normalized['cases'] = dict(normalized['cases'])
    normalized.setdefault('states', ['open', 'stayed', 'resolved'])
    normalized.setdefault('claim_types', [
        'non_delivery',
        'fraudulent_proof',
        'breach_of_commitment',
        'invalid_settlement_notice',
        'misrouted_execution',
    ])
    return normalized


def save_case_store(cases_path: str, payload: dict[str, Any], *, org_id: str | None = None) -> dict[str, Any]:
    normalized = _normalize_store(payload)
    normalized['updatedAt'] = normalized.get('updatedAt') or normalized.get('updated_at') or ''
    _write_json_atomic(cases_path, normalized)
    db_path = db_path_for_cases_file(cases_path)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        if org_id:
            conn.execute('DELETE FROM cases WHERE institution_id = ?', (org_id,))
        else:
            conn.execute('DELETE FROM cases')
        for record in normalized['cases'].values():
            _upsert_record(conn, record, org_id)
        conn.commit()
    return normalized


def db_status_for_cases_file(cases_path: str, org_id: str | None = None) -> dict[str, Any]:
    db_path = db_path_for_cases_file(cases_path)
    snapshot = {
        'path': db_path,
        'status': 'absent',
        'reason': 'sqlite case mirror has not been initialized yet',
    }
    if not os.path.exists(db_path):
        return snapshot
    try:
        with _connect(db_path) as conn:
            _ensure_schema(conn)
            if org_id:
                case_count = conn.execute('SELECT COUNT(*) FROM cases WHERE institution_id = ?', (org_id,)).fetchone()[0]
                row = conn.execute('SELECT MAX(updated_at) AS updated_at FROM cases WHERE institution_id = ?', (org_id,)).fetchone()
            else:
                case_count = conn.execute('SELECT COUNT(*) FROM cases').fetchone()[0]
                row = conn.execute('SELECT MAX(updated_at) AS updated_at FROM cases').fetchone()
        snapshot.update({
            'status': 'present',
            'reason': '',
            'size_bytes': os.path.getsize(db_path),
            'case_count': int(case_count or 0),
            'updated_at': row['updated_at'] if row and row['updated_at'] else '',
        })
    except sqlite3.Error as exc:
        snapshot.update({
            'status': 'degraded',
            'reason': str(exc),
        })
    return snapshot
