#!/usr/bin/env python3
"""
Live-only Loom deployment proof helpers.

This module intentionally stays read-only. It maps governed Meridian agent
records to live Loom handles and parses Loom JSON health and service surfaces
into a structured proof object for the current single-host deployment.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional


PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(PLATFORM_DIR)
REPO_ROOT = os.path.dirname(WORKSPACE_DIR)

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

from agent_registry import load_registry, normalize_agent_record  # noqa: E402
from constitutional_model import constitutional_model  # noqa: E402
from loom_runtime_discovery import preferred_loom_bin, preferred_loom_root  # noqa: E402


AGENT_HANDLE_FIELDS = ('economy_key', 'name', 'id')
HEALTH_PROBE_TIMEOUT_SECONDS = 5
SERVICE_PROBE_TIMEOUT_SECONDS = 5
MEMORY_PROBE_TIMEOUT_SECONDS = 5
CONTEXT_PROBE_TIMEOUT_SECONDS = 5
_HEALTH_AGENT_RE = re.compile(r'^Agents:\s*(?P<agents>.+)$')
_HEALTH_HEARTBEAT_RE = re.compile(r'^Heartbeat interval:\s*(?P<interval>.+?)(?:\s+\((?P<primary>[^)]+)\))?$')
_HEALTH_SESSION_RE = re.compile(r'^Session store \((?P<agent>[^)]+)\):\s*(?P<path>.+?)\s+\((?P<count>\d+)\s+entries?\)$')
_HEALTH_SESSION_ENTRY_RE = re.compile(r'^-?\s*(?P<agent>[^:]+):(?P<scope>[^:]+):(?P<session>[^ ]+)\s+\((?P<age>[^)]+)\)$')
_HEALTH_TELEGRAM_RE = re.compile(
    r'^Telegram:\s*(?P<status>[^()]+?)'
    r'(?:\s+\((?P<detail1>[^)]+)\))?'
    r'(?:\s+\((?P<detail2>[^)]+)\))?$'
)
RUNTIME_PROOF_CONTRACT_VERSION = "runtime_proof_contract_v1"


def _now() -> str:
    return _dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _slugify_handle(value: str) -> str:
    value = (value or '').strip().lower()
    if not value:
        return ''
    return re.sub(r'[^a-z0-9]+', '_', value).strip('_')


def _agent_handle(agent: Mapping[str, Any]) -> str:
    for field in AGENT_HANDLE_FIELDS:
        raw = (agent.get(field) or '').strip()
        if not raw:
            continue
        if field == 'economy_key':
            return raw
        if field == 'name':
            return _slugify_handle(raw)
        return _slugify_handle(raw)
    return ''


def _agent_handle_candidates(agent: Mapping[str, Any]) -> List[str]:
    seen = set()
    candidates: List[str] = []
    for field in AGENT_HANDLE_FIELDS:
        raw = (agent.get(field) or '').strip()
        if not raw:
            continue
        handle = raw if field == 'economy_key' else _slugify_handle(raw)
        if handle and handle not in seen:
            candidates.append(handle)
            seen.add(handle)
    return candidates


def _loom_bin() -> str:
    return preferred_loom_bin()


def _loom_root() -> str:
    return preferred_loom_root()


def _health_command() -> List[str]:
    return [_loom_bin(), 'health', '--root', _loom_root(), '--format', 'json']


def _service_probe_command() -> List[str]:
    return [_loom_bin(), 'service', 'status', '--root', _loom_root(), '--format', 'json']


def _memory_command() -> List[str]:
    return [_loom_bin(), 'memory', 'status', '--root', _loom_root(), '--format', 'json']


def _context_command() -> List[str]:
    return [_loom_bin(), 'context', 'status', '--root', _loom_root(), '--format', 'json']


def map_governed_agents_to_loom_handles(
    agents: Optional[Iterable[Mapping[str, Any]]] = None,
    runtime_handles: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    if agents is None:
        registry = load_registry()
        agents = registry.get('agents', {}).values()

    available_handles = {str(handle or '').strip() for handle in (runtime_handles or []) if str(handle or '').strip()}
    mapped = []
    for agent in agents:
        normalized = normalize_agent_record(agent)
        candidates = _agent_handle_candidates(normalized)
        handle = next((candidate for candidate in candidates if candidate in available_handles), '') if available_handles else ''
        if not handle:
            handle = candidates[0] if candidates else ''
        handle_source = 'runtime_match' if (available_handles and handle in available_handles) else (
            'economy_key' if (normalized.get('economy_key') or '').strip() else 'name'
        )
        mapped.append({
            'agent_id': normalized.get('id'),
            'agent_name': normalized.get('name'),
            'org_id': normalized.get('org_id'),
            'role': normalized.get('role'),
            'loom_handle': handle,
            'economy_key': (normalized.get('economy_key') or '').strip(),
            'handle_candidates': candidates,
            'runtime_binding': dict(normalized.get('runtime_binding') or {}),
            'has_loom_handle': bool(handle),
            'handle_source': handle_source,
        })
    return mapped


def _split_csv_agents(raw: str) -> List[Dict[str, Any]]:
    agents = []
    for chunk in (raw or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = re.match(r'^(?P<name>.+?)(?:\s+\((?P<role>[^)]+)\))?$', chunk)
        name = (match.group('name') if match else chunk).strip()
        role = (match.group('role') if match and match.group('role') else None)
        agents.append({
            'name': name,
            'role': role,
            'handle': _slugify_handle(name),
            'is_default': bool(role and role == 'default'),
        })
    return agents


def _parse_loom_health_lines(output: str) -> Dict[str, Any]:
    lines = [line.rstrip() for line in (output or '').splitlines() if line.strip()]
    proof = {
        'checked_at': _now(),
        'status': 'unknown',
        'raw_line_count': len(lines),
        'telegram': {'status': None, 'detail': None, 'ok': False},
        'agents': [],
        'heartbeat': {'interval': None, 'primary_agent': None},
        'session_stores': [],
        'sessions': [],
        'raw': lines,
    }

    for line in lines:
        telegram = _HEALTH_TELEGRAM_RE.match(line)
        if telegram:
            status = (telegram.group('status') or '').strip()
            detail = (telegram.group('detail1') or telegram.group('detail2') or '').strip() or None
            proof['telegram'] = {
                'status': status,
                'detail': detail,
                'ok': status.lower().startswith('ok'),
            }
            continue

        agents = _HEALTH_AGENT_RE.match(line)
        if agents:
            proof['agents'] = _split_csv_agents(agents.group('agents'))
            continue

        heartbeat = _HEALTH_HEARTBEAT_RE.match(line)
        if heartbeat:
            proof['heartbeat'] = {
                'interval': (heartbeat.group('interval') or '').strip() or None,
                'primary_agent': (heartbeat.group('primary') or '').strip() or None,
            }
            continue

        session_store = _HEALTH_SESSION_RE.match(line)
        if session_store:
            proof['session_stores'].append({
                'agent': session_store.group('agent').strip(),
                'path': session_store.group('path').strip(),
                'entries': int(session_store.group('count')),
            })
            continue

        session_entry = _HEALTH_SESSION_ENTRY_RE.match(line)
        if session_entry:
            proof['sessions'].append({
                'agent': session_entry.group('agent').strip(),
                'scope': session_entry.group('scope').strip(),
                'session_id': session_entry.group('session').strip(),
                'age': session_entry.group('age').strip(),
            })
            continue

    proof['health_ok'] = bool(proof['telegram']['ok'] and proof['agents'])
    proof['session_total'] = sum(item['entries'] for item in proof['session_stores'])
    proof['agent_count'] = len(proof['agents'])
    return proof


def _extract_check(payload: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    for item in payload.get('checks') or []:
        if isinstance(item, Mapping) and item.get('label') == label:
            return item
    return {}


def _parse_agent_runtime_detail(detail: str) -> List[Dict[str, Any]]:
    match = re.search(r'agents=([^ ]+)', detail or '')
    if not match:
        return []
    handles = [item.strip() for item in match.group(1).split(',') if item.strip()]
    return [
        {'name': handle, 'role': None, 'handle': handle, 'is_default': handle == 'leviathann'}
        for handle in handles
    ]


def _parse_int_field(detail: str, key: str) -> int:
    match = re.search(rf'{re.escape(key)}=(\d+)', detail or '')
    return int(match.group(1)) if match else 0


def _parse_csv_field(detail: str, key: str) -> List[str]:
    match = re.search(rf'{re.escape(key)}=([^ ]+)', detail or '')
    if not match:
        return []
    raw = (match.group(1) or '').strip()
    if not raw or raw == '(none)':
        return []
    return [item.strip() for item in raw.split(',') if item.strip()]


def _parse_loom_health_json(output: str) -> Dict[str, Any]:
    payload = json.loads(output)
    if isinstance(payload, list):
        payload = {'status': 'unknown', 'checks': payload}
    if not isinstance(payload, dict):
        raise ValueError('loom health payload must be a JSON object')

    agent_runtime = _extract_check(payload, 'agent_runtime')
    channel_runtime = _extract_check(payload, 'channel_runtime')
    session_runtime = _extract_check(payload, 'session_provenance')

    agents = _parse_agent_runtime_detail((agent_runtime.get('detail') or '').strip())
    channel_detail = (channel_runtime.get('detail') or '').strip()
    channel_handles = []
    channel_handles = _parse_csv_field(channel_detail, 'channels')
    enabled_count = _parse_int_field(channel_detail, 'enabled')
    session_detail = (session_runtime.get('detail') or '').strip()
    session_total = _parse_int_field(session_detail, 'total')
    session_active = _parse_int_field(session_detail, 'active')
    session_archived = _parse_int_field(session_detail, 'archived')
    if session_total and session_active == 0 and session_archived == 0:
        session_active = session_total

    channel_active_deliveries = _parse_int_field(channel_detail, 'active_deliveries')
    channel_archived_deliveries = _parse_int_field(channel_detail, 'archived_deliveries')

    return {
        'checked_at': _now(),
        'status': (payload.get('status') or 'unknown').strip().lower(),
        'raw_line_count': 0,
        'telegram': {
            'status': 'enabled' if 'telegram' in channel_handles else 'disabled',
            'detail': channel_detail or None,
            'ok': 'telegram' in channel_handles and enabled_count >= 2,
        },
        'agents': agents,
        'heartbeat': {'interval': None, 'primary_agent': None},
        'session_stores': [],
        'sessions': [],
        'raw': payload,
        'health_ok': (payload.get('status') or '').strip().lower() == 'healthy',
        'session_total': session_total,
        'agent_count': len(agents),
        'session_runtime': {
            'total_count': session_total,
            'active_count': session_active,
            'archived_count': session_archived,
            'session_keys': _parse_csv_field(session_detail, 'sessions'),
        },
        'channel_runtime': {
            'total_count': _parse_int_field(channel_detail, 'total'),
            'enabled_count': enabled_count,
            'ingress_count': _parse_int_field(channel_detail, 'ingress'),
            'active_delivery_count': channel_active_deliveries,
            'archived_delivery_count': channel_archived_deliveries,
            'channel_ids': channel_handles,
        },
    }


def parse_loom_health(output: str) -> Dict[str, Any]:
    raw = (output or '').strip()
    if raw.startswith('{') or raw.startswith('['):
        try:
            return _parse_loom_health_json(raw)
        except (json.JSONDecodeError, ValueError):
            pass
    return _parse_loom_health_lines(output)


def _run_command(command: List[str], timeout: int) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            'command': list(command),
            'ok': False,
            'returncode': 124,
            'stdout': '',
            'stderr': f'timeout after {timeout}s',
        }
    return {
        'command': list(command),
        'ok': result.returncode == 0,
        'returncode': result.returncode,
        'stdout': (result.stdout or '').strip(),
        'stderr': (result.stderr or '').strip(),
    }


def _parse_service_probe(stdout: str) -> Dict[str, Any]:
    raw = (stdout or '').strip()
    if not raw:
        return {'ok': False, 'service_status': '', 'health': '', 'transport': '', 'running': False}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError('loom service status payload must be a JSON object')
    return {
        'ok': bool(payload.get('running')) and payload.get('service_status') == 'running' and payload.get('health') == 'healthy',
        'service_status': payload.get('service_status', ''),
        'health': payload.get('health', ''),
        'transport': payload.get('transport', ''),
        'running': bool(payload.get('running')),
    }


def collect_loom_runtime_proof(
    *,
    health_output: Optional[str] = None,
    health_command: Optional[List[str]] = None,
    agents: Optional[Iterable[Mapping[str, Any]]] = None,
    include_service_probe: bool = False,
    service_probe_command: Optional[List[str]] = None,
) -> Dict[str, Any]:
    health_probe = None
    if health_output is None:
        health_probe = _run_command(
            health_command or _health_command(),
            timeout=HEALTH_PROBE_TIMEOUT_SECONDS,
        )
        health_output = health_probe['stdout']

    health = parse_loom_health(health_output)
    health_handles = {agent.get('handle') for agent in health.get('agents', []) if agent.get('handle')}
    mapped_agents = map_governed_agents_to_loom_handles(agents=agents, runtime_handles=health_handles)
    mapped_handles = {
        entry['loom_handle']
        for entry in mapped_agents
        if entry.get('loom_handle')
    }
    service_probe = {
        'checked': False,
        'ok': False,
        'output': '',
        'stderr': '',
        'command': list(service_probe_command or _service_probe_command()),
        'service_status': '',
        'health': '',
        'transport': '',
    }
    memory_context = {
        'checked': False,
        'memory_ok': False,
        'context_ok': False,
        'memory': {},
        'context': {},
    }
    if include_service_probe:
        probe = _run_command(
            service_probe_command or _service_probe_command(),
            timeout=SERVICE_PROBE_TIMEOUT_SECONDS,
        )
        try:
            parsed = _parse_service_probe(probe['stdout']) if probe['ok'] else {
                'ok': False,
                'service_status': '',
                'health': '',
                'transport': '',
                'running': False,
            }
        except (json.JSONDecodeError, ValueError):
            parsed = {'ok': False, 'service_status': '', 'health': '', 'transport': '', 'running': False}
        service_probe = {
            'checked': True,
            'ok': bool(parsed.get('ok')),
            'output': probe['stdout'],
            'stderr': probe['stderr'],
            'command': probe['command'],
            'service_status': parsed.get('service_status', ''),
            'health': parsed.get('health', ''),
            'transport': parsed.get('transport', ''),
        }
        memory_probe = _run_command(_memory_command(), timeout=MEMORY_PROBE_TIMEOUT_SECONDS)
        context_probe = _run_command(_context_command(), timeout=CONTEXT_PROBE_TIMEOUT_SECONDS)
        if memory_probe.get('ok'):
            try:
                memory_payload = json.loads(memory_probe['stdout']) if memory_probe['stdout'] else {}
            except json.JSONDecodeError:
                memory_payload = {}
        else:
            memory_payload = {}
        if context_probe.get('ok'):
            try:
                context_payload = json.loads(context_probe['stdout']) if context_probe['stdout'] else {}
            except json.JSONDecodeError:
                context_payload = {}
        else:
            context_payload = {}
        memory_context = {
            'checked': True,
            'memory_ok': bool(memory_probe.get('ok') and isinstance(memory_payload, dict)),
            'context_ok': bool(context_probe.get('ok') and isinstance(context_payload, dict)),
            'memory': memory_payload if isinstance(memory_payload, dict) else {},
            'context': context_payload if isinstance(context_payload, dict) else {},
        }

    return {
        'runtime_id': 'loom_native',
        'proof_type': 'live_single_host_loom_deployment',
        'checked_at': _now(),
        'health': health,
        'health_probe': health_probe or {
            'command': list(health_command or _health_command()),
            'ok': True,
            'returncode': 0,
            'stdout': health_output,
            'stderr': '',
        },
        'service_probe': service_probe,
        'memory_context': memory_context,
        'governed_agents': mapped_agents,
        'handle_overlap': sorted(health_handles & mapped_handles),
        'handle_gap': sorted(mapped_handles - health_handles),
        'health_output_supplied': health_output is not None,
        'deployment_truth': {
            'scope': 'single_host',
            'deployment_mode': 'live',
            'proof_level': 'read_only',
            'generic_runtime_claim': False,
        },
    }


def public_loom_runtime_receipt(
    proof: Mapping[str, Any],
    *,
    bound_org_id: Optional[str] = None,
) -> Dict[str, Any]:
    health = dict(proof.get('health') or {})
    governed_agents = list(proof.get('governed_agents') or [])
    service_probe = dict(proof.get('service_probe') or {})
    memory_context = dict(proof.get('memory_context') or {})
    effective_health_status = (
        health.get('status')
        or service_probe.get('health')
        or service_probe.get('service_status')
        or 'unknown'
    )
    if effective_health_status == 'unknown' and service_probe.get('ok'):
        effective_health_status = service_probe.get('health') or service_probe.get('service_status') or 'healthy'
    source_health_status = str(health.get('status') or 'unknown').strip().lower() or 'unknown'
    effective_health_status = str(effective_health_status or source_health_status).strip().lower() or source_health_status
    runtime_health = {
        'status': effective_health_status,
        'source_status': source_health_status,
        'health_ok': bool(health.get('health_ok') or service_probe.get('ok')),
        'service_probe_ok': bool(service_probe.get('ok')),
    }
    session_surface = dict(health.get('session_runtime') or {})
    channel_surface = dict(health.get('channel_runtime') or {})
    memory_ok = bool(memory_context.get('checked') and memory_context.get('memory_ok') and memory_context.get('context_ok'))
    channel_ok = bool(service_probe.get('ok') and int(channel_surface.get('enabled_count') or 0) > 0)
    runtime_ok = bool(runtime_health.get('health_ok'))
    # Keep runtime status consistent with runtime_ok/service_probe truth to avoid
    # contradictory "degraded" labels when all checks are actually healthy.
    if runtime_ok and runtime_health['status'] in {'unknown', 'warning', 'degraded'}:
        runtime_health['status'] = 'healthy'
    effective_health_status = runtime_health.get('status') or source_health_status
    runtime_proof_contract = {
        'version': RUNTIME_PROOF_CONTRACT_VERSION,
        'runtime_proof_status': 'proven' if runtime_ok else 'degraded',
        'channel_surface_status': 'bounded_proven' if channel_ok else 'unverified',
        'memory_surface_status': 'bounded_proven' if memory_ok else 'unverified',
        'proof_chain_status': (
            'complete'
            if runtime_ok and channel_ok and memory_ok
            else ('partial' if runtime_ok else 'degraded')
        ),
        'proof_path': '/api/status -> /api/runtime-proof -> /api/runtime-proof-contract -> /api/kernel-proof-bundle',
        'session_surface_status': 'bounded_proven' if int(session_surface.get('total_count') or 0) >= 0 else 'unverified',
    }
    return {
        'runtime_id': proof.get('runtime_id', 'loom_native'),
        'proof_type': proof.get('proof_type', 'live_single_host_loom_deployment'),
        'checked_at': proof.get('checked_at', _now()),
        'bound_org_id': bound_org_id,
        'constitutional_model': constitutional_model(),
        'deployment_truth': dict(proof.get('deployment_truth') or {}),
        'health': {
            'status': effective_health_status,
            'health_ok': bool(health.get('health_ok') or service_probe.get('ok')),
            'telegram_ok': bool((health.get('telegram') or {}).get('ok')),
            'agent_count': health.get('agent_count', 0),
            'agent_handles': [agent.get('handle', '') for agent in health.get('agents', []) if agent.get('handle')],
            'heartbeat_interval': (health.get('heartbeat') or {}).get('interval'),
            'primary_agent': (health.get('heartbeat') or {}).get('primary_agent'),
            'session_total': health.get('session_total', 0),
        },
        'runtime_surfaces': {
            'session_provenance': session_surface,
            'channel_runtime': channel_surface,
        },
        'runtime_health': runtime_health,
        'runtime_proof_contract': runtime_proof_contract,
        'service_probe': {
            'checked': bool(service_probe.get('checked')),
            'ok': bool(service_probe.get('ok')),
            'status': service_probe.get('service_status', ''),
            'health': service_probe.get('health', ''),
            'transport': service_probe.get('transport', ''),
            'output': service_probe.get('output', ''),
        },
        'memory_context': {
            'checked': bool(memory_context.get('checked')),
            'memory_ok': bool(memory_context.get('memory_ok')),
            'context_ok': bool(memory_context.get('context_ok')),
            'memory': dict(memory_context.get('memory') or {}),
            'context': dict(memory_context.get('context') or {}),
        },
        'governed_agents': [
            {
                'agent_id': entry.get('agent_id'),
                'agent_name': entry.get('agent_name'),
                'org_id': entry.get('org_id'),
                'role': entry.get('role'),
                'loom_handle': entry.get('loom_handle'),
                'economy_key': entry.get('economy_key'),
                'handle_candidates': list(entry.get('handle_candidates') or []),
                'handle_source': entry.get('handle_source'),
                'runtime_binding': {
                    'runtime_id': ((entry.get('runtime_binding') or {}).get('runtime_id', '')),
                    'runtime_registered': bool((entry.get('runtime_binding') or {}).get('runtime_registered', False)),
                    'registration_status': ((entry.get('runtime_binding') or {}).get('registration_status', '')),
                    'bound_org_id': ((entry.get('runtime_binding') or {}).get('bound_org_id', '')),
                },
            }
            for entry in governed_agents
        ],
        'mapping': {
            'handle_overlap': list(proof.get('handle_overlap') or []),
            'handle_gap': list(proof.get('handle_gap') or []),
            'governed_agent_count': len(governed_agents),
        },
    }


def public_loom_surface_contract_receipt(
    proof: Mapping[str, Any],
    *,
    bound_org_id: Optional[str] = None,
) -> Dict[str, Any]:
    health = dict(proof.get('health') or {})
    service_probe = dict(proof.get('service_probe') or {})
    memory_context = dict(proof.get('memory_context') or {})
    session_runtime = dict(health.get('session_runtime') or {})
    channel_runtime = dict(health.get('channel_runtime') or {})
    memory = dict(memory_context.get('memory') or {})
    context = dict(memory_context.get('context') or {})
    enabled_channels = [channel for channel in (channel_runtime.get('channel_ids') or []) if channel]

    omni_channel_status = (
        'bounded_proven'
        if bool(service_probe.get('ok')) and bool(enabled_channels)
        else 'unverified'
    )
    memory_status = (
        'bounded_proven'
        if bool(memory_context.get('checked')) and bool(memory_context.get('memory_ok')) and bool(memory_context.get('context_ok'))
        else 'unverified'
    )
    runtime_proof_contract = {
        'version': RUNTIME_PROOF_CONTRACT_VERSION,
        'runtime_proof_status': 'proven' if bool(service_probe.get('ok')) else 'degraded',
        'channel_surface_status': omni_channel_status,
        'memory_surface_status': memory_status,
        'proof_chain_status': (
            'complete'
            if bool(service_probe.get('ok')) and omni_channel_status == 'bounded_proven' and memory_status == 'bounded_proven'
            else ('partial' if bool(service_probe.get('ok')) else 'degraded')
        ),
        'proof_path': '/api/status -> /api/runtime-proof -> /api/runtime-proof-contract -> /api/kernel-proof-bundle',
    }

    return {
        'runtime_id': proof.get('runtime_id', 'loom_native'),
        'proof_type': 'bounded_live_surface_contract',
        'contract_version': 1,
        'runtime_proof_contract': runtime_proof_contract,
        'checked_at': proof.get('checked_at', _now()),
        'bound_org_id': bound_org_id,
        'deployment_truth': dict(proof.get('deployment_truth') or {}),
        'surface_contract': {
            'scope': 'bounded_live_host_surfaces',
            'surfaces': {
                'omni_channel_presence': {
                    'status': omni_channel_status,
                    'claim': (
                        'This host proves bounded channel runtime presence and delivery state for the '
                        'currently enabled Loom channels on this deployment.'
                    ),
                    'evidence': {
                        'service_probe_ok': bool(service_probe.get('ok')),
                        'transport': service_probe.get('transport', ''),
                        'channel_count': channel_runtime.get('total_count', 0),
                        'enabled_count': channel_runtime.get('enabled_count', 0),
                        'channel_ids': enabled_channels,
                        'ingress_count': channel_runtime.get('ingress_count', 0),
                        'active_delivery_count': channel_runtime.get('active_delivery_count', 0),
                        'archived_delivery_count': channel_runtime.get('archived_delivery_count', 0),
                        'telegram_ok': bool((health.get('telegram') or {}).get('ok')),
                        'session_total': session_runtime.get('total_count', 0),
                        'active_session_count': session_runtime.get('active_count', 0),
                    },
                    'proven_boundary': [
                        'enabled channel registry on this host',
                        'ingress and delivery counters on this host',
                        'bounded Telegram and web channel presence where enabled',
                        'live runtime service probe for the Loom transport',
                    ],
                    'not_claimed': [
                        'email delivery',
                        'slack delivery',
                        'every future channel kind',
                        'self-serve universal customer automation',
                        '24/7 autonomous delivery guarantees',
                    ],
                },
                'persistent_memory': {
                    'status': memory_status,
                    'claim': (
                        'This host proves bounded durable memory and context-engine surfaces through '
                        'live Loom memory/context status receipts.'
                    ),
                    'evidence': {
                        'checked': bool(memory_context.get('checked')),
                        'memory_ok': bool(memory_context.get('memory_ok')),
                        'context_ok': bool(memory_context.get('context_ok')),
                        'agent_count': memory.get('agent_count', 0),
                        'total_entries': memory.get('total_entries', 0),
                        'total_bytes': memory.get('total_bytes', 0),
                        'agent_isolation': bool((memory.get('policy') or {}).get('agent_isolation')),
                        'max_entries_per_agent': (memory.get('policy') or {}).get('max_entries_per_agent'),
                        'retention_days': (memory.get('policy') or {}).get('retention_days'),
                        'layer_count': context.get('layer_count', 0),
                        'section_count': context.get('section_count', 0),
                        'mutable_count': context.get('mutable_count', 0),
                        'sections': list(context.get('sections') or []),
                    },
                    'proven_boundary': [
                        'agent-isolated memory store policy on this host',
                        'memory store status and entry counters',
                        'context engine registry and overlay section counts',
                        'read-only proof of durable state surfaces, not semantic quality claims',
                    ],
                    'not_claimed': [
                        'broad semantic recall quality',
                        'cross-user memory sharing',
                        'non-empty customer memory for every agent',
                        'blanket hosted-memory guarantees for every deployment',
                    ],
                },
            },
            'not_claimed': [
                'blanket proof for every Loom architecture surface',
                'broad hosted runtime replacement',
                'future channel kinds that are not enabled on this host',
                'future memory behavior beyond the current live status receipts',
            ],
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if '--json' in argv:
        proof = collect_loom_runtime_proof()
        print(json.dumps(proof, indent=2, sort_keys=True))
        return 0

    proof = collect_loom_runtime_proof(include_service_probe=True)
    print(f"Checked at: {proof['checked_at']}")
    print(f"Health OK: {proof['health']['health_ok']}")
    print(f"Service probe OK: {proof['service_probe']['ok']}")
    print(f"Agents mapped: {len(proof['governed_agents'])}")
    print(f"Handle overlap: {', '.join(proof['handle_overlap']) or 'none'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
