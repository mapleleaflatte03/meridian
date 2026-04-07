#!/usr/bin/env python3
import base64
import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error as urllib_error
from urllib import request as urllib_request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
WORKSPACE = os.path.dirname(ROOT)
sys.path.insert(0, ROOT)


def _now_stub():
    return '2026-03-22T00:00:00Z'


def _write_json(path, payload):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(payload, f, indent=2, sort_keys=True)


def _read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _seed_commitments(path, records):
    _write_json(
        path,
        {
            'commitments': {
                record['commitment_id']: record
                for record in records
            },
            'states': ['proposed', 'accepted', 'rejected', 'breached', 'settled'],
            'updatedAt': _now_stub(),
        },
    )


def _accepted_commitment_record(*, org_id, commitment_id, target_host_id,
                                target_institution_id, warrant_id=''):
    return {
        'commitment_id': commitment_id,
        'institution_id': org_id,
        'source_institution_id': org_id,
        'target_host_id': target_host_id,
        'target_institution_id': target_institution_id,
        'commitment_type': 'federated_delivery',
        'summary': 'Federated delivery settlement proof',
        'terms_hash': '',
        'terms_payload': {},
        'warrant_id': warrant_id,
        'state': 'accepted',
        'status': 'accepted',
        'proposed_by': f'{org_id}_owner',
        'proposed_at': _now_stub(),
        'updated_at': _now_stub(),
        'reviewed_by': f'{org_id}_owner',
        'reviewed_at': _now_stub(),
        'review_note': '',
        'accepted_by': f'{org_id}_owner',
        'accepted_at': _now_stub(),
        'rejected_by': '',
        'rejected_at': '',
        'breached_by': '',
        'settled_by': '',
        'delivery_refs': [],
        'settlement_refs': [],
        'last_delivery_at': '',
        'last_settlement_at': '',
        'breached_at': '',
        'settled_at': '',
        'note': '',
        'metadata': {},
    }


def _executed_payout_proposal_record(*, proposal_id, commitment_id, contribution_type='code'):
    return {
        'proposal_id': proposal_id,
        'id': proposal_id,
        'institution_id': 'org_beta',
        'contributor_id': 'contrib_beta',
        'contributor_name': 'Beta Contributor',
        'amount_usd': 12.0,
        'currency': 'USDC',
        'contribution_type': contribution_type,
        'evidence': {
            'pr_urls': ['https://example.test/pr/1'],
            'commit_hashes': [],
            'issue_refs': [],
            'description': 'Federated execution closes on an executed payout proposal',
        },
        'recipient_wallet_id': 'wallet_beta',
        'proposed_by': 'user_owner_beta',
        'reviewed_by': 'user_reviewer_beta',
        'approved_by': 'user_owner_beta',
        'status': 'executed',
        'created_at': _now_stub(),
        'updated_at': _now_stub(),
        'submitted_at': _now_stub(),
        'reviewed_at': _now_stub(),
        'approved_at': _now_stub(),
        'dispute_window_started_at': _now_stub(),
        'dispute_window_ends_at': _now_stub(),
        'executed_at': _now_stub(),
        'executed_by': 'user_owner_beta',
        'tx_hash': '0xfeedbeef',
        'warrant_id': 'war_payout_beta',
        'settlement_adapter': 'internal_ledger',
        'settlement_adapter_contract': {
            'adapter_id': 'internal_ledger',
            'execution_mode': 'host_ledger',
            'settlement_path': 'journal_append',
            'proof_type': 'ledger_transaction',
            'verification_state': 'host_ledger_final',
            'finality_state': 'host_local_final',
            'dispute_model': 'court_case',
            'finality_model': 'host_local_final',
            'host_supported': True,
            'host_supported_adapters': [],
            'execution_readiness': 'ready',
            'execution_blockers': [],
            'execution_ready': True,
        },
        'linked_commitment_id': commitment_id,
        'execution_refs': {
            'tx_ref': 'ptx_demo_beta',
            'settlement_adapter': 'internal_ledger',
            'settlement_adapter_contract': {
                'adapter_id': 'internal_ledger',
                'execution_mode': 'host_ledger',
                'settlement_path': 'journal_append',
                'proof_type': 'ledger_transaction',
                'verification_state': 'host_ledger_final',
                'finality_state': 'host_local_final',
                'dispute_model': 'court_case',
                'finality_model': 'host_local_final',
                'host_supported': True,
                'host_supported_adapters': [],
                'execution_readiness': 'ready',
                'execution_blockers': [],
                'execution_ready': True,
            },
            'tx_hash': '0xfeedbeef',
            'proof_type': 'ledger_transaction',
            'verification_state': 'host_ledger_final',
            'finality_state': 'host_local_final',
            'reversal_or_dispute_capability': 'court_case',
            'proof': {
                'mode': 'institution_transactions_journal',
            },
            'linked_commitment_id': commitment_id,
        },
        'note': 'Executed payout proof reused by federated execution close-loop',
        'metadata': {},
    }


def _base_usdc_x402_contract_snapshot():
    return {
        'contract_version': 2,
        'adapter_id': 'base_usdc_x402',
        'status': 'active',
        'payout_execution_enabled': True,
        'execution_mode': 'external_chain',
        'settlement_path': 'x402_onchain',
        'supported_currencies': ['USDC'],
        'requires_tx_hash': True,
        'requires_settlement_proof': True,
        'requires_verifier_attestation': True,
        'verification_mode': 'external_attestation',
        'verification_ready': True,
        'accepted_attestation_types': ['x402_settlement_verifier'],
        'proof_type': 'onchain_receipt',
        'verification_state': 'external_verification_required',
        'finality_state': 'external_chain_finality',
        'finality_model': 'external_chain_finality',
        'reversal_or_dispute_capability': 'court_case_plus_chain_review',
        'dispute_model': 'court_case_plus_chain_review',
    }


def _contract_digest(snapshot):
    raw = json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _find_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(('127.0.0.1', 0))
        sock.listen(1)
        return sock.getsockname()[1]
    finally:
        sock.close()


def _auth_header(user, password):
    raw = f'{user}:{password}'.encode('utf-8')
    return 'Basic ' + base64.b64encode(raw).decode('ascii')


def _http_json(method, url, *, payload=None, headers=None):
    req = urllib_request.Request(
        url,
        data=(json.dumps(payload).encode('utf-8') if payload is not None else None),
        headers=headers or {},
        method=method,
    )
    try:
        with urllib_request.urlopen(req, timeout=10) as response:
            body = response.read().decode('utf-8')
            return response.status, (json.loads(body) if body else {})
    except urllib_error.HTTPError as exc:
        body = exc.read().decode('utf-8')
        return exc.code, (json.loads(body) if body else {})


def _seed_workspace_root(root_dir, *, org_id, user_id, host_id, port, signing_secret,
                         peer_entries=None, host_role='institution_host',
                         settlement_adapters=None):
    kernel_src = os.path.join(WORKSPACE, 'kernel')
    economy_src = os.path.join(WORKSPACE, 'economy')
    kernel_dst = os.path.join(root_dir, 'kernel')
    economy_dst = os.path.join(root_dir, 'economy')
    shutil.copytree(kernel_src, kernel_dst, ignore_dangling_symlinks=True)
    shutil.copytree(economy_src, economy_dst, ignore_dangling_symlinks=True)

    _write_json(
        os.path.join(kernel_dst, 'organizations.json'),
        {
            'organizations': {
                org_id: {
                    'id': org_id,
                    'name': f'{org_id} Institution',
                    'slug': org_id,
                    'owner_id': user_id,
                    'members': [
                        {
                            'user_id': user_id,
                            'role': 'owner',
                            'added_at': _now_stub(),
                        }
                    ],
                    'plan': 'enterprise',
                    'status': 'active',
                    'charter': '',
                    'policy_defaults': {},
                    'treasury_id': None,
                    'lifecycle_state': 'active',
                    'settings': {},
                    'created_at': _now_stub(),
                },
            },
            'updatedAt': _now_stub(),
        },
    )
    _write_json(
        os.path.join(kernel_dst, 'agent_registry.json'),
        {'agents': {}, 'updatedAt': _now_stub()},
    )
    _write_json(
        os.path.join(kernel_dst, 'host_identity.json'),
        {
            'host_id': host_id,
            'label': host_id,
            'role': host_role,
            'federation_enabled': True,
            'peer_transport': 'https',
            'supported_boundaries': [
                'workspace',
                'cli',
                'federation_gateway',
            ],
            'settlement_adapters': list(settlement_adapters or []),
        },
    )

    capsule_spec = importlib.util.spec_from_file_location(
        f'kernel_capsule_seed_{host_id}',
        os.path.join(kernel_dst, 'capsule.py'),
    )
    capsule_mod = importlib.util.module_from_spec(capsule_spec)
    capsule_spec.loader.exec_module(capsule_mod)
    # The checked-in reference economy can carry founding-host live state at
    # the root economy/ boundary. Strip all root capsule files before seeding
    # temp hosts so tests run against isolated capsules/<org_id>/ state instead
    # of inheriting stale execution jobs, inbox entries, or ledgers.
    for filename in capsule_mod.CAPSULE_FILES:
        copied_path = os.path.join(economy_dst, filename)
        if os.path.exists(copied_path):
            os.remove(copied_path)
    capsule_mod.init_capsule(org_id)
    capsule_dir = capsule_mod.capsule_dir(org_id)

    _write_json(
        os.path.join(kernel_dst, 'institution_admissions.json'),
        {
            'host_id': host_id,
            'institutions': {
                org_id: {
                    'status': 'admitted',
                    'source': 'test_seed',
                    'updated_at': _now_stub(),
                    'admitted_at': _now_stub(),
                },
            },
            'updated_at': _now_stub(),
        },
    )
    _write_json(
        os.path.join(kernel_dst, 'federation_peers.json'),
        {
            'host_id': host_id,
            'peers': peer_entries or {},
            'updated_at': _now_stub(),
        },
    )
    open(os.path.join(kernel_dst, 'audit_log.jsonl'), 'w').close()
    open(os.path.join(kernel_dst, '.federation_replay'), 'w').close()

    env = os.environ.copy()
    env.update({
        'MERIDIAN_WORKSPACE_USER': f'{org_id}_user',
        'MERIDIAN_WORKSPACE_PASS': f'{org_id}_pass',
        'MERIDIAN_WORKSPACE_AUTH_ORG_ID': org_id,
        'MERIDIAN_WORKSPACE_USER_ID': user_id,
        'MERIDIAN_RUNTIME_HOST_IDENTITY_FILE': os.path.join(kernel_dst, 'host_identity.json'),
        'MERIDIAN_RUNTIME_ADMISSION_FILE': os.path.join(kernel_dst, 'institution_admissions.json'),
        'MERIDIAN_FEDERATION_PEERS_FILE': os.path.join(kernel_dst, 'federation_peers.json'),
        'MERIDIAN_FEDERATION_REPLAY_FILE': os.path.join(kernel_dst, '.federation_replay'),
        'MERIDIAN_FEDERATION_SIGNING_SECRET': signing_secret,
        'MERIDIAN_SESSION_SECRET': f'{host_id}-session-secret',
        'PYTHONUNBUFFERED': '1',
    })
    return {
        'root': root_dir,
        'kernel': kernel_dst,
        'economy': capsule_dir,
        'economy_root': economy_dst,
        'port': port,
        'org_id': org_id,
        'user_id': user_id,
        'host_id': host_id,
        'workspace_py': os.path.join(kernel_dst, 'workspace.py'),
        'audit_log': os.path.join(kernel_dst, 'audit_log.jsonl'),
        'env': env,
        'auth_header': _auth_header(env['MERIDIAN_WORKSPACE_USER'], env['MERIDIAN_WORKSPACE_PASS']),
        'base_url': f'http://127.0.0.1:{port}',
    }


@contextlib.contextmanager
def _run_workspace(instance):
    proc = subprocess.Popen(
        [
            sys.executable,
            instance['workspace_py'],
            '--port',
            str(instance['port']),
            '--org-id',
            instance['org_id'],
        ],
        cwd=instance['root'],
        env=instance['env'],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 10
        last_error = ''
        while time.time() < deadline:
            if proc.poll() is not None:
                output = proc.stdout.read() if proc.stdout else ''
                raise RuntimeError(
                    f"workspace {instance['host_id']} exited early with code {proc.returncode}: {output}"
                )
            try:
                status, body = _http_json('GET', instance['base_url'] + '/api/federation/manifest')
                if status == 200 and body.get('host_identity', {}).get('host_id') == instance['host_id']:
                    break
                last_error = f'status={status} body={body}'
            except Exception as exc:
                last_error = str(exc)
            time.sleep(0.1)
        else:
            raise RuntimeError(
                f"workspace {instance['host_id']} did not become ready: {last_error}"
            )
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.close()


def _issue_workspace_session(instance):
    status, body = _http_json(
        'POST',
        instance['base_url'] + '/api/session/issue',
        payload={},
        headers={
            'Authorization': instance['auth_header'],
            'Content-Type': 'application/json',
        },
    )
    if status != 200:
        raise AssertionError(f'failed issuing session for {instance["host_id"]}: {status} {body}')
    return body


def _issue_workspace_warrant(instance, token, request_payload, *, auto_issue=False,
                            review_decision='approve', action_class='federated_execution'):
    status, body = _http_json(
        'POST',
        instance['base_url'] + '/api/warrants/issue',
        payload={
            'action_class': action_class,
            'boundary_name': 'federation_gateway',
            'request_payload': request_payload,
            'risk_class': 'moderate',
            'auto_issue': auto_issue,
        },
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        },
    )
    if status != 200:
        raise AssertionError(f'failed issuing warrant for {instance["host_id"]}: {status} {body}')
    warrant = body['warrant']
    if not auto_issue and review_decision:
        status, body = _http_json(
            'POST',
            instance['base_url'] + f'/api/warrants/{review_decision}',
            payload={'warrant_id': warrant['warrant_id']},
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            },
        )
        if status != 200:
            raise AssertionError(
                f'failed {review_decision} warrant for {instance["host_id"]}: {status} {body}'
            )
        warrant = body['warrant']
    return warrant


def _wait_for_execution_job(instance, envelope_id, *, timeout=5.0):
    deadline = time.time() + timeout
    last_body = {}
    while time.time() < deadline:
        status, body = _http_json(
            'GET',
            instance['base_url'] + '/api/federation/execution-jobs',
            headers={'Authorization': instance['auth_header']},
        )
        if status == 200:
            last_body = body
            for job in body.get('jobs') or []:
                if (job.get('envelope_id') or '').strip() == (envelope_id or '').strip():
                    return body, job
        time.sleep(0.1)
    raise AssertionError(
        f"timed out waiting for execution job envelope={envelope_id}: {last_body}"
    )


def _wait_for_warrant(instance, warrant_id, *, timeout=5.0):
    deadline = time.time() + timeout
    last_body = {}
    while time.time() < deadline:
        status, body = _http_json(
            'GET',
            instance['base_url'] + '/api/warrants',
            headers={'Authorization': instance['auth_header']},
        )
        if status == 200:
            last_body = body
            for warrant in body.get('warrants') or []:
                if (warrant.get('warrant_id') or '').strip() == (warrant_id or '').strip():
                    return warrant
        time.sleep(0.1)
    raise AssertionError(
        f"timed out waiting for warrant {warrant_id}: {last_body}"
    )


def _run_handoff_dispatch_proof():
    try:
        port_alpha = _find_free_port()
        port_beta = _find_free_port()
    except PermissionError as exc:
        raise unittest.SkipTest(f'localhost socket bind unavailable in sandbox: {exc}')

    with tempfile.TemporaryDirectory() as tmp:
        alpha = _seed_workspace_root(
            os.path.join(tmp, 'alpha'),
            org_id='org_alpha',
            user_id='user_owner_alpha',
            host_id='host_alpha',
            port=port_alpha,
            signing_secret='alpha-secret',
            peer_entries={
                'host_beta': {
                    'label': 'Beta Host',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_beta}',
                    'trust_state': 'trusted',
                    'shared_secret': 'beta-secret',
                    'admitted_org_ids': ['org_beta'],
                },
            },
        )
        beta = _seed_workspace_root(
            os.path.join(tmp, 'beta'),
            org_id='org_beta',
            user_id='user_owner_beta',
            host_id='host_beta',
            port=port_beta,
            signing_secret='beta-secret',
            peer_entries={
                'host_alpha': {
                    'label': 'Alpha Host',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                    'trust_state': 'trusted',
                    'shared_secret': 'alpha-secret',
                    'admitted_org_ids': ['org_alpha'],
                },
            },
        )
        with _run_workspace(beta), _run_workspace(alpha):
            session = _issue_workspace_session(alpha)
            federation_status, federation_body = _http_json(
                'GET',
                alpha['base_url'] + '/api/federation',
                headers={'Authorization': f"Bearer {session['token']}"},
            )
            if federation_status != 200:
                raise AssertionError(f'failed reading federation state: {federation_status} {federation_body}')
            remote_handoff = next(
                item for item in federation_body['handoff_preview']['handoff_candidates']
                if item['requested_org_id'] == 'org_beta'
            )
            handoff_id = remote_handoff['handoff_id']

            acknowledge_status, acknowledge_body = _http_json(
                'POST',
                alpha['base_url'] + '/api/federation/handoff-preview-queue/acknowledge',
                payload={'handoff_id': handoff_id, 'note': 'operator reviewed'},
                headers={
                    'Authorization': f"Bearer {session['token']}",
                    'Content-Type': 'application/json',
                },
            )
            if acknowledge_status != 200:
                raise AssertionError(f'failed acknowledging handoff: {acknowledge_status} {acknowledge_body}')
            dispatch_id = acknowledge_body['dispatch_record']['dispatch_id']

            request_payload = {'task': 'remote handoff capsule'}
            warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
            dispatch_status, dispatch_body = _http_json(
                'POST',
                alpha['base_url'] + '/api/federation/handoff-dispatch-queue/run',
                payload={
                    'dispatch_id': dispatch_id,
                    'payload': request_payload,
                    'warrant_id': warrant['warrant_id'],
                    'note': 'send queued handoff to remote host',
                },
                headers={
                    'Authorization': f"Bearer {session['token']}",
                    'Content-Type': 'application/json',
                },
            )
            if dispatch_status != 200:
                raise AssertionError(f'failed running handoff dispatch: {dispatch_status} {dispatch_body}')

            queue_status, queue_body = _http_json(
                'GET',
                alpha['base_url'] + '/api/federation/handoff-dispatch-queue',
                headers={'Authorization': alpha['auth_header']},
            )
            if queue_status != 200:
                raise AssertionError(f'failed reading dispatch queue: {queue_status} {queue_body}')
            queue_record = next(
                item for item in queue_body['handoff_dispatch_records']
                if item['dispatch_id'] == dispatch_id
            )

            jobs_status, jobs_body = _http_json(
                'GET',
                beta['base_url'] + '/api/federation/execution-jobs',
                headers={'Authorization': beta['auth_header']},
            )
            if jobs_status != 200:
                raise AssertionError(f'failed reading execution jobs: {jobs_status} {jobs_body}')

            inbox_status, inbox_body = _http_json(
                'GET',
                beta['base_url'] + '/api/federation/inbox',
                headers={'Authorization': beta['auth_header']},
            )
            if inbox_status != 200:
                raise AssertionError(f'failed reading federation inbox: {inbox_status} {inbox_body}')

        alpha_events = _read_jsonl(alpha['audit_log'])
        beta_events = _read_jsonl(beta['audit_log'])
        return {
            'handoff_id': handoff_id,
            'dispatch_id': dispatch_id,
            'route_kind': remote_handoff.get('route_kind', ''),
            'dispatch_ready': bool(remote_handoff.get('dispatch_ready')),
            'dispatch_runner': dispatch_body.get('dispatch_runner', ''),
            'delivery': {
                'envelope_id': (((dispatch_body.get('delivery') or {}).get('claims') or {}).get('envelope_id', '')),
                'receipt_id': (((dispatch_body.get('delivery') or {}).get('receipt') or {}).get('receipt_id', '')),
                'receiver_host_id': (((dispatch_body.get('delivery') or {}).get('receipt') or {}).get('receiver_host_id', '')),
                'receiver_institution_id': (((dispatch_body.get('delivery') or {}).get('receipt') or {}).get('receiver_institution_id', '')),
            },
            'dispatch_record': {
                'state': queue_record.get('state', ''),
                'execution_job_state': queue_record.get('execution_job_state', ''),
                'dispatch_runner': queue_record.get('dispatch_runner', ''),
            },
            'execution_job': {
                'job_id': ((dispatch_body.get('execution_job') or {}).get('job_id', '')),
                'state': ((dispatch_body.get('execution_job') or {}).get('state', '')),
                'local_warrant_id': (((jobs_body.get('jobs') or [{}])[0]).get('local_warrant_id', '')),
            },
            'inbox': {
                'message_type_counts': (inbox_body.get('summary') or {}).get('message_type_counts', {}),
                'entry_state': ((inbox_body.get('entries') or [{}])[0]).get('state', ''),
            },
            'audit_markers': {
                'alpha_sent': 'federation_envelope_sent' in [event.get('action') for event in alpha_events],
                'beta_received': 'federation_envelope_received' in [event.get('action') for event in beta_events],
                'beta_job_created': 'federation_execution_job_created' in [event.get('action') for event in beta_events],
            },
        }


