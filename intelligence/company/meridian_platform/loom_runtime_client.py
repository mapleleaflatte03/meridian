#!/usr/bin/env python3
"""Shared Loom runtime client helpers for Intelligence surfaces."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional


Runner = Callable[..., subprocess.CompletedProcess]
Sleeper = Callable[[float], None]
ResultLoader = Callable[[str, object], object]
CapabilityNormalizer = Callable[[dict], dict]

DEFAULT_CAPABILITY_COSTS_USD: dict[str, float] = {
    'loom.browser.navigate.v1': 0.03,
    'loom.llm.inference.v1': 0.05,
    'loom.fs.write.v1': 0.01,
    'loom.memory.core.v1': 0.01,
    'loom.system.info.v1': 0.01,
}
DEFAULT_ACTION_COSTS_USD: dict[str, float] = {
    'research': 0.03,
    'write': 0.01,
    'observe': 0.01,
    'execute': 0.02,
    'synthesize': 0.05,
}


@dataclass(frozen=True)
class LoomRuntimeContext:
    loom_bin: str
    loom_root: str
    org_id: str
    agent_id: str
    service_token: str = ''
    cwd: str = '.'
    runtime_env: Optional[Mapping[str, str]] = None

    def env(self) -> dict[str, str]:
        env = dict(self.runtime_env or os.environ)
        if self.service_token:
            env['LOOM_SERVICE_TOKEN'] = self.service_token
        return env


def _coerce_cost(candidate: Any) -> float | None:
    try:
        value = float(candidate)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return round(value, 4)


def format_estimated_cost_usd(value: float | int | str | None) -> str:
    numeric = _coerce_cost(value) or 0.0
    rendered = f'{numeric:.4f}'.rstrip('0').rstrip('.')
    return rendered or '0'


def estimate_capability_cost_usd(
    capability_name: str,
    payload: Mapping[str, Any] | None = None,
    *,
    action_type: str = '',
    resource: str = '',
) -> float:
    payload = payload or {}
    explicit = _coerce_cost(payload.get('estimated_cost_usd'))
    if explicit is not None:
        return explicit
    explicit = _coerce_cost(payload.get('estimatedCostUsd'))
    if explicit is not None:
        return explicit
    name = str(capability_name or '').strip()
    if name in DEFAULT_CAPABILITY_COSTS_USD:
        return DEFAULT_CAPABILITY_COSTS_USD[name]
    action = str(action_type or '').strip().lower()
    if action in DEFAULT_ACTION_COSTS_USD:
        return DEFAULT_ACTION_COSTS_USD[action]
    resource_text = str(resource or '').strip().lower()
    if 'research' in resource_text or 'search' in resource_text:
        return DEFAULT_ACTION_COSTS_USD['research']
    if 'write' in resource_text or resource_text.endswith('.md') or resource_text.endswith('.txt'):
        return DEFAULT_ACTION_COSTS_USD['write']
    return 0.01


def _job_record_path(context: LoomRuntimeContext, job_id: str) -> str:
    return os.path.join(context.loom_root, 'state', 'runtime', 'jobs', job_id, 'job.json')


def _load_job_record(context: LoomRuntimeContext, job_id: str) -> dict:
    path = _job_record_path(context, job_id)
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def capability_preflight(
    context: LoomRuntimeContext,
    capability_name: str,
    *,
    route: str,
    runner: Runner = subprocess.run,
    normalize_capability: CapabilityNormalizer | None = None,
    transport_allowlist: tuple[str, ...] = ('http', 'socket+http'),
) -> dict:
    preflight = {
        'ok': False,
        'runtime': 'loom',
        'route': route,
        'capability_name': capability_name,
        'errors': [],
        'warnings': [],
        'execution_mode': 'service_submit',
    }
    if not capability_name:
        preflight['errors'].append(f'{route} capability is not configured')
        return preflight

    env = context.env()
    service_errors: list[str] = []
    service_cmd = [context.loom_bin, 'service', 'status', '--root', context.loom_root, '--format', 'json']
    capability_cmd = [
        context.loom_bin,
        'capability',
        'show',
        '--root',
        context.loom_root,
        '--name',
        capability_name,
        '--format',
        'json',
    ]

    try:
        service = runner(service_cmd, capture_output=True, text=True, timeout=15, cwd=context.cwd, env=env)
    except subprocess.TimeoutExpired:
        service_errors.append('loom service status timed out')
        service = None
    except Exception as exc:
        service_errors.append(str(exc))
        service = None

    if service is not None:
        if service.returncode != 0:
            message = (service.stderr or service.stdout or 'unknown error').strip()
            service_errors.append(f'loom service status failed: {message[:500]}')
        else:
            try:
                service_payload = json.loads((service.stdout or '').strip())
            except json.JSONDecodeError:
                service_errors.append('loom service status returned non-JSON output')
            else:
                preflight['service'] = service_payload
                if not service_payload.get('running'):
                    service_errors.append('loom service is not running')
                if service_payload.get('service_status') != 'running':
                    service_errors.append(f"loom service_status={service_payload.get('service_status', '')}")
                if service_payload.get('health') != 'healthy':
                    service_errors.append(f"loom health={service_payload.get('health', '')}")
                transport = (service_payload.get('transport') or '').strip()
                if transport_allowlist and transport not in transport_allowlist:
                    service_errors.append(f'loom transport={transport}')

    try:
        capability = runner(capability_cmd, capture_output=True, text=True, timeout=15, cwd=context.cwd, env=env)
    except subprocess.TimeoutExpired:
        preflight['errors'].append('loom capability show timed out')
        capability = None
    except Exception as exc:
        preflight['errors'].append(str(exc))
        capability = None

    if capability is not None:
        if capability.returncode != 0:
            message = (capability.stderr or capability.stdout or 'unknown error').strip()
            preflight['errors'].append(f'loom capability show failed: {message[:500]}')
        else:
            try:
                capability_payload = json.loads((capability.stdout or '').strip())
            except json.JSONDecodeError:
                preflight['errors'].append('loom capability show returned non-JSON output')
            else:
                preflight['capability'] = capability_payload
                if normalize_capability is not None:
                    normalized = normalize_capability(capability_payload)
                    preflight['normalized_import_metadata'] = normalized
                    if normalized.get('source_kind'):
                        preflight['capability']['source_kind'] = normalized['source_kind']
                    if normalized.get('worker_entry'):
                        preflight['capability']['worker_entry'] = normalized['worker_entry']
                    if normalized.get('source_manifest'):
                        preflight['capability']['source_manifest'] = normalized['source_manifest']
                    if normalized.get('source_path'):
                        preflight['capability']['source_path'] = normalized['source_path']
                    if not normalized.get('supported', True):
                        reason = normalized.get('unsupported_reason') or 'unknown'
                        preflight['errors'].append(f'loom imported skill subset unsupported: {reason}')
                if not capability_payload.get('enabled', False):
                    preflight['errors'].append('loom capability is disabled')
                if capability_payload.get('verification_status') not in {'verified', 'builtin'}:
                    preflight['errors'].append(
                        f"loom capability verification={capability_payload.get('verification_status', '')}"
                    )
                if capability_payload.get('promotion_state') not in {'promoted', 'builtin'}:
                    preflight['errors'].append(
                        f"loom capability promotion={capability_payload.get('promotion_state', '')}"
                    )

    if preflight['errors']:
        preflight['ok'] = False
        return preflight

    if service_errors:
        preflight['warnings'] = service_errors
        preflight['execution_mode'] = 'direct_action_execute'
        preflight['service_warnings'] = list(service_errors)
        preflight['ok'] = True
        return preflight

    preflight['ok'] = not preflight['errors']
    return preflight


def _direct_execute_capability(
    context: LoomRuntimeContext,
    capability_name: str,
    payload: dict,
    timeout: int,
    *,
    agent_id: str,
    session_id: str = '',
    action_type: str = '',
    resource: str = '',
    estimated_cost_usd: float | None = None,
    runner: Runner = subprocess.run,
    result_loader: ResultLoader | None = None,
) -> dict:
    env = context.env()
    resolved_action_type = (action_type or '').strip() or 'execute'
    resolved_resource = (resource or '').strip() or capability_name
    resolved_estimated_cost_usd = (
        estimate_capability_cost_usd(
            capability_name,
            payload,
            action_type=resolved_action_type,
            resource=resolved_resource,
        )
        if estimated_cost_usd is None
        else max(float(estimated_cost_usd), 0.0)
    )
    cmd = [
        context.loom_bin,
        'action',
        'execute',
        '--root',
        context.loom_root,
        '--org-id',
        context.org_id,
        '--agent-id',
        agent_id.strip() or context.agent_id,
        '--capability',
        capability_name,
        '--action-type',
        resolved_action_type,
        '--resource',
        resolved_resource,
        '--estimated-cost-usd',
        format_estimated_cost_usd(resolved_estimated_cost_usd),
        '--payload-json',
        json.dumps(payload),
        '--format',
        'json',
    ]
    if session_id:
        cmd.extend(['--session-id', session_id])
    try:
        completed = runner(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=context.cwd,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'execution_mode': 'direct_action_execute',
            'error': f'Loom direct action execute timed out ({timeout}s limit)',
        }
    except Exception as exc:
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'execution_mode': 'direct_action_execute',
            'error': str(exc),
        }

    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or 'unknown error').strip()
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'execution_mode': 'direct_action_execute',
            'error': f'Loom direct action execute failed: {message[:500]}',
        }

    try:
        payload_json = json.loads((completed.stdout or '').strip())
    except json.JSONDecodeError:
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'execution_mode': 'direct_action_execute',
            'error': 'Loom direct action execute returned non-JSON output',
        }

    worker_result = {}
    worker_result_path = str(payload_json.get('worker_result_path') or '').strip()
    if worker_result_path and result_loader is not None:
        loaded = result_loader(worker_result_path, default={})
        worker_result = loaded or {}

    snapshot = {
        'job_status': 'completed' if payload_json.get('worker_status') == 'completed' else 'failed',
        'runtime_outcome': payload_json.get('runtime_outcome') or '',
        'worker_status': payload_json.get('worker_status') or '',
        'execution_mode': 'direct_action_execute',
        'estimated_cost_usd': resolved_estimated_cost_usd,
    }
    worker_status = str(payload_json.get('worker_status') or '').strip().lower()
    ok = worker_status == 'completed'
    return {
        'ok': ok,
        'runtime': 'loom',
        'capability_name': capability_name,
        'job_id': str(payload_json.get('job_id') or '').strip(),
        'submit': payload_json,
        'snapshot': snapshot,
        'worker_result': worker_result,
        'execution_mode': 'direct_action_execute',
        'estimated_cost_usd': resolved_estimated_cost_usd,
        'error': '' if ok else f"Loom direct action execute ended with worker_status={worker_status or 'unknown'}",
    }


def run_capability(
    context: LoomRuntimeContext,
    capability_name: str,
    payload: dict,
    timeout: int,
    *,
    agent_id: str | None = None,
    session_id: str = '',
    action_type: str = '',
    resource: str = '',
    estimated_cost_usd: float | None = None,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
    result_loader: ResultLoader | None = None,
) -> dict:
    if not capability_name:
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': '',
            'error': 'Loom runtime selected but capability is not configured',
        }

    env = context.env()
    resolved_action_type = (action_type or '').strip()
    resolved_resource = (resource or '').strip()
    resolved_estimated_cost_usd = (
        estimate_capability_cost_usd(
            capability_name,
            payload,
            action_type=resolved_action_type,
            resource=resolved_resource,
        )
        if estimated_cost_usd is None
        else max(float(estimated_cost_usd), 0.0)
    )
    submit_cmd = [
        context.loom_bin,
        'service',
        'submit',
        '--root',
        context.loom_root,
        '--org-id',
        context.org_id,
        '--agent-id',
        (agent_id or context.agent_id).strip(),
        '--capability',
        capability_name,
        '--estimated-cost-usd',
        format_estimated_cost_usd(resolved_estimated_cost_usd),
        '--payload-json',
        json.dumps(payload),
    ]
    if resolved_action_type:
        submit_cmd.extend(['--action-type', resolved_action_type])
    if resolved_resource:
        submit_cmd.extend(['--resource', resolved_resource])
    if session_id:
        submit_cmd.extend(['--session-id', session_id])
    if context.service_token:
        submit_cmd.extend(['--service-token', context.service_token])
    submit_cmd.extend(['--format', 'json'])

    try:
        submit = runner(
            submit_cmd,
            capture_output=True,
            text=True,
            timeout=min(timeout, 30),
            cwd=context.cwd,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return _direct_execute_capability(
            context,
            capability_name,
            payload,
            timeout,
            agent_id=(agent_id or context.agent_id).strip(),
            session_id=session_id,
            action_type=resolved_action_type,
            resource=resolved_resource,
            estimated_cost_usd=resolved_estimated_cost_usd,
            runner=runner,
            result_loader=result_loader,
        )
    except Exception as exc:
        direct = _direct_execute_capability(
            context,
            capability_name,
            payload,
            timeout,
            agent_id=(agent_id or context.agent_id).strip(),
            session_id=session_id,
            action_type=resolved_action_type,
            resource=resolved_resource,
            estimated_cost_usd=resolved_estimated_cost_usd,
            runner=runner,
            result_loader=result_loader,
        )
        if direct.get('ok'):
            direct['warnings'] = [str(exc)]
            return direct
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'error': str(exc),
        }

    if submit.returncode != 0:
        direct = _direct_execute_capability(
            context,
            capability_name,
            payload,
            timeout,
            agent_id=(agent_id or context.agent_id).strip(),
            session_id=session_id,
            action_type=resolved_action_type,
            resource=resolved_resource,
            estimated_cost_usd=resolved_estimated_cost_usd,
            runner=runner,
            result_loader=result_loader,
        )
        if direct.get('ok'):
            message = (submit.stderr or submit.stdout or 'unknown error').strip()
            direct['warnings'] = [f'Loom service submit failed: {message[:500]}']
            return direct
        message = (submit.stderr or submit.stdout or 'unknown error').strip()
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'error': f'Loom service submit failed: {message[:500]}',
        }

    try:
        submit_payload = json.loads((submit.stdout or '').strip())
    except json.JSONDecodeError:
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'error': 'Loom service submit returned non-JSON output',
        }

    job_id = (submit_payload.get('job_id') or '').strip()
    if not job_id:
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'error': 'Loom service submit did not return a job_id',
            'submit': submit_payload,
        }

    inspect_cmd = [
        context.loom_bin,
        'job',
        'inspect',
        '--root',
        context.loom_root,
        '--job-id',
        job_id,
        '--format',
        'json',
    ]
    deadline = time.time() + timeout
    last_snapshot = None
    while time.time() < deadline:
        try:
            inspect = runner(
                inspect_cmd,
                capture_output=True,
                text=True,
                timeout=15,
                cwd=context.cwd,
                env=env,
            )
        except subprocess.TimeoutExpired:
            inspect = None
        if inspect and inspect.returncode == 0:
            try:
                last_snapshot = json.loads((inspect.stdout or '').strip())
            except json.JSONDecodeError:
                last_snapshot = None
            if isinstance(last_snapshot, dict):
                status = (last_snapshot.get('job_status') or '').strip().lower()
                if status == 'completed':
                    result_path = os.path.join(context.loom_root, 'state', 'runtime', 'jobs', job_id, 'result.json')
                    worker_result = {}
                    if result_loader is not None:
                        loaded = result_loader(result_path, default={})
                        worker_result = loaded or {}
                    return {
                        'ok': True,
                        'runtime': 'loom',
                        'capability_name': capability_name,
                        'job_id': job_id,
                        'submit': submit_payload,
                        'snapshot': last_snapshot,
                        'worker_result': worker_result,
                        'estimated_cost_usd': resolved_estimated_cost_usd,
                    }
                if status in {'failed', 'denied', 'cancelled', 'hard_deny'}:
                    return {
                        'ok': False,
                        'runtime': 'loom',
                        'capability_name': capability_name,
                        'job_id': job_id,
                        'submit': submit_payload,
                        'snapshot': last_snapshot,
                        'estimated_cost_usd': resolved_estimated_cost_usd,
                        'error': f'Loom job ended with status={status}',
                    }
        sleeper(1)

    job_record = _load_job_record(context, job_id)
    job_status = str(job_record.get('job_status') or '').strip().lower()
    if job_status in {'failed', 'denied', 'cancelled', 'hard_deny'}:
        note = str(job_record.get('budget_reservation_reason') or job_record.get('note') or '').strip()
        message = f'Loom job ended with status={job_status}'
        if note:
            message = f'{message}: {note}'
        return {
            'ok': False,
            'runtime': 'loom',
            'capability_name': capability_name,
            'job_id': job_id,
            'submit': submit_payload,
            'snapshot': last_snapshot or job_record,
            'estimated_cost_usd': resolved_estimated_cost_usd,
            'error': message,
        }

    direct = _direct_execute_capability(
        context,
        capability_name,
        payload,
        timeout,
        agent_id=(agent_id or context.agent_id).strip(),
        session_id=session_id,
        action_type=resolved_action_type,
        resource=resolved_resource,
        estimated_cost_usd=resolved_estimated_cost_usd,
        runner=runner,
        result_loader=result_loader,
    )
    if direct.get('ok'):
        direct['warnings'] = [f'Loom job timed out ({timeout}s limit)']
        direct['submit_fallback'] = submit_payload
        return direct
    return {
        'ok': False,
        'runtime': 'loom',
        'capability_name': capability_name,
        'job_id': job_id,
        'submit': submit_payload,
        'snapshot': last_snapshot or job_record,
        'error': f'Loom job timed out ({timeout}s limit)',
    }
