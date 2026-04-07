#!/usr/bin/env python3
"""SQLite-backed storage helpers for Meridian observability streams."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any


def db_path_for_log(log_path: str) -> str:
    directory = os.path.dirname(os.path.abspath(log_path))
    return os.path.join(directory, 'observability.db')


def _connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    timeout = float(os.environ.get('MERIDIAN_OBSERVABILITY_SQLITE_TIMEOUT_SEC', '0.25') or '0.25')
    conn = sqlite3.connect(db_path, timeout=max(0.05, timeout))
    conn.row_factory = sqlite3.Row
    conn.execute(f'PRAGMA busy_timeout={int(max(50.0, timeout * 1000.0))}')
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except sqlite3.OperationalError:
        # Continue in default journal mode when WAL negotiation is temporarily unavailable.
        pass
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            org_id TEXT,
            agent_id TEXT,
            actor_type TEXT,
            action TEXT NOT NULL,
            resource TEXT,
            outcome TEXT,
            details_json TEXT,
            policy_ref TEXT,
            session_id TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metering_events (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            org_id TEXT NOT NULL,
            agent_id TEXT,
            metric TEXT NOT NULL,
            quantity REAL NOT NULL,
            unit TEXT,
            cost_usd REAL NOT NULL,
            run_id TEXT,
            details_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS slo_alert_events (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            org_id TEXT NOT NULL,
            policy_name TEXT NOT NULL,
            objective TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT NOT NULL,
            evaluated_at TEXT,
            active INTEGER NOT NULL,
            state_change TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            details_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS slo_alert_deliveries (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            org_id TEXT NOT NULL,
            alert_event_id TEXT NOT NULL,
            hook_name TEXT,
            status TEXT NOT NULL,
            delivered INTEGER NOT NULL,
            details_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS slo_alert_dispatches (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            org_id TEXT NOT NULL,
            alert_event_id TEXT NOT NULL,
            hook_name TEXT,
            status TEXT NOT NULL,
            acknowledged INTEGER NOT NULL,
            details_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS slo_alert_state (
            org_id TEXT NOT NULL,
            policy_name TEXT NOT NULL,
            objective TEXT NOT NULL,
            current_status TEXT NOT NULL,
            current_fingerprint TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            last_evaluated_at TEXT NOT NULL,
            current_event_id TEXT NOT NULL,
            current_message TEXT NOT NULL,
            PRIMARY KEY (org_id, policy_name, objective)
        )
        """
    )
    conn.execute('CREATE INDEX IF NOT EXISTS idx_audit_org_time ON audit_events(org_id, timestamp DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_meter_org_time ON metering_events(org_id, timestamp DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_alert_org_time ON slo_alert_events(org_id, timestamp DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_alert_policy_time ON slo_alert_events(policy_name, timestamp DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_alert_delivery_org_time ON slo_alert_deliveries(org_id, timestamp DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_alert_dispatch_org_time ON slo_alert_dispatches(org_id, timestamp DESC)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_alert_state_org_policy ON slo_alert_state(org_id, policy_name, objective)')


def _write_audit_row(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO audit_events (
            id, timestamp, org_id, agent_id, actor_type, action, resource,
            outcome, details_json, policy_ref, session_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.get('id', ''),
            event.get('timestamp', ''),
            event.get('org_id', ''),
            event.get('agent_id', ''),
            event.get('actor_type', ''),
            event.get('action', ''),
            event.get('resource', ''),
            event.get('outcome', ''),
            json.dumps(event.get('details') or {}, sort_keys=True),
            event.get('policy_ref', ''),
            event.get('session_id', ''),
        ),
    )


def _write_meter_row(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO metering_events (
            id, timestamp, org_id, agent_id, metric, quantity, unit,
            cost_usd, run_id, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.get('id', ''),
            event.get('timestamp', ''),
            event.get('org_id', ''),
            event.get('agent_id', ''),
            event.get('metric', ''),
            float(event.get('quantity', 0.0) or 0.0),
            event.get('unit', ''),
            float(event.get('cost_usd', 0.0) or 0.0),
            event.get('run_id', ''),
            json.dumps(event.get('details') or {}, sort_keys=True),
        ),
    )