def _run_execution_settlement_loop_proof():
    try:
        port_alpha = _find_free_port()
        port_beta = _find_free_port()
        port_gamma = _find_free_port()
    except PermissionError as exc:
        raise unittest.SkipTest(f'localhost socket bind unavailable in sandbox: {exc}')

    with tempfile.TemporaryDirectory() as tmp:
        alpha = _seed_workspace_root(
            os.path.join(tmp, 'alpha'),
            org_id='org_alpha',
            user_id='user_owner_alpha',
            host_id='host_alpha',
            port=port_alpha,
            signing_secret='alpha-secret',
            peer_entries={
                'host_beta': {
                    'label': 'Beta Host',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_beta}',
                    'trust_state': 'trusted',
                    'shared_secret': 'beta-secret',
                    'admitted_org_ids': ['org_beta'],
                },
                'host_gamma': {
                    'label': 'Gamma Witness',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                    'trust_state': 'trusted',
                    'shared_secret': 'gamma-secret',
                    'witness_archive_user': 'org_gamma_user',
                    'witness_archive_pass': 'org_gamma_pass',
                    'admitted_org_ids': ['org_gamma'],
                },
            },
        )
        beta = _seed_workspace_root(
            os.path.join(tmp, 'beta'),
            org_id='org_beta',
            user_id='user_owner_beta',
            host_id='host_beta',
            port=port_beta,
            signing_secret='beta-secret',
            peer_entries={
                'host_alpha': {
                    'label': 'Alpha Host',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                    'trust_state': 'trusted',
                    'shared_secret': 'alpha-secret',
                    'admitted_org_ids': ['org_alpha'],
                },
            },
        )
        gamma = _seed_workspace_root(
            os.path.join(tmp, 'gamma'),
            org_id='org_gamma',
            user_id='user_witness_gamma',
            host_id='host_gamma',
            port=port_gamma,
            signing_secret='gamma-secret',
            host_role='witness_host',
            peer_entries={
                'host_alpha': {
                    'label': 'Alpha Host',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                    'trust_state': 'trusted',
                    'shared_secret': 'alpha-secret',
                    'admitted_org_ids': ['org_alpha'],
                },
                'host_beta': {
                    'label': 'Beta Host',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_beta}',
                    'trust_state': 'trusted',
                    'shared_secret': 'beta-secret',
                    'admitted_org_ids': ['org_beta'],
                },
            },
        )
        commitment_id = 'cmt_execution_loop'
        _seed_commitments(
            os.path.join(alpha['economy'], 'commitments.json'),
            [
                _accepted_commitment_record(
                    org_id='org_alpha',
                    commitment_id=commitment_id,
                    target_host_id='host_beta',
                    target_institution_id='org_beta',
                ),
            ],
        )
        _seed_commitments(
            os.path.join(beta['economy'], 'commitments.json'),
            [
                _accepted_commitment_record(
                    org_id='org_beta',
                    commitment_id=commitment_id,
                    target_host_id='host_alpha',
                    target_institution_id='org_alpha',
                ),
            ],
        )
        _write_json(
            os.path.join(beta['economy'], 'wallets.json'),
            {
                'wallets': {
                    'wallet_beta': {
                        'id': 'wallet_beta',
                        'verification_level': 3,
                        'verification_label': 'self_custody_verified',
                        'payout_eligible': True,
                        'status': 'active',
                    },
                },
                'verification_levels': {},
            },
        )
        _write_json(
            os.path.join(beta['economy'], 'contributors.json'),
            {
                'contributors': {
                    'contrib_beta': {
                        'id': 'contrib_beta',
                        'name': 'Beta Contributor',
                        'payout_wallet_id': 'wallet_beta',
                    },
                },
                'contribution_types': ['code'],
                'registration_requirements': {},
            },
        )
        _write_json(
            os.path.join(beta['economy'], 'payout_proposals.json'),
            {
                'proposals': {
                    'ppo_demo_beta': _executed_payout_proposal_record(
                        proposal_id='ppo_demo_beta',
                        commitment_id=commitment_id,
                    ),
                },
                'state_machine': json.loads(
                    json.dumps(
                        {
                            'states': [
                                'draft',
                                'submitted',
                                'under_review',
                                'approved',
                                'dispute_window',
                                'executed',
                                'rejected',
                                'cancelled',
                            ],
                            'transitions': {
                                'draft': ['submitted', 'cancelled'],
                                'submitted': ['under_review', 'rejected', 'cancelled'],
                                'under_review': ['approved', 'rejected'],
                                'approved': ['dispute_window'],
                                'dispute_window': ['executed', 'rejected'],
                                'executed': [],
                                'rejected': [],
                                'cancelled': [],
                            },
                            'dispute_window_hours': 72,
                            'notes': 'Seeded executed payout proof for federated execution tests.',
                        }
                    )
                ),
                'proposal_schema': {},
                'updatedAt': _now_stub(),
            },
        )

        with _run_workspace(gamma), _run_workspace(beta), _run_workspace(alpha):
            session = _issue_workspace_session(alpha)
            request_payload = {'task': 'demo'}
            warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
            status, body = _http_json(
                'POST',
                alpha['base_url'] + '/api/federation/send',
                payload={
                    'target_host_id': 'host_beta',
                    'target_org_id': 'org_beta',
                    'message_type': 'execution_request',
                    'commitment_id': commitment_id,
                    'payload': request_payload,
                    'warrant_id': warrant['warrant_id'],
                },
                headers={
                    'Authorization': f"Bearer {session['token']}",
                    'Content-Type': 'application/json',
                },
            )
            if status != 200:
                raise AssertionError(f'failed sending execution request: {status} {body}')
            delivery = body['delivery']
            jobs_body, execution_job = _wait_for_execution_job(
                beta,
                ((delivery.get('claims') or {}).get('envelope_id') or '').strip(),
            )
            job_id = execution_job['job_id']
            local_warrant_id = execution_job['local_warrant_id']
            _wait_for_warrant(beta, local_warrant_id)

            status, review_body = _http_json(
                'POST',
                beta['base_url'] + '/api/warrants/approve',
                payload={'warrant_id': local_warrant_id},
                headers={'Authorization': beta['auth_header']},
            )
            if status != 200:
                raise AssertionError(f'failed approving local warrant: {status} {review_body}')

            status, execute_body = _http_json(
                'POST',
                beta['base_url'] + '/api/federation/execution-jobs/execute',
                payload={'job_id': job_id},
                headers={
                    'Authorization': beta['auth_header'],
                    'Content-Type': 'application/json',
                },
            )
            if status != 200:
                raise AssertionError(f'failed executing job: {status} {execute_body}')

            inbox_status, inbox_body = _http_json(
                'GET',
                alpha['base_url'] + '/api/federation/inbox',
                headers={'Authorization': alpha['auth_header']},
            )
            if inbox_status != 200:
                raise AssertionError(f'failed reading sender inbox: {inbox_status} {inbox_body}')

            beta_jobs_status, beta_jobs_body = _http_json(
                'GET',
                beta['base_url'] + '/api/federation/execution-jobs',
                headers={'Authorization': beta['auth_header']},
            )
            if beta_jobs_status != 200:
                raise AssertionError(f'failed reading post-execution jobs: {beta_jobs_status} {beta_jobs_body}')

        with open(os.path.join(alpha['economy'], 'commitments.json')) as f:
            alpha_commitments = json.load(f)
        alpha_record = alpha_commitments['commitments'][commitment_id]

        with open(os.path.join(beta['economy'], 'commitments.json')) as f:
            beta_commitments = json.load(f)
        beta_record = beta_commitments['commitments'][commitment_id]

        return {
            'commitment_id': commitment_id,
            'delivery': {
                'envelope_id': (((delivery.get('claims') or {}).get('envelope_id')) or ''),
                'receipt_id': (((delivery.get('receipt') or {}).get('receipt_id')) or ''),
            },
            'execution_job': {
                'job_id': job_id,
                'local_warrant_id': local_warrant_id,
                'state': ((execute_body.get('execution_job') or {}).get('state', '')),
                'proposal_id': (((execute_body.get('execution_job') or {}).get('execution_refs') or {}).get('proposal_id', '')),
            },
            'settlement_notice': {
                'envelope_id': ((execute_body.get('settlement_notice') or {}).get('envelope_id', '')),
                'message_type': ((execute_body.get('settlement_notice') or {}).get('message_type', '')),
            },
            'sender_inbox': {
                'processed': (inbox_body.get('summary') or {}).get('processed', 0),
                'message_type_counts': (inbox_body.get('summary') or {}).get('message_type_counts', {}),
            },
            'receiver_jobs': {
                'executed': (beta_jobs_body.get('summary') or {}).get('executed', 0),
                'ready': (beta_jobs_body.get('summary') or {}).get('ready', 0),
            },
            'commitment_states': {
                'sender_state': alpha_record.get('state', ''),
                'receiver_delivery_ref_message_type': ((beta_record.get('delivery_refs') or [{}])[0]).get('message_type', ''),
            },
        }


def _run_base_usdc_x402_settlement_proof():
    try:
        port_alpha = _find_free_port()
        port_beta = _find_free_port()
    except PermissionError as exc:
        raise unittest.SkipTest(f'localhost socket bind unavailable in sandbox: {exc}')

    with tempfile.TemporaryDirectory() as tmp:
        alpha = _seed_workspace_root(
            os.path.join(tmp, 'alpha'),
            org_id='org_alpha',
            user_id='user_owner_alpha',
            host_id='host_alpha',
            port=port_alpha,
            signing_secret='alpha-secret',
            settlement_adapters=['base_usdc_x402'],
            peer_entries={
                'host_beta': {
                    'label': 'Beta Host',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_beta}',
                    'trust_state': 'trusted',
                    'shared_secret': 'beta-secret',
                    'admitted_org_ids': ['org_beta'],
                },
            },
        )
        beta = _seed_workspace_root(
            os.path.join(tmp, 'beta'),
            org_id='org_beta',
            user_id='user_owner_beta',
            host_id='host_beta',
            port=port_beta,
            signing_secret='beta-secret',
            settlement_adapters=['base_usdc_x402'],
            peer_entries={
                'host_alpha': {
                    'label': 'Alpha Host',
                    'transport': 'https',
                    'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                    'trust_state': 'trusted',
                    'shared_secret': 'alpha-secret',
                    'admitted_org_ids': ['org_alpha'],
                },
            },
        )
        commitment_id = 'cmt_base_x402_settlement'
        _seed_commitments(
            os.path.join(alpha['economy'], 'commitments.json'),
            [
                _accepted_commitment_record(
                    org_id='org_alpha',
                    commitment_id=commitment_id,
                    target_host_id='host_beta',
                    target_institution_id='org_beta',
                ),
            ],
        )
        _seed_commitments(
            os.path.join(beta['economy'], 'commitments.json'),
            [
                _accepted_commitment_record(
                    org_id='org_beta',
                    commitment_id=commitment_id,
                    target_host_id='host_alpha',
                    target_institution_id='org_alpha',
                ),
            ],
        )
        adapter_store = {
            'default_payout_adapter': 'base_usdc_x402',
            'adapters': {
                'base_usdc_x402': {
                    'status': 'active',
                    'payout_execution_enabled': True,
                    'verification_ready': True,
                },
            },
        }
        _write_json(os.path.join(alpha['economy'], 'settlement_adapters.json'), adapter_store)
        _write_json(os.path.join(beta['economy'], 'settlement_adapters.json'), adapter_store)

        with _run_workspace(beta), _run_workspace(alpha):
            session = _issue_workspace_session(alpha)
            status, body = _http_json(
                'POST',
                alpha['base_url'] + '/api/federation/send',
                payload={
                    'target_host_id': 'host_beta',
                    'target_org_id': 'org_beta',
                    'message_type': 'settlement_notice',
                    'commitment_id': commitment_id,
                    'payload': {
                        'proposal_id': 'ppo_chain_demo',
                        'tx_ref': 'tx_base_x402_demo',
                        'tx_hash': '0xbase123',
                        'settlement_adapter': 'base_usdc_x402',
                        'settlement_adapter_contract_snapshot': _base_usdc_x402_contract_snapshot(),
                        'settlement_adapter_contract_digest': _contract_digest(
                            _base_usdc_x402_contract_snapshot()
                        ),
                        'proof': {
                            'reference': 'base://receipt/demo',
                            'payer_wallet': '0xabc123',
                            'verification_attestation': {
                                'type': 'x402_settlement_verifier',
                                'reference': 'attest://base/demo',
                            },
                        },
                    },
                },
                headers={
                    'Authorization': f"Bearer {session['token']}",
                    'Content-Type': 'application/json',
                },
            )
            if status != 200:
                raise AssertionError(f'failed sending x402 settlement notice: {status} {body}')
            processing = ((body.get('delivery') or {}).get('response') or {}).get('processing', {})

        with open(os.path.join(beta['economy'], 'commitments.json')) as f:
            beta_commitments = json.load(f)
        beta_ref = beta_commitments['commitments'][commitment_id]['settlement_refs'][0]
        return {
            'commitment_id': commitment_id,
            'processing': {
                'applied': bool(processing.get('applied')),
                'reason': processing.get('reason', ''),
                'settlement_adapter': ((processing.get('settlement_ref') or {}).get('settlement_adapter', '')),
                'proof_type': ((processing.get('settlement_ref') or {}).get('proof_type', '')),
                'verification_state': ((processing.get('settlement_ref') or {}).get('verification_state', '')),
                'finality_state': ((processing.get('settlement_ref') or {}).get('finality_state', '')),
                'settlement_path': ((((processing.get('settlement_ref') or {}).get('settlement_adapter_contract') or {}).get('settlement_path')) or ''),
                'accepted_attestation_type': (((processing.get('settlement_ref') or {}).get('proof') or {}).get('verification_attestation', {}).get('type', '')),
            },
            'recorded_ref': {
                'settlement_adapter': beta_ref.get('settlement_adapter', ''),
                'proof_type': beta_ref.get('proof_type', ''),
                'tx_hash': beta_ref.get('tx_hash', ''),
            },
        }


