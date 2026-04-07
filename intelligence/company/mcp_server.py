#!/usr/bin/env python3
"""
Meridian MCP Server — x402-capable intelligence tools.

Three tools:
  1. intelligence/latest-brief     — $0.50  — Today's intelligence brief
  2. intelligence/on-demand-research — $2.00 — On-demand research on any topic
  3. intelligence/qa-verify         — $1.00  — QA verification of any text

Payment: USDC on Base L2 via x402-capable settlement.

Run:
  python3 mcp_server.py                    # MCP stdio mode (default)
  python3 mcp_server.py --http 18900       # HTTP mode on port 18900
  python3 mcp_server.py --free             # Free mode (no payment required, for testing)

Institution scope:
  This server is bound to the founding Meridian institution (slug='meridian').
  All audit, metering, and revenue recording attaches to DEFAULT_ORG_ID, which
  is resolved once at startup from organizations.json.  There is no per-session
  or per-request org routing.  Revenue writes flow through the live
  economy/revenue.py service layer, which resolves through the founding
  institution's capsule aliases.  This x402 settlement flow is a deployment
  integration path, not an OSS substrate primitive.

  Multi-institution MCP support requires an org-scoped auth model that does
  not yet exist.  Until then, this server serves exactly one institution.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import datetime
import fcntl
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote_plus

from mcp.server.fastmcp import FastMCP
from brief_quality import analyze_brief

# ── Configuration ────────────────────────────────────────────────────────────

MCP_SERVER_FILE = os.path.abspath(__file__)
COMPANY_DIR = os.path.dirname(MCP_SERVER_FILE)
WORKSPACE = os.path.dirname(COMPANY_DIR)
MERIDIAN_HOME = os.path.dirname(WORKSPACE)
NIGHT_SHIFT_DIR = os.path.join(WORKSPACE, 'night-shift')
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')
PLATFORM_DIR = os.path.join(COMPANY_DIR, 'meridian_platform')
WALLET_FILE = os.path.join(MERIDIAN_HOME, 'credentials', 'base_wallet.json')
MCP_SETTLEMENT_LOG = os.path.join(COMPANY_DIR, 'mcp_settlements.jsonl')
MCP_SETTLEMENT_LOCK = os.path.join(COMPANY_DIR, '.mcp_settlement.lock')
RESEARCH_CACHE_FILE = os.path.join(MERIDIAN_HOME, 'state', 'mcp', 'research_cache.json')
RESEARCH_CACHE_TTL_SECONDS = int(os.environ.get('MERIDIAN_RESEARCH_CACHE_TTL_SECONDS', '900'))

# Platform integration — audit, metering, authority, treasury
sys.path.insert(0, PLATFORM_DIR)
import brain_router
try:
    from audit import log_event as audit_log
    from metering import record as meter_record
    PLATFORM_ENABLED = True
except ImportError:
    PLATFORM_ENABLED = False

try:
    from organizations import load_orgs, get_org
    from constitutional_model import constitutional_model
    from institution_context import InstitutionContext, MCP_SERVICE_BOUNDARY
    from capsule import ensure_payment_monitor_aliases
    from capsule import payment_events_log_path as capsule_payment_events_log_path
    ORG_CONTEXT_ENABLED = True
except ImportError:
    ORG_CONTEXT_ENABLED = False

# Constitutional OS primitives
try:
    from authority import check_authority as _authority_check, is_kill_switch_engaged as _kill_switch_check
    from treasury import check_budget as _treasury_check_budget
    CONSTITUTIONAL_ENABLED = True
except ImportError:
    CONSTITUTIONAL_ENABLED = False

from loom_runtime_discovery import preferred_loom_bin as _shared_preferred_loom_bin
from loom_runtime_discovery import preferred_loom_root as _shared_preferred_loom_root
from loom_runtime_discovery import runtime_value as _shared_runtime_value
from loom_runtime_client import LoomRuntimeContext
from loom_runtime_client import capability_preflight as _shared_loom_capability_preflight
from loom_runtime_client import run_capability as _shared_run_loom_capability
from team_topology import load_runtime_env, load_team_topology, sync_loom_team_profiles

# Founding institution binding — resolved once at startup.
# All audit, metering, treasury, and revenue calls use this org_id.
# There is no per-session or per-request org routing.
MCP_ORG_ID = (os.environ.get('MERIDIAN_MCP_ORG_ID') or '').strip() or None
DEFAULT_ORG_ID = None
try:
    if ORG_CONTEXT_ENABLED:
        from organizations import load_orgs
        _orgs = load_orgs()
        for _oid, _org in _orgs.get('organizations', {}).items():
            if _org.get('slug') == 'meridian':
                DEFAULT_ORG_ID = _oid
                break
except Exception:
    pass

# USDC on Base L2
BASE_NETWORK = 'eip155:8453'
USDC_ASSET = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913'
USDC_DECIMALS = 6

# Pricing (in USDC, smallest unit = 1e-6)
PRICES = {
    'latest-brief': 0.50,
    'on-demand-research': 2.00,
    'qa-verify': 1.00,
    'weekly-digest': 1.50,
    'competitor-snapshot': 3.00,
}

SUPPORTED_LOOM_IMPORT_RUNTIME_LANE = 'python_host_process/imported_workspace_skill'
SUPPORTED_LOOM_IMPORT_WORKER_KIND = 'python'
SUPPORTED_LOOM_IMPORT_PAYLOAD_MODE = 'json'
SUPPORTED_LOOM_IMPORT_ADAPTER_KIND = 'url_report_v0'
SUPPORTED_LOOM_IMPORT_DEPENDENCY_MODE = 'workspace_host_python'
SUPPORTED_LOOM_IMPORT_PROVENANCE = 'clawfamily_skill_contract_v0/workspace_python_entrypoint'

_LOOM_SKILL_MANIFEST_RE = re.compile(r'(?P<root>.*/skills/(?P<skill_slug>[^/]+)/SKILL\.md)$')
_LOOM_SKILL_PATH_RE = re.compile(r'(?P<root>.*/skills/(?P<skill_slug>[^/]+))$')
_LOOM_IMPORTED_WORKER_ENTRY_RE = re.compile(r'^workers/python/imported-(?P<import_token>[^/]+)\.py$')

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s')
logger = logging.getLogger('meridian.mcp')
TEAM_RUNTIME_ENV = load_runtime_env()
TEAM_TOPOLOGY = load_team_topology()


def _research_cache_key(topic: str, depth: str, agent_id: str, capability_name: str = '') -> str:
    raw = json.dumps(
        {
            'topic': str(topic or '').strip().lower(),
            'depth': str(depth or '').strip().lower(),
            'agent_id': str(agent_id or '').strip().lower(),
            'capability_name': str(capability_name or '').strip().lower(),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _load_research_cache() -> dict[str, dict]:
    if not os.path.exists(RESEARCH_CACHE_FILE):
        return {}
    try:
        with open(RESEARCH_CACHE_FILE, encoding='utf-8') as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get('entries', payload)
    return entries if isinstance(entries, dict) else {}


def _save_research_cache(entries: dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(RESEARCH_CACHE_FILE), exist_ok=True)
    payload = {
        'updated_at': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'entries': entries,
    }
    tmp_path = f'{RESEARCH_CACHE_FILE}.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    os.replace(tmp_path, RESEARCH_CACHE_FILE)


def _research_cache_get(topic: str, depth: str, agent_id: str, capability_name: str = '') -> dict | None:
    cache_key = _research_cache_key(topic, depth, agent_id, capability_name)
    entries = _load_research_cache()
    record = entries.get(cache_key)
    if not isinstance(record, dict):
        return None
    expires_at = float(record.get('expires_at_unix') or 0.0)
    if expires_at <= time.time():
        entries.pop(cache_key, None)
        _save_research_cache(entries)
        return None
    result = record.get('result')
    return dict(result) if isinstance(result, dict) else None


def _research_cache_put(topic: str, depth: str, agent_id: str, result: dict, capability_name: str = '') -> None:
    research_text = str((result or {}).get('research') or '').strip()
    if not research_text:
        return
    if str((result or {}).get('error') or '').strip():
        return
    cache_key = _research_cache_key(topic, depth, agent_id, capability_name)
    entries = _load_research_cache()
    entries[cache_key] = {
        'stored_at_unix': time.time(),
        'expires_at_unix': time.time() + max(60, RESEARCH_CACHE_TTL_SECONDS),
        'topic': str(topic or '').strip(),
        'depth': str(depth or '').strip(),
        'agent_id': str(agent_id or '').strip(),
        'capability_name': str(capability_name or '').strip(),
        'result': dict(result or {}),
    }
    _save_research_cache(entries)


def _team_specialist(agent_id: str):
    if not agent_id:
        return None
    return TEAM_TOPOLOGY.specialist_by_id(agent_id)


def _specialist_completion_url(agent_id: str) -> str:
    specialist = _team_specialist(agent_id)
    if specialist is None:
        return ''
    base_url = (specialist.base_url or '').strip()
    if base_url.endswith('/api/v1') or base_url.endswith('/v1'):
        return f"{base_url.rstrip('/')}/chat/completions"
    return base_url


def _specialist_direct_provider_fallback(
    agent_id: str,
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 900,
    timeout: int = 90,
) -> dict[str, Any]:
    specialist = _team_specialist(agent_id)
    if specialist is None:
        return {'ok': False, 'error': f'unknown specialist {agent_id}'}
    api_key = (TEAM_RUNTIME_ENV.get(specialist.api_key_env_var) or os.environ.get(specialist.api_key_env_var) or '').strip()
    url = _specialist_completion_url(agent_id)
    result = brain_router.execute_specialist_http(
        profile_name=specialist.profile_name,
        endpoint=url,
        model=specialist.model,
        api_key=api_key,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        timeout=timeout,
    )
    if not result.get('ok'):
        if not api_key:
            result.setdefault('error', f'missing API key env {specialist.api_key_env_var}')
        elif not url:
            result.setdefault('error', f'missing completion url for {agent_id}')
        return result
    result['note'] = f'direct provider fallback via {url}'
    return result


def _extract_json_object(text: str) -> dict | None:
    raw = (text or '').strip()
    if not raw:
        return None
    candidates = [raw]
    for opener, closer in (('{', '}'), ('[', ']')):
        first = raw.find(opener)
        last = raw.rfind(closer)
        if first != -1 and last != -1 and last > first:
            candidates.append(raw[first:last + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _specialist_llm_payload(agent_id: str, system_prompt: str, user_prompt: str, *, max_tokens: int = 900) -> dict | None:
    specialist = _team_specialist(agent_id)
    if specialist is None:
        return None
    return {
        'provider_profile': specialist.profile_name,
        'model': specialist.model,
        'system_prompt': system_prompt,
        'user_prompt': user_prompt,
        'max_tokens': max_tokens,
    }


def _specialist_llm_result(loom_result: dict, *, preferred_key: str) -> tuple[str, str]:
    worker_result = loom_result.get('worker_result') or {}
    host_response = worker_result.get('host_response_json') or {}
    output_text = str(host_response.get('output_text') or '').strip()
    payload = _extract_json_object(output_text) if output_text else None
    if isinstance(payload, dict):
        fallback_keys = [preferred_key, 'result']
        if preferred_key == 'result':
            fallback_keys.extend(['research', 'verification'])
        elif preferred_key == 'verification':
            fallback_keys.extend(['result', 'response'])
        seen = set()
        for key in fallback_keys:
            if key in seen:
                continue
            seen.add(key)
            value = str(payload.get(key) or '').strip()
            if value:
                return value, output_text
        results = payload.get('results')
        if isinstance(results, list):
            normalized = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                text = item.get('normalized_text')
                if isinstance(text, str) and text.strip():
                    normalized.append(text.strip())
            if normalized:
                return '\n\n'.join(normalized), output_text
    fallback_keys = [preferred_key]
    if preferred_key == 'result':
        fallback_keys.extend(['research', 'result'])
    elif preferred_key == 'verification':
        fallback_keys.extend(['verification', 'result'])
    fallback_keys.extend(['response', 'message', 'text', 'output_text'])
    deduped_keys: list[str] = []
    for key in fallback_keys:
        if key not in deduped_keys:
            deduped_keys.append(key)
    return output_text or _extract_loom_content(worker_result, tuple(deduped_keys)), output_text


def _specialist_llm_json(raw_output: str) -> dict[str, Any]:
    payload = _extract_json_object(raw_output or "")
    return payload if isinstance(payload, dict) else {}


def _specialist_host_response_note(loom_result: dict) -> str:
    worker_result = loom_result.get('worker_result') or {}
    host_response = worker_result.get('host_response_json') or {}
    if isinstance(host_response, dict):
        decision = str(host_response.get('decision') or '').strip().lower()
        note = str(host_response.get('note') or '').strip()
        if note and decision == 'denied':
            return f'LLM request denied: {note}'
        if note:
            return note
        if decision == 'denied':
            return 'LLM request denied by provider host'
    return ''


def _normalize_runtime(runtime: str) -> str:
    runtime = (runtime or '').strip().lower()
    return 'loom' if runtime in {'loom', ''} else 'legacy'


def _blocked_runtime_message(route_name: str, requested_runtime: str) -> str:
    runtime_label = (requested_runtime or 'unknown').strip() or 'unknown'
    return (
        f"Requested runtime '{runtime_label}' is not enabled on this host. "
        f"Meridian serves {route_name} through Loom-managed execution only."
    )


def _company_info_payload(context: dict, wallet_addr: str) -> dict:
    model = constitutional_model()
    return {
        'company': 'Meridian',
        'tagline': 'Governed Digital Labor on a Constitutional Kernel',
        'description': (
            'Meridian is a constitutional operating system for governed digital labor. '
            'On this host, Loom is the active execution runtime and competitor intelligence '
            'is the first commercial wedge. The kernel contributes five governance '
            'primitives, and the Meridian platform composes Commitment as the sixth '
            'platform primitive.'
        ),
        'constitutional_model': model,
        'commercial_wedge': {
            'name': 'Competitive Intelligence',
            'status': 'live',
            'current_offer': 'founder-led managed intelligence with governed MCP access',
        },
        'live_host_truth': {
            'primary_execution_runtime': 'Meridian Loom',
            'runtime_id': 'loom_native',
            'runtime_boundary': context.get('boundary_name', 'mcp_service'),
            'service_scope': context.get('service_scope', 'founding_meridian_service'),
            'institution_routing': 'founding_meridian_only',
            'public_mcp_endpoint': 'https://app.welliam.codes/sse',
            'public_mcp_transport': 'sse_bootstrap_plus_messages_session_channel',
            'payment_mode': 'x402_fail_closed_for_paid_tools',
        },
        'current_workflows': [
            'Competitive Intelligence — daily cited alerts, weekly briefs, battlecards (live)',
            'On-demand research — topic-driven sourced findings (live)',
            'QA verification — factual accuracy and claim checking (live)',
        ],
        'primitives': {
            'Institution': 'Charter-governed organizations with lifecycle management and policy defaults',
            'Agent': 'First-class managed entities with identity, scopes, budget, risk state, and economy participation',
            'Authority': 'Approval queues, delegations, and kill switch — who can act and when',
            'Treasury': 'Real-money accounting — balance, runway, reserve floor, spend tracking',
            'Court': 'Violation records, sanctions, and appeals — constitutional enforcement',
            'Commitment': 'Capsule-backed obligations, lifecycle transitions, and federation delivery references',
        },
        'platform_capabilities': [
            'Kernel: five governance primitives; platform: six with Commitment',
            'Agent registry with identity, scopes, budget, risk state, and lifecycle',
            'Organization-scoped resources with charter and policy defaults',
            'Audit logging for every significant action',
            'Usage metering per org and per agent',
            'Authority approval queues and kill switch',
            'Court system with violations, sanctions, and appeals',
        ],
        'tools': {
            'intelligence_latest_brief': {
                'price': '$0.50 USDC',
                'description': 'Daily competitor intelligence alert with cited findings',
            },
            'intelligence_on_demand_research': {
                'price': '$2.00 USDC',
                'description': 'On-demand competitive research on any company or topic',
            },
            'intelligence_competitor_snapshot': {
                'price': '$3.00 USDC',
                'description': 'Battlecard-ready competitor snapshot: recent moves, pricing, product, talking points',
            },
            'intelligence_qa_verify': {
                'price': '$1.00 USDC',
                'description': 'QA verification of competitive claims or intelligence text',
            },
            'intelligence_weekly_digest': {
                'price': '$1.50 USDC',
                'description': 'Weekly competitive digest: top developments across tracked competitors',
            },
            'company_info': {
                'price': 'FREE',
                'description': 'Meridian capabilities, runtime truth, and pricing',
            },
        },
        'payment': {
            'protocol': 'x402',
            'chain': 'Base L2',
            'asset': 'USDC',
            'wallet': wallet_addr,
        },
        'institution_scope': context,
        'sources_monitored': '30+ including provider blogs, changelogs, pricing pages, tech aggregators',
        'pipeline': '7-agent nightly pipeline with multi-stage QA verification',
    }


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _intelligence_exec_runtime(tool: str | None = None) -> str:
    if tool:
        scoped = os.environ.get(f'MERIDIAN_INTELLIGENCE_{tool.upper()}_RUNTIME')
        if scoped:
            return _normalize_runtime(scoped)
    return _normalize_runtime(os.environ.get('MERIDIAN_INTELLIGENCE_EXEC_RUNTIME') or 'loom')


def _intelligence_route_runtime(route: str, tool: str | None = None) -> str:
    scoped = os.environ.get(f'MERIDIAN_INTELLIGENCE_{route.upper()}_RUNTIME')
    if scoped:
        return _normalize_runtime(scoped)
    return _intelligence_exec_runtime(tool)


def _intelligence_route_fallback(route: str, default: bool = False) -> bool:
    return _env_truthy(f'MERIDIAN_INTELLIGENCE_{route.upper()}_ALLOW_FALLBACK', default=default)


def _loom_bin() -> str:
    return _shared_preferred_loom_bin(os.environ)


def _loom_root() -> str:
    return _shared_preferred_loom_root(os.environ)


def _loom_agent_id() -> str:
    return (os.environ.get('MERIDIAN_LOOM_AGENT_ID') or 'leviathann').strip()


def _loom_org_id() -> str:
    for key in ('MERIDIAN_LOOM_ORG_ID', 'MERIDIAN_MCP_ORG_ID', 'MERIDIAN_WORKSPACE_ORG_ID'):
        value = (os.environ.get(key) or '').strip()
        if value:
            return value
    if MCP_ORG_ID:
        return MCP_ORG_ID
    if DEFAULT_ORG_ID:
        return DEFAULT_ORG_ID
    return 'org_48b05c21'


def _loom_service_token() -> str:
    return (
        os.environ.get('MERIDIAN_LOOM_SERVICE_TOKEN')
        or os.environ.get('LOOM_SERVICE_TOKEN')
        or ''
    ).strip()


@functools.lru_cache(maxsize=1)
def _loom_capability_inventory() -> tuple[dict, ...]:
    command = [
        _loom_bin(),
        'capability',
        'list',
        '--root',
        _loom_root(),
        '--limit',
        '200',
        '--format',
        'json',
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            cwd=WORKSPACE,
            env=os.environ,
            check=False,
        )
    except Exception:
        return tuple()
    if completed.returncode != 0:
        return tuple()
    try:
        payload = json.loads((completed.stdout or '').strip())
    except json.JSONDecodeError:
        return tuple()
    items = payload if isinstance(payload, list) else payload.get('capabilities', [])
    return tuple(item for item in items if isinstance(item, dict))


def _discover_loom_capability(*candidates: str) -> str:
    inventory = _loom_capability_inventory()
    names = {str(item.get('name') or '').strip() for item in inventory}
    for candidate in candidates:
        name = (candidate or '').strip()
        if name and name in names:
            return name
    return ''


def _loom_research_capability() -> str:
    configured = (os.environ.get('MERIDIAN_LOOM_RESEARCH_CAPABILITY') or '').strip()
    if configured:
        return configured
    return _discover_loom_capability('clawskill.safe-web-research.v0')


def _loom_qa_capability() -> str:
    configured = (os.environ.get('MERIDIAN_LOOM_QA_CAPABILITY') or '').strip()
    if configured:
        return configured
    return 'loom.llm.inference.v1'


def _loom_runtime_context() -> LoomRuntimeContext:
    sync_loom_team_profiles(TEAM_TOPOLOGY, loom_root=_loom_root())
    return LoomRuntimeContext(
        loom_bin=_loom_bin(),
        loom_root=_loom_root(),
        org_id=_loom_org_id(),
        agent_id=_loom_agent_id(),
        service_token=_loom_service_token(),
        cwd=WORKSPACE,
        runtime_env=os.environ,
    )


def _load_json_file(path: str, default=None):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _legacy_response_content(stdout: str):
    try:
        response = json.loads(stdout)
        return response.get('response', response.get('message', stdout))
    except json.JSONDecodeError:
        return stdout


def _legacy_agent_bin() -> str | None:
    configured = (os.environ.get('MERIDIAN_LEGACY_AGENT_BIN') or '').strip()
    if configured:
        return configured
    for candidate in ('legacy-agent', 'legacy_v1_agent', 'legacy-v1-agent'):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return 'legacy-agent'


def _run_legacy_agent(agent: str, prompt: str, timeout: int) -> dict:
    legacy_bin = _legacy_agent_bin()
    if not legacy_bin:
        return {
            'ok': False,
            'runtime': 'legacy',
            'agent': agent,
            'error': 'Legacy agent binary is not configured',
        }
    try:
        result = subprocess.run(
            [legacy_bin, 'agent', '--agent', agent, '--message', prompt, '--json'],
            capture_output=True, text=True, timeout=timeout, cwd=WORKSPACE
        )
        if result.returncode != 0:
            return {
                'ok': False,
                'runtime': 'legacy',
                'agent': agent,
                'error': f'Legacy agent returned error: {result.stderr[:500]}',
            }
        return {
            'ok': True,
            'runtime': 'legacy',
            'agent': agent,
            'content': _legacy_response_content(result.stdout),
        }
    except subprocess.TimeoutExpired:
        return {
            'ok': False,
            'runtime': 'legacy',
            'agent': agent,
            'error': f'Legacy agent timed out ({timeout}s limit)',
        }
    except Exception as exc:
        return {
            'ok': False,
            'runtime': 'legacy',
            'agent': agent,
            'error': str(exc),
        }


def _extract_loom_content(worker_result: dict, preferred_keys: tuple[str, ...]) -> str:
    payload = worker_result.get('skill_output')
    if isinstance(payload, dict):
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        for key in ('research', 'verification', 'result'):
            if key in preferred_keys:
                continue
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        results = payload.get('results')
        if isinstance(results, list):
            normalized = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                text = item.get('normalized_text')
                if isinstance(text, str) and text.strip():
                    normalized.append(text.strip())
            if normalized:
                return '\n\n'.join(normalized)
    host_response = worker_result.get('host_response_json')
    if isinstance(host_response, dict):
        for key in preferred_keys:
            value = host_response.get(key)
            if isinstance(value, str) and value.strip():
                return value
    if isinstance(host_response, dict):
        output_text = host_response.get('output_text')
        if isinstance(output_text, str) and output_text.strip():
            return output_text
    summary = worker_result.get('summary')
    if isinstance(summary, str) and summary.strip():
        return summary
    return json.dumps(payload if payload is not None else worker_result)


def _looks_like_http_url(value: str) -> bool:
    raw = (value or '').strip().lower()
    return raw.startswith('http://') or raw.startswith('https://')


def _placeholder_citation_in_text(text: str) -> bool:
    lowered = str(text or '').strip().lower()
    return 'example.com' in lowered or 'placeholder citation' in lowered or 'placeholder source' in lowered


def _loom_research_url(topic: str) -> str:
    topic = (topic or '').strip()
    if _looks_like_http_url(topic):
        return topic
    if not topic:
        return ''
    return f'https://duckduckgo.com/html/?q={quote_plus(topic)}'


def _loom_research_payload(topic: str, depth: str, prompt: str) -> dict:
    payload = {'topic': topic, 'depth': depth, 'prompt': prompt}
    loom_url = _loom_research_url(topic)
    if loom_url:
        payload['url'] = loom_url
        payload['urls'] = [loom_url]
    return payload


def _normalize_loom_skill_slug(value: str) -> str:
    value = (value or '').strip().lower().replace('_', '-')
    value = re.sub(r'[^a-z0-9-]+', '-', value)
    return re.sub(r'-{2,}', '-', value).strip('-')


def _normalize_import_source_kind(value: str) -> str:
    source_kind = (value or '').strip()
    if source_kind.startswith('legacy_v1_'):
        source_kind = source_kind[len('legacy_v1_'):]
    legacy_map = {
        'legacy_workspace_skill': 'loom_workspace_skill_import',
        'workspace_skill': 'loom_workspace_skill_import',
        'legacy_plugin_skill': 'loom_plugin_skill_import',
        'plugin_skill': 'loom_plugin_skill_import',
        'legacy_plugin_packaged_skill': 'loom_plugin_packaged_skill_import',
        'plugin_packaged_skill': 'loom_plugin_packaged_skill_import',
    }
    return legacy_map.get(source_kind, source_kind)


def _normalize_loom_import_metadata(capability_payload: dict) -> dict:
    payload = dict(capability_payload or {})
    source_manifest = (payload.get('source_manifest') or '').strip()
    source_path = (payload.get('source_path') or '').strip()
    worker_entry = (payload.get('worker_entry') or '').strip()
    worker_kind = (payload.get('worker_kind') or '').strip().lower()
    runtime_lane = (payload.get('runtime_lane') or '').strip()
    payload_mode = (payload.get('payload_mode') or '').strip().lower()
    adapter_kind = (payload.get('adapter_kind') or '').strip()
    dependency_mode = (payload.get('dependency_mode') or '').strip()
    import_provenance = (payload.get('import_provenance') or '').strip()
    source_kind = _normalize_import_source_kind(payload.get('source_kind') or '')
    env_contract = (payload.get('env_contract') or '').strip()
    capability_name = (payload.get('name') or '').strip()

    unsupported_reasons = []
    skill_slug = ''
    import_token = ''

    manifest_match = _LOOM_SKILL_MANIFEST_RE.match(source_manifest)
    if manifest_match:
        skill_slug = _normalize_loom_skill_slug(manifest_match.group('skill_slug'))
    elif source_manifest:
        unsupported_reasons.append('source_manifest must end in /skills/<skill>/SKILL.md')

    path_match = _LOOM_SKILL_PATH_RE.match(source_path)
    if path_match:
        path_slug = _normalize_loom_skill_slug(path_match.group('skill_slug'))
        if skill_slug and path_slug != skill_slug:
            unsupported_reasons.append(
                f'source_path skill slug {path_slug} does not match source_manifest skill slug {skill_slug}'
            )
        skill_slug = skill_slug or path_slug
    elif source_path:
        unsupported_reasons.append('source_path must end in /skills/<skill>')

    worker_match = _LOOM_IMPORTED_WORKER_ENTRY_RE.match(worker_entry)
    if worker_match and not import_token:
        import_token = _normalize_loom_skill_slug(worker_match.group('import_token'))
        derived_skill_slug = import_token
        if derived_skill_slug.startswith('clawskill-'):
            derived_skill_slug = derived_skill_slug[len('clawskill-'):]
        if derived_skill_slug.endswith('-v0'):
            derived_skill_slug = derived_skill_slug[:-3]
        skill_slug = skill_slug or _normalize_loom_skill_slug(derived_skill_slug)

    normalized_source_path = source_path or (source_manifest.rsplit('/SKILL.md', 1)[0] if source_manifest else '')
    normalized_source_manifest = source_manifest or (f'{normalized_source_path}/SKILL.md' if normalized_source_path else '')
    if capability_name:
        import_token = _normalize_loom_skill_slug(capability_name.replace('.', '-'))
    elif not import_token and skill_slug:
        import_token = f'clawskill-{skill_slug}-v0'
    normalized_worker_entry = f'workers/python/imported-{import_token}.py' if import_token else worker_entry

    if not skill_slug:
        unsupported_reasons.append('could not derive a skill slug from import metadata')
    if worker_kind and worker_kind != SUPPORTED_LOOM_IMPORT_WORKER_KIND:
        unsupported_reasons.append(f'worker_kind={worker_kind}')
    if runtime_lane and runtime_lane != SUPPORTED_LOOM_IMPORT_RUNTIME_LANE:
        unsupported_reasons.append(f'runtime_lane={runtime_lane}')
    if payload_mode and payload_mode != SUPPORTED_LOOM_IMPORT_PAYLOAD_MODE:
        unsupported_reasons.append(f'payload_mode={payload_mode}')
    if adapter_kind and adapter_kind != SUPPORTED_LOOM_IMPORT_ADAPTER_KIND:
        unsupported_reasons.append(f'adapter_kind={adapter_kind}')
    if dependency_mode and dependency_mode != SUPPORTED_LOOM_IMPORT_DEPENDENCY_MODE:
        unsupported_reasons.append(f'dependency_mode={dependency_mode}')
    if import_provenance and import_provenance != SUPPORTED_LOOM_IMPORT_PROVENANCE:
        unsupported_reasons.append(f'import_provenance={import_provenance}')
    if normalized_worker_entry and worker_entry and worker_entry != normalized_worker_entry:
        unsupported_reasons.append(f'worker_entry={worker_entry}')
    supported_source_kinds = {
        'loom_workspace_skill',
        'loom_plugin_skill',
        'loom_plugin_packaged_skill',
        'loom_workspace_skill_import',
        'loom_plugin_skill_import',
        'loom_plugin_packaged_skill_import',
    }
    if source_kind and source_kind not in supported_source_kinds:
        if '_' in source_kind:
            suffix = source_kind.split('_', 1)[1]
            normalized_candidate = _normalize_import_source_kind(suffix)
            if normalized_candidate in supported_source_kinds:
                source_kind = normalized_candidate
    if source_kind and source_kind not in supported_source_kinds:
        unsupported_reasons.append(f'source_kind={source_kind}')

    supported = not unsupported_reasons
    return {
        'subset': 'loom_plugin_skill_subset',
        'supported': supported,
        'unsupported_reasons': unsupported_reasons,
        'unsupported_reason': '; '.join(unsupported_reasons) if unsupported_reasons else '',
        'skill_slug': skill_slug,
        'capability_name': capability_name,
        'import_token': import_token,
        'source_kind': source_kind,
        'source_manifest': normalized_source_manifest,
        'source_path': normalized_source_path,
        'worker_kind': worker_kind or SUPPORTED_LOOM_IMPORT_WORKER_KIND,
        'worker_entry': normalized_worker_entry,
        'runtime_lane': runtime_lane,
        'isolation_lane': runtime_lane,
        'payload_mode': payload_mode or SUPPORTED_LOOM_IMPORT_PAYLOAD_MODE,
        'adapter_kind': adapter_kind,
        'dependency_mode': dependency_mode,
        'env_contract': env_contract,
        'import_provenance': import_provenance,
    }


def _on_demand_research_prompt(topic: str, depth: str = 'standard') -> str:
    depth_map = {'quick': 3, 'standard': 5, 'deep': 7}
    n_findings = depth_map.get(depth, 5)
    return (
        f"Research the following topic and provide {n_findings} sourced findings. "
        f"Be specific and cite sources. Topic: {topic}"
    )


def _loom_capability_preflight(capability_name: str, *, route: str) -> dict:
    return _shared_loom_capability_preflight(
        _loom_runtime_context(),
        capability_name,
        route=route,
        runner=subprocess.run,
        normalize_capability=_normalize_loom_import_metadata,
    )


def _loom_research_preflight(capability_name: str) -> dict:
    return _loom_capability_preflight(capability_name, route='intelligence_on_demand_research')


def _loom_qa_preflight(capability_name: str) -> dict:
    if capability_name == 'loom.llm.inference.v1':
        return _shared_loom_capability_preflight(
            _loom_runtime_context(),
            capability_name,
            route='intelligence_qa_verify',
            runner=subprocess.run,
            normalize_capability=None,
        )
    return _loom_capability_preflight(capability_name, route='intelligence_qa_verify')

def _route_cutover_state(
    route_name: str,
    requested_runtime: str,
    selected_runtime: str,
    fallback_enabled: bool,
    *,
    fallback_state: dict | None = None,
    loom_result: dict | None = None,
    loom_preflight: dict | None = None,
) -> dict:
    state = {
        'route': route_name,
        'requested_runtime': requested_runtime,
        'selected_runtime': selected_runtime,
        'fallback_enabled': fallback_enabled,
    }
    if fallback_state:
        state['fallback'] = fallback_state
    if isinstance(loom_preflight, dict):
        state['loom_preflight'] = loom_preflight
    transcript_bits = [
        f'route={route_name}',
        f'requested={requested_runtime}',
        f'selected={selected_runtime}',
        f"fallback={'on' if fallback_enabled else 'off'}",
    ]
    if isinstance(loom_preflight, dict):
        transcript_bits.append(f"preflight={'ok' if loom_preflight.get('ok') else 'blocked'}")
        capability_name = (loom_preflight.get('capability_name') or '').strip()
        if capability_name:
            transcript_bits.append(f'capability={capability_name}')
    if isinstance(fallback_state, dict):
        fallback_used = fallback_state.get('used')
        if fallback_used is not None:
            transcript_bits.append(f"fallback_used={'true' if fallback_used else 'false'}")
        fallback_state_name = (fallback_state.get('state') or '').strip()
        if fallback_state_name:
            transcript_bits.append(f"fallback_state={fallback_state_name}")
        fallback_reason = (fallback_state.get('reason') or '').strip()
        if fallback_reason:
            transcript_bits.append(f'fallback_reason={fallback_reason}')
    if isinstance(loom_result, dict):
        job_id = (loom_result.get('job_id') or '').strip()
        if job_id:
            transcript_bits.append(f'job_id={job_id}')
        submit = loom_result.get('submit')
        if isinstance(submit, dict):
            transport = (submit.get('transport') or '').strip()
            if transport:
                transcript_bits.append(f'transport={transport}')
        snapshot = loom_result.get('snapshot')
        if isinstance(snapshot, dict):
            job_status = (snapshot.get('job_status') or '').strip()
            worker_status = (snapshot.get('worker_status') or '').strip()
            if job_status:
                transcript_bits.append(f'job_status={job_status}')
            if worker_status:
                transcript_bits.append(f'worker_status={worker_status}')
    state['transcript'] = ' | '.join(transcript_bits)
    if not isinstance(loom_result, dict):
        return state
    loom_meta = {}
    capability_name = (loom_result.get('capability_name') or '').strip()
    job_id = (loom_result.get('job_id') or '').strip()
    if capability_name:
        loom_meta['capability_name'] = capability_name
    if job_id:
        loom_meta['job_id'] = job_id
    submit = loom_result.get('submit')
    if isinstance(submit, dict):
        for key in ('transport', 'service_target', 'queue_path', 'ingress_request_path', 'ingress_receipt_path', 'policy_class'):
            value = submit.get(key)
            if value:
                loom_meta[key] = value
    snapshot = loom_result.get('snapshot')
    if isinstance(snapshot, dict):
        for key in ('job_status', 'job_stage', 'runtime_outcome', 'worker_status', 'job_path', 'event_path', 'audit_log_path', 'parity_report_path'):
            value = snapshot.get(key)
            if value:
                loom_meta[key] = value
        job_path = snapshot.get('job_path')
        if isinstance(job_path, str) and job_path.strip():
            loom_meta['result_path_hint'] = os.path.join(os.path.dirname(job_path), 'result.json')
    if loom_meta:
        state['loom'] = loom_meta
    return state


def _on_demand_research_cutover_state(
    requested_runtime: str,
    selected_runtime: str,
    fallback_enabled: bool,
    *,
    fallback_state: dict | None = None,
    loom_result: dict | None = None,
    loom_preflight: dict | None = None,
) -> dict:
    return _route_cutover_state(
        'intelligence_on_demand_research',
        requested_runtime,
        selected_runtime,
        fallback_enabled,
        fallback_state=fallback_state,
        loom_result=loom_result,
        loom_preflight=loom_preflight,
    )


def _qa_verify_cutover_state(
    requested_runtime: str,
    selected_runtime: str,
    fallback_enabled: bool,
    *,
    fallback_state: dict | None = None,
    loom_result: dict | None = None,
    loom_preflight: dict | None = None,
) -> dict:
    return _route_cutover_state(
        'intelligence_qa_verify',
        requested_runtime,
        selected_runtime,
        fallback_enabled,
        fallback_state=fallback_state,
        loom_result=loom_result,
        loom_preflight=loom_preflight,
    )


def _with_on_demand_research_cutover(
    result: dict,
    requested_runtime: str,
    selected_runtime: str,
    fallback_enabled: bool,
    *,
    fallback_state: dict | None = None,
    loom_result: dict | None = None,
    loom_preflight: dict | None = None,
) -> dict:
    enriched = dict(result)
    enriched['route_cutover'] = _on_demand_research_cutover_state(
        requested_runtime,
        selected_runtime,
        fallback_enabled,
        fallback_state=fallback_state,
        loom_result=loom_result,
        loom_preflight=loom_preflight,
    )
    return enriched


def _with_qa_verify_cutover(
    result: dict,
    requested_runtime: str,
    selected_runtime: str,
    fallback_enabled: bool,
    *,
    fallback_state: dict | None = None,
    loom_result: dict | None = None,
    loom_preflight: dict | None = None,
) -> dict:
    enriched = dict(result)
    enriched['route_cutover'] = _qa_verify_cutover_state(
        requested_runtime,
        selected_runtime,
        fallback_enabled,
        fallback_state=fallback_state,
        loom_result=loom_result,
        loom_preflight=loom_preflight,
    )
    return enriched

def _extract_loom_research_content(worker_result: dict) -> str:
    payload = worker_result.get('skill_output')
    if isinstance(payload, dict):
        for key in ('research', 'response', 'message', 'text'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        results = payload.get('results')
        if isinstance(results, list):
            normalized = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                text = item.get('normalized_text')
                if isinstance(text, str) and text.strip():
                    normalized.append(text.strip())
            if normalized:
                return '\n\n'.join(normalized)
    summary = worker_result.get('summary')
    if isinstance(summary, str) and summary.strip():
        return summary
    return json.dumps(payload if payload is not None else worker_result)


def _run_loom_capability(
    capability_name: str,
    payload: dict,
    timeout: int,
    *,
    agent_id: str = '',
    session_id: str = '',
    action_type: str = '',
    resource: str = '',
) -> dict:
    return _shared_run_loom_capability(
        _loom_runtime_context(),
        capability_name,
        payload,
        timeout,
        agent_id=agent_id or None,
        session_id=session_id,
        action_type=action_type,
        resource=resource,
        runner=subprocess.run,
        sleeper=time.sleep,
        result_loader=_load_json_file,
    )


def _resolve_mcp_context():
    """Return the single institution context this live MCP service may use."""
    if not ORG_CONTEXT_ENABLED:
        raise RuntimeError('Institution context primitives unavailable for live MCP service')
    if not DEFAULT_ORG_ID:
        raise RuntimeError('Founding Meridian institution could not be resolved for MCP service')
    if MCP_ORG_ID:
        if MCP_ORG_ID != DEFAULT_ORG_ID:
            raise RuntimeError(
                f"Live MCP only supports founding org '{DEFAULT_ORG_ID}', got '{MCP_ORG_ID}'"
            )
        source = 'configured_org'
    else:
        source = 'founding_default'
    org = get_org(DEFAULT_ORG_ID)
    if not org:
        raise RuntimeError(f"Founding Meridian institution not found: {DEFAULT_ORG_ID}")
    ctx = InstitutionContext.bind(DEFAULT_ORG_ID, org, source, MCP_SERVICE_BOUNDARY)
    return {
        **ctx.to_dict(),
        'org_id': ctx.org_id,
        'source': ctx.context_source,
        'service_scope': 'founding_meridian_service',
        'supports_institution_routing': False,
    }


def _payment_events_log_path():
    if ORG_CONTEXT_ENABLED:
        ensure_payment_monitor_aliases()
        return capsule_payment_events_log_path()
    return os.path.join(COMPANY_DIR, 'payment_events.log')


@contextlib.contextmanager
def settlement_lock():
    os.makedirs(COMPANY_DIR, exist_ok=True)
    with open(MCP_SETTLEMENT_LOCK, 'a+') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_wallet_address() -> str:
    """Load wallet address from credentials."""
    if os.path.exists(WALLET_FILE):
        with open(WALLET_FILE) as f:
            return json.load(f)['address']
    raise RuntimeError(f'Wallet not found at {WALLET_FILE}. Run: python3 company/wallet.py generate')


def usd_to_amount(usd: float) -> str:
    """Convert USD amount to USDC smallest unit string."""
    return str(int(usd * (10 ** USDC_DECIMALS)))


def append_mcp_settlement_event(event: str, tool_name: str, product: str,
                                amount_usd: float, payment_ref: str,
                                details: dict | None = None):
    context = _resolve_mcp_context()
    entry = {
        'ts': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
        'event': event,
        'tool_name': tool_name,
        'product': product,
        'amount_usd': float(amount_usd),
        'payment_ref': payment_ref,
        'org_id': context.get('org_id'),
        'context_source': context.get('source'),
        'service_scope': context.get('service_scope'),
    }
    if details:
        entry['details'] = details
    with settlement_lock():
        with open(MCP_SETTLEMENT_LOG, 'a') as f:
            f.write(json.dumps(entry) + '\n')


def load_mcp_settlement_events() -> list[dict]:
    if not os.path.exists(MCP_SETTLEMENT_LOG):
        return []
    events = []
    with settlement_lock():
        with open(MCP_SETTLEMENT_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return events


def pending_mcp_settlements(events: list[dict] | None = None) -> list[dict]:
    events = events if events is not None else load_mcp_settlement_events()
    pending: dict[str, dict] = {}
    for entry in events:
        payment_ref = entry.get('payment_ref')
        if not payment_ref:
            continue
        if entry.get('event') == 'settled':
            pending[payment_ref] = {
                'payment_ref': payment_ref,
                'tool_name': entry.get('tool_name', ''),
                'product': entry.get('product', ''),
                'amount_usd': float(entry.get('amount_usd', 0.0)),
            }
            continue
        if entry.get('event') in {'recorded', 'duplicate'}:
            pending.pop(payment_ref, None)
    return list(pending.values())


def recover_pending_mcp_settlements(record_fn=None, events: list[dict] | None = None) -> list[dict]:
    record_fn = record_fn or record_revenue
    results = []
    for settlement in pending_mcp_settlements(events):
        result = record_fn(
            settlement['product'],
            settlement['amount_usd'],
            payment_ref=settlement['payment_ref'],
            tool_name=settlement['tool_name'],
        )
        results.append({'payment_ref': settlement['payment_ref'], **result})
    return results


def record_revenue(product: str, amount_usd: float, payment_ref: str = '', tool_name: str = ''):
    """Record founding-service revenue via the live revenue layer.

    This is deployment-specific settlement handling for the founding Meridian
    service.  It is intentionally not a generic OSS substrate contract.
    """
    if not payment_ref:
        logger.warning(f'record_revenue called without payment_ref for {product} — skipping (settlement not captured)')
        return {'status': 'missing_ref', 'product': product}

    try:
        context = _resolve_mcp_context()
        # Direct import instead of subprocess
        sys.path.insert(0, ECONOMY_DIR)
        now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        from revenue import record_external_customer_payment

        client_id = payment_ref[:8] if payment_ref else 'mcp-anon'
        result = record_external_customer_payment(
            product,
            amount_usd,
            payment_key=f'ref:{payment_ref}',
            client_name=f'mcp:{client_id}',
            client_contact=f'x402:{payment_ref}',
            note=f'x402 MCP payment ref:{payment_ref}',
            payment_ref=payment_ref,
            payment_source='mcp_x402',
        )

        # Persist to payment events log
        log_path = _payment_events_log_path()
        with open(log_path, 'a') as f:
            event = 'DUPLICATE' if result['duplicate'] else 'REVENUE'
            f.write(
                f"{now} {event} ${amount_usd:.2f} product={product} order={result['order_id']} ref={payment_ref}\n"
            )

        if result['duplicate']:
            append_mcp_settlement_event(
                'duplicate',
                tool_name or product,
                product,
                amount_usd,
                payment_ref,
                details={'order_id': result['order_id']},
            )
            logger.warning(f'Duplicate payment_ref {payment_ref} for {product} — skipping')
            return {'status': 'duplicate', 'order_id': result['order_id'], 'product': product}

        append_mcp_settlement_event(
            'recorded',
            tool_name or product,
            product,
            amount_usd,
            payment_ref,
            details={'order_id': result['order_id']},
        )
        logger.info(f'Revenue recorded: ${amount_usd} for {product} (order {result["order_id"]})')

        # Founding-institution metadata tagging (append-only observability).
        # These calls tag audit/metering records with the founding org_id.
        # This is NOT per-request org routing — the server is single-tenant.
        if PLATFORM_ENABLED and DEFAULT_ORG_ID:
            audit_log(context['org_id'], 'system', 'revenue_recorded',
                      resource=product, outcome='success',
                      details={
                          'amount_usd': amount_usd,
                          'order_id': result['order_id'],
                          'payment_ref': payment_ref,
                          'service_scope': context['service_scope'],
                          'context_source': context['source'],
                      })
            meter_record(context['org_id'], '', 'payment_received',
                         quantity=1, unit='transactions', cost_usd=amount_usd,
                         details={'service_scope': context['service_scope']})
        return {'status': 'recorded', 'order_id': result['order_id'], 'product': product}

    except Exception as e:
        logger.error(f'Failed to record revenue: {e}')
        append_mcp_settlement_event(
            'failed',
            tool_name or product,
            product,
            amount_usd,
            payment_ref,
            details={'error': str(e)},
        )
        # Fallback: at least log the event
        try:
            log_path = _payment_events_log_path()
            with open(log_path, 'a') as f:
                f.write(f"{datetime.datetime.utcnow().isoformat()}Z FAILED ${amount_usd:.2f} product={product} error={e}\n")
        except Exception:
            pass
        return {'status': 'failed', 'error': str(e), 'product': product}


def _audit_tool_call(tool_name: str, price_usd: float, outcome: str = 'success',
                     agent_id: str = '', details: dict = None):
    """Log audit event and meter record for an MCP tool call.
    Also checks authority and treasury if constitutional primitives are available."""
    context = _resolve_mcp_context()
    # Constitutional checks for paid tools
    if CONSTITUTIONAL_ENABLED and price_usd > 0:
        if _kill_switch_check():
            raise RuntimeError('Kill switch engaged — all paid operations halted')
        if agent_id:
            allowed, reason = _treasury_check_budget(agent_id, price_usd, org_id=context['org_id'])
            if not allowed:
                raise RuntimeError(f'Treasury check failed: {reason}')

    if not PLATFORM_ENABLED or not context['org_id']:
        return
    # Founding-institution metadata tagging (append-only observability).
    audit_log(context['org_id'], agent_id or 'mcp_client', 'mcp_tool_call',
              resource=tool_name, outcome=outcome, actor_type='user',
              details={**(details or {}), 'service_scope': context['service_scope'],
                       'context_source': context['source']})
    meter_record(context['org_id'], agent_id, 'mcp_tool_call',
                 quantity=1, unit='calls', cost_usd=price_usd,
                 details={'tool': tool_name, 'service_scope': context['service_scope']})


# ── Tool implementations ─────────────────────────────────────────────────────

def get_latest_brief(topic_filter: str = '') -> dict:
    """Fetch today's (or most recent) intelligence brief."""
    today = datetime.date.today().isoformat()
    brief_path = os.path.join(NIGHT_SHIFT_DIR, f'brief-{today}.md')

    # If today's brief doesn't exist, find most recent
    if not os.path.exists(brief_path):
        briefs = sorted(glob.glob(os.path.join(NIGHT_SHIFT_DIR, 'brief-*.md')))
        if not briefs:
            return {'error': 'No briefs available', 'date': today}
        brief_path = briefs[-1]

    with open(brief_path) as f:
        content = f.read()
    full_content = content

    date = os.path.basename(brief_path).replace('brief-', '').replace('.md', '')
    audit = analyze_brief(brief_path)

    # Apply topic filter if provided
    if topic_filter:
        lines = full_content.split('\n')
        filtered = [l for l in lines if topic_filter.lower() in l.lower()]
        if filtered:
            content = '\n'.join(filtered)
        else:
            content = full_content
    else:
        content = full_content

    # Also get findings if available
    findings_path = os.path.join(NIGHT_SHIFT_DIR, f'findings-{date}.md')
    findings = ''
    if os.path.exists(findings_path):
        with open(findings_path) as f:
            findings = f.read()

    return {
        'date': date,
        'brief': content,
        'findings': findings[:2000] if findings else None,
        'source': 'Meridian Night-Shift Pipeline',
        'qa_status': 'PASS' if audit['passed'] else 'FAIL',
        'quality_audit': audit,
    }


