#!/usr/bin/env python3
"""Workspace federation and admission control plane routes."""

NOT_HANDLED = object()


def handle_get(handler, path, *, org_id, inst_ctx=None, deps, **_ignored):
    if path in ('/api/federation', '/api/federation/peers'):
        host_identity, admission_registry = deps._runtime_host_state(org_id)
        return handler._json(deps._federation_snapshot(
            org_id,
            host_identity=host_identity,
            admission_registry=admission_registry,
        ))
    if path == '/api/federation/inbox':
        return handler._json(deps._federation_inbox_snapshot(org_id))
    if path == '/api/federation/handoff-preview-queue':
        return handler._json(deps._handoff_preview_queue_snapshot(org_id))
    if path == '/api/federation/handoff-dispatch-queue':
        return handler._json(deps._handoff_dispatch_queue_snapshot(org_id))
    if path == '/api/federation/manifest':
        host_identity, admission_registry = deps._runtime_host_state(org_id)
        return handler._json(deps._federation_manifest(
            inst_ctx,
            host_identity=host_identity,
            admission_registry=admission_registry,
        ))
    if path == '/api/federation/witness/archive':
        host_identity, _admission_registry = deps._runtime_host_state(org_id)
        return handler._json(deps._witness_archive_snapshot(org_id, host_identity=host_identity))
    if path == '/api/admission':
        host_identity, admission_registry = deps._runtime_host_state(org_id)
        return handler._json(deps._admission_snapshot(
            org_id,
            host_identity=host_identity,
            admission_registry=admission_registry,
        ))
    return NOT_HANDLED


def _archive_witness_observation(handler, *, bound_org_id, host_identity, body, actor_id, deps, source_manifest=None, target_manifest=None):
    if getattr(host_identity, 'role', '') != 'witness_host':
        return handler._json({
            'error': (
                f"Witness archive is disabled on host '{host_identity.host_id}' "
                f'(witness_host_only)'
            ),
            'witness_archive': deps._witness_archive_snapshot(
                bound_org_id,
                host_identity=host_identity,
            ),
        }, 503)
    envelope = (body.get('envelope') or '').strip()
    if not envelope:
        return handler._json({'error': 'envelope is required'}, 400)
    receipt = body.get('receipt')
    if not isinstance(receipt, dict) or not receipt:
        return handler._json({'error': 'receipt is required'}, 400)
    payload = body.get('payload')
    authority = deps._federation_authority(host_identity)
    claims = authority.validate(
        envelope,
        payload=payload,
        expected_boundary_name='federation_gateway',
    )
    source_peer = authority.peer_registry.get('peers', {}).get(claims.source_host_id)
    if not source_peer:
        raise deps.FederationValidationError(
            f"Source host '{claims.source_host_id}' is not in peer registry"
        )
    if not isinstance(source_manifest, dict):
        source_peer, source_manifest = authority.fetch_peer_manifest(claims.source_host_id)
    authority._validate_peer_manifest(
        source_peer,
        source_manifest,
        target_institution_id=claims.source_institution_id,
    )
    target_peer = authority.peer_registry.get('peers', {}).get(claims.target_host_id)
    if not target_peer:
        raise deps.FederationValidationError(
            f"Target host '{claims.target_host_id}' is not in peer registry"
        )
    if not isinstance(target_manifest, dict):
        target_peer, target_manifest = authority.fetch_peer_manifest(claims.target_host_id)
    authority._validate_peer_manifest(
        target_peer,
        target_manifest,
        target_institution_id=claims.target_institution_id,
    )
    validated_receipt = authority._validate_delivery_receipt(
        {'receipt': receipt},
        peer_host_id=claims.target_host_id,
        target_institution_id=claims.target_institution_id,
        claims=claims,
    )
    record, created = deps.archive_witness_observation(
        deps.WITNESS_ARCHIVE_FILE,
        host_id=host_identity.host_id,
        bound_org_id=bound_org_id,
        actor_id=actor_id,
        claims=claims.to_dict(),
        receipt=validated_receipt,
        payload=payload,
        source_manifest=source_manifest,
        target_manifest=target_manifest,
    )
    deps.log_event(
        bound_org_id,
        actor_id,
        'federation_witness_observation_archived',
        resource=record['archive_id'],
        outcome='success',
        details={
            'created': created,
            'message_type': record.get('message_type', ''),
            'source_host_id': record.get('source_host_id', ''),
            'target_host_id': record.get('target_host_id', ''),
            'receipt_id': record.get('receipt_id', ''),
        },
        session_id=claims.session_id or None,
    )
    return handler._json({
        'message': (
            'Witness observation archived'
            if created else
            f"Witness observation already archived: {record['archive_id']}"
        ),
        'created': created,
        'archive': record,
        'witness_archive': deps._witness_archive_snapshot(
            bound_org_id,
            host_identity=host_identity,
        ),
    })


