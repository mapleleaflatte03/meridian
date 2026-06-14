#!/usr/bin/env python3
"""File-backed persistence and observability snapshots for the live workspace."""

from __future__ import annotations

import concurrent.futures
import copy
import datetime
import json
import os
import threading
import time

import audit
from audit import stats as audit_stats
from audit import tail_events as audit_tail_events
from capsule import capsule_path
import metering
from metering import get_usage as metering_usage
from metering import summary as metering_summary
import organizations
import organizations_store
import observability_store
import accounting_store
import cases_store
import slo_policy
import alerting


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(os.path.dirname(PLATFORM_DIR))
OBSERVABILITY_SNAPSHOT_CACHE_TTL_SECONDS = float(
    os.environ.get('MERIDIAN_OBSERVABILITY_SNAPSHOT_CACHE_TTL_SECONDS', '5')
)
OBSERVABILITY_SNAPSHOT_CACHE = {}
OBSERVABILITY_SNAPSHOT_CACHE_LOCK = threading.Lock()
OBSERVABILITY_SNAPSHOT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=2,
    thread_name_prefix='meridian_observability_snapshot',
)


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def _iso_utc(dt_value):
    if not isinstance(dt_value, datetime.datetime):
        return ''
    return dt_value.strftime('%Y-%m-%dT%H:%M:%SZ')


def _age_seconds(dt_value):
    if not isinstance(dt_value, datetime.datetime):
        return None
    delta = _utc_now() - dt_value
    return max(int(delta.total_seconds()), 0)


def _parse_iso_timestamp(timestamp):
    if not timestamp:
        return None
    value = str(timestamp).strip()
    if not value:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(datetime.timezone.utc)
    else:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _is_stale_timestamp(timestamp, threshold_seconds):
    parsed = _parse_iso_timestamp(timestamp)
    if parsed is None:
        return True
    return _age_seconds(parsed) is None or _age_seconds(parsed) >= int(threshold_seconds or 0)


def _ensure_observability_heartbeats(org_id, audit_latest_at, metering_latest_at, *, threshold_seconds=3600):
    """Emit low-cost heartbeats when observability feeds are stale."""
    wrote = False
    if _is_stale_timestamp(audit_latest_at, threshold_seconds):
        try:
            audit.log_event(
                org_id=org_id,
                agent_id='system_observability',
                action='poge_status_heartbeat',
                resource='status_surface',
                outcome='success',
                actor_type='system',
                details={'source': 'status_surface'},
            )
            wrote = True
        except Exception:
            pass
    if _is_stale_timestamp(metering_latest_at, threshold_seconds):
        try:
            metering.record(
                org_id=org_id,
                agent_id='system_observability',
                metric='observability_status_heartbeat',
                quantity=1,
                unit='heartbeat',
                cost_usd=0.0,
                run_id='status_surface',
                details={'source': 'status_surface'},
            )
            wrote = True
        except Exception:
            pass
    return wrote


def _safe_relpath(path):
    if not path:
        return ''
    try:
        return os.path.relpath(path, WORKSPACE)
    except ValueError:
        return path


def _safe_capsule_path(org_id, filename):
    try:
        return capsule_path(org_id, filename)
    except Exception:
        return ''


def _file_snapshot(path, *, kind, owner, append_only=False, role='canonical'):
    snapshot = {
        'path': _safe_relpath(path),
        'kind': kind,
        'owner': owner,
        'role': role,
        'append_only': append_only,
    }
    if not path:
        snapshot.update({
            'status': 'unresolved',
            'exists': False,
            'size_bytes': 0,
            'modified_at': '',
            'age_seconds': None,
        })
        return snapshot
    if not os.path.exists(path):
        snapshot.update({
            'status': 'missing',
            'exists': False,
            'size_bytes': 0,
            'modified_at': '',
            'age_seconds': None,
        })
        return snapshot
    stat = os.stat(path)
    modified_at = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc)
    snapshot.update({
        'status': 'present',
        'exists': True,
        'size_bytes': stat.st_size,
        'modified_at': _iso_utc(modified_at),
        'age_seconds': _age_seconds(modified_at),
    })
    return snapshot