def get_weekly_digest() -> dict:
    """Return top findings from the past 7 days."""
    findings = []
    today = datetime.date.today()
    for i in range(7):
        d = today - datetime.timedelta(days=i)
        f_path = os.path.join(NIGHT_SHIFT_DIR, f'findings-{d.isoformat()}.md')
        if os.path.exists(f_path):
            with open(f_path) as fh:
                findings.append({'date': d.isoformat(), 'content': fh.read()[:600]})
    period_start = (today - datetime.timedelta(days=6)).isoformat()
    return {
        'period': f'{period_start} to {today.isoformat()}',
        'count': len(findings),
        'findings': findings[:5],
        'source': 'Meridian Night-Shift Pipeline',
        'qa_status': 'ARTIFACT_DERIVED_NOT_REVALIDATED',
    }


def _run_legacy_on_demand_research(topic: str, depth: str, prompt: str) -> dict:
    result = _run_legacy_agent('atlas', prompt, timeout=120)
    if result.get('ok'):
        return {
            'topic': topic,
            'depth': depth,
            'research': result.get('content', ''),
            'agent': 'Atlas',
            'runtime': 'legacy',
            'source': 'Meridian Research Pipeline',
        }
    return {
        'topic': topic,
        'depth': depth,
        'runtime': 'legacy',
        'error': result.get('error', 'Legacy runtime failed'),
    }


