#!/usr/bin/env python3
"""Formal SLO policy evaluation for Meridian observability."""

from __future__ import annotations

import datetime
from typing import Any


POLICY_NAME = 'meridian_observability_slo_v1'
DEFAULT_POLICY = {
    'name': POLICY_NAME,
    'objectives': [
        {
            'name': 'audit_freshness',
            'metric': 'audit.latest_at',
            'warning_after_seconds': 3600,
            'breach_after_seconds': 86400,
        },
        {
            'name': 'metering_freshness',
            'metric': 'metering.latest_at',
            'warning_after_seconds': 3600,
            'breach_after_seconds': 86400,
        },
        {
            'name': 'monthly_metering_cost',
            'metric': 'metering.total_cost_usd',
            'warning_at_usd': 80.0,
            'breach_at_usd': 100.0,
        },
        {
            'name': 'proof_settle_freshness',
            'metric': 'governance.proof_settle_latest_at',
            'warning_after_seconds': 7200,
            'breach_after_seconds': 172800,
        },
        {
            'name': 'governance_sanction_clean',
            'metric': 'governance.active_sanctions',
        },
    ],
}


def _now():
    return datetime.datetime.utcnow()


def _parse_timestamp(timestamp: str) -> datetime.datetime | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc).replace(tzinfo=None)


def _objective_status_rank(status: str) -> int:
    return {'healthy': 0, 'warning': 1, 'breached': 2, 'unknown': -1}.get(status, -1)


def _eval_freshness(name: str, latest_at: str, warning_after_seconds: int, breach_after_seconds: int) -> dict[str, Any]:
    parsed = _parse_timestamp(latest_at)
    if parsed is None:
        return {
            'name': name,
            'metric': latest_at,
            'status': 'unknown',
            'observed_seconds': None,
            'warning_after_seconds': warning_after_seconds,
            'breach_after_seconds': breach_after_seconds,
            'message': 'No timestamp available for freshness evaluation',
        }
    age_seconds = max(int((_now() - parsed).total_seconds()), 0)
    if age_seconds >= breach_after_seconds:
        status = 'breached'
    elif age_seconds >= warning_after_seconds:
        status = 'warning'
    else:
        status = 'healthy'
    return {
        'name': name,
        'metric': latest_at,
        'status': status,
        'observed_seconds': age_seconds,
        'warning_after_seconds': warning_after_seconds,
        'breach_after_seconds': breach_after_seconds,
        'message': f'Latest sample age is {age_seconds}s',
    }


def _eval_budget(name: str, total_cost_usd: float, warning_at_usd: float, breach_at_usd: float) -> dict[str, Any]:
    if total_cost_usd >= breach_at_usd:
        status = 'breached'
        message = f'Monthly cost ${total_cost_usd:.4f} exceeds breach threshold ${breach_at_usd:.2f}'
    elif total_cost_usd >= warning_at_usd:
        status = 'warning'
        message = f'Monthly cost ${total_cost_usd:.4f} exceeds warning threshold ${warning_at_usd:.2f}'
    else:
        status = 'healthy'
        message = f'Monthly cost ${total_cost_usd:.4f} is within budget'
    return {
        'name': name,
        'metric': total_cost_usd,
        'status': status,
        'observed_usd': round(float(total_cost_usd), 4),
        'warning_at_usd': warning_at_usd,
        'breach_at_usd': breach_at_usd,
        'message': message,
    }


def _eval_sanction_clean(name: str, active_sanctions: int) -> dict[str, Any]:
    active = int(active_sanctions or 0)
    if active > 0:
        status = 'breached'
        message = f'{active} active sanction(s) require court review'
    else:
        status = 'healthy'
        message = 'No active sanctions'
    return {
        'name': name,
        'metric': active,
        'status': status,
        'active_sanctions': active,
        'message': message,
    }


def evaluate_observability(metrics: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    policy = policy or DEFAULT_POLICY
    audit = metrics.get('audit', {}) if isinstance(metrics, dict) else {}
    metering = metrics.get('metering', {}) if isinstance(metrics, dict) else {}
    governance = metrics.get('governance', {}) if isinstance(metrics, dict) else {}
    objectives = [
        _eval_freshness(
            'audit_freshness',
            audit.get('latest_at', ''),
            3600,
            86400,
        ),
        _eval_freshness(
            'metering_freshness',
            metering.get('latest_at', ''),
            3600,
            86400,
        ),
        _eval_budget(
            'monthly_metering_cost',
            float(metering.get('total_cost_usd', 0.0) or 0.0),
            80.0,
            100.0,
        ),
        _eval_freshness(
            'proof_settle_freshness',
            governance.get('proof_settle_latest_at', ''),
            7200,
            172800,
        ),
        _eval_sanction_clean(
            'governance_sanction_clean',
            int(governance.get('active_sanctions', 0) or 0),
        ),
    ]
    ranked = max((_objective_status_rank(obj['status']) for obj in objectives), default=-1)
    if ranked == 2:
        overall_status = 'breached'
    elif ranked == 1:
        overall_status = 'warning'
    elif ranked == 0:
        overall_status = 'healthy'
    else:
        overall_status = 'unknown'
    alerts = [
        {
            'objective': obj['name'],
            'status': obj['status'],
            'message': obj['message'],
        }
        for obj in objectives
        if obj['status'] in {'warning', 'breached'}
    ]
    return {
        'policy_name': policy.get('name', POLICY_NAME),
        'status': overall_status,
        'evaluated_at': _now().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'objectives': objectives,
        'alerts': alerts,
        'alert_count': len(alerts),
        'healthy_objective_count': sum(1 for obj in objectives if obj['status'] == 'healthy'),
        'objective_count': len(objectives),
        'policy': policy,
    }


def prometheus_lines(evaluation: dict[str, Any], org_id: str | None = None) -> list[str]:
    labels = f'org_id="{org_id or ""}"'
    status_map = {'healthy': 1, 'warning': 0, 'breached': -1, 'unknown': -2}
    lines = [
        '# HELP meridian_slo_overall_status Overall SLO health (-1 breached, 0 warning, 1 healthy, -2 unknown).',
        '# TYPE meridian_slo_overall_status gauge',
        f"meridian_slo_overall_status{{{labels}}} {status_map.get(evaluation.get('status', 'unknown'), -2)}",
        '# HELP meridian_slo_alerts_total Count of active SLO alerts.',
        '# TYPE meridian_slo_alerts_total gauge',
        f"meridian_slo_alerts_total{{{labels}}} {int(evaluation.get('alert_count', 0) or 0)}",
    ]
    for objective in evaluation.get('objectives', []):
        lines.extend([
            f'# HELP meridian_slo_objective_status_{objective["name"]} Objective health for {objective["name"]} (-1 breached, 0 warning, 1 healthy, -2 unknown).',
            f'# TYPE meridian_slo_objective_status_{objective["name"]} gauge',
            f'meridian_slo_objective_status{{{labels},objective="{objective["name"]}"}} {status_map.get(objective.get("status", "unknown"), -2)}',
        ])
    return lines