def persistence_snapshot(org_id=None):
    """Return the concrete file-backed persistence seams for the workspace."""
    orgs_db = organizations_store.db_path_for_file(organizations.ORGS_FILE)
    orgs_db_snapshot = _file_snapshot(
        orgs_db,
        kind='sqlite',
        owner='organizations.py',
        role='state_mirror',
    )
    observability_db = observability_store.db_path_for_log(audit.AUDIT_FILE)
    observability_db_snapshot = _file_snapshot(
        observability_db,
        kind='sqlite',
        owner='observability_store.py',
        role='observability_mirror',
    )
    accounting_db = accounting_store.db_path_for_owner_ledger(
        _safe_capsule_path(org_id, 'owner_ledger.json') or os.path.join(PLATFORM_DIR, 'owner_ledger.json')
    )
    accounting_db_snapshot = _file_snapshot(
        accounting_db,
        kind='sqlite',
        owner='accounting_store.py',
        role='state_mirror',
    )
    cases_db = cases_store.db_path_for_cases_file(
        _safe_capsule_path(org_id, 'cases.json') or os.path.join(PLATFORM_DIR, 'cases.json')
    )
    cases_db_snapshot = _file_snapshot(
        cases_db,
        kind='sqlite',
        owner='cases_store.py',
        role='state_mirror',
    )
    seams = [
        _file_snapshot(
            os.path.join(PLATFORM_DIR, 'organizations.json'),
            kind='json',
            owner='organizations.py',
        ),
        _file_snapshot(
            os.path.join(PLATFORM_DIR, 'agent_registry.json'),
            kind='json',
            owner='agent_registry.py',
        ),
        _file_snapshot(
            os.path.join(PLATFORM_DIR, 'authority_queue.json'),
            kind='json',
            owner='authority.py',
            role='compatibility_input',
        ),
        _file_snapshot(
            os.path.join(PLATFORM_DIR, 'court_records.json'),
            kind='json',
            owner='court.py',
            role='compatibility_input',
        ),
        _file_snapshot(
            os.path.join(PLATFORM_DIR, 'audit_log.jsonl'),
            kind='jsonl',
            owner='audit.py',
            append_only=True,
        ),
        _file_snapshot(
            os.path.join(PLATFORM_DIR, 'metering.jsonl'),
            kind='jsonl',
            owner='metering.py',
            append_only=True,
        ),
        _file_snapshot(
            alerting.ALERT_LOG_FILE,
            kind='jsonl',
            owner='alerting.py',
            append_only=True,
        ),
        _file_snapshot(
            _safe_capsule_path(org_id, 'ledger.json'),
            kind='json',
            owner='treasury.py',
        ),
        _file_snapshot(
            _safe_capsule_path(org_id, 'revenue.json'),
            kind='json',
            owner='treasury.py',
        ),
        _file_snapshot(
            _safe_capsule_path(org_id, 'transactions.jsonl'),
            kind='jsonl',
            owner='treasury.py',
            append_only=True,
        ),
        _file_snapshot(
            _safe_capsule_path(org_id, 'subscriptions.json'),
            kind='json',
            owner='subscription_service.py',
        ),
        _file_snapshot(
            _safe_capsule_path(org_id, 'subscription_preview_queue.json'),
            kind='json',
            owner='subscription_preview_queue.py',
        ),
        _file_snapshot(
            _safe_capsule_path(org_id, 'owner_ledger.json'),
            kind='json',
            owner='accounting_service.py',
        ),
        accounting_db_snapshot,
        _file_snapshot(
            _safe_capsule_path(org_id, 'cases.json'),
            kind='json',
            owner='cases.py',
        ),
        cases_db_snapshot,
        _file_snapshot(
            _safe_capsule_path(org_id, 'commitments.json'),
            kind='json',
            owner='commitments.py',
        ),
        _file_snapshot(
            _safe_capsule_path(org_id, 'federation_inbox.json'),
            kind='json',
            owner='federation_inbox.py',
        ),
        _file_snapshot(
            _safe_capsule_path(org_id, 'pilot_intake.json'),
            kind='json',
            owner='pilot_intake.py',
        ),
        orgs_db_snapshot,
        observability_db_snapshot,
    ]
    orgs_db_status = organizations_store.db_status_for_file(organizations.ORGS_FILE)
    observability_db_status = observability_store.db_status_for_log(audit.AUDIT_FILE)
    db_status = {
        'status': 'present' if orgs_db_status.get('status') == 'present' or observability_db_status.get('status') == 'present' or accounting_db_snapshot.get('status') == 'present' or cases_db_snapshot.get('status') == 'present' else 'absent',
        'reason': '',
        'organizations': orgs_db_status,
        'observability': observability_db_status,
        'accounting': accounting_db_snapshot,
        'cases': cases_db_snapshot,
    }
    if db_status['status'] != 'present':
        db_status['reason'] = 'sqlite mirrors are not initialized yet'
    backend_parts = []
    if orgs_db_status.get('status') == 'present':
        backend_parts.append('sqlite-organizations')
    if observability_db_status.get('status') == 'present':
        backend_parts.append('sqlite-observability')
    if accounting_db_snapshot.get('status') == 'present':
        backend_parts.append('sqlite-accounting')
    if cases_db_snapshot.get('status') == 'present':
        backend_parts.append('sqlite-cases')
    backend = '+'.join(backend_parts + ['jsonl']) if backend_parts else 'file-backed-jsonl'
    return {
        'backend': backend,
        'db': db_status,
        'seams': seams,
    }