class FederationTests(unittest.TestCase):
    def test_issue_and_validate_self_signed_envelope(self):
        from federation import FederationAuthority
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            role='control_host',
            federation_enabled=True,
            peer_transport='https',
        )
        authority = FederationAuthority(host, signing_secret='alpha-secret')
        envelope = authority.issue(
            'org_alpha',
            'host_alpha',
            'org_alpha',
            'execution_request',
            payload={'task': 'demo'},
        )
        claims = authority.validate(
            envelope,
            payload={'task': 'demo'},
            expected_target_host_id='host_alpha',
            expected_target_org_id='org_alpha',
            expected_boundary_name='federation_gateway',
        )
        self.assertEqual(claims.source_host_id, 'host_alpha')
        self.assertEqual(claims.target_institution_id, 'org_alpha')

    def test_validate_rejects_wrong_target_host(self):
        from federation import FederationAuthority, FederationValidationError
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            peer_transport='https',
        )
        authority = FederationAuthority(host, signing_secret='alpha-secret')
        envelope = authority.issue(
            'org_alpha',
            'host_beta',
            'org_beta',
            'execution_request',
            payload={'task': 'demo'},
        )
        with self.assertRaises(FederationValidationError):
            authority.validate(
                envelope,
                payload={'task': 'demo'},
                expected_target_host_id='host_alpha',
            )

    def test_accept_rejects_replay_across_restart(self):
        from federation import FederationAuthority, ReplayStore, FederationReplayError
        from runtime_host import default_host_identity

        with tempfile.TemporaryDirectory() as tmp:
            replay_path = os.path.join(tmp, 'federation_replay.log')
            host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            issuer = FederationAuthority(host, signing_secret='alpha-secret')
            envelope = issuer.issue(
                'org_alpha',
                'host_alpha',
                'org_alpha',
                'execution_request',
                payload={'task': 'demo'},
            )

            receiver1 = FederationAuthority(
                host,
                signing_secret='alpha-secret',
                replay_store=ReplayStore(replay_path),
            )
            claims = receiver1.accept(
                envelope,
                payload={'task': 'demo'},
                expected_target_host_id='host_alpha',
                expected_target_org_id='org_alpha',
            )
            self.assertTrue(claims.envelope_id.startswith('fed_'))

            receiver2 = FederationAuthority(
                host,
                signing_secret='alpha-secret',
                replay_store=ReplayStore(replay_path),
            )
            with self.assertRaises(FederationReplayError):
                receiver2.accept(
                    envelope,
                    payload={'task': 'demo'},
                    expected_target_host_id='host_alpha',
                    expected_target_org_id='org_alpha',
                )

    def test_validate_uses_trusted_peer_registry(self):
        from federation import FederationAuthority, load_peer_registry
        from runtime_host import default_host_identity

        with tempfile.TemporaryDirectory() as tmp:
            peers_path = os.path.join(tmp, 'federation_peers.json')
            with open(peers_path, 'w') as f:
                json.dump({
                    'host_id': 'host_beta',
                    'peers': {
                        'host_alpha': {
                            'label': 'Alpha Host',
                            'transport': 'https',
                            'endpoint_url': 'http://127.0.0.1:19011',
                            'trust_state': 'trusted',
                            'shared_secret': 'alpha-secret',
                            'admitted_org_ids': ['org_alpha'],
                        }
                    },
                }, f)

            source_host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            target_host = default_host_identity(
                host_id='host_beta',
                role='witness_host',
                federation_enabled=True,
                peer_transport='https',
            )
            sender = FederationAuthority(source_host, signing_secret='alpha-secret')
            receiver = FederationAuthority(
                target_host,
                signing_secret='beta-secret',
                peer_registry=load_peer_registry(peers_path, host_identity=target_host),
            )
            envelope = sender.issue(
                'org_alpha',
                'host_beta',
                'org_beta',
                'settlement_notice',
                payload={'tx_ref': '0xabc'},
            )
            claims = receiver.validate(
                envelope,
                payload={'tx_ref': '0xabc'},
                expected_target_host_id='host_beta',
                expected_target_org_id='org_beta',
            )
            self.assertEqual(claims.source_host_id, 'host_alpha')
            self.assertEqual(claims.message_type, 'settlement_notice')

    def test_validate_accepts_court_notice_from_suspended_peer(self):
        from federation import FederationAuthority, load_peer_registry
        from runtime_host import default_host_identity

        with tempfile.TemporaryDirectory() as tmp:
            peers_path = os.path.join(tmp, 'federation_peers.json')
            with open(peers_path, 'w') as f:
                json.dump({
                    'host_id': 'host_beta',
                    'peers': {
                        'host_alpha': {
                            'label': 'Alpha Host',
                            'transport': 'https',
                            'endpoint_url': 'http://127.0.0.1:19011',
                            'trust_state': 'suspended',
                            'shared_secret': 'alpha-secret',
                            'admitted_org_ids': ['org_alpha'],
                        }
                    },
                }, f)

            source_host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            target_host = default_host_identity(
                host_id='host_beta',
                federation_enabled=True,
                peer_transport='https',
            )
            sender = FederationAuthority(source_host, signing_secret='alpha-secret')
            receiver = FederationAuthority(
                target_host,
                signing_secret='beta-secret',
                peer_registry=load_peer_registry(peers_path, host_identity=target_host),
            )
            envelope = sender.issue(
                'org_alpha',
                'host_beta',
                'org_beta',
                'court_notice',
                payload={
                    'court_decision': 'stay',
                    'sender_warrant_id': 'war_sender',
                    'local_warrant_id': 'war_local',
                    'source_execution_envelope_id': 'fed_exec_demo',
                    'target_host_id': 'host_beta',
                    'target_institution_id': 'org_beta',
                    'note': 'Receiver stayed local warrant',
                    'metadata': {},
                },
                warrant_id='war_sender',
            )
            claims = receiver.validate(
                envelope,
                payload={
                    'court_decision': 'stay',
                    'sender_warrant_id': 'war_sender',
                    'local_warrant_id': 'war_local',
                    'source_execution_envelope_id': 'fed_exec_demo',
                    'target_host_id': 'host_beta',
                    'target_institution_id': 'org_beta',
                    'note': 'Receiver stayed local warrant',
                    'metadata': {},
                },
                expected_target_host_id='host_beta',
                expected_target_org_id='org_beta',
            )
            self.assertEqual(claims.source_host_id, 'host_alpha')
            self.assertEqual(claims.message_type, 'court_notice')

    def test_load_peer_registry_includes_endpoint_url(self):
        from federation import load_peer_registry
        from runtime_host import default_host_identity

        with tempfile.TemporaryDirectory() as tmp:
            peers_path = os.path.join(tmp, 'federation_peers.json')
            with open(peers_path, 'w') as f:
                json.dump({
                    'host_id': 'host_alpha',
                    'peers': {
                        'host_beta': {
                            'label': 'Beta Host',
                            'transport': 'https',
                            'base_url': 'http://127.0.0.1:19012',
                            'trust_state': 'trusted',
                            'shared_secret': 'beta-secret',
                        }
                    },
                }, f)

            registry = load_peer_registry(
                peers_path,
                host_identity=default_host_identity(host_id='host_alpha'),
            )
            peer = registry['peers']['host_beta']
            self.assertEqual(peer.endpoint_url, 'http://127.0.0.1:19012')
            self.assertEqual(peer.receive_url, 'http://127.0.0.1:19012/api/federation/receive')

    def test_deliver_posts_to_trusted_peer_endpoint(self):
        from federation import FederationAuthority, FederationPeer
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            peer_transport='https',
        )
        authority = FederationAuthority(
            host,
            signing_secret='alpha-secret',
            peer_registry={
                'source': 'test',
                'host_id': 'host_alpha',
                'trusted_peer_ids': ['host_beta'],
                'peers': {
                    'host_beta': FederationPeer(
                        'host_beta',
                        transport='https',
                        endpoint_url='http://127.0.0.1:19013',
                        trust_state='trusted',
                        shared_secret='beta-secret',
                        admitted_org_ids=['org_beta'],
                    ),
                },
            },
        )

        calls = {}

        def fake_post(url, data):
            body_b64 = data['envelope'].split('.', 1)[0]
            padding = '=' * ((4 - len(body_b64) % 4) % 4)
            envelope_payload = json.loads(
                base64.urlsafe_b64decode(body_b64 + padding).decode('utf-8')
            )
            calls['url'] = url
            calls['data'] = data
            return {
                'accepted': True,
                'receipt': {
                    'receipt_id': 'fedrcpt_demo',
                    'envelope_id': envelope_payload['envelope_id'],
                    'accepted_at': '2026-03-22T00:00:00Z',
                    'receiver_host_id': 'host_beta',
                    'receiver_institution_id': 'org_beta',
                    'message_type': envelope_payload['message_type'],
                    'boundary_name': envelope_payload['boundary_name'],
                    'identity_model': 'signed_host_service',
                },
            }

        result = authority.deliver(
            'host_beta',
            'org_alpha',
            'org_beta',
            'execution_request',
            payload={'task': 'demo'},
            http_post=fake_post,
            http_get=lambda _url: {
                'host_identity': {'host_id': 'host_beta'},
                'admission': {'admitted_org_ids': ['org_beta']},
                'service_registry': {
                    'federation_gateway': {
                        'identity_model': 'signed_host_service',
                        'supports_institution_routing': True,
                    },
                },
                'federation': {
                    'enabled': True,
                    'boundary_name': 'federation_gateway',
                    'identity_model': 'signed_host_service',
                },
            },
        )
        self.assertEqual(calls['url'], 'http://127.0.0.1:19013/api/federation/receive')
        self.assertIn('envelope', calls['data'])
        self.assertEqual(calls['data']['payload'], {'task': 'demo'})
        self.assertTrue(result['response']['accepted'])
        self.assertEqual(result['receipt']['receipt_id'], 'fedrcpt_demo')
        self.assertEqual(result['response']['receipt']['receipt_id'], 'fedrcpt_demo')
        self.assertEqual(result['peer']['host_id'], 'host_beta')
        self.assertEqual(result['claims']['target_host_id'], 'host_beta')
        self.assertEqual(result['claims']['target_institution_id'], 'org_beta')
        self.assertEqual(result['claims']['message_type'], 'execution_request')

    def test_deliver_rejects_receipt_with_wrong_receiver_host(self):
        from federation import FederationAuthority, FederationDeliveryError, FederationPeer
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            peer_transport='https',
        )
        authority = FederationAuthority(
            host,
            signing_secret='alpha-secret',
            peer_registry={
                'source': 'test',
                'host_id': 'host_alpha',
                'trusted_peer_ids': ['host_beta'],
                'peers': {
                    'host_beta': FederationPeer(
                        'host_beta',
                        transport='https',
                        endpoint_url='http://127.0.0.1:19013',
                        trust_state='trusted',
                        shared_secret='beta-secret',
                        admitted_org_ids=['org_beta'],
                    ),
                },
            },
        )

        with self.assertRaises(FederationDeliveryError):
            authority.deliver(
                'host_beta',
                'org_alpha',
                'org_beta',
                'execution_request',
                payload={'task': 'demo'},
                http_post=lambda _url, _data: {
                    'accepted': True,
                    'receipt': {
                        'receipt_id': 'fedrcpt_bad',
                        'envelope_id': 'fed_wrong',
                        'receiver_host_id': 'host_wrong',
                        'receiver_institution_id': 'org_beta',
                    },
                },
                http_get=lambda _url: {
                    'host_identity': {'host_id': 'host_beta'},
                    'admission': {'admitted_org_ids': ['org_beta']},
                    'service_registry': {
                        'federation_gateway': {
                            'identity_model': 'signed_host_service',
                            'supports_institution_routing': True,
                        },
                    },
                    'federation': {
                        'enabled': True,
                        'boundary_name': 'federation_gateway',
                        'identity_model': 'signed_host_service',
                    },
                },
            )

    def test_deliver_rejects_peer_without_endpoint_url(self):
        from federation import FederationAuthority, FederationDeliveryError, FederationPeer
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            peer_transport='https',
        )
        authority = FederationAuthority(
            host,
            signing_secret='alpha-secret',
            peer_registry={
                'source': 'test',
                'host_id': 'host_alpha',
                'trusted_peer_ids': ['host_beta'],
                'peers': {
                    'host_beta': FederationPeer(
                        'host_beta',
                        transport='https',
                        trust_state='trusted',
                        shared_secret='beta-secret',
                    ),
                },
            },
        )

        with self.assertRaises(FederationDeliveryError) as ctx:
            authority.deliver(
                'host_beta',
                'org_alpha',
                'org_beta',
                'execution_request',
                payload={'task': 'demo'},
            )
        self.assertEqual(ctx.exception.peer_host_id, '')
        self.assertEqual(ctx.exception.response, None)

    def test_deliver_failure_carries_claims(self):
        from federation import FederationAuthority, FederationDeliveryError, FederationPeer
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            peer_transport='https',
        )
        authority = FederationAuthority(
            host,
            signing_secret='alpha-secret',
            peer_registry={
                'source': 'test',
                'host_id': 'host_alpha',
                'trusted_peer_ids': ['host_beta'],
                'peers': {
                    'host_beta': FederationPeer(
                        'host_beta',
                        transport='https',
                        endpoint_url='http://127.0.0.1:19013',
                        trust_state='trusted',
                        shared_secret='beta-secret',
                        admitted_org_ids=['org_beta'],
                    ),
                },
            },
        )

        def fake_post(_url, _data):
            raise RuntimeError('network down')

        with self.assertRaises(FederationDeliveryError) as ctx:
            authority.deliver(
                'host_beta',
                'org_alpha',
                'org_beta',
                'execution_request',
                payload={'task': 'demo'},
                http_post=fake_post,
                http_get=lambda _url: {
                    'host_identity': {'host_id': 'host_beta'},
                    'admission': {'admitted_org_ids': ['org_beta']},
                    'service_registry': {
                        'federation_gateway': {
                            'identity_model': 'signed_host_service',
                            'supports_institution_routing': True,
                        },
                    },
                    'federation': {
                        'enabled': True,
                        'boundary_name': 'federation_gateway',
                        'identity_model': 'signed_host_service',
                    },
                },
            )

        self.assertEqual(ctx.exception.peer_host_id, 'host_beta')
        self.assertTrue(ctx.exception.envelope)
        self.assertEqual(ctx.exception.claims.target_host_id, 'host_beta')
        self.assertEqual(ctx.exception.claims.target_institution_id, 'org_beta')
        self.assertEqual(ctx.exception.claims.message_type, 'execution_request')

    def test_deliver_round_trips_over_http_between_two_hosts(self):
        from federation import FederationAuthority, FederationPeer
        from runtime_host import default_host_identity

        receiver_host = default_host_identity(
            host_id='host_beta',
            federation_enabled=True,
            peer_transport='https',
        )
        receiver = FederationAuthority(
            receiver_host,
            signing_secret='beta-secret',
            peer_registry={
                'source': 'test',
                'host_id': 'host_beta',
                'trusted_peer_ids': ['host_alpha'],
                'peers': {
                    'host_alpha': FederationPeer(
                        'host_alpha',
                        transport='https',
                        endpoint_url='http://127.0.0.1:0',
                        trust_state='trusted',
                        shared_secret='alpha-secret',
                        admitted_org_ids=['org_alpha'],
                    ),
                },
            },
        )
        received_claims = []

        class PeerHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path != '/api/federation/manifest':
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({
                    'manifest_version': 1,
                    'host_identity': {'host_id': 'host_beta'},
                    'admission': {'admitted_org_ids': ['org_beta']},
                    'service_registry': {
                        'federation_gateway': {
                            'identity_model': 'signed_host_service',
                            'supports_institution_routing': True,
                        },
                    },
                    'federation': {
                        'enabled': True,
                        'boundary_name': 'federation_gateway',
                        'identity_model': 'signed_host_service',
                    },
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != '/api/federation/receive':
                    self.send_response(404)
                    self.end_headers()
                    return
                length = int(self.headers.get('Content-Length', '0') or 0)
                payload = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                claims = receiver.accept(
                    payload.get('envelope', ''),
                    payload=payload.get('payload'),
                    expected_target_host_id='host_beta',
                    expected_target_org_id='org_beta',
                    expected_boundary_name='federation_gateway',
                )
                received_claims.append(claims.to_dict())
                body = json.dumps({
                    'accepted': True,
                    'receipt': {
                        'receipt_id': 'fedrcpt_http',
                        'envelope_id': claims.envelope_id,
                        'accepted_at': '2026-03-22T00:00:00Z',
                        'receiver_host_id': 'host_beta',
                        'receiver_institution_id': 'org_beta',
                        'message_type': claims.message_type,
                        'boundary_name': claims.boundary_name,
                        'identity_model': 'signed_host_service',
                    },
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), PeerHandler)
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            sender_host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            authority = FederationAuthority(
                sender_host,
                signing_secret='alpha-secret',
                peer_registry={
                    'source': 'test',
                    'host_id': 'host_alpha',
                    'trusted_peer_ids': ['host_beta'],
                    'peers': {
                        'host_beta': FederationPeer(
                            'host_beta',
                            transport='https',
                            endpoint_url=f'http://127.0.0.1:{server.server_address[1]}',
                            trust_state='trusted',
                            shared_secret='beta-secret',
                            admitted_org_ids=['org_beta'],
                        ),
                    },
                },
            )
            result = authority.deliver(
                'host_beta',
                'org_alpha',
                'org_beta',
                'execution_request',
                payload={'task': 'demo'},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result['receipt']['receipt_id'], 'fedrcpt_http')
        self.assertEqual(result['receipt']['receiver_host_id'], 'host_beta')
        self.assertEqual(result['claims']['target_host_id'], 'host_beta')
        self.assertEqual(len(received_claims), 1)
        self.assertEqual(received_claims[0]['source_host_id'], 'host_alpha')
        self.assertEqual(received_claims[0]['target_institution_id'], 'org_beta')

    def test_deliver_rejects_http_manifest_target_mismatch(self):
        from federation import FederationAuthority, FederationDeliveryError, FederationPeer
        from runtime_host import default_host_identity

        class ManifestOnlyHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path != '/api/federation/manifest':
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({
                    'manifest_version': 1,
                    'host_identity': {'host_id': 'host_beta'},
                    'admission': {'admitted_org_ids': ['org_other']},
                    'service_registry': {
                        'federation_gateway': {
                            'identity_model': 'signed_host_service',
                            'supports_institution_routing': True,
                        },
                    },
                    'federation': {
                        'enabled': True,
                        'boundary_name': 'federation_gateway',
                        'identity_model': 'signed_host_service',
                    },
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.send_response(500)
                self.end_headers()

        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), ManifestOnlyHandler)
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            authority = FederationAuthority(
                host,
                signing_secret='alpha-secret',
                peer_registry={
                    'source': 'test',
                    'host_id': 'host_alpha',
                    'trusted_peer_ids': ['host_beta'],
                    'peers': {
                        'host_beta': FederationPeer(
                            'host_beta',
                            transport='https',
                            endpoint_url=f'http://127.0.0.1:{server.server_address[1]}',
                            trust_state='trusted',
                            shared_secret='beta-secret',
                            admitted_org_ids=['org_beta'],
                        ),
                    },
                },
            )
            with self.assertRaises(FederationDeliveryError):
                authority.deliver(
                    'host_beta',
                    'org_alpha',
                    'org_beta',
                    'execution_request',
                    payload={'task': 'demo'},
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_workspace_federation_send_round_trips_between_two_hosts_with_session_audit(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                session_id = session['session_id']
                request_payload = {'task': 'demo'}
                warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                delivery = body['delivery']
                self.assertEqual(delivery['receipt']['receiver_host_id'], 'host_beta')
                self.assertEqual(delivery['receipt']['receiver_institution_id'], 'org_beta')
                self.assertEqual(delivery['claims']['session_id'], session_id)
                self.assertEqual(delivery['claims']['actor_id'], 'user_owner_alpha')
                self.assertEqual(delivery['claims']['warrant_id'], warrant['warrant_id'])
                inbox_status, inbox_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['total'], 1)
                self.assertEqual(inbox_body['summary']['message_type_counts'], {
                    'execution_request': 1,
                })
                self.assertEqual(inbox_body['entries'][0]['envelope_id'], delivery['claims']['envelope_id'])
                self.assertEqual(inbox_body['entries'][0]['receipt_id'], delivery['receipt']['receipt_id'])
                self.assertEqual(inbox_body['entries'][0]['warrant_id'], warrant['warrant_id'])
                self.assertEqual(inbox_body['entries'][0]['payload'], request_payload)
                self.assertEqual(inbox_body['entries'][0]['state'], 'processed')

                jobs_status, jobs_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/execution-jobs',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(jobs_status, 200, jobs_body)
                self.assertEqual(jobs_body['summary']['total'], 1)
                self.assertEqual(jobs_body['summary']['pending_local_warrant'], 1)
                self.assertEqual(jobs_body['summary']['message_type_counts'], {
                    'execution_request': 1,
                })
                self.assertEqual(jobs_body['jobs'][0]['envelope_id'], delivery['claims']['envelope_id'])
                self.assertEqual(jobs_body['jobs'][0]['receipt_id'], delivery['receipt']['receipt_id'])
                self.assertEqual(jobs_body['jobs'][0]['state'], 'pending_local_warrant')
                self.assertEqual(jobs_body['jobs'][0]['local_warrant']['court_review_state'], 'pending_review')
                self.assertEqual(jobs_body['jobs'][0]['local_warrant']['execution_state'], 'ready')
                self.assertEqual(jobs_body['jobs'][0]['local_warrant']['warrant_id'], jobs_body['jobs'][0]['local_warrant_id'])
                local_warrant_id = jobs_body['jobs'][0]['local_warrant_id']

                status, review_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/warrants/approve',
                    payload={'warrant_id': local_warrant_id},
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(status, 200, review_body)
                self.assertEqual(review_body['warrant']['warrant_id'], local_warrant_id)
                self.assertEqual(review_body['warrant']['court_review_state'], 'approved')
                self.assertEqual(review_body['execution_job']['job_id'], jobs_body['jobs'][0]['job_id'])
                self.assertEqual(review_body['execution_job']['state'], 'ready')

                jobs_status, jobs_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/execution-jobs',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(jobs_status, 200, jobs_body)
                self.assertEqual(jobs_body['summary']['ready'], 1)
                self.assertEqual(jobs_body['summary']['pending_local_warrant'], 0)
                self.assertEqual(jobs_body['jobs'][0]['state'], 'ready')
                self.assertEqual(jobs_body['jobs'][0]['metadata']['review_decision'], 'approve')
                self.assertEqual(jobs_body['jobs'][0]['local_warrant']['court_review_state'], 'approved')

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            sent = [event for event in alpha_events if event.get('action') == 'federation_envelope_sent']
            received = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_received'
            ]
            self.assertTrue(sent)
            self.assertTrue(received)
            self.assertEqual(sent[-1].get('session_id'), session_id)
            self.assertEqual(received[-1].get('session_id'), session_id)
            self.assertEqual(sent[-1]['details']['receiver_host_id'], 'host_beta')
            self.assertEqual(sent[-1]['details']['warrant_id'], warrant['warrant_id'])
            self.assertEqual(received[-1]['details']['source_host_id'], 'host_alpha')
            self.assertEqual(received[-1]['details']['warrant_id'], warrant['warrant_id'])
            self.assertEqual(received[-1]['agent_id'], 'user_owner_alpha')

            warrants_path = os.path.join(alpha['economy'], 'warrants.json')
            with open(warrants_path) as f:
                warrant_store = json.load(f)
            warrant_record = warrant_store['warrants'][warrant['warrant_id']]
            self.assertEqual(warrant_record['execution_state'], 'executed')
            self.assertEqual(
                warrant_record['execution_refs']['receipt_id'],
                delivery['receipt']['receipt_id'],
            )

    def test_workspace_handoff_dispatch_queue_delivers_remote_execution_request(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)

                federation_status, federation_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/federation',
                    headers={'Authorization': f"Bearer {session['token']}"},
                )
                self.assertEqual(federation_status, 200, federation_body)
                remote_handoff = next(
                    item for item in federation_body['handoff_preview']['handoff_candidates']
                    if item['requested_org_id'] == 'org_beta'
                )
                self.assertEqual(remote_handoff['route_kind'], 'remote')
                self.assertTrue(remote_handoff['dispatch_ready'])
                handoff_id = remote_handoff['handoff_id']

                acknowledge_status, acknowledge_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/handoff-preview-queue/acknowledge',
                    payload={'handoff_id': handoff_id, 'note': 'operator reviewed'},
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(acknowledge_status, 200, acknowledge_body)
                dispatch_id = acknowledge_body['dispatch_record']['dispatch_id']
                self.assertEqual(dispatch_id, handoff_id)
                self.assertEqual(acknowledge_body['dispatch_record']['state'], 'dispatchable')

                request_payload = {'task': 'remote handoff capsule'}
                warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                dispatch_status, dispatch_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/handoff-dispatch-queue/run',
                    payload={
                        'dispatch_id': dispatch_id,
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                        'note': 'send queued handoff to remote host',
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(dispatch_status, 200, dispatch_body)
                self.assertEqual(dispatch_body['dispatch_runner'], 'remote_http_federation_runner')
                self.assertEqual(dispatch_body['dispatch_record']['state'], 'dispatched')
                self.assertEqual(dispatch_body['dispatch_record']['dispatch_runner'], 'remote_http_federation_runner')
                self.assertEqual(dispatch_body['delivery']['receipt']['receiver_host_id'], 'host_beta')
                self.assertEqual(dispatch_body['delivery']['receipt']['receiver_institution_id'], 'org_beta')
                self.assertEqual(dispatch_body['execution_job']['state'], 'pending_local_warrant')
                self.assertEqual(dispatch_body['execution_job']['target_host_id'], 'host_beta')
                self.assertEqual(dispatch_body['dispatch_record']['delivery_snapshot']['receipt']['receipt_id'], dispatch_body['delivery']['receipt']['receipt_id'])
                self.assertEqual(dispatch_body['dispatch_record']['execution_job_id'], dispatch_body['execution_job']['job_id'])

                queue_status, queue_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/federation/handoff-dispatch-queue',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(queue_status, 200, queue_body)
                record = next(
                    item for item in queue_body['handoff_dispatch_records']
                    if item['dispatch_id'] == dispatch_id
                )
                self.assertEqual(record['state'], 'dispatched')
                self.assertEqual(record['dispatch_runner'], 'remote_http_federation_runner')
                self.assertEqual(record['delivery_snapshot']['claims']['envelope_id'], dispatch_body['delivery']['claims']['envelope_id'])
                self.assertEqual(record['execution_job_state'], 'pending_local_warrant')

                jobs_status, jobs_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/execution-jobs',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(jobs_status, 200, jobs_body)
                self.assertEqual(jobs_body['summary']['total'], 1)
                self.assertEqual(jobs_body['summary']['pending_local_warrant'], 1)
                self.assertEqual(jobs_body['jobs'][0]['envelope_id'], dispatch_body['delivery']['claims']['envelope_id'])
                self.assertEqual(jobs_body['jobs'][0]['receipt_id'], dispatch_body['delivery']['receipt']['receipt_id'])
                self.assertEqual(jobs_body['jobs'][0]['state'], 'pending_local_warrant')
                self.assertEqual(jobs_body['jobs'][0]['local_warrant']['court_review_state'], 'pending_review')

                inbox_status, inbox_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['message_type_counts'], {'execution_request': 1})
                self.assertEqual(inbox_body['entries'][0]['envelope_id'], dispatch_body['delivery']['claims']['envelope_id'])

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            sent = [event for event in alpha_events if event.get('action') == 'federation_envelope_sent']
            received = [event for event in beta_events if event.get('action') == 'federation_envelope_received']
            created = [event for event in beta_events if event.get('action') == 'federation_execution_job_created']
            self.assertTrue(sent)
            self.assertTrue(received)
            self.assertTrue(created)
            self.assertEqual(sent[-1]['details']['receiver_host_id'], 'host_beta')
            self.assertEqual(received[-1]['details']['source_host_id'], 'host_alpha')

    def test_workspace_federation_court_notice_round_trip_stays_sender_warrant(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            commitment_id = 'cmt_court_notice'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )

            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                request_payload = {'task': 'demo', 'phase': 'receiver_review'}
                warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'commitment_id': commitment_id,
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)

                jobs_status, jobs_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/execution-jobs',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(jobs_status, 200, jobs_body)
                self.assertEqual(jobs_body['summary']['pending_local_warrant'], 1)
                job_id = jobs_body['jobs'][0]['job_id']
                local_warrant_id = jobs_body['jobs'][0]['local_warrant_id']

                status, review_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/warrants/stay',
                    payload={'warrant_id': local_warrant_id, 'note': 'Receiver hold pending local review'},
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(status, 200, review_body)
                self.assertEqual(review_body['warrant']['court_review_state'], 'stayed')
                self.assertEqual(review_body['execution_job']['job_id'], job_id)
                self.assertEqual(review_body['execution_job']['state'], 'blocked')
                self.assertTrue(review_body['court_notice']['applied'])
                self.assertEqual(review_body['court_notice']['court_notice']['decision'], 'stay')

                alpha_inbox_status, alpha_inbox_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_inbox_status, 200, alpha_inbox_body)
                self.assertEqual(alpha_inbox_body['summary']['processed'], 1)
                self.assertEqual(alpha_inbox_body['summary']['message_type_counts'], {'court_notice': 1})
                self.assertEqual(alpha_inbox_body['entries'][0]['message_type'], 'court_notice')

                alpha_warrants_status, alpha_warrants_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/warrants',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_warrants_status, 200, alpha_warrants_body)
                sender_warrant = next(
                    item for item in alpha_warrants_body['warrants']
                    if item['warrant_id'] == warrant['warrant_id']
                )
                self.assertEqual(sender_warrant['court_review_state'], 'stayed')
                self.assertEqual(sender_warrant['execution_state'], 'ready')
                self.assertEqual(sender_warrant['reviewed_by'], 'user_owner_beta')

                alpha_commit_status, alpha_commit_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/commitments',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_commit_status, 200, alpha_commit_body)
                alpha_commitment = next(
                    item for item in alpha_commit_body['commitments']
                    if item['commitment_id'] == commitment_id
                )
                court_notice_ref = next(
                    ref for ref in alpha_commitment['delivery_refs']
                    if ref['message_type'] == 'court_notice'
                )
                self.assertEqual(court_notice_ref['warrant_id'], warrant['warrant_id'])
                self.assertEqual(court_notice_ref['local_warrant_id'], local_warrant_id)
                self.assertEqual(court_notice_ref['court_decision'], 'stay')
                self.assertEqual(court_notice_ref['source_execution_envelope_id'], body['delivery']['claims']['envelope_id'])

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            self.assertTrue(
                any(event.get('action') == 'federation_court_notice_applied' for event in alpha_events)
            )
            self.assertTrue(
                any(event.get('action') == 'federation_court_notice_sent' for event in beta_events)
            )

    def test_workspace_federation_court_notice_round_trip_syncs_sender_approve_and_revoke(self):
        decision_expectations = {
            'approve': {
                'sender_review_state': 'approved',
                'receiver_job_state': 'ready',
            },
            'revoke': {
                'sender_review_state': 'revoked',
                'receiver_job_state': 'rejected',
            },
        }

        for decision, expected in decision_expectations.items():
            with self.subTest(decision=decision):
                try:
                    port_alpha = _find_free_port()
                    port_beta = _find_free_port()
                except PermissionError as exc:
                    self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

                with tempfile.TemporaryDirectory() as tmp:
                    alpha = _seed_workspace_root(
                        os.path.join(tmp, 'alpha'),
                        org_id='org_alpha',
                        user_id='user_owner_alpha',
                        host_id='host_alpha',
                        port=port_alpha,
                        signing_secret='alpha-secret',
                        peer_entries={
                            'host_beta': {
                                'label': 'Beta Host',
                                'transport': 'https',
                                'endpoint_url': f'http://127.0.0.1:{port_beta}',
                                'trust_state': 'trusted',
                                'shared_secret': 'beta-secret',
                                'admitted_org_ids': ['org_beta'],
                            },
                        },
                    )
                    beta = _seed_workspace_root(
                        os.path.join(tmp, 'beta'),
                        org_id='org_beta',
                        user_id='user_owner_beta',
                        host_id='host_beta',
                        port=port_beta,
                        signing_secret='beta-secret',
                        peer_entries={
                            'host_alpha': {
                                'label': 'Alpha Host',
                                'transport': 'https',
                                'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                                'trust_state': 'trusted',
                                'shared_secret': 'alpha-secret',
                                'admitted_org_ids': ['org_alpha'],
                            },
                        },
                    )
                    commitment_id = f'cmt_court_notice_{decision}'
                    _seed_commitments(
                        os.path.join(alpha['economy'], 'commitments.json'),
                        [
                            _accepted_commitment_record(
                                org_id='org_alpha',
                                commitment_id=commitment_id,
                                target_host_id='host_beta',
                                target_institution_id='org_beta',
                            ),
                        ],
                    )

                    with _run_workspace(beta), _run_workspace(alpha):
                        session = _issue_workspace_session(alpha)
                        request_payload = {'task': 'demo', 'phase': f'receiver_review_{decision}'}
                        warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                        status, body = _http_json(
                            'POST',
                            alpha['base_url'] + '/api/federation/send',
                            payload={
                                'target_host_id': 'host_beta',
                                'target_org_id': 'org_beta',
                                'message_type': 'execution_request',
                                'commitment_id': commitment_id,
                                'payload': request_payload,
                                'warrant_id': warrant['warrant_id'],
                            },
                            headers={
                                'Authorization': f"Bearer {session['token']}",
                                'Content-Type': 'application/json',
                            },
                        )
                        self.assertEqual(status, 200, body)

                        jobs_status, jobs_body = _http_json(
                            'GET',
                            beta['base_url'] + '/api/federation/execution-jobs',
                            headers={'Authorization': beta['auth_header']},
                        )
                        self.assertEqual(jobs_status, 200, jobs_body)
                        self.assertEqual(jobs_body['summary']['pending_local_warrant'], 1)
                        job_id = jobs_body['jobs'][0]['job_id']
                        local_warrant_id = jobs_body['jobs'][0]['local_warrant_id']

                        status, review_body = _http_json(
                            'POST',
                            beta['base_url'] + f'/api/warrants/{decision}',
                            payload={
                                'warrant_id': local_warrant_id,
                                'note': f'Receiver {decision} pending local review',
                            },
                            headers={'Authorization': beta['auth_header']},
                        )
                        self.assertEqual(status, 200, review_body)
                        self.assertEqual(review_body['warrant']['court_review_state'], expected['sender_review_state'])
                        self.assertEqual(review_body['execution_job']['job_id'], job_id)
                        self.assertEqual(review_body['execution_job']['state'], expected['receiver_job_state'])
                        self.assertTrue(review_body['court_notice']['applied'])
                        self.assertEqual(review_body['court_notice']['court_notice']['decision'], decision)

                        alpha_inbox_status, alpha_inbox_body = _http_json(
                            'GET',
                            alpha['base_url'] + '/api/federation/inbox',
                            headers={'Authorization': alpha['auth_header']},
                        )
                        self.assertEqual(alpha_inbox_status, 200, alpha_inbox_body)
                        self.assertEqual(alpha_inbox_body['summary']['processed'], 1)
                        self.assertEqual(alpha_inbox_body['summary']['message_type_counts'], {'court_notice': 1})
                        self.assertEqual(alpha_inbox_body['entries'][0]['message_type'], 'court_notice')

                        alpha_warrants_status, alpha_warrants_body = _http_json(
                            'GET',
                            alpha['base_url'] + '/api/warrants',
                            headers={'Authorization': alpha['auth_header']},
                        )
                        self.assertEqual(alpha_warrants_status, 200, alpha_warrants_body)
                        sender_warrant = next(
                            item for item in alpha_warrants_body['warrants']
                            if item['warrant_id'] == warrant['warrant_id']
                        )
                        self.assertEqual(sender_warrant['court_review_state'], expected['sender_review_state'])
                        self.assertEqual(sender_warrant['execution_state'], 'ready')
                        self.assertEqual(sender_warrant['reviewed_by'], 'user_owner_beta')

                        alpha_commit_status, alpha_commit_body = _http_json(
                            'GET',
                            alpha['base_url'] + '/api/commitments',
                            headers={'Authorization': alpha['auth_header']},
                        )
                        self.assertEqual(alpha_commit_status, 200, alpha_commit_body)
                        alpha_commitment = next(
                            item for item in alpha_commit_body['commitments']
                            if item['commitment_id'] == commitment_id
                        )
                        court_notice_ref = next(
                            ref for ref in alpha_commitment['delivery_refs']
                            if ref['message_type'] == 'court_notice'
                        )
                        self.assertEqual(court_notice_ref['warrant_id'], warrant['warrant_id'])
                        self.assertEqual(court_notice_ref['local_warrant_id'], local_warrant_id)
                        self.assertEqual(court_notice_ref['court_decision'], decision)
                        self.assertEqual(
                            court_notice_ref['source_execution_envelope_id'],
                            body['delivery']['claims']['envelope_id'],
                        )

                    alpha_events = _read_jsonl(alpha['audit_log'])
                    beta_events = _read_jsonl(beta['audit_log'])
                    self.assertTrue(
                        any(event.get('action') == 'federation_court_notice_applied' for event in alpha_events)
                    )
                    self.assertTrue(
                        any(event.get('action') == 'federation_court_notice_sent' for event in beta_events)
                    )

    def test_workspace_federation_court_notice_auto_archives_to_witness_peer(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
            port_gamma = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'org_gamma_user',
                        'witness_archive_pass': 'org_gamma_pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'org_gamma_user',
                        'witness_archive_pass': 'org_gamma_pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            gamma = _seed_workspace_root(
                os.path.join(tmp, 'gamma'),
                org_id='org_gamma',
                user_id='user_witness_gamma',
                host_id='host_gamma',
                port=port_gamma,
                signing_secret='gamma-secret',
                host_role='witness_host',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            commitment_id = 'cmt_court_notice_witness'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )

            with _run_workspace(gamma), _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                request_payload = {'task': 'demo', 'phase': 'receiver_review'}
                warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'commitment_id': commitment_id,
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)

                jobs_status, jobs_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/execution-jobs',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(jobs_status, 200, jobs_body)
                local_warrant_id = jobs_body['jobs'][0]['local_warrant_id']

                status, review_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/warrants/stay',
                    payload={'warrant_id': local_warrant_id, 'note': 'Receiver hold pending local review'},
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(status, 200, review_body)
                self.assertEqual(
                    review_body['court_notice']['delivery']['witness_archive']['attempted'],
                    1,
                )
                self.assertEqual(
                    review_body['court_notice']['delivery']['witness_archive']['created'],
                    1,
                )
                self.assertEqual(
                    review_body['court_notice']['delivery']['witness_archive']['records'][0]['peer_host_id'],
                    'host_gamma',
                )

                witness_status, witness_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(witness_status, 200, witness_body)
                self.assertEqual(witness_body['summary']['total'], 2)
                self.assertEqual(
                    witness_body['summary']['message_type_counts'],
                    {'court_notice': 1, 'execution_request': 1},
                )

            beta_events = _read_jsonl(beta['audit_log'])
            self.assertTrue(
                any(event.get('action') == 'federation_witness_archive_sent' for event in beta_events)
            )

    def test_workspace_federation_execution_job_execute_sends_settlement_notice_once(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
            port_gamma = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'org_gamma_user',
                        'witness_archive_pass': 'org_gamma_pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            gamma = _seed_workspace_root(
                os.path.join(tmp, 'gamma'),
                org_id='org_gamma',
                user_id='user_witness_gamma',
                host_id='host_gamma',
                port=port_gamma,
                signing_secret='gamma-secret',
                host_role='witness_host',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            commitment_id = 'cmt_execution_loop'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_alpha',
                        target_institution_id='org_alpha',
                    ),
                ],
            )
            _write_json(
                os.path.join(beta['economy'], 'wallets.json'),
                {
                    'wallets': {
                        'wallet_beta': {
                            'id': 'wallet_beta',
                            'verification_level': 3,
                            'verification_label': 'self_custody_verified',
                            'payout_eligible': True,
                            'status': 'active',
                        },
                    },
                    'verification_levels': {},
                },
            )
            _write_json(
                os.path.join(beta['economy'], 'contributors.json'),
                {
                    'contributors': {
                        'contrib_beta': {
                            'id': 'contrib_beta',
                            'name': 'Beta Contributor',
                            'payout_wallet_id': 'wallet_beta',
                        },
                    },
                    'contribution_types': ['code'],
                    'registration_requirements': {},
                },
            )
            _write_json(
                os.path.join(beta['economy'], 'payout_proposals.json'),
                {
                    'proposals': {
                        'ppo_demo_beta': _executed_payout_proposal_record(
                            proposal_id='ppo_demo_beta',
                            commitment_id=commitment_id,
                        ),
                    },
                    'state_machine': json.loads(
                        json.dumps(
                            {
                                'states': [
                                    'draft',
                                    'submitted',
                                    'under_review',
                                    'approved',
                                    'dispute_window',
                                    'executed',
                                    'rejected',
                                    'cancelled',
                                ],
                                'transitions': {
                                    'draft': ['submitted', 'cancelled'],
                                    'submitted': ['under_review', 'rejected', 'cancelled'],
                                    'under_review': ['approved', 'rejected'],
                                    'approved': ['dispute_window'],
                                    'dispute_window': ['executed', 'rejected'],
                                    'executed': [],
                                    'rejected': [],
                                    'cancelled': [],
                                },
                                'dispute_window_hours': 72,
                                'notes': 'Seeded executed payout proof for federated execution tests.',
                            }
                        )
                    ),
                    'proposal_schema': {},
                    'updatedAt': _now_stub(),
                    },
                )

            with _run_workspace(gamma), _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                request_payload = {'task': 'demo'}
                warrant = _issue_workspace_warrant(
                    alpha,
                    session['token'],
                    request_payload,
                )
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'commitment_id': commitment_id,
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                delivery = body['delivery']
                self.assertEqual(delivery['claims']['commitment_id'], commitment_id)
                self.assertEqual(delivery['witness_archive']['attempted'], 1)
                self.assertEqual(delivery['witness_archive']['created'], 1)
                self.assertEqual(delivery['witness_archive']['failed'], 0)
                self.assertEqual(len(delivery['witness_archive']['records']), 1)
                auto_archive = delivery['witness_archive']['records'][0]
                self.assertEqual(auto_archive['peer_host_id'], 'host_gamma')
                self.assertTrue(auto_archive['archived'])
                self.assertTrue(auto_archive['created'])
                self.assertTrue(auto_archive['archive_id'])

                alpha_warrants_status, alpha_warrants_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/warrants',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_warrants_status, 200, alpha_warrants_body)
                sender_warrant = next(
                    item for item in alpha_warrants_body['warrants']
                    if item['warrant_id'] == warrant['warrant_id']
                )
                self.assertEqual(sender_warrant['execution_state'], 'ready')
                jobs_body, execution_job = _wait_for_execution_job(
                    beta,
                    delivery['claims']['envelope_id'],
                )
                self.assertEqual(execution_job['state'], 'pending_local_warrant')
                job_id = execution_job['job_id']
                local_warrant_id = execution_job['local_warrant_id']
                self.assertTrue(local_warrant_id)
                _wait_for_warrant(beta, local_warrant_id)

                status, review_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/warrants/approve',
                    payload={'warrant_id': local_warrant_id},
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(status, 200, review_body)
                self.assertEqual(review_body['execution_job']['state'], 'ready')

                status, rejected_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/federation/execution-jobs/execute',
                    payload={
                        'job_id': job_id,
                        'execution_refs': {
                            'tx_ref': 'tx_untrusted',
                        },
                    },
                    headers={
                        'Authorization': beta['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 400, rejected_body)
                self.assertIn('execution_refs are not accepted', rejected_body['error'])

                status, execute_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/federation/execution-jobs/execute',
                    payload={'job_id': job_id},
                    headers={
                        'Authorization': beta['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, execute_body)
                self.assertEqual(execute_body['execution_job']['state'], 'executed')
                self.assertEqual(execute_body['warrant']['execution_state'], 'executed')
                self.assertEqual(execute_body['settlement_notice']['message_type'], 'settlement_notice')
                first_notice_id = execute_body['settlement_notice']['envelope_id']
                self.assertTrue(first_notice_id)
                self.assertEqual(
                    execute_body['execution_job']['execution_refs']['proposal_id'],
                    'ppo_demo_beta',
                )

                status, replay_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/federation/execution-jobs/execute',
                    payload={'job_id': job_id},
                    headers={
                        'Authorization': beta['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, replay_body)
                self.assertEqual(replay_body['execution_job']['state'], 'executed')
                self.assertEqual(replay_body['settlement_notice']['envelope_id'], first_notice_id)

                inbox_status, inbox_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['processed'], 2)
                self.assertEqual(inbox_body['summary']['message_type_counts'], {
                    'court_notice': 1,
                    'settlement_notice': 1,
                })
                self.assertEqual(
                    {entry['message_type'] for entry in inbox_body['entries']},
                    {'court_notice', 'settlement_notice'},
                )
                self.assertTrue(
                    any(
                        entry['message_type'] == 'settlement_notice'
                        and entry['commitment_id'] == commitment_id
                        for entry in inbox_body['entries']
                    )
                )

                alpha_warrants_status, alpha_warrants_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/warrants',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_warrants_status, 200, alpha_warrants_body)
                sender_warrant = next(
                    item for item in alpha_warrants_body['warrants']
                    if item['warrant_id'] == warrant['warrant_id']
                )
                self.assertEqual(sender_warrant['execution_state'], 'executed')
                self.assertEqual(
                    sender_warrant['execution_refs']['completion_envelope_id'],
                    first_notice_id,
                )

                beta_jobs_status, beta_jobs_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/execution-jobs',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(beta_jobs_status, 200, beta_jobs_body)
                self.assertEqual(beta_jobs_body['summary']['executed'], 1)
                self.assertEqual(beta_jobs_body['summary']['ready'], 0)
                receiver_job = next(
                    item for item in beta_jobs_body['jobs']
                    if item['job_id'] == job_id
                )
                self.assertEqual(
                    receiver_job['execution_refs']['settlement_notice_envelope_id'],
                    first_notice_id,
                )
                self.assertEqual(
                    receiver_job['execution_refs']['proposal_id'],
                    'ppo_demo_beta',
                )

            with open(os.path.join(beta['economy'], 'commitments.json')) as f:
                beta_commitments = json.load(f)
            beta_record = beta_commitments['commitments'][commitment_id]
            self.assertEqual(len(beta_record['delivery_refs']), 1)
            self.assertEqual(beta_record['delivery_refs'][0]['message_type'], 'settlement_notice')

            with open(os.path.join(alpha['economy'], 'commitments.json')) as f:
                alpha_commitments = json.load(f)
            alpha_record = alpha_commitments['commitments'][commitment_id]
            self.assertEqual(alpha_record['state'], 'settled')
            self.assertEqual(len(alpha_record['settlement_refs']), 1)

    def test_workspace_federation_settlement_notice_applies_on_receiver(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            commitment_id = 'cmt_shared_settlement'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_alpha',
                        target_institution_id='org_alpha',
                    ),
                ],
            )

            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'settlement_notice',
                        'commitment_id': commitment_id,
                        'payload': {
                            'proposal_id': 'ppo_demo',
                            'tx_ref': 'tx_demo_settlement',
                            'settlement_adapter': 'internal_ledger',
                        },
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                delivery = body['delivery']
                self.assertEqual(delivery['claims']['commitment_id'], commitment_id)
                self.assertTrue(delivery['response']['processing']['applied'])
                self.assertEqual(
                    delivery['response']['processing']['reason'],
                    'settlement_notice_applied',
                )
                self.assertEqual(
                    delivery['response']['processing']['commitment']['state'],
                    'settled',
                )
                self.assertEqual(
                    delivery['response']['processing']['settlement_ref']['tx_ref'],
                    'tx_demo_settlement',
                )
                self.assertEqual(
                    delivery['response']['processing']['settlement_ref']['proof_type'],
                    'ledger_transaction',
                )
                self.assertEqual(
                    delivery['response']['processing']['settlement_ref']['verification_state'],
                    'host_ledger_final',
                )
                self.assertEqual(
                    delivery['response']['processing']['settlement_ref']['finality_state'],
                    'host_local_final',
                )
                self.assertEqual(
                    delivery['response']['processing']['inbox_entry']['state'],
                    'processed',
                )
                self.assertTrue(
                    delivery['response']['processing']['settlement_preflight']['preflight_ok']
                )

                inbox_status, inbox_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['processed'], 1)
                self.assertEqual(inbox_body['entries'][0]['state'], 'processed')
                self.assertEqual(inbox_body['entries'][0]['commitment_id'], commitment_id)

            with open(os.path.join(beta['economy'], 'commitments.json')) as f:
                beta_commitments = json.load(f)
            beta_record = beta_commitments['commitments'][commitment_id]
            self.assertEqual(beta_record['state'], 'settled')
            self.assertEqual(beta_record['settlement_refs'][0]['proposal_id'], 'ppo_demo')
            self.assertEqual(beta_record['settlement_refs'][0]['tx_ref'], 'tx_demo_settlement')
            self.assertEqual(beta_record['settlement_refs'][0]['proof_type'], 'ledger_transaction')
            self.assertEqual(beta_record['settlement_refs'][0]['source_host_id'], 'host_alpha')

            beta_events = _read_jsonl(beta['audit_log'])
            applied = [
                event for event in beta_events
                if event.get('action') == 'federation_settlement_notice_applied'
            ]
            self.assertTrue(applied)
            self.assertEqual(applied[-1]['resource'], commitment_id)

    def test_workspace_federation_settlement_notice_accepts_enabled_base_x402_adapter(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                settlement_adapters=['base_usdc_x402'],
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                settlement_adapters=['base_usdc_x402'],
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            commitment_id = 'cmt_base_x402_settlement'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_alpha',
                        target_institution_id='org_alpha',
                    ),
                ],
            )
            _write_json(
                os.path.join(alpha['economy'], 'settlement_adapters.json'),
                {
                    'default_payout_adapter': 'base_usdc_x402',
                    'adapters': {
                        'base_usdc_x402': {
                            'status': 'active',
                            'payout_execution_enabled': True,
                            'verification_ready': True,
                        },
                    },
                },
            )
            _write_json(
                os.path.join(beta['economy'], 'settlement_adapters.json'),
                {
                    'default_payout_adapter': 'base_usdc_x402',
                    'adapters': {
                        'base_usdc_x402': {
                            'status': 'active',
                            'payout_execution_enabled': True,
                            'verification_ready': True,
                        },
                    },
                },
            )

            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'settlement_notice',
                        'commitment_id': commitment_id,
                        'payload': {
                            'proposal_id': 'ppo_chain_demo',
                            'tx_ref': 'tx_base_x402_demo',
                            'tx_hash': '0xbase123',
                            'settlement_adapter': 'base_usdc_x402',
                            'settlement_adapter_contract_snapshot': _base_usdc_x402_contract_snapshot(),
                            'settlement_adapter_contract_digest': _contract_digest(
                                _base_usdc_x402_contract_snapshot()
                            ),
                            'proof': {
                                'reference': 'base://receipt/demo',
                                'payer_wallet': '0xabc123',
                                'verification_attestation': {
                                    'type': 'x402_settlement_verifier',
                                    'reference': 'attest://base/demo',
                                },
                            },
                        },
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                processing = body['delivery']['response']['processing']
                self.assertTrue(processing['applied'])
                self.assertEqual(processing['reason'], 'settlement_notice_applied')
                self.assertTrue(processing['settlement_preflight']['preflight_ok'])
                self.assertEqual(
                    processing['settlement_ref']['settlement_adapter'],
                    'base_usdc_x402',
                )
                self.assertEqual(
                    processing['settlement_ref']['proof_type'],
                    'onchain_receipt',
                )
                self.assertEqual(
                    processing['settlement_ref']['verification_state'],
                    'external_verification_required',
                )
                self.assertEqual(
                    processing['settlement_ref']['finality_state'],
                    'external_chain_finality',
                )
                self.assertEqual(
                    processing['settlement_ref']['settlement_adapter_contract']['settlement_path'],
                    'x402_onchain',
                )
                self.assertEqual(
                    processing['settlement_ref']['proof']['reference'],
                    'base://receipt/demo',
                )
                self.assertEqual(
                    processing['settlement_ref']['proof']['verification_attestation']['type'],
                    'x402_settlement_verifier',
                )

            with open(os.path.join(beta['economy'], 'commitments.json')) as f:
                beta_commitments = json.load(f)
            beta_ref = beta_commitments['commitments'][commitment_id]['settlement_refs'][0]
            self.assertEqual(beta_ref['settlement_adapter'], 'base_usdc_x402')
            self.assertEqual(beta_ref['proof_type'], 'onchain_receipt')
            self.assertEqual(beta_ref['tx_hash'], '0xbase123')

    def test_workspace_federation_invalid_settlement_notice_opens_case_and_suspends_peer(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            commitment_id = 'cmt_invalid_settlement'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )

            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'settlement_notice',
                        'commitment_id': commitment_id,
                        'payload': {
                            'proposal_id': 'ppo_invalid',
                            'tx_ref': 'tx_invalid',
                            'settlement_adapter': 'imaginary_chain',
                        },
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                processing = body['delivery']['response']['processing']
                self.assertFalse(processing['applied'])
                self.assertEqual(processing['reason'], 'invalid_settlement_notice')
                self.assertEqual(processing['case']['claim_type'], 'invalid_settlement_notice')
                self.assertTrue(processing['case_created'])
                self.assertEqual(processing['federation_peer']['trust_state'], 'suspended')
                self.assertFalse(processing['settlement_preflight']['preflight_ok'])
                self.assertEqual(processing['settlement_preflight']['error_type'], 'unknown_adapter')

                inbox_status, inbox_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['received'], 1)
                self.assertEqual(inbox_body['entries'][0]['state'], 'received')

                cases_status, cases_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/cases',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(cases_status, 200, cases_body)
                self.assertIn(commitment_id, cases_body['blocking_commitment_ids'])
                self.assertIn('host_alpha', cases_body['blocked_peer_host_ids'])

            with open(os.path.join(beta['economy'], 'commitments.json')) as f:
                beta_commitments = json.load(f)
            beta_record = beta_commitments['commitments'][commitment_id]
            self.assertEqual(beta_record['state'], 'accepted')
            self.assertEqual(beta_record['settlement_refs'], [])

    def test_workspace_federation_settlement_notice_rejects_contract_snapshot_drift(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            commitment_id = 'cmt_drifted_settlement'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )

            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'settlement_notice',
                        'commitment_id': commitment_id,
                        'payload': {
                            'proposal_id': 'ppo_invalid',
                            'tx_ref': 'tx_invalid',
                            'settlement_adapter': 'internal_ledger',
                            'proof': {'mode': 'institution_transactions_journal'},
                            'settlement_adapter_contract_snapshot': {
                                'contract_version': 2,
                                'adapter_id': 'internal_ledger',
                                'status': 'active',
                                'payout_execution_enabled': True,
                                'execution_mode': 'host_ledger',
                                'settlement_path': 'tampered_path',
                                'supported_currencies': ['USD', 'USDC'],
                                'requires_tx_hash': False,
                                'requires_settlement_proof': False,
                                'requires_verifier_attestation': False,
                                'verification_mode': 'host_ledger',
                                'verification_ready': True,
                                'accepted_attestation_types': [],
                                'proof_type': 'ledger_transaction',
                                'verification_state': 'host_ledger_final',
                                'finality_state': 'host_local_final',
                                'finality_model': 'host_local_final',
                                'reversal_or_dispute_capability': 'court_case',
                                'dispute_model': 'court_case',
                            },
                            'settlement_adapter_contract_digest': 'bad-digest',
                        },
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                processing = body['delivery']['response']['processing']
                self.assertFalse(processing['applied'])
                self.assertEqual(processing['reason'], 'invalid_settlement_notice')
                self.assertEqual(processing['case']['claim_type'], 'invalid_settlement_notice')
                self.assertTrue(processing['case_created'])
                self.assertEqual(processing['federation_peer']['trust_state'], 'suspended')
                self.assertFalse(processing['settlement_preflight']['preflight_ok'])
                self.assertEqual(processing['settlement_preflight']['error_type'], 'validation_error')
                self.assertIn('contract drifted', processing['error'])

    def test_workspace_federation_settlement_notice_replay_is_idempotent(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            commitment_id = 'cmt_replay_settlement'
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )

            from federation import FederationAuthority
            from runtime_host import default_host_identity

            sender_host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            authority = FederationAuthority(sender_host, signing_secret='alpha-secret')
            envelope = authority.issue(
                'org_alpha',
                'host_beta',
                'org_beta',
                'settlement_notice',
                payload={
                    'proposal_id': 'ppo_replay',
                    'tx_ref': 'tx_replay',
                    'settlement_adapter': 'internal_ledger',
                    'proof_type': 'internal_ledger',
                    'verification_state': 'accepted',
                    'finality_state': 'final',
                    'proof': {'entry': 1},
                },
                commitment_id=commitment_id,
                warrant_id='',
            )

            with _run_workspace(beta), _run_workspace(alpha):
                first_status, first_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/federation/receive',
                    payload={
                        'envelope': envelope,
                        'payload': {
                            'proposal_id': 'ppo_replay',
                            'tx_ref': 'tx_replay',
                            'settlement_adapter': 'internal_ledger',
                            'proof_type': 'internal_ledger',
                            'verification_state': 'accepted',
                            'finality_state': 'final',
                            'proof': {'entry': 1},
                        },
                    },
                )
                self.assertEqual(first_status, 200, first_body)
                self.assertTrue(first_body['processing']['applied'])
                self.assertEqual(first_body['processing']['inbox_entry']['state'], 'processed')

                second_status, second_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/federation/receive',
                    payload={
                        'envelope': envelope,
                        'payload': {
                            'proposal_id': 'ppo_replay',
                            'tx_ref': 'tx_replay',
                            'settlement_adapter': 'internal_ledger',
                            'proof_type': 'internal_ledger',
                            'verification_state': 'accepted',
                            'finality_state': 'final',
                            'proof': {'entry': 1},
                        },
                    },
                )
                self.assertEqual(second_status, 409, second_body)
                self.assertIn('nonce already consumed', second_body['error'])

                inbox_status, inbox_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['total'], 1)
                self.assertEqual(inbox_body['summary']['processed'], 1)

            with open(os.path.join(beta['economy'], 'commitments.json')) as f:
                beta_commitments = json.load(f)
            beta_record = beta_commitments['commitments'][commitment_id]
            self.assertEqual(len(beta_record['settlement_refs']), 1)
            self.assertEqual(beta_record['settlement_refs'][0]['receipt_id'], first_body['receipt']['receipt_id'])
            self.assertEqual(beta_record['settlement_refs'][0]['envelope_id'], first_body['claims']['envelope_id'])

            beta_events = _read_jsonl(beta['audit_log'])
            applied = [
                event for event in beta_events
                if event.get('action') == 'federation_settlement_notice_applied'
            ]
            self.assertEqual(len(applied), 1)

    def test_workspace_federation_settlement_notice_keeps_inbox_received_when_case_blocked(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            commitment_id = 'cmt_shared_blocked'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_alpha',
                        target_institution_id='org_alpha',
                    ),
                ],
            )

            with _run_workspace(beta), _run_workspace(alpha):
                beta_session = _issue_workspace_session(beta)
                status, body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/cases/open',
                    payload={
                        'claim_type': 'non_delivery',
                        'linked_commitment_id': commitment_id,
                        'target_host_id': 'host_alpha',
                        'target_institution_id': 'org_alpha',
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                case_id = body['case']['case_id']

                alpha_session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'settlement_notice',
                        'commitment_id': commitment_id,
                        'payload': {
                            'proposal_id': 'ppo_blocked',
                            'tx_ref': 'tx_blocked',
                            'settlement_adapter': 'internal_ledger',
                        },
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                delivery = body['delivery']
                self.assertFalse(delivery['response']['processing']['applied'])
                self.assertEqual(delivery['response']['processing']['reason'], 'case_blocked')
                self.assertEqual(delivery['response']['processing']['case']['case_id'], case_id)
                self.assertEqual(delivery['response']['inbox_entry']['state'], 'received')

                inbox_status, inbox_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['received'], 1)
                self.assertEqual(inbox_body['summary']['processed'], 0)
                self.assertEqual(inbox_body['entries'][0]['state'], 'received')

            with open(os.path.join(beta['economy'], 'commitments.json')) as f:
                beta_commitments = json.load(f)
            beta_record = beta_commitments['commitments'][commitment_id]
            self.assertEqual(beta_record['state'], 'accepted')
            self.assertEqual(beta_record['settlement_refs'], [])

            beta_events = _read_jsonl(beta['audit_log'])
            blocked = [
                event for event in beta_events
                if event.get('action') == 'federation_settlement_notice_blocked'
            ]
            self.assertTrue(blocked)
            self.assertEqual(blocked[-1]['resource'], commitment_id)

    def test_workspace_witness_host_observes_federation_and_rejects_mutations(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
            port_gamma = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'org_gamma_user',
                        'witness_archive_pass': 'org_gamma_pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'org_gamma_user',
                        'witness_archive_pass': 'org_gamma_pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            gamma = _seed_workspace_root(
                os.path.join(tmp, 'gamma'),
                org_id='org_gamma',
                user_id='user_witness_gamma',
                host_id='host_gamma',
                port=port_gamma,
                signing_secret='gamma-secret',
                host_role='witness_host',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )

            commitment_id = 'cmt_witness_three_host'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_alpha',
                        target_institution_id='org_alpha',
                    ),
                ],
            )

            with _run_workspace(gamma), _run_workspace(beta), _run_workspace(alpha):
                witness_status, witness_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/status',
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(witness_status, 200, witness_body)
                self.assertEqual(
                    witness_body['runtime_core']['admission']['management_mode'],
                    'witness_read_only',
                )
                self.assertFalse(witness_body['runtime_core']['admission']['mutation_enabled'])
                self.assertEqual(
                    witness_body['runtime_core']['admission']['mutation_disabled_reason'],
                    'witness_host_read_only',
                )

                witness_status, witness_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/federation/manifest',
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(witness_status, 200, witness_body)
                self.assertEqual(witness_body['federation']['management_mode'], 'witness_read_only')
                self.assertFalse(witness_body['federation']['mutation_enabled'])
                self.assertEqual(witness_body['federation']['mutation_disabled_reason'], 'witness_host_read_only')

                session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'settlement_notice',
                        'commitment_id': commitment_id,
                        'payload': {
                            'proposal_id': 'ppo_demo',
                            'tx_ref': 'tx_demo_settlement',
                            'settlement_adapter': 'internal_ledger',
                        },
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                delivery = body['delivery']
                self.assertEqual(delivery['claims']['commitment_id'], commitment_id)

                witness_peer_status, witness_peer_body = _http_json(
                    'POST',
                    gamma['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'commitment_id': commitment_id,
                        'payload': {'task': 'witness_probe'},
                    },
                    headers={
                        'Authorization': gamma['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(witness_peer_status, 403, witness_peer_body)
                self.assertIn('witness_host_read_only', witness_peer_body['error'])

                witness_admit_status, witness_admit_body = _http_json(
                    'POST',
                    gamma['base_url'] + '/api/admission/admit',
                    payload={'org_id': 'org_beta'},
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(witness_admit_status, 403, witness_admit_body)
                self.assertIn('witness_host_read_only', witness_admit_body['error'])

                from federation import FederationAuthority, FederationEnvelopeClaims, load_peer_registry
                from runtime_host import default_host_identity

                witness_host = default_host_identity(
                    host_id='host_gamma',
                    role='witness_host',
                    federation_enabled=True,
                    peer_transport='https',
                    supported_boundaries=['workspace', 'cli', 'federation_gateway'],
                )
                witness_registry_path = os.path.join(tmp, 'gamma_peers.json')
                _write_json(
                    witness_registry_path,
                    {
                        'host_id': 'host_gamma',
                        'peers': {
                            'host_alpha': {
                                'label': 'Alpha Host',
                                'transport': 'https',
                                'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                                'trust_state': 'trusted',
                                'shared_secret': 'alpha-secret',
                                'admitted_org_ids': ['org_alpha'],
                            },
                            'host_beta': {
                                'label': 'Beta Host',
                                'transport': 'https',
                                'endpoint_url': f'http://127.0.0.1:{port_beta}',
                                'trust_state': 'trusted',
                                'shared_secret': 'beta-secret',
                                'admitted_org_ids': ['org_beta'],
                            },
                        },
                    },
                )
                witness_authority = FederationAuthority(
                    witness_host,
                    signing_secret='gamma-secret',
                    peer_registry=load_peer_registry(witness_registry_path, host_identity=witness_host),
                )
                peer_alpha, manifest_alpha = witness_authority.fetch_peer_manifest(
                    'host_alpha',
                    http_get=lambda url: _http_json('GET', url, headers={'Authorization': alpha['auth_header']})[1],
                )
                peer_beta, manifest_beta = witness_authority.fetch_peer_manifest(
                    'host_beta',
                    http_get=lambda url: _http_json('GET', url, headers={'Authorization': beta['auth_header']})[1],
                )
                self.assertEqual(peer_alpha.host_id, 'host_alpha')
                self.assertEqual(peer_beta.host_id, 'host_beta')
                self.assertEqual(manifest_alpha['host_identity']['host_id'], 'host_alpha')
                self.assertEqual(manifest_beta['host_identity']['host_id'], 'host_beta')

                receipt = delivery['receipt']
                validated_receipt = witness_authority._validate_delivery_receipt(
                    {'receipt': receipt},
                    peer_host_id='host_beta',
                    target_institution_id='org_beta',
                    claims=FederationEnvelopeClaims(**delivery['claims']),
                )
                self.assertEqual(validated_receipt['receiver_host_id'], 'host_beta')
                self.assertEqual(validated_receipt['receiver_institution_id'], 'org_beta')
                self.assertEqual(validated_receipt['identity_model'], 'signed_host_service')

                archive_status, archive_body = _http_json(
                    'POST',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    payload={
                        'envelope': delivery['envelope'],
                        'payload': {
                            'proposal_id': 'ppo_demo',
                            'tx_ref': 'tx_demo_settlement',
                            'settlement_adapter': 'internal_ledger',
                        },
                        'receipt': receipt,
                    },
                    headers={
                        'Authorization': gamma['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(archive_status, 200, archive_body)
                self.assertFalse(archive_body['created'])
                self.assertTrue(archive_body['archive']['archive_id'])
                self.assertEqual(archive_body['archive']['source_host_id'], 'host_alpha')
                self.assertEqual(archive_body['archive']['target_host_id'], 'host_beta')
                self.assertEqual(archive_body['archive']['receipt_id'], receipt['receipt_id'])
                self.assertEqual(archive_body['witness_archive']['summary']['total'], 1)
                self.assertEqual(
                    archive_body['witness_archive']['records'][0]['archive_id'],
                    archive_body['archive']['archive_id'],
                )

                replay_status, replay_body = _http_json(
                    'POST',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    payload={
                        'envelope': delivery['envelope'],
                        'payload': {
                            'proposal_id': 'ppo_demo',
                            'tx_ref': 'tx_demo_settlement',
                            'settlement_adapter': 'internal_ledger',
                        },
                        'receipt': receipt,
                    },
                    headers={
                        'Authorization': gamma['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(replay_status, 200, replay_body)
                self.assertFalse(replay_body['created'])
                self.assertEqual(
                    replay_body['archive']['archive_id'],
                    archive_body['archive']['archive_id'],
                )

                archive_get_status, archive_get_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(archive_get_status, 200, archive_get_body)
                self.assertTrue(archive_get_body['archive_enabled'])
                self.assertEqual(archive_get_body['summary']['total'], 1)

                blocked_archive_status, blocked_archive_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/witness/archive',
                    payload={
                        'envelope': delivery['envelope'],
                        'payload': {
                            'proposal_id': 'ppo_demo',
                            'tx_ref': 'tx_demo_settlement',
                            'settlement_adapter': 'internal_ledger',
                        },
                        'receipt': receipt,
                    },
                    headers={
                        'Authorization': alpha['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(blocked_archive_status, 503, blocked_archive_body)
                self.assertEqual(
                    blocked_archive_body['witness_archive']['archive_disabled_reason'],
                    'witness_host_only',
                )

            gamma_events = _read_jsonl(gamma['audit_log'])
            self.assertIn(
                'federation_send_blocked',
                [event.get('action') for event in gamma_events],
            )
            self.assertIn(
                'federation_witness_observation_archived',
                [event.get('action') for event in gamma_events],
            )

    def test_workspace_witness_host_archives_independent_delivery_evidence(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
            port_gamma = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            gamma = _seed_workspace_root(
                os.path.join(tmp, 'gamma'),
                org_id='org_gamma',
                user_id='user_witness_gamma',
                host_id='host_gamma',
                port=port_gamma,
                signing_secret='gamma-secret',
                host_role='witness_host',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            commitment_id = 'cmt_witness_archive'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_alpha',
                        target_institution_id='org_alpha',
                    ),
                ],
            )

            with _run_workspace(gamma), _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                payload = {
                    'proposal_id': 'ppo_demo',
                    'tx_ref': 'tx_demo_settlement',
                    'settlement_adapter': 'internal_ledger',
                }
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'settlement_notice',
                        'commitment_id': commitment_id,
                        'payload': payload,
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                delivery = body['delivery']
                self.assertTrue(delivery['envelope'])
                self.assertTrue(delivery['receipt']['receipt_id'])

                witness_status, witness_body = _http_json(
                    'POST',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    payload={
                        'envelope': delivery['envelope'],
                        'payload': payload,
                        'receipt': delivery['receipt'],
                    },
                    headers={
                        'Authorization': gamma['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(witness_status, 200, witness_body)
                self.assertTrue(witness_body['created'])
                self.assertTrue(witness_body['archive']['archive_id'])
                self.assertEqual(witness_body['archive']['message_type'], 'settlement_notice')
                self.assertEqual(witness_body['archive']['source_host_id'], 'host_alpha')
                self.assertEqual(witness_body['archive']['target_host_id'], 'host_beta')
                self.assertEqual(
                    witness_body['archive']['receipt']['receipt_id'],
                    delivery['receipt']['receipt_id'],
                )
                archive_id = witness_body['archive']['archive_id']

                replay_status, replay_body = _http_json(
                    'POST',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    payload={
                        'envelope': delivery['envelope'],
                        'payload': payload,
                        'receipt': delivery['receipt'],
                    },
                    headers={
                        'Authorization': gamma['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(replay_status, 200, replay_body)
                self.assertFalse(replay_body['created'])
                self.assertEqual(replay_body['archive']['archive_id'], archive_id)

                archive_status, archive_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(archive_status, 200, archive_body)
                self.assertTrue(archive_body['archive_enabled'])
                self.assertEqual(archive_body['summary']['total'], 1)
                self.assertEqual(
                    archive_body['summary']['message_type_counts'],
                    {'settlement_notice': 1},
                )
                self.assertEqual(archive_body['records'][0]['archive_id'], archive_id)

                non_witness_status, non_witness_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/witness/archive',
                    payload={
                        'envelope': delivery['envelope'],
                        'payload': payload,
                        'receipt': delivery['receipt'],
                    },
                    headers={
                        'Authorization': alpha['auth_header'],
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(non_witness_status, 503, non_witness_body)
                self.assertIn('witness_host_only', non_witness_body['error'])

            gamma_events = _read_jsonl(gamma['audit_log'])
            archived = [
                event for event in gamma_events
                if event.get('action') == 'federation_witness_observation_archived'
            ]
            self.assertTrue(archived)
            self.assertEqual(archived[-1]['resource'], archive_id)

    def test_workspace_federation_send_auto_archives_settlement_notice_to_witness_peer(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
            port_gamma = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'org_gamma_user',
                        'witness_archive_pass': 'org_gamma_pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            gamma = _seed_workspace_root(
                os.path.join(tmp, 'gamma'),
                org_id='org_gamma',
                user_id='user_witness_gamma',
                host_id='host_gamma',
                port=port_gamma,
                signing_secret='gamma-secret',
                host_role='witness_host',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            commitment_id = 'cmt_witness_auto_archive'
            _seed_commitments(
                os.path.join(alpha['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_alpha',
                        commitment_id=commitment_id,
                        target_host_id='host_beta',
                        target_institution_id='org_beta',
                    ),
                ],
            )
            _seed_commitments(
                os.path.join(beta['economy'], 'commitments.json'),
                [
                    _accepted_commitment_record(
                        org_id='org_beta',
                        commitment_id=commitment_id,
                        target_host_id='host_alpha',
                        target_institution_id='org_alpha',
                    ),
                ],
            )

            with _run_workspace(gamma), _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                payload = {
                    'proposal_id': 'ppo_demo',
                    'tx_ref': 'tx_demo_settlement',
                    'settlement_adapter': 'internal_ledger',
                }
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'settlement_notice',
                        'commitment_id': commitment_id,
                        'payload': payload,
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                self.assertEqual(body['delivery']['witness_archive']['attempted'], 1)
                self.assertEqual(body['delivery']['witness_archive']['created'], 1)
                self.assertEqual(
                    body['delivery']['witness_archive']['records'][0]['peer_host_id'],
                    'host_gamma',
                )

                witness_status, witness_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(witness_status, 200, witness_body)
                self.assertEqual(witness_body['summary']['total'], 1)
                self.assertEqual(witness_body['summary']['message_type_counts'], {'settlement_notice': 1})

            alpha_events = _read_jsonl(alpha['audit_log'])
            self.assertTrue(
                any(event.get('action') == 'federation_witness_archive_sent' for event in alpha_events)
            )

    def test_workspace_federation_send_rejects_manifest_host_mismatch(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_gamma': {
                        'label': 'Gamma Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                request_payload = {'task': 'demo'}
                warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_gamma',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 502, body)
                self.assertIn("manifest host_id 'host_beta' does not match trusted peer 'host_gamma'", body['error'])

            beta_events = _read_jsonl(beta['audit_log'])
            received = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_received'
            ]
            self.assertEqual(received, [])

    def test_workspace_federation_send_rejects_manifest_target_org_mismatch(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                request_payload = {'task': 'demo'}
                warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_wrong',
                        'message_type': 'execution_request',
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 502, body)
                self.assertIn("registry does not admit target institution 'org_wrong'", body['error'])

            alpha_events = _read_jsonl(alpha['audit_log'])
            failed = [
                event for event in alpha_events
                if event.get('action') == 'federation_envelope_delivery_failed'
            ]
            beta_events = _read_jsonl(beta['audit_log'])
            received = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_received'
            ]
            self.assertTrue(failed)
            self.assertEqual(failed[-1]['details']['target_institution_id'], 'org_wrong')
            self.assertEqual(received, [])

    def test_workspace_federation_send_rejects_forged_peer_signature(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'wrong-alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                request_payload = {'task': 'demo'}
                warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 502, body)
                self.assertIn('HTTP 403', body['error'])
                self.assertIn('Envelope signature verification failed', body['error'])

            alpha_events = _read_jsonl(alpha['audit_log'])
            failed = [
                event for event in alpha_events
                if event.get('action') == 'federation_envelope_delivery_failed'
            ]
            beta_events = _read_jsonl(beta['audit_log'])
            received = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_received'
            ]
            self.assertTrue(failed)
            self.assertEqual(failed[-1]['details']['target_host_id'], 'host_beta')
            self.assertEqual(received, [])

    def test_workspace_federation_send_opens_case_for_bad_receipt(self):
        try:
            port_alpha = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        class BadReceiptHandler(BaseHTTPRequestHandler):
            receive_count = 0

            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path != '/api/federation/manifest':
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({
                    'manifest_version': 1,
                    'host_identity': {'host_id': 'host_beta'},
                    'admission': {'admitted_org_ids': ['org_beta']},
                    'service_registry': {
                        'federation_gateway': {
                            'identity_model': 'signed_host_service',
                            'supports_institution_routing': True,
                        },
                    },
                    'federation': {
                        'enabled': True,
                        'boundary_name': 'federation_gateway',
                        'identity_model': 'signed_host_service',
                    },
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != '/api/federation/receive':
                    self.send_response(404)
                    self.end_headers()
                    return
                type(self).receive_count += 1
                length = int(self.headers.get('Content-Length', '0') or 0)
                payload = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                envelope = payload.get('envelope', '')
                body_b64 = envelope.split('.', 1)[0]
                padding = '=' * ((4 - len(body_b64) % 4) % 4)
                claims = json.loads(base64.urlsafe_b64decode(body_b64 + padding).decode('utf-8'))
                body = json.dumps({
                    'accepted': True,
                    'receipt': {
                        'receipt_id': 'fedrcpt_bad',
                        'envelope_id': claims['envelope_id'],
                        'accepted_at': '2026-03-22T00:00:00Z',
                        'receiver_host_id': 'host_beta',
                        'receiver_institution_id': 'org_wrong',
                        'message_type': claims['message_type'],
                        'boundary_name': claims['boundary_name'],
                        'identity_model': 'signed_host_service',
                    },
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), BadReceiptHandler)
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                alpha = _seed_workspace_root(
                    os.path.join(tmp, 'alpha'),
                    org_id='org_alpha',
                    user_id='user_owner_alpha',
                    host_id='host_alpha',
                    port=port_alpha,
                    signing_secret='alpha-secret',
                    peer_entries={
                        'host_beta': {
                            'label': 'Beta Host',
                            'transport': 'https',
                            'endpoint_url': f'http://127.0.0.1:{server.server_address[1]}',
                            'trust_state': 'trusted',
                            'shared_secret': 'beta-secret',
                            'admitted_org_ids': ['org_beta'],
                        },
                    },
                )
                with _run_workspace(alpha):
                    session = _issue_workspace_session(alpha)
                    status, body = _http_json(
                        'POST',
                        alpha['base_url'] + '/api/federation/send',
                        payload={
                            'target_host_id': 'host_beta',
                            'target_org_id': 'org_beta',
                            'message_type': 'settlement_notice',
                            'payload': {'tx_ref': '0xabc'},
                        },
                        headers={
                            'Authorization': f"Bearer {session['token']}",
                            'Content-Type': 'application/json',
                        },
                    )
                    self.assertEqual(status, 502, body)
                    self.assertEqual(body['case']['claim_type'], 'misrouted_execution')
                    self.assertEqual(body['case']['target_host_id'], 'host_beta')
                    self.assertTrue(body['federation_peer']['applied'])
                    self.assertEqual(body['federation_peer']['trust_state'], 'suspended')
                    self.assertEqual(BadReceiptHandler.receive_count, 1)

                    blocked_status, blocked_body = _http_json(
                        'POST',
                        alpha['base_url'] + '/api/federation/send',
                        payload={
                            'target_host_id': 'host_beta',
                            'target_org_id': 'org_beta',
                            'message_type': 'settlement_notice',
                            'payload': {'tx_ref': '0xdef'},
                        },
                        headers={
                            'Authorization': f"Bearer {session['token']}",
                            'Content-Type': 'application/json',
                        },
                    )
                    self.assertEqual(blocked_status, 409, blocked_body)
                    self.assertEqual(blocked_body['case']['case_id'], body['case']['case_id'])
                    self.assertEqual(blocked_body['case']['claim_type'], 'misrouted_execution')
                    self.assertEqual(blocked_body['federation_peer']['peer_host_id'], 'host_beta')
                    self.assertEqual(blocked_body['federation_peer']['trust_state'], 'suspended')
                    self.assertEqual(blocked_body['federation_peer']['reason'], 'case_blocked')
                    self.assertEqual(BadReceiptHandler.receive_count, 1)

                    status, cases_body = _http_json(
                        'GET',
                        alpha['base_url'] + '/api/cases',
                        headers={'Authorization': alpha['auth_header']},
                    )
                    self.assertEqual(status, 200, cases_body)
                    self.assertEqual(cases_body['total'], 1)
                    self.assertEqual(cases_body['blocked_peer_host_ids'], ['host_beta'])

                    resolve_status, resolve_body = _http_json(
                        'POST',
                        alpha['base_url'] + '/api/cases/resolve',
                        payload={
                            'case_id': body['case']['case_id'],
                            'note': 'Peer reviewed and reinstated for retry',
                        },
                        headers={
                            'Authorization': alpha['auth_header'],
                            'Content-Type': 'application/json',
                        },
                    )
                    self.assertEqual(resolve_status, 200, resolve_body)
                    self.assertTrue(resolve_body['federation_peer']['applied'])
                    self.assertEqual(resolve_body['federation_peer']['trust_state'], 'trusted')

                    status, cases_body = _http_json(
                        'GET',
                        alpha['base_url'] + '/api/cases',
                        headers={'Authorization': alpha['auth_header']},
                    )
                    self.assertEqual(status, 200, cases_body)
                    self.assertEqual(cases_body['blocked_peer_host_ids'], [])

                    retry_status, retry_body = _http_json(
                        'POST',
                        alpha['base_url'] + '/api/federation/send',
                        payload={
                            'target_host_id': 'host_beta',
                            'target_org_id': 'org_beta',
                            'message_type': 'settlement_notice',
                            'payload': {'tx_ref': '0xghi'},
                        },
                        headers={
                            'Authorization': f"Bearer {session['token']}",
                            'Content-Type': 'application/json',
                        },
                    )
                    self.assertEqual(retry_status, 502, retry_body)
                    self.assertEqual(retry_body['case']['claim_type'], 'misrouted_execution')
                    self.assertEqual(BadReceiptHandler.receive_count, 2)

                alpha_events = _read_jsonl(alpha['audit_log'])
                opened = [e for e in alpha_events if e.get('action') == 'case_opened']
                suspended = [e for e in alpha_events if e.get('action') == 'federation_peer_auto_suspended']
                reinstated = [e for e in alpha_events if e.get('action') == 'federation_peer_auto_reinstated']
                failed = [e for e in alpha_events if e.get('action') == 'federation_envelope_delivery_failed']
                blocked = [e for e in alpha_events if e.get('action') == 'federation_case_blocked']
                self.assertTrue(opened)
                self.assertEqual(opened[-1]['details']['claim_type'], 'misrouted_execution')
                self.assertTrue(suspended)
                self.assertEqual(suspended[-1]['details']['trust_state'], 'suspended')
                self.assertTrue(reinstated)
                self.assertEqual(reinstated[-1]['details']['trust_state'], 'trusted')
                self.assertTrue(failed)
                self.assertTrue(blocked)
                self.assertIn(
                    blocked[-1]['details']['case_id'],
                    [event['resource'] for event in opened],
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_workspace_case_notice_round_trip_open_then_resolve_thaws_peer(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')
        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )

            with _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/cases/open',
                    payload={
                        'claim_type': 'misrouted_execution',
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'note': 'Open federated control-plane case',
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                case_id = body['case']['case_id']
                self.assertEqual(body['delivery']['response']['processing']['reason'], 'case_notice_applied')
                self.assertTrue(body['delivery']['response']['processing']['case_created'])
                self.assertEqual(body['delivery']['response']['processing']['case']['status'], 'open')
                self.assertEqual(body['delivery']['response']['processing']['case']['target_host_id'], 'host_alpha')
                self.assertEqual(body['delivery']['response']['processing']['case']['target_institution_id'], 'org_alpha')

                status, cases_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/cases',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(status, 200, cases_body)
                self.assertEqual(cases_body['total'], 1)
                self.assertEqual(cases_body['blocked_peer_host_ids'], ['host_alpha'])
                mirrored_case = next(
                    item for item in cases_body['cases']
                    if item['metadata']['federation_source_case_id'] == case_id
                )
                self.assertEqual(mirrored_case['status'], 'open')
                self.assertEqual(mirrored_case['target_host_id'], 'host_alpha')

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/cases/resolve',
                    payload={
                        'case_id': case_id,
                        'note': 'Resolve federated control-plane case',
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                self.assertEqual(body['delivery']['response']['processing']['reason'], 'case_notice_applied')
                self.assertEqual(body['delivery']['response']['processing']['case']['status'], 'resolved')
                self.assertEqual(body['delivery']['response']['processing']['federation_peer']['trust_state'], 'trusted')

                status, cases_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/cases',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(status, 200, cases_body)
                self.assertEqual(cases_body['blocked_peer_host_ids'], [])
                mirrored_case = next(
                    item for item in cases_body['cases']
                    if item['metadata']['federation_source_case_id'] == case_id
                )
                self.assertEqual(mirrored_case['status'], 'resolved')
                self.assertEqual(mirrored_case['resolution'], 'Resolve federated control-plane case')

    def test_workspace_case_notice_round_trip_stay_keeps_peer_blocked(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')
        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )

            with _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                open_status, open_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/cases/open',
                    payload={
                        'claim_type': 'misrouted_execution',
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'note': 'Open federated control-plane case for stay path',
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(open_status, 200, open_body)
                case_id = open_body['case']['case_id']

                stay_status, stay_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/cases/stay',
                    payload={
                        'case_id': case_id,
                        'note': 'Stay federated control-plane case',
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(stay_status, 200, stay_body)
                self.assertEqual(stay_body['delivery']['response']['processing']['reason'], 'case_notice_applied')
                self.assertEqual(stay_body['delivery']['response']['processing']['case']['status'], 'stayed')
                self.assertIsNone(stay_body['delivery']['response']['processing']['federation_peer'])
                self.assertIsNone(stay_body['delivery']['response']['processing']['warrant'])

                status, cases_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/cases',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(status, 200, cases_body)
                self.assertEqual(cases_body['total'], 1)
                self.assertEqual(cases_body['blocked_peer_host_ids'], ['host_beta'])
                alpha_case = next(item for item in cases_body['cases'] if item['case_id'] == case_id)
                self.assertEqual(alpha_case['status'], 'stayed')

                status, cases_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/cases',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(status, 200, cases_body)
                self.assertEqual(cases_body['blocked_peer_host_ids'], ['host_alpha'])
                mirrored_case = next(
                    item for item in cases_body['cases']
                    if item['metadata']['federation_source_case_id'] == case_id
                )
                self.assertEqual(mirrored_case['status'], 'stayed')
                self.assertEqual(mirrored_case['review_note'], 'Stay federated control-plane case')

            beta_events = _read_jsonl(beta['audit_log'])
            self.assertTrue(
                any(event.get('action') == 'federation_case_notice_applied' for event in beta_events)
            )

    def test_workspace_case_notice_round_trip_auto_archives_to_witness_peer(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
            port_gamma = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')
        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'gamma-user',
                        'witness_archive_pass': 'gamma-pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            gamma = _seed_workspace_root(
                os.path.join(tmp, 'gamma'),
                org_id='org_gamma',
                user_id='user_witness_gamma',
                host_id='host_gamma',
                port=port_gamma,
                signing_secret='gamma-secret',
                host_role='witness_host',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )

            with _run_workspace(gamma), _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                case_notice_payload = {
                    'claim_type': 'misrouted_execution',
                    'target_host_id': 'host_beta',
                    'target_institution_id': 'org_beta',
                    'note': 'Open federated control-plane case with witness archive',
                    'federate': True,
                }
                open_status, open_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/cases/open',
                    payload=case_notice_payload,
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(open_status, 200, open_body)
                self.assertEqual(open_body['delivery']['witness_archive']['attempted'], 1)
                self.assertEqual(open_body['delivery']['witness_archive']['created'], 1)
                case_id = open_body['case']['case_id']

                resolve_status, resolve_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/cases/resolve',
                    payload={
                        'case_id': case_id,
                        'note': 'Resolve federated control-plane case with witness archive',
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(resolve_status, 200, resolve_body)
                self.assertEqual(resolve_body['delivery']['witness_archive']['attempted'], 1)
                self.assertEqual(resolve_body['delivery']['witness_archive']['created'], 1)
                self.assertEqual(
                    resolve_body['delivery']['response']['processing']['federation_peer']['trust_state'],
                    'trusted',
                )

                gamma_archive_status, gamma_archive_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(gamma_archive_status, 200, gamma_archive_body)
                self.assertEqual(gamma_archive_body['summary']['total'], 2)
                self.assertEqual(
                    gamma_archive_body['summary']['message_type_counts'],
                    {'case_notice': 2},
                )

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            gamma_events = _read_jsonl(gamma['audit_log'])
            self.assertGreaterEqual(
                len([event for event in alpha_events if event.get('action') == 'federation_witness_archive_sent']),
                2,
            )
            self.assertGreaterEqual(
                len([event for event in beta_events if event.get('action') == 'federation_case_notice_applied']),
                2,
            )
            self.assertGreaterEqual(
                len([event for event in gamma_events if event.get('action') == 'federation_witness_observation_archived']),
                2,
            )

    def test_workspace_commitment_settlement_is_blocked_by_active_case(self):
        try:
            port_alpha = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')
        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={},
            )
            with _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                request_payload = {'task': 'settle-demo'}
                warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': 'Deliver governed work',
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                commitment_id = body['commitment']['commitment_id']

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/accept',
                    payload={'commitment_id': commitment_id},
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/cases/open',
                    payload={
                        'claim_type': 'non_delivery',
                        'linked_commitment_id': commitment_id,
                        'linked_warrant_id': warrant['warrant_id'],
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                self.assertEqual(body['warrant']['court_review_state'], 'stayed')

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/settle',
                    payload={'commitment_id': commitment_id},
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 409, body)
                self.assertEqual(body['case']['linked_commitment_id'], commitment_id)
                self.assertEqual(body['warrant']['warrant_id'], warrant['warrant_id'])
                self.assertIn(body['warrant']['reason'], ('already_stayed', 'case_hold_applied'))

                status, warrants_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/warrants',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(status, 200, warrants_body)
                warrant_record = next(
                    item for item in warrants_body['warrants']
                    if item['warrant_id'] == warrant['warrant_id']
                )
                self.assertEqual(warrant_record['court_review_state'], 'stayed')

                alpha_events = _read_jsonl(alpha['audit_log'])
                blocked = [
                    event for event in alpha_events
                    if event.get('action') == 'commitment_settlement_blocked'
                ]
                self.assertTrue(blocked)
                self.assertEqual(blocked[-1]['resource'], commitment_id)

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/cases/resolve',
                    payload={
                        'case_id': body['case']['case_id'],
                        'note': 'Case resolved, settlement may proceed',
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                self.assertEqual(body['case']['status'], 'resolved')

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/settle',
                    payload={'commitment_id': commitment_id},
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                self.assertEqual(body['commitment']['status'], 'settled')

    def test_workspace_federated_commitment_proposal_round_trips_between_two_hosts(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                proposal_payload = {
                    'summary': 'Deliver shared brief',
                    'terms_payload': {'scope': 'shared-brief'},
                }
                warrant = _issue_workspace_warrant(
                    alpha,
                    session['token'],
                    proposal_payload,
                    action_class='cross_institution_commitment',
                )
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': proposal_payload['summary'],
                        'terms_payload': proposal_payload['terms_payload'],
                        'warrant_id': warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                commitment_id = body['commitment']['commitment_id']
                delivery = body['delivery']
                self.assertEqual(delivery['claims']['message_type'], 'commitment_proposal')
                self.assertEqual(delivery['claims']['warrant_id'], warrant['warrant_id'])
                self.assertEqual(delivery['claims']['commitment_id'], commitment_id)
                self.assertEqual(
                    delivery['response']['processing']['reason'],
                    'commitment_proposal_recorded',
                )

                beta_status, beta_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/commitments',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(beta_status, 200, beta_body)
                self.assertEqual(beta_body['total'], 1)
                self.assertEqual(beta_body['proposed'], 1)
                mirrored = next(
                    item for item in beta_body['commitments']
                    if item['commitment_id'] == commitment_id
                )
                self.assertEqual(mirrored['source_host_id'], 'host_alpha')
                self.assertEqual(mirrored['source_institution_id'], 'org_alpha')
                self.assertEqual(mirrored['target_host_id'], 'host_beta')
                self.assertEqual(mirrored['target_institution_id'], 'org_beta')
                self.assertEqual(mirrored['warrant_id'], warrant['warrant_id'])
                self.assertEqual(mirrored['proposed_by'], 'user_owner_alpha')
                self.assertEqual(
                    mirrored['metadata']['federation_source_host_id'],
                    'host_alpha',
                )
                self.assertEqual(
                    mirrored['metadata']['federation_envelope_id'],
                    delivery['claims']['envelope_id'],
                )

                inbox_status, inbox_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['total'], 1)
                self.assertEqual(
                    inbox_body['summary']['message_type_counts'],
                    {'commitment_proposal': 1},
                )
                self.assertEqual(inbox_body['entries'][0]['state'], 'processed')
                self.assertEqual(
                    inbox_body['entries'][0]['message_type'],
                    'commitment_proposal',
                )

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            sent = [
                event for event in alpha_events
                if event.get('action') == 'federation_envelope_sent'
            ]
            recorded = [
                event for event in beta_events
                if event.get('action') == 'federation_commitment_proposal_recorded'
            ]
            self.assertTrue(sent)
            self.assertTrue(recorded)
            self.assertEqual(sent[-1]['details']['warrant_id'], warrant['warrant_id'])
            self.assertEqual(recorded[-1]['resource'], commitment_id)

    def test_workspace_federated_commitment_acceptance_round_trips_back_to_source(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                proposal_payload = {
                    'summary': 'Deliver shared brief',
                    'terms_payload': {'scope': 'shared-brief'},
                }
                proposal_warrant = _issue_workspace_warrant(
                    alpha,
                    alpha_session['token'],
                    proposal_payload,
                    action_class='cross_institution_commitment',
                )
                proposal_status, proposal_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': proposal_payload['summary'],
                        'terms_payload': proposal_payload['terms_payload'],
                        'warrant_id': proposal_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(proposal_status, 200, proposal_body)
                commitment_id = proposal_body['commitment']['commitment_id']

                beta_session = _issue_workspace_session(beta)
                acceptance_payload = {'note': 'Beta accepts the commitment'}
                acceptance_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    acceptance_payload,
                    action_class='cross_institution_commitment',
                )
                status, body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/accept',
                    payload={
                        'commitment_id': commitment_id,
                        'note': acceptance_payload['note'],
                        'warrant_id': acceptance_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 200, body)
                delivery = body['delivery']
                self.assertEqual(delivery['claims']['message_type'], 'commitment_acceptance')
                self.assertEqual(
                    delivery['response']['processing']['reason'],
                    'commitment_acceptance_recorded',
                )
                self.assertEqual(delivery['claims']['warrant_id'], acceptance_warrant['warrant_id'])

                alpha_status, alpha_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/commitments',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_status, 200, alpha_body)
                original = next(
                    item for item in alpha_body['commitments']
                    if item['commitment_id'] == commitment_id
                )
                self.assertEqual(original['status'], 'accepted')
                self.assertEqual(original['accepted_by'], 'user_owner_beta')
                self.assertEqual(original['review_note'], acceptance_payload['note'])

                inbox_status, inbox_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(inbox_body['summary']['total'], 1)
                self.assertEqual(
                    inbox_body['summary']['message_type_counts'],
                    {'commitment_acceptance': 1},
                )
                self.assertEqual(inbox_body['entries'][0]['state'], 'processed')

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            accepted = [
                event for event in alpha_events
                if event.get('action') == 'federation_commitment_acceptance_recorded'
            ]
            sent = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_sent'
            ]
            self.assertTrue(accepted)
            self.assertTrue(sent)
            self.assertEqual(accepted[-1]['resource'], commitment_id)
            self.assertEqual(sent[-1]['details']['warrant_id'], acceptance_warrant['warrant_id'])

    def test_workspace_federated_commitment_proposal_rejects_missing_warrant(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': 'Deliver shared brief',
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 403, body)
                self.assertIn('requires warrant_id', body['error'])
                self.assertIn('commitment', body)

                beta_status, beta_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/commitments',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(beta_status, 200, beta_body)
                self.assertEqual(beta_body['total'], 0)

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            blocked = [
                event for event in alpha_events
                if event.get('action') == 'federation_warrant_blocked'
            ]
            received = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_received'
            ]
            self.assertTrue(blocked)
            self.assertEqual(
                blocked[-1]['details']['required_action_class'],
                'cross_institution_commitment',
            )
            self.assertEqual(received, [])

    def test_workspace_federated_commitment_acceptance_rejects_wrong_target(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                proposal_payload = {'summary': 'Deliver shared brief'}
                proposal_warrant = _issue_workspace_warrant(
                    alpha,
                    alpha_session['token'],
                    proposal_payload,
                    action_class='cross_institution_commitment',
                )
                proposal_status, proposal_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': proposal_payload['summary'],
                        'warrant_id': proposal_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(proposal_status, 200, proposal_body)
                commitment_id = proposal_body['commitment']['commitment_id']

                beta_session = _issue_workspace_session(beta)
                acceptance_payload = {'note': 'Beta accepts the commitment'}
                acceptance_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    acceptance_payload,
                    action_class='cross_institution_commitment',
                )
                status, body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/accept',
                    payload={
                        'commitment_id': commitment_id,
                        'note': acceptance_payload['note'],
                        'warrant_id': acceptance_warrant['warrant_id'],
                        'federate': True,
                        'target_host_id': 'host_gamma',
                        'target_institution_id': 'org_gamma',
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 403, body)
                self.assertIn('source_host_id', body['error'])

                beta_status, beta_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/commitments',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(beta_status, 200, beta_body)
                mirrored = next(
                    item for item in beta_body['commitments']
                    if item['commitment_id'] == commitment_id
                )
                self.assertEqual(mirrored['status'], 'accepted')

                alpha_status, alpha_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/commitments',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_status, 200, alpha_body)
                original = next(
                    item for item in alpha_body['commitments']
                    if item['commitment_id'] == commitment_id
                )
                self.assertEqual(original['status'], 'proposed')

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            blocked = [
                event for event in beta_events
                if event.get('action') == 'federation_commitment_blocked'
            ]
            received = [
                event for event in alpha_events
                if event.get('action') == 'federation_envelope_received'
                and event.get('resource') == 'commitment_acceptance'
            ]
            self.assertTrue(blocked)
            self.assertEqual(received, [])

    def test_workspace_federated_commitment_breach_notice_round_trips_back_to_source(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                proposal_payload = {'summary': 'Deliver shared brief'}
                proposal_warrant = _issue_workspace_warrant(
                    alpha,
                    alpha_session['token'],
                    proposal_payload,
                    action_class='cross_institution_commitment',
                )
                proposal_status, proposal_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': proposal_payload['summary'],
                        'warrant_id': proposal_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(proposal_status, 200, proposal_body)
                commitment_id = proposal_body['commitment']['commitment_id']

                beta_session = _issue_workspace_session(beta)
                acceptance_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    {'note': 'Accepted on beta'},
                    action_class='cross_institution_commitment',
                )
                acceptance_status, acceptance_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/accept',
                    payload={
                        'commitment_id': commitment_id,
                        'note': 'Accepted on beta',
                        'warrant_id': acceptance_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(acceptance_status, 200, acceptance_body)

                breach_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    {'note': 'Breach recorded on beta'},
                    action_class='cross_institution_commitment',
                )
                breach_status, breach_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/breach',
                    payload={
                        'commitment_id': commitment_id,
                        'note': 'Breach recorded on beta',
                        'warrant_id': breach_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(breach_status, 200, breach_body)
                self.assertEqual(
                    breach_body['delivery']['response']['processing']['reason'],
                    'commitment_breach_notice_recorded',
                )
                self.assertEqual(
                    breach_body['delivery']['response']['processing']['federation_peer']['trust_state'],
                    'suspended',
                )

                alpha_status, alpha_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/commitments',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_status, 200, alpha_body)
                original = next(
                    item for item in alpha_body['commitments']
                    if item['commitment_id'] == commitment_id
                )
                self.assertEqual(original['status'], 'breached')
                self.assertEqual(original['breached_by'], 'user_owner_beta')

                case_status, case_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/cases',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(case_status, 200, case_body)
                self.assertEqual(case_body['total'], 1)
                self.assertEqual(case_body['open'], 1)
                self.assertEqual(case_body['blocking_commitment_ids'], [commitment_id])
                self.assertEqual(case_body['cases'][0]['claim_type'], 'breach_of_commitment')
                self.assertEqual(case_body['cases'][0]['target_host_id'], 'host_beta')
                self.assertEqual(case_body['blocked_peer_host_ids'], ['host_beta'])

                inbox_status, inbox_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/federation/inbox',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(inbox_status, 200, inbox_body)
                self.assertEqual(
                    inbox_body['summary']['message_type_counts'],
                    {'commitment_acceptance': 1, 'commitment_breach_notice': 1},
                )

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            recorded = [
                event for event in alpha_events
                if event.get('action') == 'federation_commitment_breach_notice_recorded'
            ]
            sent = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_sent'
                and event.get('resource') == 'commitment_breach_notice'
            ]
            self.assertTrue(recorded)
            self.assertTrue(sent)
            self.assertEqual(recorded[-1]['resource'], commitment_id)
            self.assertEqual(sent[-1]['details']['warrant_id'], breach_warrant['warrant_id'])

    def test_workspace_three_host_federation_story_combines_review_breach_and_witness_archive(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
            port_gamma = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'gamma-user',
                        'witness_archive_pass': 'gamma-pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_gamma': {
                        'label': 'Gamma Witness',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_gamma}',
                        'trust_state': 'trusted',
                        'shared_secret': 'gamma-secret',
                        'witness_archive_user': 'gamma-user',
                        'witness_archive_pass': 'gamma-pass',
                        'admitted_org_ids': ['org_gamma'],
                    },
                },
            )
            gamma = _seed_workspace_root(
                os.path.join(tmp, 'gamma'),
                org_id='org_gamma',
                user_id='user_witness_gamma',
                host_id='host_gamma',
                port=port_gamma,
                signing_secret='gamma-secret',
                host_role='witness_host',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )

            with _run_workspace(gamma), _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                proposal_payload = {
                    'summary': 'Shared competitor brief',
                    'terms_payload': {'scope': 'shared-brief'},
                }
                proposal_warrant = _issue_workspace_warrant(
                    alpha,
                    alpha_session['token'],
                    proposal_payload,
                    action_class='cross_institution_commitment',
                )
                proposal_status, proposal_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': proposal_payload['summary'],
                        'terms_payload': proposal_payload['terms_payload'],
                        'warrant_id': proposal_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(proposal_status, 200, proposal_body)
                self.assertEqual(proposal_body['delivery']['witness_archive']['attempted'], 1)
                self.assertEqual(proposal_body['delivery']['witness_archive']['created'], 1)
                commitment_id = proposal_body['commitment']['commitment_id']

                beta_session = _issue_workspace_session(beta)
                acceptance_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    {'note': 'Beta accepts'},
                    action_class='cross_institution_commitment',
                )
                acceptance_status, acceptance_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/accept',
                    payload={
                        'commitment_id': commitment_id,
                        'note': 'Beta accepts',
                        'warrant_id': acceptance_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(acceptance_status, 200, acceptance_body)
                self.assertEqual(acceptance_body['delivery']['witness_archive']['attempted'], 1)
                self.assertEqual(acceptance_body['delivery']['witness_archive']['created'], 1)

                execution_payload = {'task': 'shared brief review'}
                execution_warrant = _issue_workspace_warrant(
                    alpha,
                    alpha_session['token'],
                    execution_payload,
                    action_class='federated_execution',
                )
                execution_status, execution_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'payload': execution_payload,
                        'warrant_id': execution_warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(execution_status, 200, execution_body)
                self.assertEqual(execution_body['delivery']['witness_archive']['attempted'], 1)
                self.assertEqual(execution_body['delivery']['witness_archive']['created'], 1)

                jobs_status, jobs_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/execution-jobs',
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(jobs_status, 200, jobs_body)
                self.assertEqual(jobs_body['summary']['pending_local_warrant'], 1)
                local_warrant_id = jobs_body['jobs'][0]['local_warrant_id']

                review_status, review_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/warrants/stay',
                    payload={
                        'warrant_id': local_warrant_id,
                        'note': 'Receiver hold pending local review',
                    },
                    headers={'Authorization': beta['auth_header']},
                )
                self.assertEqual(review_status, 200, review_body)
                self.assertEqual(review_body['court_notice']['delivery']['witness_archive']['attempted'], 1)
                self.assertEqual(review_body['court_notice']['delivery']['witness_archive']['created'], 1)

                breach_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    {'note': 'Breach recorded after failed review'},
                    action_class='cross_institution_commitment',
                )
                breach_status, breach_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/breach',
                    payload={
                        'commitment_id': commitment_id,
                        'note': 'Breach recorded after failed review',
                        'warrant_id': breach_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(breach_status, 200, breach_body)
                self.assertEqual(
                    breach_body['delivery']['response']['processing']['federation_peer']['trust_state'],
                    'suspended',
                )
                self.assertEqual(breach_body['delivery']['witness_archive']['attempted'], 1)
                self.assertEqual(breach_body['delivery']['witness_archive']['created'], 1)

                alpha_cases_status, alpha_cases_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/cases',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_cases_status, 200, alpha_cases_body)
                self.assertEqual(alpha_cases_body['total'], 1)
                self.assertEqual(alpha_cases_body['open'], 1)
                self.assertEqual(alpha_cases_body['blocking_commitment_ids'], [commitment_id])
                self.assertEqual(alpha_cases_body['blocked_peer_host_ids'], ['host_beta'])

                gamma_archive_status, gamma_archive_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    headers={'Authorization': gamma['auth_header']},
                )
                self.assertEqual(gamma_archive_status, 200, gamma_archive_body)
                self.assertEqual(gamma_archive_body['summary']['total'], 5)
                self.assertEqual(
                    gamma_archive_body['summary']['message_type_counts'],
                    {
                        'commitment_acceptance': 1,
                        'commitment_breach_notice': 1,
                        'commitment_proposal': 1,
                        'court_notice': 1,
                        'execution_request': 1,
                    },
                )

            gamma_events = _read_jsonl(gamma['audit_log'])
            archived = [
                event for event in gamma_events
                if event.get('action') == 'federation_witness_observation_archived'
            ]
            self.assertGreaterEqual(len(archived), 5)

    def test_workspace_federated_commitment_breach_notice_rejects_missing_warrant(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                proposal_warrant = _issue_workspace_warrant(
                    alpha,
                    alpha_session['token'],
                    {'summary': 'Deliver shared brief'},
                    action_class='cross_institution_commitment',
                )
                proposal_status, proposal_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': 'Deliver shared brief',
                        'warrant_id': proposal_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(proposal_status, 200, proposal_body)
                commitment_id = proposal_body['commitment']['commitment_id']

                beta_session = _issue_workspace_session(beta)
                acceptance_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    {'note': 'Accepted on beta'},
                    action_class='cross_institution_commitment',
                )
                acceptance_status, acceptance_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/accept',
                    payload={
                        'commitment_id': commitment_id,
                        'note': 'Accepted on beta',
                        'warrant_id': acceptance_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(acceptance_status, 200, acceptance_body)

                status, body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/breach',
                    payload={
                        'commitment_id': commitment_id,
                        'note': 'Breach recorded on beta',
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 403, body)
                self.assertIn('requires warrant_id', body['error'])

                alpha_status, alpha_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/cases',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_status, 200, alpha_body)
                self.assertEqual(alpha_body['total'], 0)

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            blocked = [
                event for event in beta_events
                if event.get('action') == 'federation_warrant_blocked'
            ]
            received = [
                event for event in alpha_events
                if event.get('action') == 'federation_envelope_received'
                and event.get('resource') == 'commitment_breach_notice'
            ]
            self.assertTrue(blocked)
            self.assertEqual(received, [])

    def test_workspace_federated_commitment_breach_notice_rejects_wrong_target(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                alpha_session = _issue_workspace_session(alpha)
                proposal_warrant = _issue_workspace_warrant(
                    alpha,
                    alpha_session['token'],
                    {'summary': 'Deliver shared brief'},
                    action_class='cross_institution_commitment',
                )
                proposal_status, proposal_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/commitments/propose',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                        'summary': 'Deliver shared brief',
                        'warrant_id': proposal_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(proposal_status, 200, proposal_body)
                commitment_id = proposal_body['commitment']['commitment_id']

                beta_session = _issue_workspace_session(beta)
                acceptance_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    {'note': 'Accepted on beta'},
                    action_class='cross_institution_commitment',
                )
                acceptance_status, acceptance_body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/accept',
                    payload={
                        'commitment_id': commitment_id,
                        'note': 'Accepted on beta',
                        'warrant_id': acceptance_warrant['warrant_id'],
                        'federate': True,
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(acceptance_status, 200, acceptance_body)

                breach_warrant = _issue_workspace_warrant(
                    beta,
                    beta_session['token'],
                    {'note': 'Breach recorded on beta'},
                    action_class='cross_institution_commitment',
                )
                status, body = _http_json(
                    'POST',
                    beta['base_url'] + '/api/commitments/breach',
                    payload={
                        'commitment_id': commitment_id,
                        'note': 'Breach recorded on beta',
                        'warrant_id': breach_warrant['warrant_id'],
                        'federate': True,
                        'target_host_id': 'host_gamma',
                        'target_institution_id': 'org_gamma',
                    },
                    headers={
                        'Authorization': f"Bearer {beta_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 403, body)
                self.assertIn('source_host_id', body['error'])

                alpha_status, alpha_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/cases',
                    headers={'Authorization': alpha['auth_header']},
                )
                self.assertEqual(alpha_status, 200, alpha_body)
                self.assertEqual(alpha_body['total'], 0)

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            blocked = [
                event for event in beta_events
                if event.get('action') == 'federation_commitment_blocked'
            ]
            received = [
                event for event in alpha_events
                if event.get('action') == 'federation_envelope_received'
                and event.get('resource') == 'commitment_breach_notice'
            ]
            self.assertTrue(blocked)
            self.assertEqual(received, [])

    def test_workspace_federation_send_bad_receipt_auto_stays_warrant(self):
        try:
            port_alpha = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        class BadReceiptHandler(BaseHTTPRequestHandler):
            receive_count = 0

            def log_message(self, format, *args):
                return

            def do_GET(self):
                if self.path != '/api/federation/manifest':
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({
                    'manifest_version': 1,
                    'host_identity': {'host_id': 'host_beta'},
                    'admission': {'admitted_org_ids': ['org_beta']},
                    'service_registry': {
                        'federation_gateway': {
                            'identity_model': 'signed_host_service',
                            'supports_institution_routing': True,
                        },
                    },
                    'federation': {
                        'enabled': True,
                        'boundary_name': 'federation_gateway',
                        'identity_model': 'signed_host_service',
                    },
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != '/api/federation/receive':
                    self.send_response(404)
                    self.end_headers()
                    return
                type(self).receive_count += 1
                length = int(self.headers.get('Content-Length', '0') or 0)
                payload = json.loads(self.rfile.read(length).decode('utf-8') or '{}')
                envelope = payload.get('envelope', '')
                body_b64 = envelope.split('.', 1)[0]
                padding = '=' * ((4 - len(body_b64) % 4) % 4)
                claims = json.loads(base64.urlsafe_b64decode(body_b64 + padding).decode('utf-8'))
                body = json.dumps({
                    'accepted': True,
                    'receipt': {
                        'receipt_id': 'fedrcpt_bad_warrant',
                        'envelope_id': claims['envelope_id'],
                        'accepted_at': '2026-03-22T00:00:00Z',
                        'receiver_host_id': 'host_beta',
                        'receiver_institution_id': 'org_wrong',
                        'message_type': claims['message_type'],
                        'boundary_name': claims['boundary_name'],
                        'identity_model': 'signed_host_service',
                    },
                }).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), BadReceiptHandler)
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                alpha = _seed_workspace_root(
                    os.path.join(tmp, 'alpha'),
                    org_id='org_alpha',
                    user_id='user_owner_alpha',
                    host_id='host_alpha',
                    port=port_alpha,
                    signing_secret='alpha-secret',
                    peer_entries={
                        'host_beta': {
                            'label': 'Beta Host',
                            'transport': 'https',
                            'endpoint_url': f'http://127.0.0.1:{server.server_address[1]}',
                            'trust_state': 'trusted',
                            'shared_secret': 'beta-secret',
                            'admitted_org_ids': ['org_beta'],
                        },
                    },
                )
                with _run_workspace(alpha):
                    session = _issue_workspace_session(alpha)
                    request_payload = {'task': 'demo'}
                    warrant = _issue_workspace_warrant(alpha, session['token'], request_payload)
                    status, body = _http_json(
                        'POST',
                        alpha['base_url'] + '/api/federation/send',
                        payload={
                            'target_host_id': 'host_beta',
                            'target_org_id': 'org_beta',
                            'message_type': 'execution_request',
                            'payload': request_payload,
                            'warrant_id': warrant['warrant_id'],
                        },
                        headers={
                            'Authorization': f"Bearer {session['token']}",
                            'Content-Type': 'application/json',
                        },
                    )
                    self.assertEqual(status, 502, body)
                    self.assertEqual(body['case']['claim_type'], 'misrouted_execution')
                    self.assertEqual(body['case']['linked_warrant_id'], warrant['warrant_id'])
                    self.assertTrue(body['warrant']['applied'])
                    self.assertEqual(body['warrant']['warrant_id'], warrant['warrant_id'])
                    self.assertEqual(body['warrant']['court_review_state'], 'stayed')
                    self.assertEqual(BadReceiptHandler.receive_count, 1)

                    status, warrants_body = _http_json(
                        'GET',
                        alpha['base_url'] + '/api/warrants',
                        headers={'Authorization': alpha['auth_header']},
                    )
                    self.assertEqual(status, 200, warrants_body)
                    warrant_record = next(
                        item for item in warrants_body['warrants']
                        if item['warrant_id'] == warrant['warrant_id']
                    )
                    self.assertEqual(warrant_record['court_review_state'], 'stayed')

                    blocked_status, blocked_body = _http_json(
                        'POST',
                        alpha['base_url'] + '/api/federation/send',
                        payload={
                            'target_host_id': 'host_beta',
                            'target_org_id': 'org_beta',
                            'message_type': 'execution_request',
                            'payload': request_payload,
                            'warrant_id': warrant['warrant_id'],
                        },
                        headers={
                            'Authorization': f"Bearer {session['token']}",
                            'Content-Type': 'application/json',
                        },
                    )
                    self.assertEqual(blocked_status, 403, blocked_body)
                    self.assertIn('court_review_state=stayed', blocked_body['error'])
                    self.assertEqual(BadReceiptHandler.receive_count, 1)

                alpha_events = _read_jsonl(alpha['audit_log'])
                stayed = [e for e in alpha_events if e.get('action') == 'warrant_stayed_for_case']
                failed = [e for e in alpha_events if e.get('action') == 'federation_envelope_delivery_failed']
                self.assertTrue(stayed)
                self.assertEqual(stayed[-1]['resource'], warrant['warrant_id'])
                self.assertTrue(failed)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_workspace_federation_send_rejects_missing_warrant(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'payload': {'task': 'demo'},
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 403, body)
                self.assertIn('requires warrant_id', body['error'])

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            blocked = [
                event for event in alpha_events
                if event.get('action') == 'federation_warrant_blocked'
            ]
            received = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_received'
            ]
            self.assertTrue(blocked)
            self.assertEqual(blocked[-1]['details']['required_action_class'], 'federated_execution')
            self.assertEqual(received, [])

    def test_workspace_federation_send_rejects_stayed_warrant(self):
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
        except PermissionError as exc:
            self.skipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_owner_alpha',
                host_id='host_alpha',
                port=port_alpha,
                signing_secret='alpha-secret',
                peer_entries={
                    'host_beta': {
                        'label': 'Beta Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_beta}',
                        'trust_state': 'trusted',
                        'shared_secret': 'beta-secret',
                        'admitted_org_ids': ['org_beta'],
                    },
                },
            )
            beta = _seed_workspace_root(
                os.path.join(tmp, 'beta'),
                org_id='org_beta',
                user_id='user_owner_beta',
                host_id='host_beta',
                port=port_beta,
                signing_secret='beta-secret',
                peer_entries={
                    'host_alpha': {
                        'label': 'Alpha Host',
                        'transport': 'https',
                        'endpoint_url': f'http://127.0.0.1:{port_alpha}',
                        'trust_state': 'trusted',
                        'shared_secret': 'alpha-secret',
                        'admitted_org_ids': ['org_alpha'],
                    },
                },
            )
            with _run_workspace(beta), _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                request_payload = {'task': 'demo'}
                warrant = _issue_workspace_warrant(
                    alpha,
                    session['token'],
                    request_payload,
                    review_decision='stay',
                )
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'payload': request_payload,
                        'warrant_id': warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                self.assertEqual(status, 403, body)
                self.assertIn('court_review_state=stayed', body['error'])

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            blocked = [
                event for event in alpha_events
                if event.get('action') == 'federation_warrant_blocked'
            ]
            received = [
                event for event in beta_events
                if event.get('action') == 'federation_envelope_received'
            ]
            self.assertTrue(blocked)
            self.assertEqual(blocked[-1]['details']['warrant_id'], warrant['warrant_id'])
            self.assertEqual(received, [])

    def test_upsert_peer_registry_entry_round_trips_file_backed_registry(self):
        from federation import load_peer_registry, upsert_peer_registry_entry
        from runtime_host import default_host_identity

        with tempfile.TemporaryDirectory() as tmp:
            peers_path = os.path.join(tmp, 'federation_peers.json')
            host = default_host_identity(host_id='host_alpha')
            registry = upsert_peer_registry_entry(
                peers_path,
                'host_beta',
                host_identity=host,
                label='Beta Host',
                endpoint_url='http://127.0.0.1:19014',
                shared_secret='beta-secret',
                witness_archive_user='gamma-user',
                witness_archive_pass='gamma-pass',
                admitted_org_ids=['org_beta', 'org_beta'],
            )
            self.assertEqual(registry['host_id'], 'host_alpha')
            self.assertEqual(registry['trusted_peer_ids'], ['host_beta'])

            reloaded = load_peer_registry(peers_path, host_identity=host)
            peer = reloaded['peers']['host_beta']
            self.assertEqual(peer.label, 'Beta Host')
            self.assertEqual(peer.receive_url, 'http://127.0.0.1:19014/api/federation/receive')
            self.assertEqual(peer.admitted_org_ids, ['org_beta'])
            self.assertTrue(peer.to_dict()['witness_archive_configured'])
            self.assertNotIn('witness_archive_user', peer.to_dict())
            self.assertNotIn('witness_archive_pass', peer.to_dict())

    def test_refresh_peer_registry_entry_persists_capability_snapshot(self):
        from federation import refresh_peer_registry_entry, upsert_peer_registry_entry
        from runtime_host import default_host_identity

        with tempfile.TemporaryDirectory() as tmp:
            peers_path = os.path.join(tmp, 'federation_peers.json')
            host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            upsert_peer_registry_entry(
                peers_path,
                'host_beta',
                host_identity=host,
                label='Beta Host',
                endpoint_url='http://127.0.0.1:19015',
                shared_secret='beta-secret',
                witness_archive_user='gamma-user',
                witness_archive_pass='gamma-pass',
                admitted_org_ids=['org_beta'],
            )
            registry = refresh_peer_registry_entry(
                peers_path,
                'host_beta',
                host_identity=host,
                http_get=lambda _url: {
                    'manifest_version': 1,
                    'host_identity': {'host_id': 'host_beta'},
                    'admission': {'admitted_org_ids': ['org_beta']},
                    'service_registry': {
                        'federation_gateway': {
                            'identity_model': 'signed_host_service',
                            'supports_institution_routing': True,
                        },
                    },
                    'federation': {
                        'enabled': True,
                        'boundary_name': 'federation_gateway',
                        'identity_model': 'signed_host_service',
                    },
                },
                target_org_id='org_beta',
            )
            peer = registry['peers']['host_beta']
            self.assertTrue(peer.last_refreshed_at)
            self.assertEqual(peer.capability_snapshot['manifest_version'], 1)
            self.assertEqual(
                peer.capability_snapshot['federation']['boundary_name'],
                'federation_gateway',
            )
            self.assertEqual(peer.witness_archive_user, 'gamma-user')
            self.assertEqual(peer.witness_archive_pass, 'gamma-pass')

    def test_set_peer_trust_state_updates_snapshot_and_send_enabled(self):
        from federation import (
            FederationAuthority,
            set_peer_trust_state,
            upsert_peer_registry_entry,
        )
        from runtime_host import default_host_identity

        with tempfile.TemporaryDirectory() as tmp:
            peers_path = os.path.join(tmp, 'federation_peers.json')
            host = default_host_identity(
                host_id='host_alpha',
                federation_enabled=True,
                peer_transport='https',
            )
            registry = upsert_peer_registry_entry(
                peers_path,
                'host_beta',
                host_identity=host,
                endpoint_url='http://127.0.0.1:19015',
                shared_secret='beta-secret',
                witness_archive_user='gamma-user',
                witness_archive_pass='gamma-pass',
                admitted_org_ids=['org_beta'],
            )
            authority = FederationAuthority(host, signing_secret='alpha-secret', peer_registry=registry)
            snapshot = authority.snapshot(bound_org_id='org_alpha')
            self.assertTrue(snapshot['send_enabled'])
            self.assertEqual(snapshot['routing_summary']['target_institution_id'], 'org_alpha')
            self.assertEqual(snapshot['routing_summary']['delivery_ready_count'], 0)
            self.assertEqual(snapshot['routing_summary']['blocked_peer_ids'], ['host_beta'])
            self.assertEqual(snapshot['peer_delivery_routes'][0]['peer_host_id'], 'host_beta')
            self.assertFalse(snapshot['peer_delivery_routes'][0]['delivery_ready'])
            self.assertIn('target_org_not_admitted', snapshot['peer_delivery_routes'][0]['blocked_reasons'])

            suspended = set_peer_trust_state(
                peers_path,
                'host_beta',
                'suspended',
                host_identity=host,
            )
            suspended_snapshot = FederationAuthority(
                host,
                signing_secret='alpha-secret',
                peer_registry=suspended,
            ).snapshot(bound_org_id='org_alpha')
            self.assertEqual(suspended_snapshot['trusted_peer_ids'], [])
            self.assertEqual(suspended_snapshot['all_peer_count'], 1)
            self.assertFalse(suspended_snapshot['send_enabled'])
            self.assertEqual(suspended_snapshot['routing_summary']['blocked_peer_ids'], ['host_beta'])
            self.assertIn('peer_trust_state_suspended', suspended_snapshot['peer_delivery_routes'][0]['blocked_reasons'])
            self.assertEqual(suspended['peers']['host_beta'].witness_archive_user, 'gamma-user')
            self.assertEqual(suspended['peers']['host_beta'].witness_archive_pass, 'gamma-pass')

    def test_preflight_delivery_validates_peer_manifest(self):
        from federation import FederationAuthority, FederationPeer
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            peer_transport='https',
        )
        authority = FederationAuthority(
            host,
            signing_secret='alpha-secret',
            peer_registry={
                'source': 'test',
                'host_id': 'host_alpha',
                'trusted_peer_ids': ['host_beta'],
                'peers': {
                    'host_beta': FederationPeer(
                        'host_beta',
                        transport='https',
                        endpoint_url='http://127.0.0.1:19017',
                        trust_state='trusted',
                        shared_secret='beta-secret',
                        admitted_org_ids=['org_beta'],
                    ),
                },
            },
        )

        manifest = authority.preflight_delivery(
            'host_beta',
            'org_beta',
            http_get=lambda _url: {
                'host_identity': {
                    'host_id': 'host_beta',
                    'role': 'institution_host',
                },
                'admission': {
                    'admitted_org_ids': ['org_beta'],
                },
                'service_registry': {
                    'federation_gateway': {
                        'identity_model': 'signed_host_service',
                        'supports_institution_routing': True,
                    },
                },
                'federation': {
                    'enabled': True,
                    'boundary_name': 'federation_gateway',
                    'identity_model': 'signed_host_service',
                },
            },
        )
        self.assertEqual(manifest['host_identity']['host_id'], 'host_beta')

    def test_preflight_delivery_rejects_manifest_without_target_org(self):
        from federation import FederationAuthority, FederationDeliveryError, FederationPeer
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            peer_transport='https',
        )
        authority = FederationAuthority(
            host,
            signing_secret='alpha-secret',
            peer_registry={
                'source': 'test',
                'host_id': 'host_alpha',
                'trusted_peer_ids': ['host_beta'],
                'peers': {
                    'host_beta': FederationPeer(
                        'host_beta',
                        transport='https',
                        endpoint_url='http://127.0.0.1:19018',
                        trust_state='trusted',
                        shared_secret='beta-secret',
                        admitted_org_ids=['org_beta'],
                    ),
                },
            },
        )

        with self.assertRaises(FederationDeliveryError):
            authority.preflight_delivery(
                'host_beta',
                'org_gamma',
                http_get=lambda _url: {
                    'host_identity': {
                        'host_id': 'host_beta',
                        'role': 'institution_host',
                    },
                    'admission': {
                        'admitted_org_ids': ['org_beta'],
                    },
                    'service_registry': {
                        'federation_gateway': {
                            'identity_model': 'signed_host_service',
                            'supports_institution_routing': True,
                        },
                    },
                    'federation': {
                        'enabled': True,
                        'boundary_name': 'federation_gateway',
                        'identity_model': 'signed_host_service',
                    },
                },
            )

    def test_snapshot_reports_disabled_without_signing_secret(self):
        from federation import FederationAuthority
        from runtime_host import default_host_identity

        host = default_host_identity(
            host_id='host_alpha',
            federation_enabled=True,
            peer_transport='https',
        )
        snapshot = FederationAuthority(host, signing_secret=None).snapshot(bound_org_id='org_alpha')
        self.assertFalse(snapshot['enabled'])
        self.assertEqual(snapshot['disabled_reason'], 'signing_secret_missing')

    def test_load_peer_registry_rejects_trusted_peer_without_secret(self):
        from federation import load_peer_registry
        from runtime_host import default_host_identity

        with tempfile.TemporaryDirectory() as tmp:
            peers_path = os.path.join(tmp, 'federation_peers.json')
            with open(peers_path, 'w') as f:
                json.dump({
                    'host_id': 'host_alpha',
                    'peers': {
                        'host_beta': {
                            'trust_state': 'trusted',
                            'transport': 'https',
                        }
                    },
                }, f)
            with self.assertRaises(RuntimeError):
                load_peer_registry(peers_path, host_identity=default_host_identity(host_id='host_alpha'))

    def test_workspace_payout_execution_is_warrant_bound_over_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            alpha = _seed_workspace_root(
                os.path.join(tmp, 'alpha'),
                org_id='org_alpha',
                user_id='user_alpha',
                host_id='host_alpha',
                port=_find_free_port(),
                signing_secret='alpha-secret',
            )

            economy_dir = alpha['economy']
            with open(os.path.join(economy_dir, 'ledger.json')) as f:
                ledger = json.load(f)
            ledger['treasury']['cash_usd'] = 140.0
            ledger['treasury']['reserve_floor_usd'] = 50.0
            ledger['treasury']['expenses_recorded_usd'] = 0.0
            _write_json(os.path.join(economy_dir, 'ledger.json'), ledger)
            _write_json(os.path.join(economy_dir, 'wallets.json'), {
                'wallets': {
                    'wallet_alpha': {
                        'id': 'wallet_alpha',
                        'verification_level': 3,
                        'verification_label': 'self_custody_verified',
                        'payout_eligible': True,
                        'status': 'active',
                    },
                },
                'verification_levels': {},
            })
            _write_json(os.path.join(economy_dir, 'contributors.json'), {
                'contributors': {
                    'contrib_alpha': {
                        'id': 'contrib_alpha',
                        'name': 'Contributor Alpha',
                        'payout_wallet_id': 'wallet_alpha',
                    },
                },
                'contribution_types': ['code'],
                'registration_requirements': {},
            })
            _write_json(os.path.join(economy_dir, 'payout_proposals.json'), {
                'proposals': {
                    'ppo_ready': {
                        'proposal_id': 'ppo_ready',
                        'id': 'ppo_ready',
                        'institution_id': 'org_alpha',
                        'contributor_id': 'contrib_alpha',
                        'contributor_name': 'Contributor Alpha',
                        'amount_usd': 12.0,
                        'currency': 'USDC',
                        'contribution_type': 'code',
                        'evidence': {'description': 'seeded integration proof'},
                        'recipient_wallet_id': 'wallet_alpha',
                        'proposed_by': 'user_seed',
                        'reviewed_by': 'user_reviewer',
                        'approved_by': 'user_owner',
                        'status': 'dispute_window',
                        'created_at': '2026-03-20T00:00:00Z',
                        'updated_at': '2026-03-20T00:00:00Z',
                        'submitted_at': '2026-03-20T00:00:00Z',
                        'reviewed_at': '2026-03-20T00:10:00Z',
                        'approved_at': '2026-03-20T00:20:00Z',
                        'dispute_window_started_at': '2026-03-20T00:20:00Z',
                        'dispute_window_ends_at': '2026-03-20T00:20:00Z',
                        'executed_at': '',
                        'executed_by': '',
                        'tx_hash': '',
                        'warrant_id': '',
                        'settlement_adapter': 'internal_ledger',
                        'execution_refs': {},
                        'note': '',
                        'metadata': {},
                    },
                },
            })

            with _run_workspace(alpha):
                session = _issue_workspace_session(alpha)
                token = session['token']
                bearer_headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                }

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/payouts/propose',
                    payload={
                        'contributor_id': 'contrib_alpha',
                        'amount_usd': 3.0,
                        'contribution_type': 'code',
                        'evidence': {'description': 'fresh API proposal'},
                        'recipient_wallet_id': 'wallet_alpha',
                    },
                    headers=bearer_headers,
                )
                self.assertEqual(status, 200)
                self.assertEqual(body['proposal']['status'], 'draft')

                request_payload = {
                    'proposal_id': 'ppo_ready',
                    'settlement_adapter': 'internal_ledger',
                    'tx_hash': 'tx_alpha_demo',
                }
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/warrants/issue',
                    payload={
                        'action_class': 'payout_execution',
                        'boundary_name': 'payouts',
                        'request_payload': request_payload,
                        'risk_class': 'high',
                    },
                    headers=bearer_headers,
                )
                self.assertEqual(status, 200)
                warrant_id = body['warrant']['warrant_id']
                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/warrants/approve',
                    payload={'warrant_id': warrant_id},
                    headers=bearer_headers,
                )
                self.assertEqual(status, 200)

                status, body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/payouts/execute',
                    payload={
                        **request_payload,
                        'warrant_id': warrant_id,
                    },
                    headers=bearer_headers,
                )
                self.assertEqual(status, 200)
                self.assertEqual(body['proposal']['status'], 'executed')
                self.assertEqual(body['proposal']['warrant_id'], warrant_id)
                self.assertEqual(body['warrant']['execution_state'], 'executed')
                self.assertEqual(body['proposal']['execution_refs']['proof_type'], 'ledger_transaction')
                self.assertEqual(body['proposal']['execution_refs']['verification_state'], 'host_ledger_final')

                status, payouts = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/payouts',
                    headers={'Authorization': f'Bearer {token}'},
                )
                self.assertEqual(status, 200)
                self.assertEqual(payouts['summary']['executed'], 1)
                self.assertGreaterEqual(payouts['summary']['total'], 2)
                self.assertEqual(
                    payouts['settlement_adapter_summary']['default_payout_adapter'],
                    'internal_ledger',
                )

            with open(os.path.join(economy_dir, 'ledger.json')) as f:
                ledger = json.load(f)
            self.assertAlmostEqual(ledger['treasury']['cash_usd'], 128.0, places=2)
            self.assertAlmostEqual(ledger['treasury']['expenses_recorded_usd'], 12.0, places=2)

            tx_rows = _read_jsonl(os.path.join(economy_dir, 'transactions.jsonl'))
            self.assertEqual(tx_rows[-1]['type'], 'payout_execution')
            self.assertEqual(tx_rows[-1]['proposal_id'], 'ppo_ready')
            self.assertEqual(tx_rows[-1]['tx_hash'], 'tx_alpha_demo')
            self.assertEqual(tx_rows[-1]['verification_state'], 'host_ledger_final')

            audit_rows = _read_jsonl(alpha['audit_log'])
            actions = [row.get('action') for row in audit_rows]
            self.assertIn('payout_proposal_created', actions)
            self.assertIn('payout_executed', actions)


if __name__ == '__main__':
    unittest.main()