def _run_loom_on_demand_research(
    topic: str,
    depth: str,
    prompt: str,
    *,
    agent_id: str = 'agent_atlas',
    session_id: str = '',
    timeout: int = 150,
) -> tuple[dict, dict]:
    max_tokens = 700 if str(depth or '').strip().lower() == 'quick' else 1200
    capability_name = _loom_research_capability() or 'loom.llm.inference.v1'
    specialist_payload = _specialist_llm_payload(
        agent_id,
        (
            f"You are Meridian specialist {agent_id}. Perform research and analysis for depth={depth}. "
            "Return strict JSON with keys result, confidence, citations, warnings. "
            "Never invent citations, URLs, document names, or sources. "
            "If verifiable evidence is unavailable in the current execution context, say so explicitly and leave citations empty."
        ),
        prompt,
        max_tokens=max_tokens,
    )
    use_specialist_payload = capability_name == 'loom.llm.inference.v1'
    loom_result = _run_loom_capability(
        capability_name,
        specialist_payload if use_specialist_payload and specialist_payload else _loom_research_payload(topic, depth, prompt),
        timeout=timeout,
        agent_id=agent_id,
        session_id=session_id,
        action_type='research',
        resource=session_id or '',
    )
    if loom_result.get('ok'):
        worker_result = loom_result.get('worker_result') or {}
        raw_output = ''
        parsed = {}
        if use_specialist_payload and specialist_payload:
            research_text, raw_output = _specialist_llm_result(loom_result, preferred_key='result')
            parsed = _specialist_llm_json(raw_output)
            host_response = worker_result.get('host_response_json') if isinstance(worker_result, dict) else {}
            if not research_text and isinstance(host_response, dict):
                research_text = str(host_response.get('note') or host_response.get('decision') or '').strip()
        else:
            research_text = _extract_loom_research_content(worker_result)
        warnings = parsed.get('warnings', []) if isinstance(parsed.get('warnings'), list) else []
        if _placeholder_citation_in_text(research_text) or _placeholder_citation_in_text(raw_output):
            research_text = ''
            warnings = [*warnings, 'placeholder citations detected in research output; discarded']
        return ({
            'topic': topic,
            'depth': depth,
            'research': research_text,
            'runtime': 'loom',
            'capability_name': loom_result.get('capability_name', capability_name),
            'job_id': loom_result.get('job_id', ''),
            'source': 'Meridian Research Pipeline',
            'provider_profile': (specialist_payload or {}).get('provider_profile', ''),
            'model': (specialist_payload or {}).get('model', ''),
            'confidence': parsed.get('confidence', ''),
            'citations': parsed.get('citations', []) if isinstance(parsed.get('citations'), list) else [],
            'warnings': warnings,
            'raw_output': raw_output,
        }, loom_result)
    return ({
        'topic': topic,
        'depth': depth,
        'runtime': 'loom',
        'capability_name': loom_result.get('capability_name', capability_name),
        'job_id': loom_result.get('job_id', ''),
        'error': loom_result.get('error', 'Loom runtime failed'),
    }, loom_result)