def handle_ingress_post(handler, path, *, body, inst_ctx, deps):
    if path == '/api/federation/receive':
        try:
            envelope = (body.get('envelope') or '').strip()
            if not envelope:
                return handler._json({'error': 'Federation envelope is required'}, 400)
            peer_registry_override = deps._control_plane_notice_validation_peer_registry(
                inst_ctx.org_id,
                envelope,
            )
            claims, federation_state = deps._accept_federation_request(
                inst_ctx.org_id,
                envelope,
                payload=body.get('payload'),
                peer_registry=peer_registry_override,
            )
            receipt = deps._federation_receipt(
                inst_ctx.org_id,
                federation_state.get('host_id', ''),
                claims,
            )
            inbox_entry = deps._federation_inbox_entry(
                inst_ctx.org_id,
                claims,
                receipt,
                payload=body.get('payload'),
            )
            processing = deps._process_received_federation_message(
                inst_ctx.org_id,
                claims,
                receipt,
                payload=body.get('payload'),
            )
            if processing.get('inbox_entry'):
                inbox_entry = processing['inbox_entry']
            deps.log_event(
                inst_ctx.org_id,
                claims.actor_id or f'peer:{claims.source_host_id}',
                'federation_envelope_received',
                resource=claims.message_type,
                outcome='accepted',
                actor_type=claims.actor_type or 'service',
                details={
                    'envelope_id': claims.envelope_id,
                    'source_host_id': claims.source_host_id,
                    'source_institution_id': claims.source_institution_id,
                    'target_host_id': claims.target_host_id,
                    'target_institution_id': claims.target_institution_id,
                    'nonce': claims.nonce,
                    'boundary_name': claims.boundary_name,
                    'warrant_id': claims.warrant_id,
                    'commitment_id': claims.commitment_id,
                    'receipt_id': receipt['receipt_id'],
                },
                session_id=claims.session_id or None,
            )
            return handler._json({
                'message': 'Federation envelope accepted',
                'claims': claims.to_dict(),
                'receipt': receipt,
                'inbox_entry': inbox_entry,
                'processing': processing,
                'runtime_core': {
                    'federation': dict(
                        federation_state,
                        inbox_summary=deps.summarize_inbox_entries(inst_ctx.org_id),
                    ),
                },
            })
        except deps.FederationUnavailable as e:
            return handler._json({'error': str(e)}, 503)
        except deps.FederationReplayError as e:
            return handler._json({'error': str(e)}, 409)
        except deps.FederationValidationError as e:
            return handler._json({'error': str(e)}, 403)
        except RuntimeError as e:
            return handler._json({'error': str(e)}, 503)
        except ValueError as e:
            return handler._json({'error': str(e)}, 400)

    if path == '/api/federation/witness/archive':
        try:
            host_identity, _admission_registry = deps._runtime_host_state(inst_ctx.org_id)
            return _archive_witness_observation(
                handler,
                bound_org_id=inst_ctx.org_id,
                host_identity=host_identity,
                body=body,
                actor_id=(body.get('actor_id') or '').strip() or 'witness_archive',
                deps=deps,
                source_manifest=body.get('source_manifest'),
                target_manifest=body.get('target_manifest'),
            )
        except deps.FederationDeliveryError as e:
            return handler._json({'error': str(e)}, 502)
        except deps.FederationValidationError as e:
            return handler._json({'error': str(e)}, 403)
        except deps.FederationUnavailable as e:
            return handler._json({'error': str(e)}, 503)
        except RuntimeError as e:
            return handler._json({'error': str(e)}, 503)
        except ValueError as e:
            return handler._json({'error': str(e)}, 400)

    return NOT_HANDLED


