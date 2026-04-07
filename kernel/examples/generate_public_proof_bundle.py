#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import sys
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone


ROOT_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TESTS_DIR = os.path.join(ROOT_DIR, 'kernel', 'tests')
sys.path.insert(0, TESTS_DIR)

try:  # noqa: E402
    from test_legacy_v1_federation_proof import (
        _run_legacy_reference_adapter_federation_proof,
    )
except ImportError:  # noqa: E402
    from test_legacy_v1_federation_proof import (
        _run_legacy_v1_reference_adapter_federation_proof as _run_legacy_reference_adapter_federation_proof,
    )
from test_federation import (  # noqa: E402
    _run_base_usdc_x402_settlement_proof,
    _run_execution_settlement_loop_proof,
    _run_handoff_dispatch_proof,
)
from test_three_host_federation_proof import _run_three_host_federation_proof  # noqa: E402


def _public_manifest_receipt(payload):
    host_identity = payload.get('host_identity', {}) or {}
    institution_context = payload.get('institution_context', {}) or {}
    admission = payload.get('admission', {}) or {}
    service_registry = payload.get('service_registry', {}) or {}
    federation_gateway = service_registry.get('federation_gateway', {}) or {}
    witness_archive = payload.get('witness_archive', {}) or {}
    federation = payload.get('federation', {}) or {}
    return {
        'manifest_version': payload.get('manifest_version'),
        'generated_at': payload.get('generated_at'),
        'host_identity': {
            'host_id': host_identity.get('host_id', ''),
            'label': host_identity.get('label', ''),
            'role': host_identity.get('role', ''),
            'federation_enabled': bool(host_identity.get('federation_enabled')),
            'peer_transport': host_identity.get('peer_transport', ''),
        },
        'institution_context': {
            'org_id': institution_context.get('org_id', ''),
            'institution_slug': institution_context.get('institution_slug', ''),
            'boundary_name': institution_context.get('boundary_name', ''),
            'identity_model': institution_context.get('identity_model', ''),
            'boundary_scope': institution_context.get('boundary_scope', ''),
        },
        'admission': {
            'mode': admission.get('mode', ''),
            'bound_org_id': admission.get('bound_org_id', ''),
            'admitted_org_ids': admission.get('admitted_org_ids', []),
            'additional_institutions_allowed': bool(admission.get('additional_institutions_allowed')),
            'shared_request_routing': bool(admission.get('shared_request_routing')),
            'management_mode': admission.get('management_mode', ''),
            'mutation_enabled': bool(admission.get('mutation_enabled')),
            'mutation_disabled_reason': admission.get('mutation_disabled_reason', ''),
        },
        'service_registry': {
            'federation_gateway': {
                'name': federation_gateway.get('name', ''),
                'identity_model': federation_gateway.get('identity_model', ''),
                'scope': federation_gateway.get('scope', ''),
                'supports_institution_routing': bool(federation_gateway.get('supports_institution_routing')),
                'supports_federation': bool(federation_gateway.get('supports_federation')),
                'requires_admitted_institution': bool(federation_gateway.get('requires_admitted_institution')),
                'requires_warrant': bool(federation_gateway.get('requires_warrant')),
                'required_warrant_actions': federation_gateway.get('required_warrant_actions', {}),
            },
        },
        'witness_archive': {
            'archive_enabled': bool(witness_archive.get('archive_enabled')),
            'archive_disabled_reason': witness_archive.get('archive_disabled_reason', ''),
            'management_mode': witness_archive.get('management_mode', ''),
        },
        'federation': {
            'enabled': bool(federation.get('enabled')),
            'disabled_reason': federation.get('disabled_reason', ''),
            'boundary_name': federation.get('boundary_name', ''),
            'identity_model': federation.get('identity_model', ''),
            'peer_transport': federation.get('peer_transport', ''),
            'send_enabled': bool(federation.get('send_enabled')),
        },
    }