def do_on_demand_research(
    topic: str,
    depth: str = 'standard',
    *,
    agent_id: str = 'agent_atlas',
    session_id: str = '',
    timeout: int = 150,
) -> dict:
    """Run research through the configured runtime adapter."""
    prompt = _on_demand_research_prompt(topic, depth)
    requested_runtime = _intelligence_exec_runtime('research')
    if requested_runtime == 'loom':
        result, _ = _run_loom_on_demand_research(
            topic,
            depth,
            prompt,
            agent_id=agent_id,
            session_id=session_id,
            timeout=timeout,
        )
        return result
    return {
        'topic': topic,
        'depth': depth,
        'runtime': 'blocked',
        'error': _blocked_runtime_message('intelligence_on_demand_research', requested_runtime),
    }


def do_on_demand_research_route(
    topic: str,
    depth: str = 'standard',
    *,
    agent_id: str = 'agent_atlas',
    session_id: str = '',
    timeout: int = 150,
) -> dict:
    """Run the paid on-demand research route with route-specific cutover controls."""
    requested_runtime = _intelligence_route_runtime('on_demand_research', tool='research')
    prompt = _on_demand_research_prompt(topic, depth)

    if requested_runtime != 'loom':
        blocked_message = _blocked_runtime_message('intelligence_on_demand_research', requested_runtime)
        fallback_state = {
            'used': False,
            'from_runtime': requested_runtime,
            'reason': blocked_message,
            'state': 'blocked_non_loom_runtime',
        }
        result = {
            'topic': topic,
            'depth': depth,
            'runtime': 'blocked',
            'error': blocked_message,
        }
        return _with_on_demand_research_cutover(
            result,
            requested_runtime,
            'blocked',
            False,
            fallback_state=fallback_state,
        )

    capability_name = _loom_research_capability() or 'loom.llm.inference.v1'
    cached = _research_cache_get(topic, depth, agent_id, capability_name)
    if cached is not None:
        cached_result = dict(cached)
        cached_result['cache_state'] = 'hit'
        cached_result.setdefault('runtime', 'loom')
        return _with_on_demand_research_cutover(
            cached_result,
            requested_runtime,
            'loom',
            False,
        )

    loom_preflight = _loom_research_preflight(capability_name)
    if not loom_preflight.get('ok'):
        fallback_state = {
            'used': False,
            'from_runtime': 'loom',
            'reason': '; '.join(loom_preflight.get('errors') or ['loom preflight failed']),
            'state': 'preflight_failed',
        }
        result = {
            'topic': topic,
            'depth': depth,
            'runtime': 'loom',
            'capability_name': capability_name,
            'error': f"Loom research preflight failed: {fallback_state['reason']}",
        }
        return _with_on_demand_research_cutover(
            result,
            requested_runtime,
            'loom',
            False,
            fallback_state=fallback_state,
            loom_preflight=loom_preflight,
        )

    result, loom_result = _run_loom_on_demand_research(
        topic,
        depth,
        prompt,
        agent_id=agent_id,
        session_id=session_id,
        timeout=timeout,
    )
    if not result.get('error'):
        _research_cache_put(topic, depth, agent_id, result, capability_name)
        return _with_on_demand_research_cutover(
            result,
            requested_runtime,
            'loom',
            False,
            loom_result=loom_result,
            loom_preflight=loom_preflight,
        )

    fallback_state = {
        'used': False,
        'from_runtime': 'loom',
        'reason': result.get('error', 'loom runtime failed'),
        'state': 'loom_failed',
    }
    return _with_on_demand_research_cutover(
        result,
        requested_runtime,
        'loom',
        False,
        fallback_state=fallback_state,
        loom_result=loom_result,
        loom_preflight=loom_preflight,
    )

