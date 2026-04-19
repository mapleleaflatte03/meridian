#!/usr/bin/env python3
"""Institution-owned execution routing policy for Meridian brain execution."""

from __future__ import annotations

import copy
import datetime
import os
import re
from typing import Any

from capsule import capsule_path


POLICY_SCHEMA = 'meridian.institution_brain_policy.v1'
DEFAULT_FAILOVER_ERROR_CLASSES = [
    'auth',
    'billing',
    'rate_limit',
    'transport',
    'provider_unavailable',
]


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _slug(value: str) -> str:
    token = re.sub(r'[^a-z0-9]+', '-', str(value or '').strip().lower()).strip('-')
    return token or 'default'


def _derive_model_entry_id(provider_entry_id: str, model_name: str, model_entry_id: str = '') -> str:
    explicit = str(model_entry_id or '').strip()
    if explicit:
        return explicit
    return f"{provider_entry_id}.model.{_slug(model_name)}"


def policy_path(org_id: str) -> str:
    return capsule_path(org_id, 'institution_brain_policy.json')


def _default_provider_registry() -> dict[str, dict[str, Any]]:
    return {}


def _default_model_registry() -> dict[str, dict[str, Any]]:
    return {}


def _default_auth_profiles() -> dict[str, dict[str, Any]]:
    return {}


def unconfigured_policy(org_id: str, *, updated_by: str = 'system') -> dict[str, Any]:
    return {
        'schema': POLICY_SCHEMA,
        'institution_id': org_id,
        'primary_route_id': '',
        'routes': [],
        'provider_registry': _default_provider_registry(),
        'model_registry': _default_model_registry(),
        'auth_profiles': _default_auth_profiles(),
        'failover_policy': {
            'error_classes': list(DEFAULT_FAILOVER_ERROR_CLASSES),
            'within_route_retry_limit': 1,
            'allow_route_chain_fallback': True,
        },
        'updated_at': _utc_now(),
        'updated_by': updated_by,
    }


def build_cli_route(
    *,
    route_id: str,
    provider_entry_id: str,
    model_entry_id: str,
    model_name: str,
    auth_profile_order: list[str],
    fallback_route_ids: list[str] | None = None,
    cli_bin: str = '',
    cli_home: str = '',
    authority_approved: bool = True,
    treasury_allowed: bool = True,
    budget_band: str = 'standard',
) -> dict[str, Any]:
    return {
        'route_id': route_id,
        'route_type': 'cli_session',
        'provider_ref': provider_entry_id,
        'model_ref': model_entry_id,
        'provider_profile': provider_entry_id,
        'model': model_name,
        'auth_profile_order': list(auth_profile_order),
        'fallback_route_ids': list(fallback_route_ids or []),
        'approved_by_authority': authority_approved,
        'allowed_by_treasury': treasury_allowed,
        'budget_band': budget_band,
        'disabled': False,
        'disable_reason': '',
        'cooldown_until': '',
        'last_health': 'unknown',
        'last_health_reason': '',
        'last_failover': {},
        'cli_bin': cli_bin,
        'cli_home': cli_home,
        'endpoint': '',
        'auth_env': '',
        'key_env_pool': [],
        'failover_error_classes': list(DEFAULT_FAILOVER_ERROR_CLASSES),
    }


