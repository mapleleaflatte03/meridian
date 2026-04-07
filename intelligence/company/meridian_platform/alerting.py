"""Durable SLO alert transitions, queue views, and truthful delivery hooks."""

from __future__ import annotations

import datetime
import json
import os
import uuid
from typing import Any, Callable

import observability_store


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
ALERT_LOG_FILE = os.path.join(PLATFORM_DIR, 'slo_alert_log.jsonl')
ACTIVE_STATUSES = {'warning', 'breached'}
HOOK_SUCCESS_STATUSES = {'delivered', 'success', 'sent', 'ok'}


AlertHook = Callable[[dict[str, Any]], Any]


def _now() -> str:
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _append_jsonl(path: str, record: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a') as f:
        f.write(json.dumps(record, sort_keys=True) + '\n')


def _objective_fingerprint(objective: dict[str, Any]) -> str:
    status = str(objective.get('status', 'unknown') or 'unknown')
    name = str(objective.get('name', '') or '')
    return f'{name}:{status}'


def _normalize_hook_result(result: Any) -> dict[str, Any]:
    if result is None:
        return {
            'status': 'hook_returned_none',
            'delivered': False,
            'details': {'hook_response': None},
        }
    if isinstance(result, bool):
        return {
            'status': 'delivered' if result else 'failed',
            'delivered': bool(result),
            'details': {'hook_response': result},
        }
    if isinstance(result, dict):
        status = str(result.get('status') or result.get('delivery_status') or '').strip().lower()
        if not status:
            if result.get('delivered') is True or result.get('ok') is True:
                status = 'delivered'
            else:
                status = 'reported'
        delivered = bool(result.get('delivered')) or bool(result.get('ok')) or status in HOOK_SUCCESS_STATUSES
        return {
            'status': status,
            'delivered': delivered,
            'details': {'hook_response': result},
        }
    return {
        'status': 'hook_returned_non_mapping',
        'delivered': False,
        'details': {
            'hook_response': repr(result),
            'hook_response_type': type(result).__name__,
        },
    }


def _load_current_state(org_id: str, policy_name: str, objective_name: str) -> dict[str, Any] | None:
    return observability_store.get_slo_alert_state(
        ALERT_LOG_FILE,
        org_id=org_id,
        policy_name=policy_name,
        objective=objective_name,
    )


def _persist_jsonl_record(record: dict[str, Any]) -> bool:
    try:
        _append_jsonl(ALERT_LOG_FILE, record)
        return True
    except OSError:
        return False


def _event_record(org_id: str, policy_name: str, objective: dict[str, Any], state_change: str, *, evaluated_at: str) -> dict[str, Any]:
    event_id = f'sloalert_{uuid.uuid4().hex[:12]}'
    status = str(objective.get('status', 'unknown') or 'unknown')
    message = str(objective.get('message', '') or '')
    return {
        'record_type': 'event',
        'id': event_id,
        'timestamp': _now(),
        'org_id': org_id,
        'policy_name': policy_name,
        'objective': str(objective.get('name', '') or ''),
        'status': status,
        'message': message,
        'evaluated_at': evaluated_at,
        'active': status in ACTIVE_STATUSES,
        'state_change': state_change,
        'fingerprint': _objective_fingerprint(objective),
        'details': {
            'warning_after_seconds': objective.get('warning_after_seconds'),
            'breach_after_seconds': objective.get('breach_after_seconds'),
            'warning_at_usd': objective.get('warning_at_usd'),
            'breach_at_usd': objective.get('breach_at_usd'),
            'observed_seconds': objective.get('observed_seconds'),
            'observed_usd': objective.get('observed_usd'),
            'metric': objective.get('metric'),
        },
    }


def _delivery_record(org_id: str, alert_event_id: str, hook_name: str, result: Any, *, evaluated_at: str) -> dict[str, Any]:
    normalized = _normalize_hook_result(result)
    return {
        'record_type': 'delivery',
        'id': f'sloalertdel_{uuid.uuid4().hex[:12]}',
        'timestamp': _now(),
        'org_id': org_id,
        'alert_event_id': alert_event_id,
        'hook_name': hook_name,
        'status': normalized['status'],
        'delivered': normalized['delivered'],
        'evaluated_at': evaluated_at,
        'details': normalized['details'],
    }


def _event_delivery_summary(event: dict[str, Any], deliveries: list[dict[str, Any]]) -> dict[str, Any]:
    latest_delivery = deliveries[0] if deliveries else None
    latest_status = str((latest_delivery or {}).get('status', '') or '')
    delivered = bool((latest_delivery or {}).get('delivered'))
    if not deliveries:
        delivery_state = 'queued'
    elif delivered:
        delivery_state = 'delivered'
    elif latest_status:
        delivery_state = latest_status
    else:
        delivery_state = 'attempted'
    return {
        'alert_event_id': event.get('id', ''),
        'objective': event.get('objective', ''),
        'status': event.get('status', 'unknown'),
        'active': bool(event.get('active')),
        'state_change': event.get('state_change', ''),
        'delivery_state': delivery_state,
        'delivery_attempt_count': len(deliveries),
        'latest_delivery': latest_delivery,
        'event': event,
    }


def _event_dispatch_summary(event: dict[str, Any], dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    latest_dispatch = dispatches[0] if dispatches else None
    latest_status = str((latest_dispatch or {}).get('status', '') or '')
    dispatched = bool((latest_dispatch or {}).get('acknowledged'))
    if not dispatches:
        dispatch_state = 'not_dispatched'
    elif latest_status in HOOK_SUCCESS_STATUSES:
        dispatch_state = 'delivered'
    elif latest_status:
        dispatch_state = latest_status
    elif dispatched:
        dispatch_state = 'acknowledged'
    else:
        dispatch_state = 'attempted'
    return {
        'dispatch_state': dispatch_state,
        'dispatch_attempt_count': len(dispatches),
        'latest_dispatch': latest_dispatch,
    }


def record_slo_alerts(
    evaluation: dict[str, Any],
    *,
    org_id: str,
    delivery_hook: AlertHook | None = None,
    hook_name: str = '',
    dry_run: bool = False,
) -> dict[str, Any]:
    policy_name = str(evaluation.get('policy_name') or 'meridian_observability_slo_v1')
    evaluated_at = str(evaluation.get('evaluated_at') or _now())
    events: list[dict[str, Any]] = []
    deliveries: list[dict[str, Any]] = []
    changed_objectives: list[str] = []

    for objective in evaluation.get('objectives', []) or []:
        objective_name = str(objective.get('name', '') or '')
        current_status = str(objective.get('status', 'unknown') or 'unknown')
        active = current_status in ACTIVE_STATUSES
        previous_state = _load_current_state(org_id, policy_name, objective_name)
        previous_status = str((previous_state or {}).get('current_status', '') or '')
        previous_active = previous_status in ACTIVE_STATUSES
        current_fingerprint = _objective_fingerprint(objective)

        if previous_state is None:
            state_change = 'opened' if active else 'observed'
        elif previous_status == current_status:
            state_change = 'steady'
        elif previous_active and not active:
            state_change = 'resolved'
        elif not previous_active and active:
            state_change = 'opened'
        elif previous_status == 'warning' and current_status == 'breached':
            state_change = 'escalated'
        elif previous_status == 'breached' and current_status == 'warning':
            state_change = 'deescalated'
        else:
            state_change = 'updated'

        state_record = {
            'org_id': org_id,
            'policy_name': policy_name,
            'objective': objective_name,
            'current_status': current_status,
            'current_fingerprint': current_fingerprint,
            'first_seen_at': (previous_state or {}).get('first_seen_at') or evaluated_at,
            'last_seen_at': evaluated_at,
            'last_evaluated_at': evaluated_at,
            'current_event_id': (previous_state or {}).get('current_event_id') or '',
            'current_message': str(objective.get('message', '') or ''),
        }

        event_needed = state_change in {'opened', 'resolved', 'escalated', 'deescalated', 'updated'} and (previous_state is not None or active)
        event_record = None
        if event_needed and state_change not in {'steady'}:
            event_record = _event_record(org_id, policy_name, objective, state_change, evaluated_at=evaluated_at)
            state_record['current_event_id'] = event_record['id']
            events.append(event_record)
            changed_objectives.append(objective_name)
            _persist_jsonl_record(event_record)
            observability_store.write_slo_alert_event(ALERT_LOG_FILE, event_record)
        else:
            state_record['current_event_id'] = (previous_state or {}).get('current_event_id') or ''

        observability_store.upsert_slo_alert_state(ALERT_LOG_FILE, state_record)

        if event_record and active:
            if dry_run:
                delivery_result = _delivery_record(
                    org_id,
                    event_record['id'],
                    hook_name or (getattr(delivery_hook, '__name__', '') if delivery_hook is not None else ''),
                    {
                        'status': 'dry_run',
                        'delivered': False,
                        'dry_run': True,
                        'would_call_hook': delivery_hook is not None,
                    },
                    evaluated_at=evaluated_at,
                )
                deliveries.append(delivery_result)
                _persist_jsonl_record(delivery_result)
                observability_store.write_slo_alert_delivery(ALERT_LOG_FILE, delivery_result)
            elif delivery_hook is None:
                delivery_result = _delivery_record(org_id, event_record['id'], hook_name or '', None, evaluated_at=evaluated_at)
                deliveries.append(delivery_result)
                _persist_jsonl_record(delivery_result)
                observability_store.write_slo_alert_delivery(ALERT_LOG_FILE, delivery_result)
            else:
                try:
                    hook_result = delivery_hook(event_record)
                except Exception as exc:  # pragma: no cover - exercised via tests
                    delivery_result = _delivery_record(
                        org_id,
                        event_record['id'],
                        hook_name or getattr(delivery_hook, '__name__', ''),
                        {'status': 'failed', 'error': str(exc)},
                        evaluated_at=evaluated_at,
                    )
                    deliveries.append(delivery_result)
                    _persist_jsonl_record(delivery_result)
                    observability_store.write_slo_alert_delivery(ALERT_LOG_FILE, delivery_result)
                else:
                    delivery_result = _delivery_record(
                        org_id,
                        event_record['id'],
                        hook_name or getattr(delivery_hook, '__name__', ''),
                        hook_result,
                        evaluated_at=evaluated_at,
                    )
                    deliveries.append(delivery_result)
                    _persist_jsonl_record(delivery_result)
                    observability_store.write_slo_alert_delivery(ALERT_LOG_FILE, delivery_result)

    active_events = [event for event in events if event.get('active')]
    resolved_events = [event for event in events if event.get('state_change') == 'resolved']
    return {
        'log_path': ALERT_LOG_FILE,
        'policy_name': policy_name,
        'evaluated_at': evaluated_at,
        'delivery_mode': 'dry_run' if dry_run else ('hook' if delivery_hook is not None else 'none'),
        'event_count': len(events),
        'delivery_count': len(deliveries),
        'active_alert_count': len(active_events),
        'resolved_alert_count': len(resolved_events),
        'changed_objectives': changed_objectives,
        'events': events,
        'deliveries': deliveries,
        'hook': {
            'configured': delivery_hook is not None,
            'name': hook_name or (getattr(delivery_hook, '__name__', '') if delivery_hook is not None else ''),
            'dry_run': dry_run,
        },
    }


def _dispatch_record(org_id: str, alert_event_id: str, hook_name: str, result: Any, *, evaluated_at: str) -> dict[str, Any]:
    normalized = _normalize_hook_result(result)
    return {
        'record_type': 'dispatch',
        'id': f'sloalertdisp_{uuid.uuid4().hex[:12]}',
        'timestamp': _now(),
        'org_id': org_id,
        'alert_event_id': alert_event_id,
        'hook_name': hook_name,
        'status': normalized['status'],
        'acknowledged': True,
        'evaluated_at': evaluated_at,
        'details': normalized['details'],
    }


def dispatch_queued_alerts(
    org_id: str,
    *,
    limit: int = 20,
    delivery_hook: AlertHook | None = None,
    hook_name: str = '',
    acknowledge_only: bool = True,
) -> dict[str, Any]:
    queue_snapshot = alert_queue_snapshot(org_id, limit=limit)
    queue_entries = queue_snapshot.get('queue', []) or []
    dispatches: list[dict[str, Any]] = []
    dispatched_entries = 0
    skipped_existing_dispatches = 0
    for entry in queue_entries:
        if entry.get('delivery_state') in HOOK_SUCCESS_STATUSES:
            continue
        if int(entry.get('dispatch_attempt_count', 0) or 0) > 0:
            skipped_existing_dispatches += 1
            continue
        event = entry.get('event') or {}
        event_id = str(event.get('id', '') or entry.get('alert_event_id', '') or '')
        if not event_id:
            continue
        resolved_hook_name = hook_name or (getattr(delivery_hook, '__name__', '') if delivery_hook is not None else '')
        if acknowledge_only or delivery_hook is None:
            dispatch_record = _dispatch_record(
                org_id,
                event_id,
                resolved_hook_name,
                {
                    'status': 'acknowledged_pending',
                    'acknowledged': True,
                    'dispatch_mode': 'inspect_only',
                    'delivery_state': entry.get('delivery_state', ''),
                    'would_call_hook': delivery_hook is not None and not acknowledge_only,
                },
                evaluated_at=str(event.get('evaluated_at') or ''),
            )
        else:
            try:
                hook_result = delivery_hook(event)
            except Exception as exc:  # pragma: no cover - exercised via tests
                dispatch_record = _dispatch_record(
                    org_id,
                    event_id,
                    resolved_hook_name,
                    {'status': 'failed', 'error': str(exc), 'dispatch_mode': 'hook'},
                    evaluated_at=str(event.get('evaluated_at') or ''),
                )
            else:
                dispatch_record = _dispatch_record(
                    org_id,
                    event_id,
                    resolved_hook_name,
                    hook_result,
                    evaluated_at=str(event.get('evaluated_at') or ''),
                )
        dispatches.append(dispatch_record)
        dispatched_entries += 1
        _persist_jsonl_record(dispatch_record)
        observability_store.write_slo_alert_dispatch(ALERT_LOG_FILE, dispatch_record)
    refreshed_queue = alert_queue_snapshot(org_id, limit=limit)
    return {
        'log_path': ALERT_LOG_FILE,
        'org_id': org_id,
        'limit': limit,
        'dispatch_mode': 'inspect_only' if acknowledge_only or delivery_hook is None else 'hook',
        'dispatched_count': dispatched_entries,
        'acknowledged_count': dispatched_entries,
        'skipped_existing_dispatch_count': skipped_existing_dispatches,
        'queue_count': refreshed_queue.get('queue_count', 0),
        'pending_delivery_count': refreshed_queue.get('pending_delivery_count', 0),
        'delivered_count': refreshed_queue.get('delivered_count', 0),
        'dispatches': dispatches,
        'queue': refreshed_queue.get('queue', []),
        'db': refreshed_queue.get('db', observability_store.db_status_for_log(ALERT_LOG_FILE)),
    }


def alert_queue_snapshot(org_id: str, *, limit: int = 20) -> dict[str, Any]:
    events = observability_store.query_slo_alert_events(ALERT_LOG_FILE, org_id=org_id, limit=limit)
    deliveries = observability_store.query_slo_alert_deliveries(ALERT_LOG_FILE, org_id=org_id, limit=limit * 5)
    dispatches = observability_store.query_slo_alert_dispatches(ALERT_LOG_FILE, org_id=org_id, limit=limit * 5)
    deliveries_by_event: dict[str, list[dict[str, Any]]] = {}
    for delivery in deliveries:
        alert_event_id = str(delivery.get('alert_event_id', '') or '')
        deliveries_by_event.setdefault(alert_event_id, []).append(delivery)
    dispatches_by_event: dict[str, list[dict[str, Any]]] = {}
    for dispatch in dispatches:
        alert_event_id = str(dispatch.get('alert_event_id', '') or '')
        dispatches_by_event.setdefault(alert_event_id, []).append(dispatch)
    queue_entries = []
    for event in events:
        if not event.get('active'):
            continue
        event_id = str(event.get('id', '') or '')
        policy_name = str(event.get('policy_name', '') or '')
        objective_name = str(event.get('objective', '') or '')
        current_state = _load_current_state(org_id, policy_name, objective_name)
        current_event_id = str((current_state or {}).get('current_event_id', '') or '')
        current_status = str((current_state or {}).get('current_status', '') or '')
        if current_event_id != event_id or current_status not in ACTIVE_STATUSES:
            continue
        entry = _event_delivery_summary(event, deliveries_by_event.get(event_id, []))
        entry.update(_event_dispatch_summary(event, dispatches_by_event.get(event_id, [])))
        queue_entries.append(entry)
    pending_entries = [entry for entry in queue_entries if entry['delivery_state'] not in HOOK_SUCCESS_STATUSES]
    delivered_entries = [entry for entry in queue_entries if entry['delivery_state'] in HOOK_SUCCESS_STATUSES]
    acknowledged_entries = [entry for entry in queue_entries if entry['dispatch_state'] != 'not_dispatched']
    return {
        'log_path': ALERT_LOG_FILE,
        'org_id': org_id,
        'queue_count': len(queue_entries),
        'pending_delivery_count': len(pending_entries),
        'delivered_count': len(delivered_entries),
        'acknowledged_count': len(acknowledged_entries),
        'dispatch_attempt_count': sum(int(entry.get('dispatch_attempt_count', 0) or 0) for entry in queue_entries),
        'queue': queue_entries,
        'db': observability_store.db_status_for_log(ALERT_LOG_FILE),
    }


def alert_surface_snapshot(org_id: str, *, limit: int = 20) -> dict[str, Any]:
    events = observability_store.query_slo_alert_events(ALERT_LOG_FILE, org_id=org_id, limit=limit)
    deliveries = observability_store.query_slo_alert_deliveries(ALERT_LOG_FILE, org_id=org_id, limit=limit)
    state_rows = []
    for event in events:
        state_rows.append({
            'objective': event.get('objective', ''),
            'status': event.get('status', 'unknown'),
            'state_change': event.get('state_change', ''),
            'timestamp': event.get('timestamp', ''),
        })
    queue_snapshot = alert_queue_snapshot(org_id, limit=limit)
    active_count = int(queue_snapshot.get('queue_count', 0) or 0)
    return {
        'log_path': ALERT_LOG_FILE,
        'event_count': len(events),
        'delivery_count': len(deliveries),
        'active_alert_count': active_count,
        'queue_count': active_count,
        'events': events,
        'deliveries': deliveries,
        'queue': queue_snapshot,
        'state': state_rows,
        'db': observability_store.db_status_for_log(ALERT_LOG_FILE),
    }