def do_qa_verify(
    text: str,
    criteria: str = 'factual',
    *,
    agent_id: str = 'agent_aegis',
    session_id: str = '',
) -> dict:
    """Run QA verification through the configured runtime adapter."""
    prompt = (
        f"Verify the following text for {criteria} quality. "
        f"Return PASS or FAIL with specific reasons and confidence score (0-100). "
        f"Text to verify:\n\n{text[:3000]}"
    )

    requested_runtime = _intelligence_exec_runtime('qa')
    if requested_runtime == 'loom':
        capability_name = _loom_qa_capability()
        specialist_payload = _specialist_llm_payload(
            agent_id,
            f'You are Meridian specialist {agent_id}. Verify claims for {criteria} quality and return strict JSON with keys verification, confidence, warnings.',
            prompt,
        )
        use_specialist_payload = capability_name == 'loom.llm.inference.v1'
        loom_payload = specialist_payload if use_specialist_payload and specialist_payload else {'text': text, 'criteria': criteria, 'prompt': prompt}
        loom_result = _run_loom_capability(
            capability_name,
            loom_payload,
            timeout=90,
            agent_id=agent_id,
            session_id=session_id,
            action_type='verify',
            resource=session_id or '',
        )
        if loom_result.get('ok'):
            if use_specialist_payload and specialist_payload:
                verification, raw_output = _specialist_llm_result(loom_result, preferred_key='verification')
            else:
                verification = _extract_loom_content(loom_result.get('worker_result') or {}, ('verification', 'result', 'response', 'message', 'text', 'output_text'))
                raw_output = ''
            return {
                'criteria': criteria,
                'verification': verification,
                'runtime': 'loom',
                'capability_name': loom_result.get('capability_name', capability_name),
                'job_id': loom_result.get('job_id', ''),
                'source': 'Meridian QA Pipeline',
                'provider_profile': (specialist_payload or {}).get('provider_profile', ''),
                'model': (specialist_payload or {}).get('model', ''),
                'raw_output': raw_output,
            }
        return {
            'criteria': criteria,
            'runtime': 'loom',
            'capability_name': loom_result.get('capability_name', ''),
            'job_id': loom_result.get('job_id', ''),
            'error': loom_result.get('error', 'Loom runtime failed'),
        }
    return {
        'criteria': criteria,
        'runtime': 'blocked',
        'error': _blocked_runtime_message('intelligence_qa_verify', requested_runtime),
    }