def build_http_route(
    *,
    route_id: str,
    provider_entry_id: str,
    model_entry_id: str,
    model_name: str,
    endpoint: str,
    auth_profile_order: list[str],
    fallback_route_ids: list[str] | None = None,
    auth_env: str = '',
    key_env_pool: list[str] | None = None,
    authority_approved: bool = True,
    treasury_allowed: bool = True,
    budget_band: str = 'standard',
) -> dict[str, Any]:
    return {
        'route_id': route_id,
        'route_type': 'http_json',
        'provider_ref': provider_entry_id,
        'model_ref': model_entry_id,
        'provider_profile': provider_entry_id,
        'model': model_name,
        'auth_profile_order': list(auth_profile_order),
        'fallback_route_ids': list(fallback_route_ids or []),
        'approved_by_authority': authority_approved,
        'allowed_by_treasury': treasury_allowed,
        'budget_band': budget_band,
        'disabled': False,
        'disable_reason': '',
        'cooldown_until': '',
        'last_health': 'unknown',
        'last_health_reason': '',
        'last_failover': {},
        'cli_bin': '',
        'cli_home': '',
        'endpoint': endpoint,
        'auth_env': auth_env,
        'key_env_pool': list(key_env_pool or []),
        'failover_error_classes': list(DEFAULT_FAILOVER_ERROR_CLASSES),
    }


def _ensure_route_registry_bindings(policy: dict[str, Any]) -> dict[str, Any]:
    provider_registry = dict(policy.get('provider_registry') or {})
    model_registry = dict(policy.get('model_registry') or {})
    routes: list[dict[str, Any]] = []

    for route in list(policy.get('routes') or []):
        current = dict(route)
        provider_ref = str(current.get('provider_ref') or current.get('provider_profile') or '').strip()
        model_name = str(current.get('model') or '').strip()
        model_ref = str(current.get('model_ref') or '').strip()

        if not provider_ref:
            provider_ref = f"provider.{_slug(current.get('route_id') or 'primary')}"

        provider_entry = dict(provider_registry.get(provider_ref) or {})
        if not provider_entry:
            provider_entry = {
                'provider_id': provider_ref,
                'display_name': provider_ref,
                'default_route_type': str(current.get('route_type') or '').strip() or 'cli_session',
                'capabilities': [str(current.get('route_type') or '').strip() or 'cli_session'],
                'metadata': {},
            }
        provider_entry['provider_id'] = provider_ref
        provider_registry[provider_ref] = provider_entry

        resolved_model_ref = _derive_model_entry_id(provider_ref, model_name, model_ref)
        model_entry = dict(model_registry.get(resolved_model_ref) or {})
        if not model_entry:
            model_entry = {
                'model_id': resolved_model_ref,
                'provider_id': provider_ref,
                'model_name': model_name,
                'metadata': {},
            }
        model_entry['model_id'] = resolved_model_ref
        model_entry['provider_id'] = provider_ref
        if model_name:
            model_entry['model_name'] = model_name
        model_registry[resolved_model_ref] = model_entry

        current['provider_ref'] = provider_ref
        current['model_ref'] = resolved_model_ref
        current['provider_profile'] = provider_ref
        current['model'] = str(model_entry.get('model_name') or model_name)
        routes.append(current)

    policy['provider_registry'] = provider_registry
    policy['model_registry'] = model_registry
    policy['routes'] = routes
    return policy


def load_policy(org_id: str) -> dict[str, Any]:
    path = policy_path(org_id)
    if not os.path.exists(path):
        return unconfigured_policy(org_id)
    import json

    with open(path, 'r', encoding='utf-8') as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return unconfigured_policy(org_id)

    merged = unconfigured_policy(org_id)
    merged.update(payload)
    merged['provider_registry'] = {
        **_default_provider_registry(),
        **(payload.get('provider_registry') or {}),
    }
    merged['model_registry'] = {
        **_default_model_registry(),
        **(payload.get('model_registry') or {}),
    }
    merged['auth_profiles'] = {
        **_default_auth_profiles(),
        **(payload.get('auth_profiles') or {}),
    }
    merged['routes'] = list(payload.get('routes') or [])
    merged['failover_policy'] = {
        **merged['failover_policy'],
        **(payload.get('failover_policy') or {}),
    }
    return _ensure_route_registry_bindings(merged)


def save_policy(org_id: str, policy: dict[str, Any]) -> dict[str, Any]:
    import json

    payload = unconfigured_policy(org_id)
    payload.update(copy.deepcopy(policy or {}))
    payload['institution_id'] = org_id
    payload['schema'] = POLICY_SCHEMA
    payload['updated_at'] = _utc_now()
    payload = _ensure_route_registry_bindings(payload)

    path = policy_path(org_id)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    return payload