def _fetch_live_manifest(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            raw = response.read()
            payload = json.loads(raw.decode('utf-8'))
            status = getattr(response, 'status', 200)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        return {
            'included': False,
            'attempted': True,
            'route': url,
            'error': str(exc),
        }
    return {
        'included': True,
        'attempted': True,
        'route': url,
        'http_status': status,
        'fetched_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'body_sha256': hashlib.sha256(raw).hexdigest(),
        'manifest': _public_manifest_receipt(payload),
    }


def _derive_sibling_url(url, old_suffix, new_suffix):
    if not url or not url.endswith(old_suffix):
        return ''
    return url[:-len(old_suffix)] + new_suffix


def _fetch_live_runtime_proof(url):
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            raw = response.read()
            payload = json.loads(raw.decode('utf-8'))
            status = getattr(response, 'status', 200)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        return {
            'included': False,
            'attempted': True,
            'route': url,
            'error': str(exc),
        }
    return {
        'included': True,
        'attempted': True,
        'route': url,
        'http_status': status,
        'fetched_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'body_sha256': hashlib.sha256(raw).hexdigest(),
        'receipt': {
            'runtime_id': payload.get('runtime_id', ''),
            'proof_type': payload.get('proof_type', ''),
            'bound_org_id': payload.get('bound_org_id', ''),
            'deployment_truth': payload.get('deployment_truth', {}),
            'health': payload.get('health', {}),
            'pong_probe': payload.get('pong_probe', {}),
            'mapping': payload.get('mapping', {}),
        },
    }


def _latest_local_runtime_receipt():
    runtime_audit_path = os.path.join(ROOT_DIR, 'kernel', 'runtime_audit', 'loom_runtime_events.jsonl')
    if not os.path.exists(runtime_audit_path):
        return {
            'included': False,
            'attempted': False,
            'path': runtime_audit_path,
            'reason': 'no_local_runtime_audit_artifact',
        }

    last_row = None
    with open(runtime_audit_path, encoding='utf-8') as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                last_row = json.loads(line)
            except json.JSONDecodeError:
                continue
    if not last_row:
        return {
            'included': False,
            'attempted': True,
            'path': runtime_audit_path,
            'reason': 'runtime_audit_file_empty',
        }

    details = last_row.get('details', {}) or {}
    return {
        'included': True,
        'attempted': True,
        'path': runtime_audit_path,
        'captured_at': last_row.get('timestamp', ''),
        'audit_event_id': last_row.get('id', ''),
        'receipt': {
            'runtime_event_id': details.get('runtime_event_id', ''),
            'event_schema_version': details.get('event_schema_version', ''),
            'job_id': details.get('job_id', ''),
            'execution_id': details.get('execution_id', ''),
            'decision_id': details.get('decision_id', ''),
            'parity_id': details.get('parity_id', ''),
            'audit_id': details.get('audit_id', ''),
            'runtime_outcome': details.get('runtime_outcome', ''),
            'worker_status': details.get('worker_status', ''),
            'parity_status': details.get('parity_status', ''),
            'budget_reservation_status': details.get('budget_reservation_status', ''),
            'budget_reservation_reason': details.get('budget_reservation_reason', ''),
        },
    }


def _summarize_legacy_reference_proof(proof):
    return {
        'runtime_id': proof.get('runtime_id'),
        'adapter_kind': proof.get('adapter_kind'),
        'scope': proof.get('scope'),
        'action_gate': {
            'allowed': bool((proof.get('action_gate') or {}).get('allowed')),
            'stage': (proof.get('action_gate') or {}).get('stage', ''),
        },
        'commitment_id': proof.get('commitment_id', ''),
        'delivery': {
            'proposal_message_type': (((proof.get('proposal') or {}).get('body') or {}).get('delivery') or {}).get('claims', {}).get('message_type', ''),
            'acceptance_message_type': (((proof.get('acceptance') or {}).get('body') or {}).get('delivery') or {}).get('claims', {}).get('message_type', ''),
            'execution_message_type': (((proof.get('execution') or {}).get('body') or {}).get('delivery') or {}).get('claims', {}).get('message_type', ''),
            'execution_receiver_host_id': (((proof.get('execution') or {}).get('body') or {}).get('delivery') or {}).get('receipt', {}).get('receiver_host_id', ''),
            'proposal_witness_archive_created': (((proof.get('proposal') or {}).get('body') or {}).get('delivery') or {}).get('witness_archive', {}).get('created', 0),
            'acceptance_witness_archive_created': (((proof.get('acceptance') or {}).get('body') or {}).get('delivery') or {}).get('witness_archive', {}).get('created', 0),
            'execution_witness_archive_created': (((proof.get('execution') or {}).get('body') or {}).get('delivery') or {}).get('witness_archive', {}).get('created', 0),
            'review_witness_archive_created': (((proof.get('review') or {}).get('body') or {}).get('court_notice') or {}).get('delivery', {}).get('witness_archive', {}).get('created', 0),
            'breach_witness_archive_created': (((proof.get('breach') or {}).get('body') or {}).get('delivery') or {}).get('witness_archive', {}).get('created', 0),
        },
        'post_action_record': {
            'cost_usd': (proof.get('post_action_record') or {}).get('cost_usd', 0.0),
            'outcome': (proof.get('post_action_record') or {}).get('outcome', ''),
        },
        'meter_event': {
            'org_id': (proof.get('meter') or {}).get('org_id', ''),
            'agent_id': (proof.get('meter') or {}).get('agent_id', ''),
            'metric': (proof.get('meter') or {}).get('metric', ''),
            'quantity': (proof.get('meter') or {}).get('quantity', 0.0),
            'unit': (proof.get('meter') or {}).get('unit', ''),
            'cost_usd': (proof.get('meter') or {}).get('cost_usd', 0.0),
        },
        'audit_event': {
            'action': (proof.get('audit') or {}).get('action', ''),
            'resource': (proof.get('audit') or {}).get('resource', ''),
            'outcome': (proof.get('audit') or {}).get('outcome', ''),
            'actor_type': (proof.get('audit') or {}).get('actor_type', ''),
        },
        'receiver_review': {
            'decision': (((proof.get('review') or {}).get('body') or {}).get('court_notice') or {}).get('court_notice', {}).get('decision', ''),
            'local_warrant_id': (((proof.get('jobs') or {}).get('body') or {}).get('jobs') or [{}])[0].get('local_warrant_id', ''),
        },
        'breach_processing': {
            'trust_state': ((((proof.get('breach') or {}).get('body') or {}).get('delivery') or {}).get('response') or {}).get('processing', {}).get('federation_peer', {}).get('trust_state', ''),
            'blocking_commitment_ids': ((proof.get('cases') or {}).get('body') or {}).get('blocking_commitment_ids', []),
            'blocked_peer_host_ids': ((proof.get('cases') or {}).get('body') or {}).get('blocked_peer_host_ids', []),
        },
        'witness_archive_summary': ((proof.get('witness_archive') or {}).get('body') or {}).get('summary', {}),
        'audit_markers': {
            'alpha_has_breach_notice_recorded': 'federation_commitment_breach_notice_recorded' in ((proof.get('audit_events') or {}).get('alpha_actions') or []),
            'beta_has_witness_archive_sent': 'federation_witness_archive_sent' in ((proof.get('audit_events') or {}).get('beta_actions') or []),
            'gamma_archive_count': (proof.get('audit_events') or {}).get('gamma_archive_count', 0),
        },
    }


def build_bundle(live_manifest_url=None, live_runtime_proof_url=None):
    try:
        three_host = {
            'passed': True,
            'skipped': False,
            'summary': _run_three_host_federation_proof(),
        }
    except unittest.SkipTest as exc:
        three_host = {
            'passed': False,
            'skipped': True,
            'reason': str(exc),
        }
    try:
        handoff_dispatch = {
            'passed': True,
            'skipped': False,
            'summary': _run_handoff_dispatch_proof(),
        }
    except unittest.SkipTest as exc:
        handoff_dispatch = {
            'passed': False,
            'skipped': True,
            'reason': str(exc),
        }
    try:
        execution_loop = {
            'passed': True,
            'skipped': False,
            'summary': _run_execution_settlement_loop_proof(),
        }
    except unittest.SkipTest as exc:
        execution_loop = {
            'passed': False,
            'skipped': True,
            'reason': str(exc),
        }
    try:
        external_settlement = {
            'passed': True,
            'skipped': False,
            'summary': _run_base_usdc_x402_settlement_proof(),
        }
    except unittest.SkipTest as exc:
        external_settlement = {
            'passed': False,
            'skipped': True,
            'reason': str(exc),
        }
    try:
        legacy_proof = {
            'passed': True,
            'skipped': False,
            'summary': _summarize_legacy_reference_proof(
                _run_legacy_reference_adapter_federation_proof()
            ),
        }
    except unittest.SkipTest as exc:
        legacy_proof = {
            'passed': False,
            'skipped': True,
            'reason': str(exc),
        }
    return {
        'proof_bundle_version': 4,
        'generated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'reference_scope': 'oss_kernel_reference',
        'three_host_federation': three_host,
        'handoff_dispatch_reference': handoff_dispatch,
        'execution_settlement_loop_reference': execution_loop,
        'external_settlement_adapter_reference': external_settlement,
        'legacy_reference_adapter_federation': legacy_proof,
        'live_host_receipt': (
            _fetch_live_manifest(live_manifest_url)
            if live_manifest_url else
            {
                'included': False,
                'attempted': False,
                'route': '',
                'reason': 'no_live_manifest_url_supplied',
            }
        ),
        'live_runtime_receipt': (
            _fetch_live_runtime_proof(
                live_runtime_proof_url
                or _derive_sibling_url(live_manifest_url or '', '/api/federation/manifest', '/api/runtime-proof')
            )
            if (live_runtime_proof_url or live_manifest_url) else
            {
                'included': False,
                'attempted': False,
                'route': '',
                'reason': 'no_live_runtime_proof_url_supplied',
            }
        ),
        'local_loom_runtime_receipt': _latest_local_runtime_receipt(),
        'not_live_proven': [
            'live multi-host federation between independent deployments',
            'live end-to-end hosted runtime wiring',
            'live non-internal settlement execution',
        ],
    }


def _proof_status_label(item):
    if item.get('passed'):
        return 'PROVEN'
    if item.get('skipped'):
        return 'SKIPPED'
    return 'UNAVAILABLE'


def _receipt_status_label(item):
    if item.get('included'):
        return 'CAPTURED'
    if item.get('attempted'):
        return 'UNAVAILABLE'
    return 'NOT_REQUESTED'


def _render_live_receipt_summary(item, title, identity_path, detail_path):
    lines = [
        title,
        '-' * len(title),
        f"status:      {_receipt_status_label(item)}",
    ]
    route = item.get('route') or item.get('path') or '(none)'
    lines.append(f"route:       {route}")
    if item.get('included'):
        lines.append(f"fetched_at:  {item.get('fetched_at', item.get('captured_at', ''))}")
        lines.append(f"body_sha256: {item.get('body_sha256', '')}")
        identity = item
        for key in identity_path:
            identity = (identity or {}).get(key, {})
        if isinstance(identity, dict):
            detail = identity
            for key in detail_path:
                detail = (detail or {}).get(key, {})
            if detail_path:
                identity = detail
        if isinstance(identity, dict):
            host_id = identity.get('host_id') or identity.get('runtime_id') or ''
            label = identity.get('label') or identity.get('proof_type') or ''
            if host_id:
                lines.append(f"subject:     {host_id}")
            if label:
                lines.append(f"detail:      {label}")
            runtime_event_id = identity.get('runtime_event_id') or ''
            job_id = identity.get('job_id') or ''
            execution_id = identity.get('execution_id') or ''
            parity_id = identity.get('parity_id') or ''
            budget_status = identity.get('budget_reservation_status') or ''
            if runtime_event_id:
                lines.append(f"runtime_evt: {runtime_event_id}")
            if job_id:
                lines.append(f"job_id:      {job_id}")
            if execution_id:
                lines.append(f"execution:   {execution_id}")
            if parity_id:
                lines.append(f"parity_id:   {parity_id}")
            if budget_status:
                lines.append(f"budget:      {budget_status}")
        else:
            lines.append(f"detail:      {identity}")
    else:
        reason = item.get('reason') or item.get('error') or 'not requested'
        lines.append(f"reason:      {reason}")
    return '\n'.join(lines)


def render_bundle_human(bundle):
    three_host = bundle.get('three_host_federation', {}) or {}
    handoff_dispatch = bundle.get('handoff_dispatch_reference', {}) or {}
    execution_loop = bundle.get('execution_settlement_loop_reference', {}) or {}
    external_settlement = bundle.get('external_settlement_adapter_reference', {}) or {}
    legacy_proof = bundle.get('legacy_reference_adapter_federation', {}) or {}
    live_host = bundle.get('live_host_receipt', {}) or {}
    live_runtime = bundle.get('live_runtime_receipt', {}) or {}
    local_runtime = bundle.get('local_loom_runtime_receipt', {}) or {}
    not_live_proven = bundle.get('not_live_proven', []) or []

    three_host_summary = three_host.get('summary', {}) or {}
    handoff_summary = handoff_dispatch.get('summary', {}) or {}
    execution_loop_summary = execution_loop.get('summary', {}) or {}
    external_settlement_summary = external_settlement.get('summary', {}) or {}
    legacy_summary = legacy_proof.get('summary', {}) or {}

    lines = [
        'Meridian Kernel // PUBLIC PROOF BUNDLE',
        '======================================',
        f"generated_at:    {bundle.get('generated_at', '')}",
        f"bundle_version:  {bundle.get('proof_bundle_version', '')}",
        f"reference_scope: {bundle.get('reference_scope', '')}",
        'phase:           oss reference proofs + optional live host receipts',
        'boundary:        proves kernel reference surfaces; does not imply broad live deployment',
        '',
        'Reference proofs',
        '================',
        f"three_host_federation:               {_proof_status_label(three_host)}",
    ]
    if three_host.get('passed'):
        witness = (three_host_summary.get('witness_archive') or {}).get('summary', {})
        lines.extend(
            [
                f"  boundary_name:                     {three_host_summary.get('boundary_name', '')}",
                f"  local_kernel_runtime_declared:     {three_host_summary.get('local_kernel_runtime_declared', False)}",
                f"  witness_archive_total_records:     {witness.get('total_records', 0)}",
            ]
        )
    else:
        lines.append(f"  reason:                            {three_host.get('reason', 'not available')}")

    lines.append(f"handoff_dispatch_reference:         {_proof_status_label(handoff_dispatch)}")
    if handoff_dispatch.get('passed'):
        lines.extend(
            [
                f"  route_kind:                       {handoff_summary.get('route_kind', '')}",
                f"  dispatch_runner:                  {handoff_summary.get('dispatch_runner', '')}",
                f"  execution_job_state:              {(handoff_summary.get('execution_job') or {}).get('state', '')}",
                f"  inbox_message_counts:             {(handoff_summary.get('inbox') or {}).get('message_type_counts', {})}",
            ]
        )
    else:
        lines.append(f"  reason:                            {handoff_dispatch.get('reason', 'not available')}")

    lines.append(f"execution_settlement_loop:          {_proof_status_label(execution_loop)}")
    if execution_loop.get('passed'):
        lines.extend(
            [
                f"  execution_job_state:              {(execution_loop_summary.get('execution_job') or {}).get('state', '')}",
                f"  settlement_notice_type:           {(execution_loop_summary.get('settlement_notice') or {}).get('message_type', '')}",
                f"  sender_inbox_counts:              {(execution_loop_summary.get('sender_inbox') or {}).get('message_type_counts', {})}",
                f"  sender_commitment_state:          {(execution_loop_summary.get('commitment_states') or {}).get('sender_state', '')}",
            ]
        )
    else:
        lines.append(f"  reason:                            {execution_loop.get('reason', 'not available')}")

    lines.append(f"external_settlement_adapter:        {_proof_status_label(external_settlement)}")
    if external_settlement.get('passed'):
        lines.extend(
            [
                f"  settlement_adapter:               {(external_settlement_summary.get('processing') or {}).get('settlement_adapter', '')}",
                f"  proof_type:                       {(external_settlement_summary.get('processing') or {}).get('proof_type', '')}",
                f"  settlement_path:                  {(external_settlement_summary.get('processing') or {}).get('settlement_path', '')}",
                f"  attestation_type:                 {(external_settlement_summary.get('processing') or {}).get('accepted_attestation_type', '')}",
            ]
        )
    else:
        lines.append(f"  reason:                            {external_settlement.get('reason', 'not available')}")

    lines.append(f"legacy_reference_adapter:            {_proof_status_label(legacy_proof)}")
    if legacy_proof.get('passed'):
        delivery = legacy_summary.get('delivery', {}) or {}
        audit = legacy_summary.get('audit_event', {}) or {}
        lines.extend(
            [
                f"  adapter_kind:                      {legacy_summary.get('adapter_kind', '')}",
                f"  scope:                             {legacy_summary.get('scope', '')}",
                f"  action_gate_stage:                 {(legacy_summary.get('action_gate') or {}).get('stage', '')}",
                f"  execution_message_type:            {delivery.get('execution_message_type', '')}",
                f"  audit_outcome:                     {audit.get('outcome', '')}",
            ]
        )
    else:
        lines.append(f"  reason:                            {legacy_proof.get('reason', 'not available')}")

    lines.extend(
        [
            '',
            'Live receipts',
            '=============',
            _render_live_receipt_summary(
                live_host,
                'Live host manifest receipt',
                ['manifest', 'host_identity'],
                [],
            ),
            '',
            _render_live_receipt_summary(
                live_runtime,
                'Live runtime proof receipt',
                ['receipt'],
                [],
            ),
            '',
            _render_live_receipt_summary(
                local_runtime,
                'Local Loom runtime receipt',
                ['receipt'],
                [],
            ),
            '',
            'Not live proven',
            '===============',
        ]
    )
    if not_live_proven:
        lines.extend([f"- {item}" for item in not_live_proven])
    else:
        lines.append('(none declared)')
    lines.extend(
        [
            '',
            'Next',
            '====',
            '1. Re-run with --format json when you need a machine-readable artifact.',
            '2. Pass --live-manifest-url to attach a truthful live host receipt.',
            '3. Treat every missing live receipt as boundary evidence, not a formatting bug.',
            '',
        ]
    )
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Generate the Meridian public proof bundle.')
    parser.add_argument(
        '--output',
        default='-',
        help='Write JSON bundle to this path, or - for stdout',
    )
    parser.add_argument(
        '--live-manifest-url',
        default='',
        help='Optional public live federation manifest URL to embed as a host receipt',
    )
    parser.add_argument(
        '--live-runtime-proof-url',
        default='',
        help='Optional public live runtime-proof URL; defaults to a sibling of --live-manifest-url when omitted',
    )
    parser.add_argument(
        '--format',
        choices=('json', 'human'),
        default='json',
        help='Render the bundle as structured JSON (default) or human-readable terminal output',
    )
    args = parser.parse_args()

    bundle = build_bundle(
        live_manifest_url=args.live_manifest_url or None,
        live_runtime_proof_url=args.live_runtime_proof_url or None,
    )
    if args.format == 'human':
        raw = render_bundle_human(bundle) + '\n'
    else:
        raw = json.dumps(bundle, indent=2, sort_keys=True) + '\n'
    if args.output == '-':
        sys.stdout.write(raw)
        return
    output_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as handle:
        handle.write(raw)
    print(output_path)


if __name__ == '__main__':
    main()