def do_qa_verify_route(
    text: str,
    criteria: str = 'factual',
    *,
    agent_id: str = 'agent_aegis',
    session_id: str = '',
    timeout: int = 90,
) -> dict:
    """Run QA verification with truthful route preflight and cutover state."""
    requested_runtime = _intelligence_route_runtime('qa_verify', tool='qa')
    fallback_enabled = _intelligence_route_fallback('qa_verify', default=False)
    capability_name = _loom_qa_capability()
    prompt = (
        f"Verify the following text for {criteria} quality. "
        f"Return PASS or FAIL with specific reasons and confidence score (0-100). "
        f"Text to verify:\n\n{text[:3000]}"
    )
    specialist_payload = _specialist_llm_payload(
        agent_id,
        f'You are Meridian specialist {agent_id}. Verify claims for {criteria} quality and return strict JSON with keys verification, confidence, warnings.',
        prompt,
    )
    use_specialist_payload = capability_name == 'loom.llm.inference.v1'

    def _direct_fallback_result(reason: str, *, loom_job_id: str = '') -> dict | None:
        if not specialist_payload or not use_specialist_payload:
            return None
        direct = _specialist_direct_provider_fallback(
            agent_id,
            system_prompt=f'You are Meridian specialist {agent_id}. Verify claims for {criteria} quality and return strict JSON with keys verification, confidence, warnings.',
            user_prompt=prompt,
            max_tokens=900,
            timeout=timeout,
        )
        if not direct.get('ok'):
            return None
        raw_output = str(direct.get('output_text') or '').strip()
        parsed = _specialist_llm_json(raw_output)
        verification = str(parsed.get('verification') or parsed.get('result') or raw_output).strip()
        if not verification:
            verification = 'Verification lane returned no usable answer.'
        warnings = parsed.get('warnings', []) if isinstance(parsed.get('warnings'), list) else []
        warnings = [*warnings, reason]
        return {
            'criteria': criteria,
            'verification': verification,
            'runtime': 'loom',
            'capability_name': _loom_qa_capability(),
            'job_id': loom_job_id,
            'source': 'Meridian QA Pipeline',
            'provider_profile': (specialist_payload or {}).get('provider_profile', ''),
            'model': (specialist_payload or {}).get('model', ''),
            'raw_output': raw_output,
            'confidence': str(parsed.get('confidence') or '').strip(),
            'warnings': warnings,
            'transport_kind': 'direct_provider_http_fallback',
        }

    if requested_runtime != 'loom':
        blocked_message = _blocked_runtime_message('intelligence_qa_verify', requested_runtime)
        fallback_state = {
            'used': False,
            'from_runtime': requested_runtime,
            'reason': blocked_message,
            'state': 'blocked_non_loom_runtime',
        }
        result = {
            'criteria': criteria,
            'runtime': 'blocked',
            'error': blocked_message,
        }
        return _with_qa_verify_cutover(result, requested_runtime, 'blocked', False, fallback_state=fallback_state)

    loom_preflight = _loom_qa_preflight(capability_name)
    if not loom_preflight.get('ok'):
        fallback_state = {
            'used': False,
            'from_runtime': 'loom',
            'reason': '; '.join(loom_preflight.get('errors') or ['loom preflight failed']),
            'state': 'preflight_failed',
        }
        result = {
            'criteria': criteria,
            'runtime': 'loom',
            'capability_name': capability_name,
            'error': f"Loom QA preflight failed: {fallback_state['reason']}",
        }
        return _with_qa_verify_cutover(
            result,
            requested_runtime,
            'loom',
            False,
            fallback_state=fallback_state,
            loom_preflight=loom_preflight,
        )

    if timeout <= 30:
        fallback = _direct_fallback_result(
            'Fast direct QA lane used for low-latency communication skill.',
        )
        if fallback is not None:
            return _with_qa_verify_cutover(
                fallback,
                requested_runtime,
                'loom',
                False,
                fallback_state={
                    'used': True,
                    'from_runtime': 'loom',
                    'reason': 'fast_direct_qa_lane',
                    'state': 'fast_direct_provider_first',
                },
                loom_preflight=loom_preflight,
            )

    loom_result = _run_loom_capability(
        capability_name,
        specialist_payload if use_specialist_payload and specialist_payload else {'text': text, 'criteria': criteria, 'prompt': prompt},
        timeout=timeout,
        agent_id=agent_id,
        session_id=session_id,
        action_type='verify',
        resource=session_id or '',
    )
    if loom_result.get('ok'):
        if use_specialist_payload and specialist_payload:
            verification, raw_output = _specialist_llm_result(loom_result, preferred_key='verification')
        else:
            verification = _extract_loom_content(loom_result.get('worker_result') or {}, ('verification', 'result', 'response', 'message', 'text', 'output_text'))
            raw_output = ''
        host_note = _specialist_host_response_note(loom_result)
        if (not verification or verification.lstrip().startswith('{"status":')) and host_note:
            fallback = _direct_fallback_result(
                f'loom qa lane returned unusable output: {host_note}',
                loom_job_id=str(loom_result.get('job_id') or ''),
            )
            if fallback is not None:
                return _with_qa_verify_cutover(
                    fallback,
                    requested_runtime,
                    'loom',
                    False,
                    loom_result=loom_result,
                    loom_preflight=loom_preflight,
                )
            verification = host_note
        result = {
            'criteria': criteria,
            'verification': verification,
            'runtime': 'loom',
            'capability_name': loom_result.get('capability_name', ''),
            'job_id': loom_result.get('job_id', ''),
            'source': 'Meridian QA Pipeline',
            'provider_profile': (specialist_payload or {}).get('provider_profile', ''),
            'model': (specialist_payload or {}).get('model', ''),
            'raw_output': raw_output,
            'warnings': [host_note] if host_note else [],
            'confidence': '',
            'transport_kind': 'loom_capability',
        }
        return _with_qa_verify_cutover(
            result,
            requested_runtime,
            'loom',
            False,
            loom_result=loom_result,
            loom_preflight=loom_preflight,
        )

    fallback_state = {
        'used': False,
        'from_runtime': 'loom',
        'reason': loom_result.get('error', 'loom runtime failed'),
        'state': 'loom_failed',
    }

    fallback = _direct_fallback_result(
        str(loom_result.get('error') or 'loom qa lane failed'),
        loom_job_id=str(loom_result.get('job_id') or ''),
    )
    if fallback is not None:
        return _with_qa_verify_cutover(
            fallback,
            requested_runtime,
            'loom',
            False,
            fallback_state=fallback_state,
            loom_result=loom_result,
            loom_preflight=loom_preflight,
        )

    result = {
        'criteria': criteria,
        'runtime': 'loom',
        'capability_name': loom_result.get('capability_name', ''),
        'job_id': loom_result.get('job_id', ''),
        'error': loom_result.get('error', 'Loom runtime failed'),
    }
    return _with_qa_verify_cutover(
        result,
        requested_runtime,
        'loom',
        False,
        fallback_state=fallback_state,
        loom_result=loom_result,
        loom_preflight=loom_preflight,
    )