def _write_alert_event_row(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO slo_alert_events (
            id, timestamp, org_id, policy_name, objective, status, message,
            evaluated_at, active, state_change, fingerprint, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.get('id', ''),
            event.get('timestamp', ''),
            event.get('org_id', ''),
            event.get('policy_name', ''),
            event.get('objective', ''),
            event.get('status', ''),
            event.get('message', ''),
            event.get('evaluated_at', ''),
            1 if event.get('active') else 0,
            event.get('state_change', ''),
            event.get('fingerprint', ''),
            json.dumps(event.get('details') or {}, sort_keys=True),
        ),
    )


def _write_alert_delivery_row(conn: sqlite3.Connection, delivery: dict[str, Any]) -> None:
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO slo_alert_deliveries (
            id, timestamp, org_id, alert_event_id, hook_name, status,
            delivered, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            delivery.get('id', ''),
            delivery.get('timestamp', ''),
            delivery.get('org_id', ''),
            delivery.get('alert_event_id', ''),
            delivery.get('hook_name', ''),
            delivery.get('status', ''),
            1 if delivery.get('delivered') else 0,
            json.dumps(delivery.get('details') or {}, sort_keys=True),
        ),
    )


def _write_alert_dispatch_row(conn: sqlite3.Connection, dispatch: dict[str, Any]) -> None:
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO slo_alert_dispatches (
            id, timestamp, org_id, alert_event_id, hook_name, status,
            acknowledged, details_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            dispatch.get('id', ''),
            dispatch.get('timestamp', ''),
            dispatch.get('org_id', ''),
            dispatch.get('alert_event_id', ''),
            dispatch.get('hook_name', ''),
            dispatch.get('status', ''),
            1 if dispatch.get('acknowledged') else 0,
            json.dumps(dispatch.get('details') or {}, sort_keys=True),
        ),
    )