def configure_policy(
    org_id: str,
    *,
    route_type: str,
    provider_profile: str,
    model: str,
    updated_by: str,
    cli_bin: str = '',
    cli_home: str = '',
    endpoint: str = '',
    auth_profile_name: str = '',
    auth_env: str = '',
    key_env_pool: list[str] | None = None,
    fallback_routes: list[dict[str, Any]] | None = None,
    provider_entry_id: str = '',
    model_entry_id: str = '',
) -> dict[str, Any]:
    provider_entry_id = str(provider_entry_id or provider_profile or '').strip()
    model_name = str(model or '').strip()
    if not provider_entry_id:
        raise ValueError('provider_entry_id is required')

    auth_profile_name = str(auth_profile_name or provider_entry_id).strip()
    resolved_model_entry_id = _derive_model_entry_id(provider_entry_id, model_name, model_entry_id)

    policy = load_policy(org_id)

    provider_registry = dict(policy.get('provider_registry') or {})
    provider_registry[provider_entry_id] = {
        'provider_id': provider_entry_id,
        'display_name': provider_entry_id,
        'default_route_type': route_type,
        'capabilities': [route_type],
        'metadata': {},
    }

    model_registry = dict(policy.get('model_registry') or {})
    model_registry[resolved_model_entry_id] = {
        'model_id': resolved_model_entry_id,
        'provider_id': provider_entry_id,
        'model_name': model_name,
        'metadata': {},
    }

    auth_profiles = dict(policy.get('auth_profiles') or {})
    auth_profiles[auth_profile_name] = {
        'profile_name': auth_profile_name,
        'auth_mode': 'session_home' if route_type == 'cli_session' else 'bearer_pool',
        'cli_bin': cli_bin,
        'cli_home': cli_home,
        'auth_env': auth_env,
        'key_env_pool': list(key_env_pool or []),
    }

    primary_route_id = 'route_primary'
    fallback_route_ids = [
        str(route.get('route_id') or '').strip()
        for route in (fallback_routes or [])
        if str(route.get('route_id') or '').strip()
    ]

    if route_type == 'cli_session':
        primary_route = build_cli_route(
            route_id=primary_route_id,
            provider_entry_id=provider_entry_id,
            model_entry_id=resolved_model_entry_id,
            model_name=model_name,
            auth_profile_order=[auth_profile_name],
            fallback_route_ids=fallback_route_ids,
            cli_bin=cli_bin,
            cli_home=cli_home,
        )
    else:
        primary_route = build_http_route(
            route_id=primary_route_id,
            provider_entry_id=provider_entry_id,
            model_entry_id=resolved_model_entry_id,
            model_name=model_name,
            endpoint=endpoint,
            auth_profile_order=[auth_profile_name],
            fallback_route_ids=fallback_route_ids,
            auth_env=auth_env,
            key_env_pool=list(key_env_pool or []),
        )

    routes = [primary_route, *list(fallback_routes or [])]
    return save_policy(org_id, {
        'primary_route_id': primary_route_id,
        'routes': routes,
        'provider_registry': provider_registry,
        'model_registry': model_registry,
        'auth_profiles': auth_profiles,
        'updated_by': updated_by,
    })


def route_map(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(route.get('route_id') or '').strip(): route
        for route in list(policy.get('routes') or [])
        if str(route.get('route_id') or '').strip()
    }


def active_route(policy: dict[str, Any]) -> dict[str, Any] | None:
    primary_route_id = str(policy.get('primary_route_id') or '').strip()
    return route_map(policy).get(primary_route_id)


def resolve_route_chain(policy: dict[str, Any]) -> list[dict[str, Any]]:
    routes = route_map(policy)
    primary = active_route(policy)
    if not primary:
        return []
    chain = [primary]
    for route_id in list(primary.get('fallback_route_ids') or []):
        route = routes.get(str(route_id or '').strip())
        if route:
            chain.append(route)
    return chain