# ── MCP Server Setup ─────────────────────────────────────────────────────────

def create_server(free_mode: bool = False) -> FastMCP:
    """Create the MCP server with optional x402 payment gating."""

    mcp = FastMCP("Meridian Intelligence")

    if not free_mode:
        try:
            wallet_address = load_wallet_address()
            from x402 import PaymentRequirements, ResourceInfo, x402ResourceServerSync
            from x402.http.facilitator_client import HTTPFacilitatorClientSync
            from x402.mcp.server import create_payment_wrapper, PaymentWrapperHooks

            # Create resource server WITH facilitator (fixes SchemeNotFoundError)
            facilitator = HTTPFacilitatorClientSync()  # default: https://x402.org/facilitator
            resource_server = x402ResourceServerSync(facilitator_clients=[facilitator])
            resource_server.initialize()  # fetch supported schemes from facilitator
            logger.info('x402 facilitator initialized (https://x402.org/facilitator)')

            recovered = recover_pending_mcp_settlements()
            if recovered:
                statuses = ', '.join(
                    f"{item['payment_ref']}:{item['status']}" for item in recovered
                )
                logger.warning(f'Recovered pending MCP settlements on startup: {statuses}')

            def _make_settlement_hook(tool_name: str, product: str, price_usd: float):
                def on_after_settlement(ctx):
                    tx = getattr(ctx, 'settlement', None)
                    if tx:
                        ref = getattr(tx, 'transaction', 'unknown')
                        append_mcp_settlement_event('settled', tool_name, product, price_usd, ref)
                        outcome = record_revenue(product, price_usd, payment_ref=ref, tool_name=tool_name)
                        logger.info(f'Payment settled for {tool_name}: tx={ref} status={outcome["status"]}')
                return on_after_settlement

            def make_requirements(tool_name: str, price_usd: float) -> list[PaymentRequirements]:
                return [PaymentRequirements(
                    scheme='exact',
                    network=BASE_NETWORK,
                    asset=USDC_ASSET,
                    amount=usd_to_amount(price_usd),
                    pay_to=wallet_address,
                    max_timeout_seconds=300,
                    extra={
                        'name': f'Meridian: {tool_name}',
                        'description': f'Intelligence tool: {tool_name}',
                    },
                )]

            # Paid Tool 1: Latest Brief
            brief_wrapper = create_payment_wrapper(
                resource_server,
                accepts=make_requirements('latest-brief', PRICES['latest-brief']),
                resource=ResourceInfo(
                    url='mcp://meridian/intelligence/latest-brief',
                    description='Get latest AI intelligence brief ($0.50)',
                    mime_type='application/json',
                ),
                hooks=PaymentWrapperHooks(
                    on_after_settlement=_make_settlement_hook(
                        'latest-brief',
                        'intelligence/latest-brief',
                        PRICES['latest-brief'],
                    )
                ),
            )

            @mcp.tool(name='intelligence_latest_brief',
                       description='Get the latest AI intelligence brief when the governed workflow is active. Price: $0.50 USDC on Base L2.')
            @brief_wrapper
            async def latest_brief(topic_filter: str = '') -> str:
                _audit_tool_call('latest-brief', PRICES['latest-brief'],
                                 agent_id='agent_quill', details={'topic_filter': topic_filter})
                result = get_latest_brief(topic_filter)
                return json.dumps(result)

            # Paid Tool 2: On-Demand Research
            research_wrapper = create_payment_wrapper(
                resource_server,
                accepts=make_requirements('on-demand-research', PRICES['on-demand-research']),
                resource=ResourceInfo(
                    url='mcp://meridian/intelligence/on-demand-research',
                    description='On-demand AI research on any topic ($2.00)',
                    mime_type='application/json',
                ),
                hooks=PaymentWrapperHooks(
                    on_after_settlement=_make_settlement_hook(
                        'on-demand-research',
                        'intelligence/on-demand-research',
                        PRICES['on-demand-research'],
                    )
                ),
            )

            @mcp.tool(name='intelligence_on_demand_research',
                       description='Research any topic with sourced findings. Delegated to Atlas. Live Loom cutover only for this route on this host. Depth: quick/standard/deep. Price: $2.00 USDC on Base L2.')
            @research_wrapper
            async def on_demand_research(topic: str, depth: str = 'standard') -> str:
                _audit_tool_call('on-demand-research', PRICES['on-demand-research'],
                                 agent_id='agent_atlas', details={'topic': topic, 'depth': depth})
                result = do_on_demand_research_route(topic, depth)
                return json.dumps(result)

            # Paid Tool 3: QA Verify
            qa_wrapper = create_payment_wrapper(
                resource_server,
                accepts=make_requirements('qa-verify', PRICES['qa-verify']),
                resource=ResourceInfo(
                    url='mcp://meridian/intelligence/qa-verify',
                    description='QA verification of any text ($1.00)',
                    mime_type='application/json',
                ),
                hooks=PaymentWrapperHooks(
                    on_after_settlement=_make_settlement_hook(
                        'qa-verify',
                        'intelligence/qa-verify',
                        PRICES['qa-verify'],
                    )
                ),
            )

            @mcp.tool(name='intelligence_qa_verify',
                       description='Verify text for factual accuracy, completeness, or readiness. Multi-agent QA pipeline. Price: $1.00 USDC on Base L2.')
            @qa_wrapper
            async def qa_verify(text: str, criteria: str = 'factual') -> str:
                _audit_tool_call('qa-verify', PRICES['qa-verify'],
                                 agent_id='agent_aegis', details={'criteria': criteria})
                result = do_qa_verify_route(text, criteria)
                return json.dumps(result)

            # Paid Tool 4: Weekly Digest
            weekly_wrapper = create_payment_wrapper(
                resource_server,
                accepts=make_requirements('weekly-digest', PRICES['weekly-digest']),
                resource=ResourceInfo(
                    url='mcp://meridian/intelligence/weekly-digest',
                    description='Top 5 AI developments this week ($1.50)',
                    mime_type='application/json',
                ),
                hooks=PaymentWrapperHooks(
                    on_after_settlement=_make_settlement_hook(
                        'weekly-digest',
                        'intelligence/weekly-digest',
                        PRICES['weekly-digest'],
                    )
                ),
            )

            @mcp.tool(name='intelligence_weekly_digest',
                       description='Top 5 AI/ML developments from the past 7 days, sourced and dated. Price: $1.50 USDC on Base L2.')
            @weekly_wrapper
            async def weekly_digest() -> str:
                _audit_tool_call('weekly-digest', PRICES['weekly-digest'],
                                 agent_id='agent_quill')
                result = get_weekly_digest()
                return json.dumps(result)

            # Paid Tool 5: Competitor Snapshot
            competitor_wrapper = create_payment_wrapper(
                resource_server,
                accepts=make_requirements('competitor-snapshot', PRICES['competitor-snapshot']),
                resource=ResourceInfo(
                    url='mcp://meridian/intelligence/competitor-snapshot',
                    description='Snapshot analysis of a specific AI company or product ($3.00)',
                    mime_type='application/json',
                ),
                hooks=PaymentWrapperHooks(
                    on_after_settlement=_make_settlement_hook(
                        'competitor-snapshot',
                        'intelligence/competitor-snapshot',
                        PRICES['competitor-snapshot'],
                    )
                ),
            )

            @mcp.tool(name='intelligence_competitor_snapshot',
                       description='Snapshot analysis of a specific AI company or product. Deep research pipeline. Price: $3.00 USDC on Base L2.')
            @competitor_wrapper
            async def competitor_snapshot(company: str) -> str:
                _audit_tool_call('competitor-snapshot', PRICES['competitor-snapshot'],
                                 agent_id='agent_atlas', details={'company': company})
                result = do_on_demand_research(
                    topic=f'Latest developments, products, and strategic moves of {company} in AI',
                    depth='deep'
                )
                result['type'] = 'competitor-snapshot'
                result['target'] = company
                return json.dumps(result)

            logger.info(f'x402 payment gating ENABLED. Wallet: {wallet_address}')

        except Exception as e:
            logger.error(f'x402 setup failed: {e}')
            raise RuntimeError(f'x402 payment gating failed to initialize: {e}') from e

    if free_mode:
        # Free mode — tools work without payment (for testing)
        @mcp.tool(name='intelligence_latest_brief',
                   description='[FREE/TEST] Get the latest AI intelligence brief.')
        async def latest_brief_free(topic_filter: str = '') -> str:
            return json.dumps(get_latest_brief(topic_filter))

        @mcp.tool(name='intelligence_on_demand_research',
                   description='[FREE/TEST] Research any topic with sourced findings.')
        async def on_demand_research_free(topic: str, depth: str = 'standard') -> str:
            return json.dumps(do_on_demand_research(topic, depth))

        @mcp.tool(name='intelligence_qa_verify',
                   description='[FREE/TEST] QA verification of any text.')
        async def qa_verify_free(text: str, criteria: str = 'factual') -> str:
            return json.dumps(do_qa_verify_route(text, criteria))

        @mcp.tool(name='intelligence_weekly_digest',
                   description='[FREE/TEST] Top 5 AI/ML developments from the past 7 days.')
        async def weekly_digest_free() -> str:
            return json.dumps(get_weekly_digest())

        @mcp.tool(name='intelligence_competitor_snapshot',
                   description='[FREE/TEST] Snapshot analysis of a specific AI company or product.')
        async def competitor_snapshot_free(company: str) -> str:
            result = do_on_demand_research(
                topic=f'Latest developments, products, and strategic moves of {company} in AI',
                depth='deep'
            )
            result['type'] = 'competitor-snapshot'
            result['target'] = company
            return json.dumps(result)

        logger.info('Running in FREE mode (no payment required)')

    # Info tool (always free)
    @mcp.tool(name='company_info',
               description='Get Meridian information, capabilities, and pricing.')
    async def company_info() -> str:
        wallet_addr = 'not configured'
        context = _resolve_mcp_context()
        try:
            wallet_addr = load_wallet_address()
        except Exception:
            pass

        return json.dumps(_company_info_payload(context, wallet_addr))

    return mcp


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Meridian MCP Server')
    parser.add_argument('--http', type=int, default=None, help='Run as HTTP server on this port')
    parser.add_argument('--free', action='store_true', help='Free mode (no payment required)')
    args = parser.parse_args()

    mcp = create_server(free_mode=args.free)
    context = _resolve_mcp_context()
    logger.info(f"Bound institution: {context['org_id']} via {context['source']} ({context['service_scope']})")

    if args.http:
        # HTTP/SSE transport
        mcp.settings.port = args.http
        mcp.settings.host = '127.0.0.1'
        logger.info(f'Starting MCP HTTP server on 127.0.0.1:{args.http}')
        mcp.run(transport='sse')
    else:
        # stdio transport (default for MCP)
        logger.info('Starting MCP server on stdio')
        mcp.run()


if __name__ == '__main__':
    main()