def _governance_metrics(org_id):
    """Extract governance SLO metrics from audit trail and court."""
    proof_settle_latest_at = ''
    active_sanctions = 0
    try:
        events = audit_tail_events(50, org_id=org_id)
        for event in reversed(events):
            action = str(event.get('action', '')).lower()
            if 'settle' in action or 'poge' in action:
                proof_settle_latest_at = event.get('timestamp', '')
                break
    except Exception:
        pass
    try:
        import court as court_module
        restrictions = court_module.get_restrictions(org_id)
        if isinstance(restrictions, list):
            active_sanctions = sum(
                1 for item in restrictions
                if str(item.get('status', '')).lower() in ('active', 'pending_review')
            )
        elif isinstance(restrictions, dict):
            active_sanctions = int(restrictions.get('active_count', 0) or 0)
    except Exception:
        pass
    return {
        'proof_settle_latest_at': proof_settle_latest_at,
        'active_sanctions': active_sanctions,
    }


def _build_observability_snapshot(org_id, *, record_alerts=True):
    audit_summary = audit_stats(org_id)
    audit_events = audit_tail_events(1, org_id=org_id)
    audit_latest = audit_events[-1] if audit_events else {}

    metering_month = metering_summary(org_id, period='month')
    metering_events = metering_usage(org_id)
    metering_latest = metering_events[-1] if metering_events else {}

    if _ensure_observability_heartbeats(
        org_id,
        audit_latest.get('timestamp', ''),
        metering_latest.get('timestamp', ''),
    ):
        audit_summary = audit_stats(org_id)
        audit_events = audit_tail_events(1, org_id=org_id)
        audit_latest = audit_events[-1] if audit_events else {}
        metering_month = metering_summary(org_id, period='month')
        metering_events = metering_usage(org_id)
        metering_latest = metering_events[-1] if metering_events else {}
    persistence = persistence_snapshot(org_id)
    governance = _governance_metrics(org_id)
    metrics = {
        'audit': {
            **audit_summary,
            'latest_at': audit_latest.get('timestamp', ''),
            'latest_action': audit_latest.get('action', ''),
            'latest_outcome': audit_latest.get('outcome', ''),
        },
        'metering': {
            **metering_month,
            'latest_at': metering_latest.get('timestamp', ''),
            'latest_metric': metering_latest.get('metric', ''),
            'latest_cost_usd': round(float(metering_latest.get('cost_usd', 0.0) or 0.0), 4),
        },
        'governance': governance,
    }
    slo = slo_policy.evaluate_observability(metrics)
    alert_run = {
        'policy_name': slo.get('policy_name', ''),
        'evaluated_at': slo.get('evaluated_at', ''),
        'changed_objectives': [],
        'event_count': 0,
        'delivery_count': 0,
        'objectives': [],
    }
    alert_log = {
        'route': '/api/alerts',
        'queue_route': '/api/alerts/dispatch',
        'policy_name': slo.get('policy_name', ''),
        'active_count': 0,
        'events': [],
    }
    alert_queue = {
        'route': '/api/alerts',
        'dispatch_route': '/api/alerts/dispatch',
        'policy_name': slo.get('policy_name', ''),
        'active_count': 0,
        'alerts': [],
    }
    try:
        if record_alerts:
            alert_run = alerting.record_slo_alerts(slo, org_id=org_id)
        else:
            alert_run = {
                **alert_run,
                'recording_mode': 'read_only',
                'state': 'not_recorded_on_status_read',
            }
        alert_log = alerting.alert_surface_snapshot(org_id)
        alert_queue = alerting.alert_queue_snapshot(org_id)
    except Exception as exc:
        message = f'observability alerting degraded: {exc}'
        slo.setdefault('issues', []).append(message)
        alert_run['error'] = message
        alert_log['error'] = message
        alert_queue['error'] = message

    if not record_alerts:
        slo = {
            **slo,
            'alert_recording_mode': 'read_only',
        }

    return {
        'backend': persistence.get('backend', 'file-backed-jsonl'),
        'db': persistence.get('db', {}),
        'export': {
            'route': '/metrics',
            'content_type': 'text/plain; charset=utf-8',
        },
        'metrics': metrics,
        'slo': slo,
        'alerting': alert_run,
        'alert_log': alert_log,
        'alert_queue': alert_queue,
    }