def classify_reason(reason: str) -> str:
    lowered = str(reason or '').strip().lower()
    if not lowered:
        return 'unknown'
    if 'billing' in lowered or 'deactivated' in lowered or 'payment required' in lowered or 'quota' in lowered:
        return 'billing'
    if 'unauthorized' in lowered or 'invalid api key' in lowered or 'auth' in lowered:
        return 'auth'
    if 'rate limit' in lowered or '429' in lowered:
        return 'rate_limit'
    if 'timeout' in lowered or 'transport' in lowered or 'connection' in lowered:
        return 'transport'
    return 'provider_unavailable'


def policy_status(org_id: str, *, runtime_env: dict[str, str] | None = None) -> dict[str, Any]:
    env = dict(os.environ)
    if runtime_env:
        env.update(runtime_env)
    policy = load_policy(org_id)
    route = active_route(policy)
    chain = resolve_route_chain(policy)
    has_override = any(
        bool(str(env.get(name) or '').strip())
        for name in (
            'MERIDIAN_BRAIN_MANAGER_TRANSPORT',
            'MERIDIAN_BRAIN_MANAGER_CLI_BIN',
            'MERIDIAN_BRAIN_MANAGER_ENDPOINT',
            'MERIDIAN_BRAIN_MANAGER_MODEL',
            'MERIDIAN_BRAIN_ROUTER_CONFIG_PATH',
        )
    )
    if not route:
        return {
            'configured': False,
            'source': 'override' if has_override else 'institution_policy',
            'status': 'blocked',
            'reason': 'no_active_execution_route_configured',
            'active_route': None,
            'active_provider': None,
            'active_model': None,
            'fallback_chain': [],
            'provider_registry': copy.deepcopy(policy.get('provider_registry', {})),
            'model_registry': copy.deepcopy(policy.get('model_registry', {})),
            'auth_profiles': copy.deepcopy(policy.get('auth_profiles', {})),
            'failover_policy': copy.deepcopy(policy.get('failover_policy', {})),
        }

    provider_registry = dict(policy.get('provider_registry') or {})
    model_registry = dict(policy.get('model_registry') or {})
    provider_ref = str(route.get('provider_ref') or route.get('provider_profile') or '').strip()
    model_ref = str(route.get('model_ref') or '').strip()

    return {
        'configured': True,
        'source': 'override' if has_override else 'institution_policy',
        'status': route.get('last_health') or 'unknown',
        'reason': route.get('last_health_reason') or '',
        'active_route': copy.deepcopy(route),
        'active_provider': copy.deepcopy(provider_registry.get(provider_ref) or {}),
        'active_model': copy.deepcopy(model_registry.get(model_ref) or {}),
        'fallback_chain': [copy.deepcopy(item) for item in chain[1:]],
        'provider_registry': copy.deepcopy(provider_registry),
        'model_registry': copy.deepcopy(model_registry),
        'auth_profiles': copy.deepcopy(policy.get('auth_profiles', {})),
        'failover_policy': copy.deepcopy(policy.get('failover_policy', {})),
    }


def update_route_health(
    org_id: str,
    *,
    route_id: str,
    health: str,
    reason: str,
    failover: dict[str, Any] | None = None,
    updated_by: str = 'runtime',
) -> dict[str, Any]:
    policy = load_policy(org_id)
    routes = []
    for route in list(policy.get('routes') or []):
        current = dict(route)
        if str(current.get('route_id') or '') == str(route_id or ''):
            current['last_health'] = health
            current['last_health_reason'] = reason
            if isinstance(failover, dict) and failover:
                current['last_failover'] = dict(failover)
        routes.append(current)
    policy['routes'] = routes
    policy['updated_by'] = updated_by
    return save_policy(org_id, policy)