def _write_alert_state_row(conn: sqlite3.Connection, state: dict[str, Any]) -> None:
    _ensure_schema(conn)
    conn.execute(
        """
        INSERT OR REPLACE INTO slo_alert_state (
            org_id, policy_name, objective, current_status, current_fingerprint,
            first_seen_at, last_seen_at, last_evaluated_at, current_event_id,
            current_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            state.get('org_id', ''),
            state.get('policy_name', ''),
            state.get('objective', ''),
            state.get('current_status', ''),
            state.get('current_fingerprint', ''),
            state.get('first_seen_at', ''),
            state.get('last_seen_at', ''),
            state.get('last_evaluated_at', ''),
            state.get('current_event_id', ''),
            state.get('current_message', ''),
        ),
    )


def _row_to_event(row: sqlite3.Row, *, details_key: str) -> dict[str, Any]:
    event = dict(row)
    details = event.pop(details_key, '{}')
    try:
        event['details'] = json.loads(details) if details else {}
    except json.JSONDecodeError:
        event['details'] = {}
    return event


def write_audit_event(log_path: str, event: dict[str, Any]) -> bool:
    db_path = db_path_for_log(log_path)
    try:
        with _connect(db_path) as conn:
            _write_audit_row(conn, event)
            conn.commit()
        return True
    except sqlite3.Error:
        return False


def write_metering_event(log_path: str, event: dict[str, Any]) -> bool:
    db_path = db_path_for_log(log_path)
    try:
        with _connect(db_path) as conn:
            _write_meter_row(conn, event)
            conn.commit()
        return True
    except sqlite3.Error:
        return False


def write_slo_alert_event(log_path: str, event: dict[str, Any]) -> bool:
    db_path = db_path_for_log(log_path)
    try:
        with _connect(db_path) as conn:
            _write_alert_event_row(conn, event)
            conn.commit()
        return True
    except sqlite3.Error:
        return False


def write_slo_alert_delivery(log_path: str, delivery: dict[str, Any]) -> bool:
    db_path = db_path_for_log(log_path)
    try:
        with _connect(db_path) as conn:
            _write_alert_delivery_row(conn, delivery)
            conn.commit()
        return True
    except sqlite3.Error:
        return False


def write_slo_alert_dispatch(log_path: str, dispatch: dict[str, Any]) -> bool:
    db_path = db_path_for_log(log_path)
    try:
        with _connect(db_path) as conn:
            _write_alert_dispatch_row(conn, dispatch)
            conn.commit()
        return True
    except sqlite3.Error:
        return False


def upsert_slo_alert_state(log_path: str, state: dict[str, Any]) -> bool:
    db_path = db_path_for_log(log_path)
    try:
        with _connect(db_path) as conn:
            _write_alert_state_row(conn, state)
            conn.commit()
        return True
    except sqlite3.Error:
        return False


def db_status_for_log(log_path: str) -> dict[str, Any]:
    db_path = db_path_for_log(log_path)
    snapshot = {
        'path': db_path,
        'status': 'absent',
        'reason': 'sqlite observability mirror has not been initialized yet',
    }
    if not os.path.exists(db_path):
        return snapshot
    try:
        with _connect(db_path) as conn:
            _ensure_schema(conn)
            audit_count = conn.execute('SELECT COUNT(*) FROM audit_events').fetchone()[0]
            meter_count = conn.execute('SELECT COUNT(*) FROM metering_events').fetchone()[0]
            alert_count = conn.execute('SELECT COUNT(*) FROM slo_alert_events').fetchone()[0]
            alert_delivery_count = conn.execute('SELECT COUNT(*) FROM slo_alert_deliveries').fetchone()[0]
            alert_dispatch_count = conn.execute('SELECT COUNT(*) FROM slo_alert_dispatches').fetchone()[0]
            alert_state_count = conn.execute('SELECT COUNT(*) FROM slo_alert_state').fetchone()[0]
        snapshot.update({
            'status': 'present',
            'reason': '',
            'size_bytes': os.path.getsize(db_path),
            'audit_events': int(audit_count or 0),
            'metering_events': int(meter_count or 0),
            'slo_alert_events': int(alert_count or 0),
            'slo_alert_deliveries': int(alert_delivery_count or 0),
            'slo_alert_dispatches': int(alert_dispatch_count or 0),
            'slo_alert_state_rows': int(alert_state_count or 0),
        })
    except sqlite3.Error as exc:
        snapshot.update({
            'status': 'degraded',
            'reason': str(exc),
        })
    return snapshot


def query_audit_events(
    log_path: str,
    *,
    org_id: str | None = None,
    agent_id: str | None = None,
    action: str | None = None,
    since: str | None = None,
    outcome: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db_path = db_path_for_log(log_path)
    if os.path.exists(db_path):
        try:
            clauses = []
            params: list[Any] = []
            if org_id:
                clauses.append('org_id = ?')
                params.append(org_id)
            if agent_id:
                clauses.append('agent_id = ?')
                params.append(agent_id)
            if action:
                clauses.append('action = ?')
                params.append(action)
            if outcome:
                clauses.append('outcome = ?')
                params.append(outcome)
            if since:
                clauses.append('timestamp >= ?')
                params.append(since)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
            query = (
                'SELECT id, timestamp, org_id, agent_id, actor_type, action, resource, '
                'outcome, details_json, policy_ref, session_id '
                f'FROM audit_events {where} '
                'ORDER BY timestamp DESC, rowid DESC LIMIT ?'
            )
            params.append(limit)
            with _connect(db_path) as conn:
                _ensure_schema(conn)
                rows = conn.execute(query, params).fetchall()
            return [_row_to_event(row, details_key='details_json') for row in rows]
        except sqlite3.Error:
            pass
    if not os.path.exists(log_path):
        return []
    results: list[dict[str, Any]] = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('record_type') and event.get('record_type') != 'event':
                continue
            if org_id and event.get('org_id') != org_id:
                continue
            if agent_id and event.get('agent_id') != agent_id:
                continue
            if action and event.get('action') != action:
                continue
            if outcome and event.get('outcome') != outcome:
                continue
            if since and event.get('timestamp', '') < since:
                continue
            results.append(event)
    results.reverse()
    return results[:limit]


def query_metering_events(
    log_path: str,
    *,
    org_id: str,
    agent_id: str | None = None,
    since: str | None = None,
    metric: str | None = None,
) -> list[dict[str, Any]]:
    db_path = db_path_for_log(log_path)
    if os.path.exists(db_path):
        try:
            clauses = ['org_id = ?']
            params: list[Any] = [org_id]
            if agent_id:
                clauses.append('agent_id = ?')
                params.append(agent_id)
            if metric:
                clauses.append('metric = ?')
                params.append(metric)
            if since:
                clauses.append('timestamp >= ?')
                params.append(since)
            query = (
                'SELECT id, timestamp, org_id, agent_id, metric, quantity, unit, '
                'cost_usd, run_id, details_json '
                f"FROM metering_events WHERE {' AND '.join(clauses)} "
                'ORDER BY timestamp ASC, rowid ASC'
            )
            with _connect(db_path) as conn:
                _ensure_schema(conn)
                rows = conn.execute(query, params).fetchall()
            return [_row_to_event(row, details_key='details_json') for row in rows]
        except sqlite3.Error:
            pass
    if not os.path.exists(log_path):
        return []
    results: list[dict[str, Any]] = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('org_id') != org_id:
                continue
            if agent_id and event.get('agent_id') != agent_id:
                continue
            if metric and event.get('metric') != metric:
                continue
            if since and event.get('timestamp', '') < since:
                continue
            results.append(event)
    return results


def query_slo_alert_events(
    log_path: str,
    *,
    org_id: str | None = None,
    policy_name: str | None = None,
    status: str | None = None,
    objective: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db_path = db_path_for_log(log_path)
    if os.path.exists(db_path):
        try:
            clauses = []
            params: list[Any] = []
            if org_id:
                clauses.append('org_id = ?')
                params.append(org_id)
            if policy_name:
                clauses.append('policy_name = ?')
                params.append(policy_name)
            if status:
                clauses.append('status = ?')
                params.append(status)
            if objective:
                clauses.append('objective = ?')
                params.append(objective)
            if since:
                clauses.append('timestamp >= ?')
                params.append(since)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
            query = (
                'SELECT id, timestamp, org_id, policy_name, objective, status, message, '
                'evaluated_at, active, state_change, fingerprint, details_json '
                f'FROM slo_alert_events {where} '
                'ORDER BY timestamp DESC, rowid DESC LIMIT ?'
            )
            params.append(limit)
            with _connect(db_path) as conn:
                _ensure_schema(conn)
                rows = conn.execute(query, params).fetchall()
            return [_row_to_event(row, details_key='details_json') for row in rows]
        except sqlite3.Error:
            pass
    if not os.path.exists(log_path):
        return []
    results: list[dict[str, Any]] = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('record_type') and event.get('record_type') != 'event':
                continue
            if org_id and event.get('org_id') != org_id:
                continue
            if policy_name and event.get('policy_name') != policy_name:
                continue
            if status and event.get('status') != status:
                continue
            if objective and event.get('objective') != objective:
                continue
            if since and event.get('timestamp', '') < since:
                continue
            results.append(event)
    results.reverse()
    return results[:limit]


def query_slo_alert_dispatches(
    log_path: str,
    *,
    org_id: str | None = None,
    alert_event_id: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db_path = db_path_for_log(log_path)
    if os.path.exists(db_path):
        try:
            clauses = []
            params: list[Any] = []
            if org_id:
                clauses.append('org_id = ?')
                params.append(org_id)
            if alert_event_id:
                clauses.append('alert_event_id = ?')
                params.append(alert_event_id)
            if status:
                clauses.append('status = ?')
                params.append(status)
            if since:
                clauses.append('timestamp >= ?')
                params.append(since)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
            query = (
                'SELECT id, timestamp, org_id, alert_event_id, hook_name, status, acknowledged, details_json '
                f'FROM slo_alert_dispatches {where} '
                'ORDER BY timestamp DESC, rowid DESC LIMIT ?'
            )
            params.append(limit)
            with _connect(db_path) as conn:
                _ensure_schema(conn)
                rows = conn.execute(query, params).fetchall()
            return [_row_to_event(row, details_key='details_json') for row in rows]
        except sqlite3.Error:
            pass
    if not os.path.exists(log_path):
        return []
    results: list[dict[str, Any]] = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('record_type') and event.get('record_type') != 'dispatch':
                continue
            if org_id and event.get('org_id') != org_id:
                continue
            if alert_event_id and event.get('alert_event_id') != alert_event_id:
                continue
            if status and event.get('status') != status:
                continue
            if since and event.get('timestamp', '') < since:
                continue
            results.append(event)
    results.reverse()
    return results[:limit]


def query_slo_alert_deliveries(
    log_path: str,
    *,
    org_id: str | None = None,
    alert_event_id: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db_path = db_path_for_log(log_path)
    if os.path.exists(db_path):
        try:
            clauses = []
            params: list[Any] = []
            if org_id:
                clauses.append('org_id = ?')
                params.append(org_id)
            if alert_event_id:
                clauses.append('alert_event_id = ?')
                params.append(alert_event_id)
            if status:
                clauses.append('status = ?')
                params.append(status)
            if since:
                clauses.append('timestamp >= ?')
                params.append(since)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
            query = (
                'SELECT id, timestamp, org_id, alert_event_id, hook_name, status, delivered, details_json '
                f'FROM slo_alert_deliveries {where} '
                'ORDER BY timestamp DESC, rowid DESC LIMIT ?'
            )
            params.append(limit)
            with _connect(db_path) as conn:
                _ensure_schema(conn)
                rows = conn.execute(query, params).fetchall()
            return [_row_to_event(row, details_key='details_json') for row in rows]
        except sqlite3.Error:
            pass
    if not os.path.exists(log_path):
        return []
    results: list[dict[str, Any]] = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get('record_type') and event.get('record_type') != 'delivery':
                continue
            if org_id and event.get('org_id') != org_id:
                continue
            if alert_event_id and event.get('alert_event_id') != alert_event_id:
                continue
            if status and event.get('status') != status:
                continue
            if since and event.get('timestamp', '') < since:
                continue
            results.append(event)
    results.reverse()
    return results[:limit]


def get_slo_alert_state(
    log_path: str,
    *,
    org_id: str,
    policy_name: str,
    objective: str,
) -> dict[str, Any] | None:
    db_path = db_path_for_log(log_path)
    if not os.path.exists(db_path):
        return None
    try:
        with _connect(db_path) as conn:
            _ensure_schema(conn)
            row = conn.execute(
                """
                SELECT org_id, policy_name, objective, current_status, current_fingerprint,
                       first_seen_at, last_seen_at, last_evaluated_at, current_event_id,
                       current_message
                FROM slo_alert_state
                WHERE org_id = ? AND policy_name = ? AND objective = ?
                """,
                (org_id, policy_name, objective),
            ).fetchone()
        if row is None:
            return None
        return dict(row)
    except sqlite3.Error:
        return None


def _timestamp_to_epoch_seconds(timestamp: str) -> int | None:
    if not timestamp:
        return None
    try:
        dt_value = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        return None
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return int(dt_value.timestamp())


def prometheus_text(*, audit_log_path: str, metering_log_path: str, org_id: str | None = None) -> str:
    audit_events = query_audit_events(audit_log_path, org_id=org_id, limit=10000)
    metering_events = query_metering_events(metering_log_path, org_id=org_id or '')
    labels = f'org_id="{org_id or ""}"'
    total_cost = sum(float(event.get('cost_usd', 0.0) or 0.0) for event in metering_events)
    lines = [
        '# HELP meridian_audit_events_total Total audit events recorded for the organization.',
        '# TYPE meridian_audit_events_total counter',
        f'meridian_audit_events_total{{{labels}}} {len(audit_events)}',
        '# HELP meridian_metering_events_total Total metering events recorded for the organization.',
        '# TYPE meridian_metering_events_total counter',
        f'meridian_metering_events_total{{{labels}}} {len(metering_events)}',
        '# HELP meridian_metering_cost_usd_total Total metering cost recorded for the organization.',
        '# TYPE meridian_metering_cost_usd_total counter',
        f'meridian_metering_cost_usd_total{{{labels}}} {total_cost:.4f}',
    ]
    if audit_events:
        audit_latest = _timestamp_to_epoch_seconds(audit_events[0].get('timestamp', ''))
        if audit_latest is not None:
            lines.extend([
                '# HELP meridian_audit_latest_timestamp_seconds Unix timestamp for the latest audit event.',
                '# TYPE meridian_audit_latest_timestamp_seconds gauge',
                f'meridian_audit_latest_timestamp_seconds{{{labels}}} {audit_latest}',
            ])
    if metering_events:
        metering_latest = _timestamp_to_epoch_seconds(metering_events[-1].get('timestamp', ''))
        if metering_latest is not None:
            lines.extend([
                '# HELP meridian_metering_latest_timestamp_seconds Unix timestamp for the latest metering event.',
                '# TYPE meridian_metering_latest_timestamp_seconds gauge',
                f'meridian_metering_latest_timestamp_seconds{{{labels}}} {metering_latest}',
            ])
    return '\n'.join(lines) + '\n'