def observability_snapshot(org_id, *, record_alerts=True):
    """Return the file-backed metrics inputs and an explicit SLO status."""
    now = time.time()
    cache_key = f"{str(org_id or '')}:alerts:{'on' if record_alerts else 'off'}"
    ttl_seconds = max(1.0, OBSERVABILITY_SNAPSHOT_CACHE_TTL_SECONDS)
    with OBSERVABILITY_SNAPSHOT_CACHE_LOCK:
        cached_entry = OBSERVABILITY_SNAPSHOT_CACHE.get(cache_key)
        if not isinstance(cached_entry, dict):
            cached_entry = {'fetched_at': 0.0, 'payload': None, 'refresh_future': None}
            OBSERVABILITY_SNAPSHOT_CACHE[cache_key] = cached_entry
        fetched_at = float(cached_entry.get('fetched_at') or 0.0)
        payload = cached_entry.get('payload')
        refresh_future = cached_entry.get('refresh_future')
        if (
            isinstance(payload, dict)
            and fetched_at > 0
            and (now - fetched_at) <= ttl_seconds
        ):
            return json.loads(json.dumps(payload))
        if not isinstance(payload, dict):
            pass  # cold start — fall through to synchronous build below
        elif refresh_future and not refresh_future.done():
            return json.loads(json.dumps(payload))
        else:
            if not (refresh_future and not refresh_future.done()):
                refresh_future = OBSERVABILITY_SNAPSHOT_EXECUTOR.submit(
                    _build_observability_snapshot,
                    org_id,
                    record_alerts=record_alerts,
                )
                cached_entry['refresh_future'] = refresh_future
            return json.loads(json.dumps(payload))

    if not isinstance(payload, dict):
        snapshot = _build_observability_snapshot(org_id, record_alerts=record_alerts)
        with OBSERVABILITY_SNAPSHOT_CACHE_LOCK:
            cached_entry = OBSERVABILITY_SNAPSHOT_CACHE.get(cache_key)
            if not isinstance(cached_entry, dict):
                cached_entry = {'fetched_at': 0.0, 'payload': None, 'refresh_future': None}
                OBSERVABILITY_SNAPSHOT_CACHE[cache_key] = cached_entry
            cached_entry['fetched_at'] = time.time()
            cached_entry['payload'] = json.loads(json.dumps(snapshot))
            cached_entry['refresh_future'] = None
        return snapshot
    try:
        snapshot = refresh_future.result(timeout=0.2)
    except concurrent.futures.TimeoutError:
        return {
            'backend': 'file-backed-jsonl',
            'db': {},
            'export': {
                'route': '/metrics',
                'content_type': 'text/plain; charset=utf-8',
            },
            'metrics': {},
            'slo': {
                'policy_name': 'meridian_observability_slo_v1',
                'status': 'degraded',
                'issues': ['observability snapshot refresh in progress'],
                'alert_recording_mode': 'read_only' if not record_alerts else 'active',
            },
            'alerting': {
                'policy_name': 'meridian_observability_slo_v1',
                'event_count': 0,
                'delivery_count': 0,
                'changed_objectives': [],
                'state': 'refresh_in_progress',
                'recording_mode': 'read_only' if not record_alerts else 'active',
            },
            'alert_log': {
                'route': '/api/alerts',
                'queue_route': '/api/alerts/dispatch',
                'policy_name': 'meridian_observability_slo_v1',
                'active_count': 0,
                'events': [],
                'state': 'refresh_in_progress',
            },
            'alert_queue': {
                'route': '/api/alerts',
                'dispatch_route': '/api/alerts/dispatch',
                'policy_name': 'meridian_observability_slo_v1',
                'active_count': 0,
                'alerts': [],
                'queue_count': 0,
                'pending_delivery_count': 0,
                'delivered_count': 0,
                'state': 'refresh_in_progress',
            },
        }
    except Exception as exc:
        with OBSERVABILITY_SNAPSHOT_CACHE_LOCK:
            cached_entry = OBSERVABILITY_SNAPSHOT_CACHE.get(cache_key)
            if isinstance(cached_entry, dict):
                cached_entry['refresh_future'] = None
        return {
            'backend': 'file-backed-jsonl',
            'db': {},
            'export': {
                'route': '/metrics',
                'content_type': 'text/plain; charset=utf-8',
            },
            'metrics': {},
            'slo': {
                'policy_name': 'meridian_observability_slo_v1',
                'status': 'degraded',
                'issues': [f'observability snapshot refresh failed: {exc}'],
                'alert_recording_mode': 'read_only' if not record_alerts else 'active',
            },
            'alerting': {
                'policy_name': 'meridian_observability_slo_v1',
                'event_count': 0,
                'delivery_count': 0,
                'changed_objectives': [],
                'state': 'refresh_failed',
                'error': str(exc),
                'recording_mode': 'read_only' if not record_alerts else 'active',
            },
            'alert_log': {
                'route': '/api/alerts',
                'queue_route': '/api/alerts/dispatch',
                'policy_name': 'meridian_observability_slo_v1',
                'active_count': 0,
                'events': [],
                'state': 'refresh_failed',
            },
            'alert_queue': {
                'route': '/api/alerts',
                'dispatch_route': '/api/alerts/dispatch',
                'policy_name': 'meridian_observability_slo_v1',
                'active_count': 0,
                'alerts': [],
                'queue_count': 0,
                'pending_delivery_count': 0,
                'delivered_count': 0,
                'state': 'refresh_failed',
            },
        }

    with OBSERVABILITY_SNAPSHOT_CACHE_LOCK:
        cached_entry = OBSERVABILITY_SNAPSHOT_CACHE.get(cache_key)
        if not isinstance(cached_entry, dict):
            cached_entry = {'fetched_at': 0.0, 'payload': None, 'refresh_future': None}
            OBSERVABILITY_SNAPSHOT_CACHE[cache_key] = cached_entry
        cached_entry['fetched_at'] = time.time()
        cached_entry['payload'] = json.loads(json.dumps(snapshot))
        cached_entry['refresh_future'] = None
    return snapshot


def observability_metrics_text(org_id):
    snapshot = observability_snapshot(org_id)
    base_text = observability_store.prometheus_text(
        audit_log_path=audit.AUDIT_FILE,
        metering_log_path=metering.METERING_FILE,
        org_id=org_id,
    )
    slo_lines = slo_policy.prometheus_lines(snapshot.get('slo', {}), org_id=org_id)
    return base_text + '\n'.join(slo_lines) + '\n'