def handle_post(handler, path, *, body, org_id, actor_id, session_id, deps, **_ignored):
    if path == '/api/federation/send':
        target_host_id = (body.get('target_host_id') or '').strip()
        target_org_id = (body.get('target_org_id') or '').strip()
        message_type = (body.get('message_type') or '').strip()
        if not target_host_id:
            return handler._json({'error': 'target_host_id is required'}, 400)
        if not target_org_id:
            return handler._json({'error': 'target_org_id is required'}, 400)
        if not message_type:
            return handler._json({'error': 'message_type is required'}, 400)
        try:
            delivery, federation_state = deps._deliver_federation_envelope(
                org_id,
                target_host_id,
                target_org_id,
                message_type,
                payload=body.get('payload'),
                actor_type='user',
                actor_id=actor_id,
                session_id=session_id or '',
                warrant_id=(body.get('warrant_id') or '').strip(),
                commitment_id=(body.get('commitment_id') or '').strip(),
                ttl_seconds=body.get('ttl_seconds'),
            )
        except deps.FederationUnavailable as e:
            return handler._json({'error': str(e)}, 503)
        except PermissionError as e:
            case_record = getattr(e, 'case_record', None)
            if case_record:
                return handler._json({
                    'error': str(e),
                    'case': case_record,
                    'federation_peer': getattr(e, 'federation_peer', None),
                    'warrant': getattr(e, 'warrant', None),
                }, 409)
            return handler._json({'error': str(e)}, 403)
        except deps.FederationDeliveryError as e:
            return handler._json({
                'error': str(e),
                'peer_host_id': e.peer_host_id,
                'claims': deps._federation_claims_dict(e.claims),
                'case': getattr(e, 'case_record', None),
                'federation_peer': getattr(e, 'federation_peer', None),
                'warrant': getattr(e, 'warrant', None),
            }, 502)
        return handler._json({
            'message': 'Federation envelope delivered',
            'delivery': delivery,
            'runtime_core': {
                'federation': federation_state,
            },
        })

    if path == '/api/federation/handoff-preview-queue/acknowledge':
        handoff_id = (body.get('handoff_id') or '').strip()
        if not handoff_id:
            return handler._json({'error': 'handoff_id is required'}, 400)
        by_actor = (body.get('by') or actor_id or '').strip()
        if not by_actor:
            return handler._json({'error': 'by is required'}, 400)
        try:
            promotion = deps._acknowledge_and_dispatch_remote_handoff_preview(
                org_id,
                handoff_id,
                actor_id=by_actor,
                note=body.get('note', ''),
            )
        except LookupError as e:
            return handler._json({'error': str(e)}, 404)
        except PermissionError as e:
            return handler._json({'error': str(e)}, 403)
        except ValueError as e:
            return handler._json({'error': str(e)}, 400)
        response = {
            'message': 'Federation handoff preview acknowledged',
            **promotion,
        }
        if promotion.get('dispatch_record_created'):
            response['message'] = 'Federation handoff preview acknowledged and promoted to dispatch'
        return handler._json(response)

    if path == '/api/federation/handoff-dispatch-queue/run':
        dispatch_id = (body.get('dispatch_id') or body.get('handoff_id') or '').strip()
        if not dispatch_id:
            return handler._json({'error': 'dispatch_id is required'}, 400)
        by_actor = (body.get('by') or actor_id or '').strip()
        if not by_actor:
            return handler._json({'error': 'by is required'}, 400)
        try:
            dispatch_runner = deps._run_federation_dispatch(
                org_id,
                dispatch_id,
                actor_id=by_actor,
                note=body.get('note', ''),
                session_id=session_id,
                payload=body.get('payload'),
                warrant_id=(body.get('warrant_id') or '').strip(),
                commitment_id=(body.get('commitment_id') or '').strip(),
                ttl_seconds=body.get('ttl_seconds'),
            )
        except LookupError as e:
            return handler._json({'error': str(e)}, 404)
        except deps.FederationUnavailable as e:
            return handler._json({'error': str(e)}, 503)
        except PermissionError as e:
            case_record = getattr(e, 'case_record', None)
            if case_record:
                return handler._json({
                    'error': str(e),
                    'case': case_record,
                    'federation_peer': getattr(e, 'federation_peer', None),
                    'warrant': getattr(e, 'warrant', None),
                }, 409)
            return handler._json({'error': str(e)}, 403)
        except deps.FederationDeliveryError as e:
            return handler._json({
                'error': str(e),
                'peer_host_id': e.peer_host_id,
                'claims': deps._federation_claims_dict(e.claims),
                'case': getattr(e, 'case_record', None),
                'federation_peer': getattr(e, 'federation_peer', None),
                'warrant': getattr(e, 'warrant', None),
            }, 502)
        except ValueError as e:
            return handler._json({'error': str(e)}, 400)
        response = {
            'message': 'Federation handoff dispatch executed',
            **dispatch_runner,
        }
        if dispatch_runner.get('dispatch_runner') == 'remote_http_federation_runner':
            response['message'] = (
                'Federation handoff dispatch delivered to remote host '
                'and receiver-side execution job was persisted'
            )
            if dispatch_runner.get('blocking_case'):
                response['message'] = (
                    'Federation handoff dispatch delivered to remote host '
                    'and receiver-side execution job was blocked by case'
                )
            if dispatch_runner.get('already_dispatched'):
                response['message'] = 'Federation handoff dispatch was already delivered to the remote host'
        else:
            response['message'] = 'Federation handoff dispatch promoted to receiver-side execution job'
            if dispatch_runner.get('blocking_case'):
                response['message'] = 'Federation handoff dispatch promoted to blocked receiver-side execution job'
        return handler._json(response)

    if path in (
        '/api/federation/peers/upsert',
        '/api/federation/peers/refresh',
        '/api/federation/peers/suspend',
        '/api/federation/peers/revoke',
    ):
        action = path.rsplit('/', 1)[-1]
        peer_host_id = (body.get('peer_host_id') or body.get('host_id') or '').strip()
        snapshot = deps._mutate_federation_peer(org_id, action, body)
        peer_record = next(
            (
                peer for peer in snapshot.get('peers', [])
                if peer.get('host_id') == peer_host_id
            ),
            None,
        )
        deps.log_event(
            org_id,
            actor_id,
            f'federation_peer_{action}',
            resource=peer_host_id,
            outcome='success',
            details={
                'peer_host_id': peer_host_id,
                'host_id': snapshot['host_id'],
                'management_mode': snapshot['management_mode'],
                'trust_state': (peer_record or {}).get('trust_state', ''),
                'last_refreshed_at': (peer_record or {}).get('last_refreshed_at', ''),
                'manifest_version': (
                    ((peer_record or {}).get('capability_snapshot') or {}).get('manifest_version')
                ),
            },
            session_id=session_id,
        )
        return handler._json({
            'message': f'Federation peer {action} applied to {peer_host_id}',
            'federation': snapshot,
        })

    if path in ('/api/admission/admit', '/api/admission/suspend', '/api/admission/revoke'):
        action = path.rsplit('/', 1)[-1]
        target_org_id = body.get('org_id')
        snapshot = deps._mutate_admission(org_id, action, target_org_id)
        deps.log_event(
            org_id,
            actor_id,
            f'admission_{action}',
            resource=target_org_id or '',
            outcome='success',
            details={
                'target_org_id': target_org_id,
                'host_id': snapshot['host_id'],
                'host_role': snapshot['host_role'],
                'status': snapshot['institutions'][target_org_id]['status'],
            },
            session_id=session_id,
        )
        return handler._json({
            'message': f'Admission {action} applied to {target_org_id}',
            'admission': snapshot,
        })

    return NOT_HANDLED
