#!/usr/bin/env python3
"""SQLite-backed mirror for Meridian organization state."""

from __future__ import annotations

import json
import os
import sqlite3
import datetime
from typing import Any


def db_path_for_file(orgs_file: str) -> str:
    directory = os.path.dirname(os.path.abspath(orgs_file))
    return os.path.join(directory, 'organizations.db')


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            plan TEXT NOT NULL,
            status TEXT NOT NULL,
            charter TEXT NOT NULL,
            policy_defaults_json TEXT NOT NULL,
            treasury_id TEXT,
            lifecycle_state TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            members_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _row_to_org(row: sqlite3.Row) -> dict[str, Any]:
    return {
        'id': row['id'],
        'name': row['name'],
        'slug': row['slug'],
        'owner_id': row['owner_id'],
        'members': json.loads(row['members_json'] or '[]'),
        'plan': row['plan'],
        'status': row['status'],
        'charter': row['charter'],
        'policy_defaults': json.loads(row['policy_defaults_json'] or '{}'),
        'treasury_id': row['treasury_id'],
        'lifecycle_state': row['lifecycle_state'],
        'settings': json.loads(row['settings_json'] or '{}'),
        'created_at': row['created_at'],
        'updated_at': row['updated_at'],
    }


def _upsert_org(conn: sqlite3.Connection, org: dict[str, Any], updated_at: str) -> None:
    conn.execute(
        """
        INSERT INTO organizations (
            id, name, slug, owner_id, plan, status, charter,
            policy_defaults_json, treasury_id, lifecycle_state,
            settings_json, members_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            slug=excluded.slug,
            owner_id=excluded.owner_id,
            plan=excluded.plan,
            status=excluded.status,
            charter=excluded.charter,
            policy_defaults_json=excluded.policy_defaults_json,
            treasury_id=excluded.treasury_id,
            lifecycle_state=excluded.lifecycle_state,
            settings_json=excluded.settings_json,
            members_json=excluded.members_json,
            created_at=excluded.created_at,
            updated_at=excluded.updated_at
        """,
        (
            org.get('id', ''),
            org.get('name', ''),
            org.get('slug', ''),
            org.get('owner_id', ''),
            org.get('plan', 'free'),
            org.get('status', 'active'),
            org.get('charter', ''),
            json.dumps(org.get('policy_defaults') or {}, sort_keys=True),
            org.get('treasury_id'),
            org.get('lifecycle_state', 'active'),
            json.dumps(org.get('settings') or {}, sort_keys=True),
            json.dumps(org.get('members') or [], sort_keys=True),
            org.get('created_at', updated_at),
            updated_at,
        ),
    )


def _load_json(path: str) -> dict[str, Any] | None:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        payload = json.load(f)
    if isinstance(payload, dict):
        payload.setdefault('organizations', {})
        payload.setdefault('updatedAt', '')
        return payload
    return None


def save_orgs(orgs_file: str, data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data or {})
    payload.setdefault('organizations', {})
    updated_at = payload.get('updatedAt') or ''
    db_path = db_path_for_file(orgs_file)
    directory = os.path.dirname(orgs_file)
    if directory:
        os.makedirs(directory, exist_ok=True)
    payload['updatedAt'] = updated_at or datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    with open(orgs_file, 'w') as f:
        json.dump(payload, f, indent=2)
    with _connect(db_path) as conn:
        _ensure_schema(conn)
        existing_ids = {
            row['id']
            for row in conn.execute('SELECT id FROM organizations').fetchall()
        }
        current_ids = set(payload['organizations'].keys())
        for org_id in existing_ids - current_ids:
            conn.execute('DELETE FROM organizations WHERE id = ?', (org_id,))
        for org_id, org in payload['organizations'].items():
            _upsert_org(conn, org, payload['updatedAt'])
        conn.commit()
    return payload


def load_orgs(orgs_file: str) -> dict[str, Any]:
    db_path = db_path_for_file(orgs_file)
    if os.path.exists(db_path):
        try:
            with _connect(db_path) as conn:
                _ensure_schema(conn)
                rows = conn.execute('SELECT * FROM organizations').fetchall()
                updated_at_row = conn.execute('SELECT MAX(updated_at) AS updated_at FROM organizations').fetchone()
            return {
                'organizations': {row['id']: _row_to_org(row) for row in rows},
                'updatedAt': (updated_at_row['updated_at'] if updated_at_row and updated_at_row['updated_at'] else ''),
            }
        except sqlite3.Error:
            pass
    payload = _load_json(orgs_file)
    if payload is None:
        return {'organizations': {}, 'updatedAt': ''}
    try:
        save_orgs(orgs_file, payload)
    except Exception:
        pass
    return payload


def db_status_for_file(orgs_file: str) -> dict[str, Any]:
    db_path = db_path_for_file(orgs_file)
    snapshot = {
        'path': db_path,
        'status': 'absent',
        'reason': 'sqlite organization mirror has not been initialized yet',
    }
    if not os.path.exists(db_path):
        return snapshot
    try:
        with _connect(db_path) as conn:
            _ensure_schema(conn)
            count = conn.execute('SELECT COUNT(*) FROM organizations').fetchone()[0]
        snapshot.update({
            'status': 'present',
            'reason': '',
            'size_bytes': os.path.getsize(db_path),
            'organization_count': int(count or 0),
        })
    except sqlite3.Error as exc:
        snapshot.update({
            'status': 'degraded',
            'reason': str(exc),
        })
    return snapshot
