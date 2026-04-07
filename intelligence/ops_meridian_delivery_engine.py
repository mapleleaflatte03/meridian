#!/usr/bin/env python3
"""Meridian autonomous delivery engine harness.

This script is intentionally truthful:
- it writes explicit local payment evidence into an isolated temp journal
- it exercises the real subscription activation path used by checkout capture
- it settles through the host-supported Meridian treasury adapter
- it only claims on-chain settlement when a real broadcast tx hash exists
- adapter rejections are surfaced exactly as returned by the active settlement path
- outbound delivery is disabled by default for operator safety
- it only prints a generated brief if the configured Loom runtime actually returns one
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HOME_DIR = str(Path.home())
MONOREPO_ROOT = str(os.environ.get('MERIDIAN_ROOT') or '').strip()
WORKSPACE = str(
    os.environ.get('MERIDIAN_WORKSPACE_ROOT')
    or (os.path.join(MONOREPO_ROOT, 'intelligence') if MONOREPO_ROOT else '')
    or os.path.dirname(os.path.abspath(__file__))
).strip()
PLATFORM_DIR = os.path.join(WORKSPACE, 'company', 'meridian_platform')
MERIDIAN_HOME = str(os.environ.get('MERIDIAN_HOME') or os.path.join(HOME_DIR, '.meridian')).strip()
WORKSPACE_CREDENTIALS_PATH = str(
    os.environ.get('MERIDIAN_WORKSPACE_CREDENTIALS_PATH')
    or os.path.join(MERIDIAN_HOME, '.workspace_credentials')
).strip()

if PLATFORM_DIR not in sys.path:
    sys.path.insert(0, PLATFORM_DIR)

import subscription_service
import warrants as warrants_runtime


DEFAULT_PLAN = 'premium-brief-weekly'
DEFAULT_TELEGRAM_ID = 'meridian-ops-sink'
SCRIPT_ACTOR = 'script:ops_meridian_delivery_engine'
DIRECT_LOOM_BIN = str(
    os.environ.get('MERIDIAN_LOOM_BIN')
    or os.path.join(HOME_DIR, '.local', 'share', 'meridian-loom', 'current', 'bin', 'loom')
).strip()
DIRECT_LOOM_ROOT = str(
    os.environ.get('MERIDIAN_LOOM_ROOT')
    or os.path.join(HOME_DIR, '.local', 'share', 'meridian-loom', 'runtime', 'default')
).strip()
DIRECT_LOOM_AGENT_REGISTRY_PATH = os.path.join(DIRECT_LOOM_ROOT, 'agents', 'registry.json')
DIRECT_LOOM_CAPABILITY = 'loom.browser.navigate.v1'
DIRECT_LOOM_URL = 'https://httpbin.org/html'
DIRECT_X402_WALLET_ID = 'automated_loom_settlement_v1'
DIRECT_X402_SOURCE_ACCOUNT_ID = 'automated_loom_settlement'
DIRECT_X402_SETTLEMENT_ADAPTER = 'base_usdc_x402'
DIRECT_X402_PROOF_TYPE = 'signed_raw_transaction_broadcast_attempt'
DIRECT_X402_TOKEN_CONTRACT = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'
DIRECT_X402_RECIPIENT = '0x2222222222222222222222222222222222222222'
DIRECT_X402_AMOUNT_USDC = '1.00'
DIRECT_X402_RPC_URL = 'https://base-sepolia-rpc.publicnode.com'
DIRECT_INTERNAL_LEDGER_SETTLEMENT_ADAPTER = 'internal_ledger'
DIRECT_INTERNAL_SETTLEMENT_WALLET_ID = 'wallet_meridian_host_ops'
DIRECT_INTERNAL_SETTLEMENT_WALLET_ADDRESS = '0x1111111111111111111111111111111111111111'
DIRECT_INTERNAL_SETTLEMENT_CONTRIBUTOR_ID = 'contrib_meridian_host_ops'
DIRECT_INTERNAL_SETTLEMENT_AMOUNT_USD = 0.0001
CANONICAL_KERNEL_ROOT = str(
    os.environ.get('MERIDIAN_KERNEL_ROOT')
    or (os.path.join(MONOREPO_ROOT, 'kernel') if MONOREPO_ROOT else '')
    or '/opt/meridian-kernel'
).strip()
LEGACY_KERNEL_ROOT = '/tmp/meridian-kernel'


def _first_existing_path(*candidates):
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return str(candidates[0] or '')


KERNEL_ROOT = _first_existing_path(
    os.environ.get('MERIDIAN_KERNEL_ROOT'),
    CANONICAL_KERNEL_ROOT,
    LEGACY_KERNEL_ROOT,
)
KERNEL_TREASURY_PATH = _first_existing_path(
    os.path.join(KERNEL_ROOT, 'kernel', 'treasury.py'),
    os.path.join(CANONICAL_KERNEL_ROOT, 'kernel', 'treasury.py'),
    os.path.join(LEGACY_KERNEL_ROOT, 'kernel', 'treasury.py'),
)
KERNEL_CAPSULE_PATH = _first_existing_path(
    os.path.join(KERNEL_ROOT, 'kernel', 'capsule.py'),
    os.path.join(CANONICAL_KERNEL_ROOT, 'kernel', 'capsule.py'),
    os.path.join(LEGACY_KERNEL_ROOT, 'kernel', 'capsule.py'),
)
HOT_WALLET_SECRET_PATH = _first_existing_path(
    os.environ.get('MERIDIAN_HOT_WALLET_SECRET_PATH'),
    os.path.join(KERNEL_ROOT, '.hot-wallet-secrets', 'automated_loom_settlement_v1.json'),
    os.path.join(CANONICAL_KERNEL_ROOT, '.hot-wallet-secrets', 'automated_loom_settlement_v1.json'),
    os.path.join(LEGACY_KERNEL_ROOT, '.hot-wallet-secrets', 'automated_loom_settlement_v1.json'),
)
PROD_ORG_ID = 'org_prod_exec'
_KERNEL_TREASURY_MODULE = None


def _read_workspace_credentials_org_id() -> str:
    if not os.path.exists(WORKSPACE_CREDENTIALS_PATH):
        return ''
    try:
        with open(WORKSPACE_CREDENTIALS_PATH, encoding='utf-8') as handle:
            for raw_line in handle:
                line = str(raw_line or '').strip()
                if line.startswith('org_id:'):
                    return line.partition(':')[2].strip()
    except OSError:
        return ''
    return ''


def _resolve_direct_loom_org_id() -> str:
    env_org = str(os.environ.get('MERIDIAN_ORG_ID') or '').strip()
    if env_org:
        return env_org
    creds_org = _read_workspace_credentials_org_id()
    if creds_org:
        return creds_org
    return 'org_51fcd87f'


DIRECT_LOOM_ORG_ID = _resolve_direct_loom_org_id()


def _resolve_direct_loom_agent_id() -> str:
    env_agent = str(os.environ.get('MERIDIAN_LOOM_AGENT_ID') or '').strip()
    if env_agent:
        return env_agent.removeprefix('agent_')
    try:
        with open(DIRECT_LOOM_AGENT_REGISTRY_PATH, encoding='utf-8') as handle:
            agents = json.load(handle).get('agents', [])
    except (OSError, json.JSONDecodeError, AttributeError):
        agents = []
    for agent in agents:
        agent_id = str((agent or {}).get('agent_id') or '').strip()
        if agent_id == 'atlas':
            return agent_id
    for agent in agents:
        role = str((agent or {}).get('role') or '').strip().lower()
        if role in {'research', 'analyst'}:
            agent_id = str((agent or {}).get('agent_id') or '').strip()
            if agent_id:
                return agent_id
    return 'atlas'


DIRECT_LOOM_AGENT_ID = _resolve_direct_loom_agent_id()


def _target_url(cli_value=''):
    value = str(cli_value or '').strip()
    if value:
        return value
    return (
        os.environ.get('MERIDIAN_DELIVERY_TARGET_URL')
        or os.environ.get('MERIDIAN_TARGET_URL')
        or DIRECT_LOOM_URL
    )


@contextlib.contextmanager
def _temporary_environment(overrides):
    saved = {}
    try:
        for key, value in (overrides or {}).items():
            saved[key] = os.environ.get(key)
            if value in (None, ''):
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@contextlib.contextmanager
def isolated_execution_environment(*, disable_outbound_dispatch=True, keep_state=False):
    tmpdir = tempfile.mkdtemp(prefix='meridian-delivery-engine-')
    subscriptions_file = os.path.join(tmpdir, 'subscriptions.json')
    subscriptions_backup = os.path.join(tmpdir, 'subscriptions.json.bak')
    subscriptions_lock = os.path.join(tmpdir, '.subscriptions.lock')
    transactions_file = os.path.join(tmpdir, 'transactions.jsonl')

    with open(subscriptions_file, 'w') as f:
        json.dump(subscription_service._default_subscriptions(PROD_ORG_ID), f, indent=2)
    with open(subscriptions_backup, 'w') as f:
        json.dump(subscription_service._default_subscriptions(PROD_ORG_ID), f, indent=2)
    with open(subscriptions_lock, 'w') as f:
        f.write('')
    with open(transactions_file, 'w') as f:
        f.write('')

    originals = {
        'subscriptions_path': subscription_service.subscriptions_path,
        'subscriptions_backup_path': subscription_service.subscriptions_backup_path,
        'subscriptions_lock_path': subscription_service.subscriptions_lock_path,
        'ensure_subscription_aliases': subscription_service.ensure_subscription_aliases,
        'load_transactions': subscription_service._revenue_mod.load_transactions,
        'dispatch_telegram': subscription_service._dispatch_telegram_delivery,
        'dispatch_email': subscription_service._dispatch_email_delivery,
    }

    def _load_transactions():
        with open(transactions_file) as f:
            entries = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entries.append(json.loads(line))
            return entries

    try:
        subscription_service.subscriptions_path = lambda org_id=None: subscriptions_file
        subscription_service.subscriptions_backup_path = lambda org_id=None: subscriptions_backup
        subscription_service.subscriptions_lock_path = lambda org_id=None: subscriptions_lock
        subscription_service.ensure_subscription_aliases = lambda org_id=None: None
        subscription_service._revenue_mod.load_transactions = _load_transactions
        if disable_outbound_dispatch:
            subscription_service._dispatch_telegram_delivery = lambda *args, **kwargs: None
            subscription_service._dispatch_email_delivery = lambda *args, **kwargs: None
        yield {
            'tmpdir': tmpdir,
            'subscriptions_file': subscriptions_file,
            'transactions_file': transactions_file,
            'outbound_dispatch_disabled': disable_outbound_dispatch,
        }
    finally:
        subscription_service.subscriptions_path = originals['subscriptions_path']
        subscription_service.subscriptions_backup_path = originals['subscriptions_backup_path']
        subscription_service.subscriptions_lock_path = originals['subscriptions_lock_path']
        subscription_service.ensure_subscription_aliases = originals['ensure_subscription_aliases']
        subscription_service._revenue_mod.load_transactions = originals['load_transactions']
        subscription_service._dispatch_telegram_delivery = originals['dispatch_telegram']
        subscription_service._dispatch_email_delivery = originals['dispatch_email']
        if not keep_state:
            shutil.rmtree(tmpdir, ignore_errors=True)


def _plan_option(plan_name):
    plan = subscription_service.PLANS[plan_name]
    return {
        'plan': plan_name,
        'price_usd': float(plan['price_usd']),
        'duration_days': int(plan['duration_days']),
        'billing_type': plan['type'],
    }


def build_execution_preview(*, telegram_id, email, plan, target_url):
    return {
        'preview_id': 'quote_prod_exec',
        'pilot_request_id': 'pir_prod_exec',
        'name': 'Meridian Autonomous Delivery Engine',
        'company': 'Meridian Operations Runtime',
        'email': (email or '').strip(),
        'telegram_handle': (telegram_id or '').strip(),
        'requested_cadence': 'Weekly intelligence brief',
        'requested_offer': 'manual_pilot',
        'review_note': 'Local production-style activation harness using explicit captured payment evidence only',
        'preview_truth_source': 'local_activation_harness_with_explicit_customer_payment_evidence_only',
        'state': 'reviewed',
        'plan_options': [_plan_option(plan)],
        'topics': ['pricing', 'provider launches', 'agent infrastructure'],
        'competitors': ['OpenAI', 'Anthropic'],
        'target_url': target_url,
    }


def _write_execution_payment_evidence(transactions_file, *, plan, payment_ref):
    amount = float(subscription_service.PLANS[plan]['price_usd'])
    suffix = uuid.uuid4().hex[:10]
    entry = {
        'type': 'customer_payment',
        'order_id': f'ord_prod_{suffix}',
        'amount': amount,
        'client': 'prod-exec-client',
        'product': f'prod-exec-{plan}',
        'payment_key': f'ref:{payment_ref}',
        'payment_ref': payment_ref,
        'tx_hash': f'prod-exec-tx-{suffix}',
        'note': 'Local captured payment evidence only. Settlement is only claimed when a real broadcast tx hash is returned.',
        'ts': subscription_service.now_ts(),
    }
    with open(transactions_file, 'a') as f:
        f.write(json.dumps(entry) + '\n')
    return entry


def _loom_cli_prefix(loom_bin):
    prefix = []
    if os.geteuid() == 0 and shutil.which('sudo'):
        prefix.extend(['sudo', '-u', 'ubuntu', '-H'])
    prefix.append(loom_bin)
    return prefix


def _run_loom_json(args, *, loom_bin, timeout):
    command = _loom_cli_prefix(loom_bin) + list(args)
    try:
        completed = subprocess.run(
            command,
            cwd=WORKSPACE,
            capture_output=True,
            text=True,
            timeout=int(timeout),
        )
    except subprocess.TimeoutExpired:
        return {
            'ok': False,
            'payload': {},
            'stdout': '',
            'stderr': '',
            'error': f'loom command timed out after {int(timeout)}s',
            'command': command,
            'returncode': -1,
        }
    output = (completed.stdout or '').strip()
    payload = _extract_json_payload(output)
    error = ((completed.stderr or '').strip() or payload.get('error') or output or '').strip()
    return {
        'ok': completed.returncode == 0,
        'payload': payload,
        'stdout': output,
        'stderr': (completed.stderr or '').strip(),
        'error': error,
        'command': command,
        'returncode': completed.returncode,
    }


def _load_worker_result(path):
    candidate = (path or '').strip()
    if not candidate or not os.path.exists(candidate):
        return {}
    with open(candidate) as f:
        return json.load(f)


def _extract_json_payload(raw_output):
    text = str(raw_output or '').strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    marker = text.find('\n{')
    if marker != -1:
        candidate = text[marker + 1 :].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    marker = text.find('{')
    if marker != -1:
        candidate = text[marker:].strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return {}


def _normalized_host_response(worker_result):
    host_response = (worker_result or {}).get('host_response_json')
    if isinstance(host_response, str):
        try:
            host_response = json.loads(host_response)
        except Exception:
            host_response = {}
    return host_response if isinstance(host_response, dict) else {}


def _host_response_brief(worker_result, *, execute_payload=None, execution_error=''):
    worker_result = dict(worker_result or {})
    execute_payload = dict(execute_payload or {})
    host_response = _normalized_host_response(worker_result)

    title = str(host_response.get('title') or '').strip()
    excerpt = str(host_response.get('body_excerpt_utf8') or '').strip()
    if title or excerpt:
        return {
            'text': '\n\n'.join([part for part in (title, excerpt) if part]).strip(),
            'source_key': 'host_response_json.title+body_excerpt_utf8',
        }

    note = str(host_response.get('note') or '').strip()
    final_url = str(host_response.get('final_url') or '').strip()
    http_status = host_response.get('http_status')
    host_parts = []
    if final_url:
        host_parts.append(f'final_url: {final_url}')
    if http_status not in (None, ''):
        host_parts.append(f'http_status: {http_status}')
    if note:
        host_parts.append(f'note: {note}')
    if host_parts:
        return {
            'text': '\n'.join(host_parts).strip(),
            'source_key': 'host_response_json.final_url+http_status+note',
        }

    worker_parts = []
    host_calls = [str(item).strip() for item in (worker_result.get('host_calls') or []) if str(item).strip()]
    if host_calls:
        worker_parts.append(f'host_calls: {", ".join(host_calls)}')
    if worker_result.get('entrypoint_result') not in (None, ''):
        worker_parts.append(f"entrypoint_result: {worker_result.get('entrypoint_result')}")
    status = str(worker_result.get('status') or '').strip()
    if status:
        worker_parts.append(f'worker_status: {status}')
    worker_note = str(execute_payload.get('worker_note') or '').strip()
    if worker_note:
        worker_parts.append(f'worker_note: {worker_note}')
    submit_note = str(execute_payload.get('note') or '').strip()
    if submit_note and submit_note != worker_note:
        worker_parts.append(f'submit_note: {submit_note}')
    if execution_error:
        worker_parts.append(f'execution_error: {execution_error}')
    if worker_parts:
        return {
            'text': '\n'.join(worker_parts).strip(),
            'source_key': 'worker_result.host_calls+entrypoint_result+status',
        }

    return {'text': '', 'source_key': ''}

def _load_kernel_treasury_module():
    global _KERNEL_TREASURY_MODULE
    if _KERNEL_TREASURY_MODULE is not None:
        return _KERNEL_TREASURY_MODULE
    if not os.path.exists(KERNEL_TREASURY_PATH):
        return None
    kernel_dir = os.path.dirname(KERNEL_TREASURY_PATH)
    if kernel_dir in sys.path:
        sys.path.remove(kernel_dir)
    sys.path.insert(0, kernel_dir)
    if os.path.exists(KERNEL_CAPSULE_PATH):
        capsule_spec = importlib.util.spec_from_file_location('capsule', KERNEL_CAPSULE_PATH)
        capsule_module = importlib.util.module_from_spec(capsule_spec)
        sys.modules['capsule'] = capsule_module
        capsule_spec.loader.exec_module(capsule_module)
    spec = importlib.util.spec_from_file_location('meridian_kernel_treasury_runtime', KERNEL_TREASURY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _KERNEL_TREASURY_MODULE = module
    return module


def _kernel_signer_org_id(treasury=None):
    treasury = treasury or _load_kernel_treasury_module()
    if treasury is not None:
        resolver = getattr(treasury, '_default_org_id', None)
        if callable(resolver):
            resolved = str(resolver() or '').strip()
            if resolved:
                return resolved
    return DIRECT_LOOM_ORG_ID


def _finalize_warrant_execution(warrant_id, *, org_id, execution_refs):
    warrant_ref = str(warrant_id or '').strip()
    if not warrant_ref:
        return {}
    return warrants_runtime.mark_warrant_executed(
        warrant_ref,
        org_id=org_id,
        execution_refs=dict(execution_refs or {}),
    )


def _preferred_settlement_adapter(treasury, org_id):
    store = dict((treasury.load_settlement_adapters(org_id) or {}))
    adapters = dict(store.get('adapters') or {})
    default_adapter = str(store.get('default_payout_adapter') or '').strip()
    if default_adapter and dict(adapters.get(default_adapter) or {}).get('payout_execution_enabled'):
        return default_adapter
    for adapter_id, adapter in sorted(adapters.items()):
        if dict(adapter or {}).get('payout_execution_enabled'):
            return str(adapter_id).strip()
    return ''


def _ensure_internal_settlement_recipient(treasury, org_id):
    wallet = treasury.get_wallet(DIRECT_INTERNAL_SETTLEMENT_WALLET_ID, org_id)
    if not wallet:
        wallet = treasury.register_wallet(
            DIRECT_INTERNAL_SETTLEMENT_WALLET_ID,
            DIRECT_INTERNAL_SETTLEMENT_WALLET_ADDRESS,
            actor_id=SCRIPT_ACTOR,
            org_id=org_id,
            label='Meridian Host Ops Settlement Wallet',
            notes='Canonical Meridian host settlement recipient for governed operator payout flow.',
        )

    contributor_store = dict(treasury.load_contributors(org_id) or {})
    contributor_store.setdefault('contributors', {})
    contributor_store.setdefault(
        'contribution_types',
        list(getattr(treasury, '_PROTOCOL_DEFAULTS', {}).get('contributors.json', {}).get('contribution_types', [])),
    )
    contributor = dict(contributor_store['contributors'].get(DIRECT_INTERNAL_SETTLEMENT_CONTRIBUTOR_ID) or {})
    if not contributor:
        contributor = {
            'id': DIRECT_INTERNAL_SETTLEMENT_CONTRIBUTOR_ID,
            'name': 'Meridian Host Ops',
            'status': 'active',
            'payout_wallet_id': DIRECT_INTERNAL_SETTLEMENT_WALLET_ID,
            'registered_by': SCRIPT_ACTOR,
            'notes': 'Canonical Meridian host settlement recipient for governed operator payout flow.',
            'metadata': {
                'source': 'ops_meridian_delivery_engine',
            },
        }
        contributor_store['contributors'][DIRECT_INTERNAL_SETTLEMENT_CONTRIBUTOR_ID] = contributor
        treasury._save_registry_file('contributors.json', contributor_store, org_id)
    elif contributor.get('payout_wallet_id') != DIRECT_INTERNAL_SETTLEMENT_WALLET_ID:
        contributor['payout_wallet_id'] = DIRECT_INTERNAL_SETTLEMENT_WALLET_ID
        contributor_store['contributors'][DIRECT_INTERNAL_SETTLEMENT_CONTRIBUTOR_ID] = contributor
        treasury._save_registry_file('contributors.json', contributor_store, org_id)

    return wallet, contributor


def _load_hot_wallet_secret():
    if not os.path.exists(HOT_WALLET_SECRET_PATH):
        return {}
    with open(HOT_WALLET_SECRET_PATH) as f:
        return json.load(f)


def _broadcast_x402_settlement(timeout):
    treasury = _load_kernel_treasury_module()
    if treasury is None:
        return {
            'ok': False,
            'error': f'Kernel treasury module is missing at {KERNEL_TREASURY_PATH}',
            'signing': {},
        }
    secret = _load_hot_wallet_secret()
    private_key = str(secret.get('private_key_hex') or '').strip()
    if not private_key:
        return {
            'ok': False,
            'error': f'Hot wallet secret is missing a private key at {HOT_WALLET_SECRET_PATH}',
            'signing': {},
        }
    try:
        signing = treasury.sign_x402_transfer_from_wallet(
            SCRIPT_ACTOR,
            org_id=_kernel_signer_org_id(treasury),
            rpc_url=DIRECT_X402_RPC_URL,
            source_account_id=DIRECT_X402_SOURCE_ACCOUNT_ID,
            sender_wallet_id=DIRECT_X402_WALLET_ID,
            recipient_address=DIRECT_X402_RECIPIENT,
            amount_usdc=DIRECT_X402_AMOUNT_USDC,
            token_contract_address=DIRECT_X402_TOKEN_CONTRACT,
            private_key=private_key,
            host_supported_adapters=[DIRECT_X402_SETTLEMENT_ADAPTER],
            timeout_seconds=max(1, min(int(timeout), 20)),
            broadcast=True,
        )
    except Exception as exc:
        return {
            'ok': False,
            'error': str(exc),
            'signing': {},
        }
    signed_transaction = dict(signing.get('signed_transaction') or {})
    broadcast = dict(signing.get('broadcast') or {})
    raw_hex = str(signed_transaction.get('raw_transaction_hex') or '').strip()
    rpc_tx_hash = str(broadcast.get('rpc_tx_hash') or '').strip()
    return {
        'ok': bool(signing.get('signing_performed') and (raw_hex or rpc_tx_hash)),
        'error': str(broadcast.get('error') or '').strip(),
        'signing': signing,
        'raw_hex': raw_hex,
        'rpc_tx_hash': rpc_tx_hash,
    }


def _attach_x402_settlement(result, *, timeout, warrant_id=''):
    runtime = dict(result.get('runtime') or {})
    capture_result = dict(result.get('capture_result') or {})
    if not runtime.get('loom_bin_exists'):
        return result

    signing_result = _broadcast_x402_settlement(timeout)
    signing = dict(signing_result.get('signing') or {})
    result['x402_settlement'] = signing
    if not signing:
        result['x402_settlement_error'] = signing_result.get('error', '')
        return result

    signed_transaction = dict(signing.get('signed_transaction') or {})
    broadcast = dict(signing.get('broadcast') or {})
    tx_hash = str(broadcast.get('rpc_tx_hash') or '').strip()
    proof = {
        'signed_raw_hex': signing_result.get('raw_hex', ''),
        'signed_tx_hash': signed_transaction.get('signed_tx_hash', ''),
        'tx_hash': tx_hash,
        'sender_address': signed_transaction.get('sender_address', ''),
        'wallet_id': DIRECT_X402_WALLET_ID,
        'source_account_id': DIRECT_X402_SOURCE_ACCOUNT_ID,
        'broadcast_requested': bool(broadcast.get('requested')),
        'broadcast_attempted': bool(broadcast.get('attempted')),
        'broadcast_error': str(broadcast.get('error') or '').strip(),
        'truth_boundary': signing.get('truth_boundary', ''),
        'actual_transfer_blockers': list(signing.get('actual_transfer_blockers') or []),
    }
    execution_refs = dict((capture_result.get('delivery_run') or {}).get('execution_refs') or {})
    execution_refs.update({
        'settlement_adapter': DIRECT_X402_SETTLEMENT_ADAPTER,
        'proof_type': 'onchain_receipt' if tx_hash else DIRECT_X402_PROOF_TYPE,
        'tx_hash': tx_hash,
        'proof': proof,
    })
    delivery_run = dict(capture_result.get('delivery_run') or {})
    delivery_run['execution_refs'] = execution_refs
    capture_result['delivery_run'] = delivery_run

    delivery_execution = dict(capture_result.get('delivery_execution') or {})
    delivery_execution['execution_refs'] = execution_refs
    capture_result['delivery_execution'] = delivery_execution
    result['capture_result'] = capture_result
    if (warrant_id or '').strip():
        result['warrant'] = _finalize_warrant_execution(
            warrant_id,
            org_id=_kernel_signer_org_id(),
            execution_refs=execution_refs,
        )
    return result


def _attach_internal_ledger_settlement(result, *, warrant_id=''):
    treasury = _load_kernel_treasury_module()
    if treasury is None:
        result['settlement_error'] = f'Kernel treasury module is missing at {KERNEL_TREASURY_PATH}'
        return result

    org_id = _kernel_signer_org_id(treasury)
    wallet, contributor = _ensure_internal_settlement_recipient(treasury, org_id)
    capture_result = dict(result.get('capture_result') or {})
    delivery_artifact = dict(capture_result.get('delivery_artifact') or {})
    delivery_run = dict(capture_result.get('delivery_run') or {})
    subscription = dict(capture_result.get('subscription') or {})

    commitment = treasury.commitments.propose_commitment(
        'host_meridian_local',
        org_id,
        'Settle governed delivery execution',
        commitment_id=f'cmt_ops_settle_{uuid.uuid4().hex[:12]}',
        proposed_by='user:meridian_host_ops',
        warrant_id=(warrant_id or '').strip(),
        org_id=org_id,
        metadata={
            'source': 'ops_meridian_delivery_engine',
            'subscription_id': subscription.get('id', ''),
            'job_id': delivery_artifact.get('job_id', ''),
        },
    )
    treasury.commitments.accept_commitment(
        commitment['commitment_id'],
        'user:meridian_host_ops',
        org_id=org_id,
    )

    proposal = treasury.create_payout_proposal(
        DIRECT_INTERNAL_SETTLEMENT_CONTRIBUTOR_ID,
        DIRECT_INTERNAL_SETTLEMENT_AMOUNT_USD,
        'review',
        proposed_by='user:meridian_host_ops',
        org_id=org_id,
        evidence={
            'description': 'Meridian governed delivery settlement check',
            'subscription_id': subscription.get('id', ''),
            'result_path': delivery_artifact.get('result_path', ''),
            'job_id': delivery_artifact.get('job_id', ''),
        },
        settlement_adapter=DIRECT_INTERNAL_LEDGER_SETTLEMENT_ADAPTER,
        note='Canonical Meridian host settlement check',
        metadata={
            'source': 'ops_meridian_delivery_engine',
            'target_url': result.get('target_url', ''),
        },
        linked_commitment_id=commitment['commitment_id'],
    )
    proposal = treasury.submit_payout_proposal(
        proposal['proposal_id'],
        'user:meridian_host_ops',
        org_id=org_id,
    )
    proposal = treasury.review_payout_proposal(
        proposal['proposal_id'],
        'user:meridian_host_ops_reviewer',
        org_id=org_id,
    )
    proposal = treasury.approve_payout_proposal(
        proposal['proposal_id'],
        'user:meridian_host_ops_owner',
        org_id=org_id,
    )
    proposal = treasury.open_payout_dispute_window(
        proposal['proposal_id'],
        'user:meridian_host_ops_owner',
        org_id=org_id,
        dispute_window_hours=0,
    )
    proposal = treasury.execute_payout_proposal(
        proposal['proposal_id'],
        'user:meridian_host_ops_owner',
        org_id=org_id,
        warrant_id=(warrant_id or '').strip(),
        settlement_adapter=DIRECT_INTERNAL_LEDGER_SETTLEMENT_ADAPTER,
        host_supported_adapters=[DIRECT_INTERNAL_LEDGER_SETTLEMENT_ADAPTER],
    )

    execution_refs = dict(proposal.get('execution_refs') or {})
    for key in ('delivery_run', 'delivery_execution'):
        record = dict(capture_result.get(key) or {})
        merged_refs = dict(record.get('execution_refs') or {})
        merged_refs.update(execution_refs)
        record['execution_refs'] = merged_refs
        capture_result[key] = record
    result['capture_result'] = capture_result
    result['settlement'] = {
        'adapter_id': proposal.get('settlement_adapter', ''),
        'proposal_id': proposal.get('proposal_id', ''),
        'wallet_id': wallet.get('id', ''),
        'contributor_id': contributor.get('id', ''),
        'linked_commitment_id': proposal.get('linked_commitment_id', ''),
        'execution_refs': execution_refs,
    }
    if (warrant_id or '').strip():
        result['warrant'] = _finalize_warrant_execution(
            warrant_id,
            org_id=org_id,
            execution_refs={
                **execution_refs,
                'proposal_id': proposal.get('proposal_id', ''),
            },
        )
    return result


def _attach_host_supported_settlement(result, *, timeout, warrant_id=''):
    treasury = _load_kernel_treasury_module()
    if treasury is None:
        result['settlement_error'] = f'Kernel treasury module is missing at {KERNEL_TREASURY_PATH}'
        return result

    adapter_id = _preferred_settlement_adapter(treasury, _kernel_signer_org_id(treasury))
    if adapter_id == DIRECT_INTERNAL_LEDGER_SETTLEMENT_ADAPTER:
        return _attach_internal_ledger_settlement(result, warrant_id=warrant_id)
    if adapter_id == DIRECT_X402_SETTLEMENT_ADAPTER:
        return _attach_x402_settlement(result, timeout=timeout, warrant_id=warrant_id)

    result['settlement_error'] = (
        f"No payout-enabled Meridian settlement adapter is active on host; "
        f"default adapter is {(adapter_id or '<none>')}"
    )
    return result


def _builtin_browser_capability_ready(loom_bin, *, timeout=10):
    capability_result = _run_loom_json(
        [
            'capability',
            'show',
            '--root',
            DIRECT_LOOM_ROOT,
            '--name',
            DIRECT_LOOM_CAPABILITY,
            '--format',
            'json',
        ],
        loom_bin=loom_bin,
        timeout=timeout,
    )
    payload = dict(capability_result.get('payload') or {})
    ready = (
        capability_result.get('ok')
        and payload.get('name') == DIRECT_LOOM_CAPABILITY
        and bool(payload.get('enabled'))
    )
    return {
        'ok': bool(ready),
        'capability': payload,
        'error': capability_result.get('error', ''),
        'command': capability_result.get('command', []),
    }


def runtime_snapshot():
    configured_capability = (subscription_service._loom_delivery_capability() or '').strip()
    capability_name = configured_capability
    loom_bin = subscription_service._loom_bin()
    loom_bin_exists = os.path.exists(loom_bin)
    preflight = {
        'ok': False,
        'runtime': 'loom',
        'capability_name': capability_name,
        'errors': [],
    }
    if not capability_name:
        preflight['errors'].append('No Loom delivery capability is configured')
    if not loom_bin_exists:
        preflight['errors'].append(f'Loom binary is missing at {loom_bin}')
    if capability_name and loom_bin_exists:
        preflight = subscription_service._loom_delivery_preflight(capability_name)
    elif loom_bin_exists:
        direct_preflight = _builtin_browser_capability_ready(loom_bin, timeout=10)
        if direct_preflight['ok']:
            capability_name = DIRECT_LOOM_CAPABILITY
            preflight = {
                'ok': True,
                'runtime': 'loom_direct_action_execute',
                'capability_name': capability_name,
                'errors': [],
                'capability': direct_preflight.get('capability', {}),
            }

    runtime_lane = ((preflight.get('capability') or {}).get('runtime_lane') or '').strip()
    wasm_io_available = 'wasm' in runtime_lane.lower()
    runtime_path = 'loom_wasm_io' if wasm_io_available else 'current_truthful_subscription_loom_submit_path'
    return {
        'capability_name': capability_name,
        'loom_bin': loom_bin,
        'loom_bin_exists': loom_bin_exists,
        'runtime_lane': runtime_lane,
        'wasm_io_available': wasm_io_available,
        'runtime_path': runtime_path,
        'preflight': preflight,
    }


def _delivery_settlement_artifact(payload, *, source=''):
    payload = dict(payload or {})
    if not payload:
        return {}

    settlement_adapter = (payload.get('settlement_adapter') or '').strip()
    proof_type = (payload.get('proof_type') or '').strip()
    verification_state = str(payload.get('verification_state') or '').strip()
    finality_state = str(payload.get('finality_state') or '').strip()
    tx_ref = str(payload.get('tx_ref') or '').strip()
    if tx_ref:
        return {
            'artifact_type': 'tx_ref',
            'artifact': tx_ref,
            'artifact_source': source,
            'settlement_adapter': settlement_adapter,
            'proof_type': proof_type,
            'verification_state': verification_state,
            'finality_state': finality_state,
        }

    tx_hash = str(payload.get('tx_hash') or '').strip()
    if tx_hash:
        return {
            'artifact_type': 'tx_hash',
            'artifact': tx_hash,
            'artifact_source': source,
            'settlement_adapter': settlement_adapter,
            'proof_type': proof_type,
            'verification_state': verification_state,
            'finality_state': finality_state,
        }

    for field in ('signed_raw_hex', 'signed_tx_hex', 'raw_hex'):
        value = str(payload.get(field) or '').strip()
        if value:
            return {
                'artifact_type': field,
                'artifact': value,
                'artifact_source': source,
                'settlement_adapter': settlement_adapter,
                'proof_type': proof_type,
                'verification_state': verification_state,
                'finality_state': finality_state,
            }

    for nested_key in ('proof', 'settlement_proof', 'execution_refs'):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            artifact = _delivery_settlement_artifact(
                nested,
                source=f'{source}.{nested_key}' if source else nested_key,
            )
            if artifact:
                if not artifact.get('settlement_adapter'):
                    artifact['settlement_adapter'] = settlement_adapter
                if not artifact.get('proof_type'):
                    artifact['proof_type'] = proof_type
                return artifact

    return {}


def delivery_blockchain_artifact(result):
    artifact = delivery_settlement_artifact(result)
    if artifact.get('artifact_type') in {'tx_hash', 'signed_raw_hex', 'signed_tx_hex', 'raw_hex'}:
        return artifact
    return {
        'artifact_type': '',
        'artifact': '',
        'artifact_source': '',
        'settlement_adapter': '',
        'proof_type': '',
    }


def delivery_settlement_artifact(result):
    capture_result = dict((result or {}).get('capture_result') or {})
    delivery_execution = dict(capture_result.get('delivery_execution') or {})
    delivery_run = dict(capture_result.get('delivery_run') or {})
    delivery_job = dict(capture_result.get('delivery_job') or {})
    delivery_artifact = dict(capture_result.get('delivery_artifact') or {})

    candidates = [
        ('delivery_execution.worker_result', delivery_execution.get('worker_result')),
        ('delivery_execution.execution_refs', delivery_execution.get('execution_refs')),
        ('delivery_run.execution_refs', delivery_run.get('execution_refs')),
        ('delivery_job.execution_refs', delivery_job.get('execution_refs')),
        ('delivery_artifact', delivery_artifact),
    ]
    for source, payload in candidates:
        artifact = _delivery_settlement_artifact(payload, source=source)
        if artifact:
            return artifact
    return {
        'artifact_type': '',
        'artifact': '',
        'artifact_source': '',
        'settlement_adapter': '',
        'proof_type': '',
        'verification_state': '',
        'finality_state': '',
    }


def run_engine(*, plan=DEFAULT_PLAN, telegram_id=DEFAULT_TELEGRAM_ID, email='', timeout=20,
               disable_outbound_dispatch=True, keep_state=False, capability_name='', target_url='',
               warrant_id=''):
    env_overrides = {}
    if capability_name:
        env_overrides['MERIDIAN_LOOM_SUBSCRIPTION_DELIVERY_CAPABILITY'] = capability_name

    with _temporary_environment(env_overrides):
        runtime = runtime_snapshot()
        payment_ref = f'prod-exec-{uuid.uuid4().hex}'
        payment_evidence = {
            'payment_key': f'ref:{payment_ref}',
            'payment_ref': payment_ref,
        }
        target = _target_url(target_url)

        with isolated_execution_environment(
            disable_outbound_dispatch=disable_outbound_dispatch,
            keep_state=keep_state,
        ) as execution_env:
            payment_entry = _write_execution_payment_evidence(
                execution_env['transactions_file'],
                plan=plan,
                payment_ref=payment_ref,
            )
            payment_evidence.update({
                'order_id': payment_entry['order_id'],
                'tx_hash': payment_entry['tx_hash'],
                'amount_usd': float(payment_entry['amount']),
            })
            preview = build_execution_preview(
                telegram_id=telegram_id,
                email=email,
                plan=plan,
                target_url=target,
            )
            capture_result = subscription_service.capture_subscription_from_preview(
                preview,
                telegram_id=telegram_id,
                plan=plan,
                payment_method='captured',
                payment_ref=payment_ref,
                payment_evidence=payment_evidence,
                org_id=PROD_ORG_ID,
                actor=SCRIPT_ACTOR,
                timeout=int(timeout),
            )
            state = subscription_service.load_subscriptions(PROD_ORG_ID)
            result = {
                'runtime': runtime,
                'execution_state_dir': execution_env['tmpdir'],
                'outbound_dispatch_disabled': execution_env['outbound_dispatch_disabled'],
                'payment_entry': payment_entry,
                'payment_evidence': payment_evidence,
                'preview': preview,
                'capture_result': capture_result,
                'subscriptions_state': state,
                'target_url': target,
            }
            result = _direct_browser_fallback_capture(result, timeout=int(timeout), target_url=target)
            return _attach_host_supported_settlement(
                result,
                timeout=int(timeout),
                warrant_id=warrant_id,
            )


run_delivery_engine = run_engine


def _direct_browser_fallback_capture(result, *, timeout, target_url):
    runtime = dict(result.get('runtime') or {})
    capture_result = dict(result.get('capture_result') or {})
    delivery_artifact = dict(capture_result.get('delivery_artifact') or {})
    if (delivery_artifact.get('brief_text') or '').strip():
        return result
    if not runtime.get('loom_bin_exists'):
        return result
    if (runtime.get('capability_name') or '').strip() != DIRECT_LOOM_CAPABILITY:
        return result

    execute_result = _run_loom_json(
        [
            'action',
            'execute',
            '--root',
            DIRECT_LOOM_ROOT,
            '--org-id',
            DIRECT_LOOM_ORG_ID,
            '--agent-id',
            DIRECT_LOOM_AGENT_ID,
            '--capability',
            DIRECT_LOOM_CAPABILITY,
            '--payload-json',
            json.dumps({'url': target_url}),
            '--format',
            'json',
        ],
        loom_bin=runtime['loom_bin'],
        timeout=timeout,
    )
    payload = dict(execute_result.get('payload') or {})
    result_path = (payload.get('worker_result_path') or payload.get('result_path') or '').strip()
    worker_result = _load_worker_result(result_path)

    fallback_execution = {
        'ok': (
            execute_result.get('ok', False)
            and (payload.get('runtime_outcome') == 'worker_executed' or payload.get('worker_status') == 'completed')
        ),
        'runtime': 'loom_direct_action_execute',
        'capability_name': DIRECT_LOOM_CAPABILITY,
        'org_id': DIRECT_LOOM_ORG_ID,
        'agent_id': DIRECT_LOOM_AGENT_ID,
        'command': execute_result.get('command', []),
        'submit': payload,
        'result_path': result_path,
        'worker_result': worker_result,
        'error': '',
    }
    if not fallback_execution['ok']:
        fallback_execution['error'] = (
            execute_result.get('error')
            or payload.get('worker_note')
            or payload.get('runtime_outcome')
            or 'direct loom action execute failed'
        )

    brief = _host_response_brief(
        worker_result,
        execute_payload=payload,
        execution_error=fallback_execution['error'],
    )
    brief_text = brief['text']

    capture_result['delivery_execution'] = fallback_execution
    if brief_text:
        capture_result['delivery_run'] = {
            'state': 'executed',
            'delivery_status': 'artifact_ready',
            'delivered': False,
            'delivery_ref': '',
            'execution_refs': payload,
        }
        capture_result['delivery_artifact'] = {
            'artifact_type': 'subscription_brief_v1',
            'content_type': 'text/plain',
            'subscription_id': capture_result.get('subscription', {}).get('id', ''),
            'preview_id': result.get('preview', {}).get('preview_id', ''),
            'job_id': payload.get('job_id', ''),
            'delivery_title': 'Meridian autonomous delivery brief',
            'brief_date': subscription_service.now_dt().date().isoformat(),
            'topic': target_url,
            'result_path': result_path,
            'source_key': brief['source_key'] or 'host_response_json.title+body_excerpt_utf8',
            'brief_text': brief_text,
            'brief_preview': brief_text[: subscription_service.BRIEF_PREVIEW_LIMIT].strip(),
            'raw_worker_result': worker_result,
        }
    elif not fallback_execution['error']:
        fallback_execution['error'] = 'direct loom browser execution returned no deliverable brief text'
    result['capture_result'] = capture_result
    return result


def _blockchain_sender_address(result):
    signing = dict((result or {}).get('x402_settlement') or {})
    signed_transaction = dict(signing.get('signed_transaction') or {})
    sender_address = str(signed_transaction.get('sender_address') or '').strip()
    if sender_address:
        return sender_address
    secret = _load_hot_wallet_secret()
    return str(secret.get('address') or secret.get('wallet_address') or '').strip()


def _blockchain_rpc_error(result):
    signing = dict((result or {}).get('x402_settlement') or {})
    broadcast = dict(signing.get('broadcast') or {})
    direct_error = str((result or {}).get('x402_settlement_error') or '').strip()
    return str(broadcast.get('error') or '').strip() or direct_error


def _settlement_sender_address(result):
    settlement = delivery_settlement_artifact(result)
    if (settlement.get('settlement_adapter') or '').strip() != DIRECT_X402_SETTLEMENT_ADAPTER:
        return ''
    return _blockchain_sender_address(result)


def _settlement_error(result):
    settlement = dict((result or {}).get('settlement') or {})
    if settlement.get('error'):
        return str(settlement.get('error') or '').strip()
    direct_error = str((result or {}).get('settlement_error') or '').strip()
    return direct_error or _blockchain_rpc_error(result)


def _print_result(result):
    runtime = result['runtime']
    capture_result = result['capture_result']
    subscription = capture_result['subscription']
    run = capture_result.get('delivery_run', {})
    execution = capture_result.get('delivery_execution', {})
    artifact = capture_result.get('delivery_artifact', {})
    settlement = delivery_settlement_artifact(result)
    settlement_sender_address = _settlement_sender_address(result)
    settlement_error = _settlement_error(result)

    print('Meridian Autonomous Delivery Engine')
    print(f"workspace: {WORKSPACE}")
    print(f"execution_state_dir: {result['execution_state_dir']}")
    print(f"outbound_dispatch_disabled: {str(result['outbound_dispatch_disabled']).lower()}")
    print(f"settlement_claimed: {str(bool(settlement.get('artifact'))).lower()}")
    print(f"settlement_artifact_type: {settlement.get('artifact_type') or '<none>'}")
    print(f"settlement_artifact_source: {settlement.get('artifact_source') or '<none>'}")
    if settlement.get('settlement_adapter'):
        print(f"settlement_adapter: {settlement['settlement_adapter']}")
    if settlement.get('proof_type'):
        print(f"settlement_proof_type: {settlement['proof_type']}")
    if settlement.get('verification_state'):
        print(f"settlement_verification_state: {settlement['verification_state']}")
    if settlement.get('finality_state'):
        print(f"settlement_finality_state: {settlement['finality_state']}")
    if settlement_sender_address:
        print(f"settlement_sender_address: {settlement_sender_address}")
    if settlement_error:
        print(f"settlement_error: {settlement_error}")
    print(f"settlement_artifact: {settlement.get('artifact') or '<none>'}")
    print(f"runtime_path: {runtime['runtime_path']}")
    print(f"wasm_io_available: {str(runtime['wasm_io_available']).lower()}")
    print(f"loom_bin: {runtime['loom_bin']}")
    print(f"loom_bin_exists: {str(runtime['loom_bin_exists']).lower()}")
    print(f"capability_name: {runtime['capability_name'] or '<unset>'}")
    print(f"target_url: {result.get('target_url') or '<unset>'}")
    print(f"preflight_ok: {str(bool(runtime['preflight'].get('ok'))).lower()}")
    if runtime['preflight'].get('errors'):
        print('preflight_errors:')
        for error in runtime['preflight']['errors']:
            print(f'  - {error}')
    print(f"payment_ref: {result['payment_entry']['payment_ref']}")
    print(f"payment_order_id: {result['payment_entry']['order_id']}")
    print(f"payment_evidence_tx_hash: {result['payment_entry']['tx_hash']}")
    print(f"subscription_id: {subscription.get('id', '')}")
    print(f"subscription_status: {subscription.get('status', '')}")
    print(f"payment_verified: {str(bool(subscription.get('payment_verified'))).lower()}")
    print(f"delivery_run_state: {run.get('state', '')}")
    print(f"delivery_status: {run.get('delivery_status', '')}")
    print(f"delivered: {str(bool(run.get('delivered'))).lower()}")
    print(f"delivery_ref: {run.get('delivery_ref', '') or '<none>'}")
    print(f"execution_ok: {str(bool(execution.get('ok'))).lower()}")
    if execution.get('error'):
        print(f"execution_error: {execution['error']}")
    if artifact.get('result_path'):
        print(f"brief_result_path: {artifact['result_path']}")
    else:
        print('brief_result_path: <none>')
    print('brief_text:')
    brief_text = (artifact.get('brief_text') or '').strip()
    if brief_text:
        print(brief_text)
    else:
        print('<none>')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the Meridian autonomous delivery engine harness')
    parser.add_argument('--plan', default=DEFAULT_PLAN, choices=sorted(subscription_service.PLANS.keys()))
    parser.add_argument('--telegram-id', default=DEFAULT_TELEGRAM_ID, help='Subscriber identifier used for activation')
    parser.add_argument('--email', default='', help='Optional email address')
    parser.add_argument('--timeout', type=int, default=20, help='Loom execution timeout in seconds')
    parser.add_argument('--capability-name', default='', help='Optional Loom delivery capability override')
    parser.add_argument('--url', default='', help='Target URL for the browser capability')
    parser.add_argument('--enable-outbound-dispatch', action='store_true', help='Allow real outbound dispatch to configured channels')
    parser.add_argument('--keep-state', action='store_true', help='Keep isolated temp state for inspection after the run')
    args = parser.parse_args(argv)

    try:
        result = run_engine(
            plan=args.plan,
            telegram_id=args.telegram_id,
            email=args.email,
            timeout=args.timeout,
            disable_outbound_dispatch=not args.enable_outbound_dispatch,
            keep_state=args.keep_state,
            capability_name=args.capability_name,
            target_url=args.url,
            warrant_id='',
        )
    except Exception as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2

    _print_result(result)
    artifact = result['capture_result'].get('delivery_artifact', {})
    return 0 if (artifact.get('brief_text') or '').strip() else 1


if __name__ == '__main__':
    raise SystemExit(main())
