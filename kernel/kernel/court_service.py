#!/usr/bin/env python3
"""Workspace court, warrant, commitment, and case control plane routes."""

NOT_HANDLED = object()


def handle_get(handler, path, *, org_id, deps, **_ignored):
    if path == '/api/court':
        records = deps._load_records(org_id)
        return handler._json({
            'violations': list(records['violations'].values()),
            'appeals': list(records['appeals'].values()),
        })
    if path == '/api/warrants':
        return handler._json({
            'warrants': deps.list_warrants(org_id),
            'summary': deps._warrant_summary(org_id),
        })
    if path == '/api/commitments':
        return handler._json(deps._commitment_snapshot(org_id))
    if path == '/api/cases':
        return handler._json(deps._case_snapshot(org_id))
    return NOT_HANDLED


def handle_post(handler, path, *, body, org_id, actor_id, session_id, deps, **_ignored):
    if path == '/api/court/file':
        vid = deps.file_violation(
            body['agent'], org_id, body['type'], body['severity'], body['evidence'], body.get('policy_ref', '')
        )
        deps.log_event(
            org_id,
            actor_id,
            'violation_filed',
            resource=vid,
            outcome='success',
            details={'agent': body['agent'], 'type': body['type'], 'severity': body['severity']},
            session_id=session_id,
        )
        return handler._json({'message': f'Violation filed: {vid}', 'violation_id': vid})

    if path == '/api/court/resolve':
        deps.resolve_violation(body['violation_id'], body['note'], org_id=org_id)
        deps.log_event(
            org_id,
            actor_id,
            'violation_resolved',
            resource=body['violation_id'],
            outcome='success',
            details={'note': body['note']},
            session_id=session_id,
        )
        return handler._json({'message': f'Violation resolved: {body["violation_id"]}'})

    if path == '/api/court/appeal':
        aid = deps.file_appeal(body['violation_id'], body['agent'], body['grounds'], org_id=org_id)
        return handler._json({'message': f'Appeal filed: {aid}', 'appeal_id': aid})

    if path == '/api/court/decide-appeal':
        deps.decide_appeal(body['appeal_id'], body['decision'], actor_id, org_id=org_id)
        deps.log_event(
            org_id,
            actor_id,
            'appeal_decided',
            resource=body['appeal_id'],
            outcome='success',
            details={'decision': body['decision']},
            session_id=session_id,
        )
        return handler._json({'message': f'Appeal {body["appeal_id"]}: {body["decision"]}'})

    if path == '/api/court/auto-review':
        vids = deps.auto_review(org_id=org_id)
        deps.log_event(
            org_id,
            actor_id,
            'court_auto_review',
            outcome='success',
            details={'violations': vids, 'count': len(vids)},
            session_id=session_id,
        )
        return handler._json({'message': f'Auto-review: {len(vids)} violation(s) created', 'violations': vids})

    if path == '/api/court/remediate':
        lifted = deps.remediate(body['agent_id'], actor_id, body.get('note', ''), org_id=org_id)
        deps.log_event(
            org_id,
            actor_id,
            'court_remediation',
            resource=body['agent_id'],
            outcome='success',
            details={'lifted': lifted, 'note': body.get('note', '')},
            session_id=session_id,
        )
        return handler._json({'message': f'Remediation complete: lifted {lifted}', 'lifted': lifted})

    if path == '/api/warrants/issue':
        action_class = (body.get('action_class') or '').strip()
        boundary_name = (body.get('boundary_name') or '').strip()
        if not action_class:
            return handler._json({'error': 'action_class is required'}, 400)
        if not boundary_name:
            return handler._json({'error': 'boundary_name is required'}, 400)
        warrant = deps.issue_warrant(
            org_id,
            action_class,
            boundary_name,
            actor_id,
            session_id=session_id or '',
            request_payload=body.get('request_payload'),
            risk_class=(body.get('risk_class') or 'moderate').strip(),
            evidence_refs=body.get('evidence_refs'),
            policy_refs=body.get('policy_refs'),
            ttl_seconds=body.get('ttl_seconds'),
            auto_issue=bool(body.get('auto_issue')),
            note=body.get('note', ''),
        )
        deps.log_event(
            org_id,
            actor_id,
            'warrant_issued',
            outcome='success',
            resource=warrant['warrant_id'],
            details={
                'action_class': warrant['action_class'],
                'boundary_name': warrant['boundary_name'],
                'court_review_state': warrant['court_review_state'],
            },
            session_id=session_id,
        )
        return handler._json({'message': f"Warrant issued: {warrant['warrant_id']}", 'warrant': warrant})

    if path in ('/api/warrants/approve', '/api/warrants/stay', '/api/warrants/revoke'):
        warrant_id = (body.get('warrant_id') or '').strip()
        if not warrant_id:
            return handler._json({'error': 'warrant_id is required'}, 400)
        decision = path.rsplit('/', 1)[-1]
        decision_past = {'approve': 'approved', 'stay': 'stayed', 'revoke': 'revoked'}
        warrant = deps.review_warrant(
            warrant_id,
            decision,
            actor_id,
            org_id=org_id,
            note=body.get('note', ''),
        )
        execution_job = deps._sync_execution_job_for_warrant_review(
            org_id,
            warrant,
            decision=decision,
            note=body.get('note', ''),
            actor_id=actor_id,
            session_id=session_id,
            reason=f'workspace_warrant_{decision}',
        )
        court_notice = None
        if execution_job:
            try:
                court_notice = deps._deliver_execution_job_court_notice(
                    org_id,
                    execution_job,
                    warrant,
                    decision,
                    actor_id=actor_id,
                    session_id=session_id,
                    note=body.get('note', ''),
                )
            except (
                deps.FederationUnavailable,
                deps.FederationDeliveryError,
                deps.FederationValidationError,
                PermissionError,
                LookupError,
                RuntimeError,
                ValueError,
            ) as exc:
                deps.log_event(
                    org_id,
                    actor_id,
                    'federation_court_notice_delivery_failed',
                    outcome='failed',
                    resource=(execution_job or {}).get('job_id', ''),
                    details={'warrant_id': warrant_id, 'decision': decision, 'error': str(exc)},
                    session_id=session_id,
                )
        deps.log_event(
            org_id,
            actor_id,
            f'warrant_{decision}',
            outcome='success',
            resource=warrant_id,
            details={
                'court_review_state': warrant['court_review_state'],
                'execution_job_id': (execution_job or {}).get('job_id', ''),
                'execution_job_state': (execution_job or {}).get('state', ''),
            },
            session_id=session_id,
        )
        response = {'message': f"Warrant {decision_past[decision]}: {warrant_id}", 'warrant': warrant}
        if execution_job:
            response['execution_job'] = execution_job
        if court_notice:
            response['court_notice'] = court_notice
        return handler._json(response)

    if path == '/api/commitments/propose':
        target_host_id = (body.get('target_host_id') or '').strip()
        target_org_id = (body.get('target_institution_id') or body.get('target_org_id') or '').strip()
        summary = (body.get('summary') or body.get('commitment_type') or '').strip()
        if not target_host_id:
            return handler._json({'error': 'target_host_id is required'}, 400)
        if not target_org_id:
            return handler._json({'error': 'target_institution_id is required'}, 400)
        if not summary:
            return handler._json({'error': 'summary is required'}, 400)
        commitment = deps.propose_commitment(
            org_id,
            target_host_id,
            target_org_id,
            summary,
            actor_id,
            terms_payload=body.get('terms_payload'),
            warrant_id=(body.get('warrant_id') or '').strip(),
            note=body.get('note', ''),
            metadata=body.get('metadata'),
        )
        deps.log_event(
            org_id,
            actor_id,
            'commitment_proposed',
            outcome='success',
            resource=commitment['commitment_id'],
            details={
                'target_host_id': target_host_id,
                'target_institution_id': target_org_id,
                'summary': summary,
                'warrant_id': commitment.get('warrant_id', ''),
            },
            session_id=session_id,
        )
        response = {
            'message': f"Commitment proposed: {commitment['commitment_id']}",
            'commitment': commitment,
            'summary': deps._commitment_summary(org_id),
        }
        if body.get('federate'):
            federated_payload = {'summary': summary}
            if 'terms_payload' in body:
                federated_payload['terms_payload'] = body.get('terms_payload')
            if body.get('note'):
                federated_payload['note'] = body.get('note', '')
            if 'metadata' in body:
                federated_payload['metadata'] = body.get('metadata')
            try:
                delivery, federation_state = deps._deliver_federation_envelope(
                    org_id,
                    target_host_id,
                    target_org_id,
                    'commitment_proposal',
                    payload=federated_payload,
                    actor_type='user',
                    actor_id=actor_id,
                    session_id=session_id or '',
                    warrant_id=commitment.get('warrant_id', ''),
                    commitment_id=commitment['commitment_id'],
                )
            except deps.FederationUnavailable as e:
                response['error'] = str(e)
                return handler._json(response, 503)
            except PermissionError as e:
                response['error'] = str(e)
                response['case'] = getattr(e, 'case_record', None)
                response['federation_peer'] = getattr(e, 'federation_peer', None)
                response['warrant'] = getattr(e, 'warrant', None)
                if response['case']:
                    return handler._json(response, 409)
                return handler._json(response, 403)
            except deps.FederationDeliveryError as e:
                response.update({
                    'error': str(e),
                    'peer_host_id': e.peer_host_id,
                    'claims': deps._federation_claims_dict(e.claims),
                    'case': getattr(e, 'case_record', None),
                    'federation_peer': getattr(e, 'federation_peer', None),
                    'warrant': getattr(e, 'warrant', None),
                })
                return handler._json(response, 502)
            response['delivery'] = delivery
            response['runtime_core'] = {'federation': federation_state}
        return handler._json(response)

    if path in ('/api/commitments/accept', '/api/commitments/reject', '/api/commitments/breach', '/api/commitments/settle'):
        commitment_id = (body.get('commitment_id') or '').strip()
        if not commitment_id:
            return handler._json({'error': 'commitment_id is required'}, 400)
        proposal_id = (body.get('proposal_id') or '').strip()
        settlement_proposal = None
        settlement_ref = None
        if proposal_id:
            settlement_proposal = deps.get_payout_proposal(proposal_id, org_id=org_id)
            if not settlement_proposal:
                return handler._json({'error': f'Payout proposal not found: {proposal_id}'}, 404)
            if settlement_proposal.get('status') != 'executed':
                return handler._json({
                    'error': (
                        f"Payout proposal '{proposal_id}' must be executed before settling "
                        f"commitment '{commitment_id}'"
                    ),
                    'proposal': settlement_proposal,
                }, 409)
            if (settlement_proposal.get('linked_commitment_id') or '').strip() != commitment_id:
                return handler._json({
                    'error': (
                        f"Payout proposal '{proposal_id}' is linked to commitment "
                        f"{settlement_proposal.get('linked_commitment_id', '')!r}, not {commitment_id!r}"
                    ),
                    'proposal': settlement_proposal,
                }, 409)
            settlement_ref = {
                'proposal_id': proposal_id,
                'tx_ref': (settlement_proposal.get('execution_refs') or {}).get('tx_ref', ''),
                'settlement_adapter': settlement_proposal.get('settlement_adapter', ''),
                'tx_hash': settlement_proposal.get('tx_hash', ''),
                'proof_type': (settlement_proposal.get('execution_refs') or {}).get('proof_type', ''),
                'verification_state': (settlement_proposal.get('execution_refs') or {}).get('verification_state', ''),
                'finality_state': (settlement_proposal.get('execution_refs') or {}).get('finality_state', ''),
                'warrant_id': settlement_proposal.get('warrant_id', ''),
                'recorded_by': actor_id,
                'proof': (settlement_proposal.get('execution_refs') or {}).get('proof', {}),
            }
        decision = path.rsplit('/', 1)[-1]
        if decision == 'settle':
            case_record, warrant = deps._maybe_block_commitment_settlement(
                commitment_id,
                actor_id,
                org_id=org_id,
                session_id=session_id,
                note=body.get('note', ''),
            )
            if case_record:
                return handler._json({
                    'error': (
                        f"Commitment '{commitment_id}' cannot settle while case "
                        f"'{case_record.get('case_id', '')}' is {case_record.get('status', '')}"
                    ),
                    'case': case_record,
                    'warrant': warrant,
                    'summary': deps._commitment_summary(org_id),
                }, 409)
            if settlement_ref:
                deps.record_settlement_ref(commitment_id, settlement_ref, org_id=org_id)
        decision_past = {'accept': 'accepted', 'reject': 'rejected', 'breach': 'breached', 'settle': 'settled'}
        event_name = {
            'accept': 'commitment_accepted',
            'reject': 'commitment_rejected',
            'breach': 'commitment_breached',
            'settle': 'commitment_settled',
        }[decision]
        commitment = {
            'accept': deps.accept_commitment,
            'reject': deps.reject_commitment,
            'breach': deps.breach_commitment,
            'settle': deps.settle_commitment,
        }[decision](commitment_id, actor_id, org_id=org_id, note=body.get('note', ''))
        deps.log_event(
            org_id,
            actor_id,
            event_name,
            outcome='success',
            resource=commitment_id,
            details={'status': commitment['status']},
            session_id=session_id,
        )
        case_record = None
        warrant = None
        if decision == 'breach' and body.get('open_case', True):
            case_record, created = deps._maybe_open_case_for_commitment_breach(
                commitment,
                actor_id,
                org_id=org_id,
                note=body.get('case_note') or body.get('note', ''),
            )
            if created:
                deps.log_event(
                    org_id,
                    actor_id,
                    'case_opened',
                    outcome='success',
                    resource=case_record['case_id'],
                    details={
                        'claim_type': case_record['claim_type'],
                        'linked_commitment_id': commitment_id,
                        'linked_warrant_id': case_record.get('linked_warrant_id', ''),
                    },
                    session_id=session_id,
                )
            warrant = deps._maybe_stay_warrant_for_case(
                case_record,
                actor_id,
                org_id=org_id,
                session_id=session_id,
                note=body.get('case_note') or body.get('note', ''),
            )
        response = {
            'message': f"Commitment {decision_past[decision]}: {commitment_id}",
            'commitment': commitment,
            'proposal': settlement_proposal,
            'summary': deps._commitment_summary(org_id),
            'case': case_record,
            'warrant': warrant,
        }
        if decision in ('accept', 'breach') and body.get('federate'):
            target_host_id = (
                body.get('target_host_id') or commitment.get('source_host_id') or ''
            ).strip()
            target_org_id = (
                body.get('target_institution_id')
                or body.get('target_org_id')
                or commitment.get('source_institution_id')
                or ''
            ).strip()
            if not target_host_id:
                response['error'] = (
                    f"Commitment '{commitment_id}' does not declare source_host_id for federated {decision} dispatch"
                )
                return handler._json(response, 400)
            if not target_org_id:
                response['error'] = (
                    f"Commitment '{commitment_id}' does not declare source_institution_id for federated {decision} dispatch"
                )
                return handler._json(response, 400)
            federated_payload = {}
            if body.get('note'):
                federated_payload['note'] = body.get('note', '')
            message_type = 'commitment_acceptance' if decision == 'accept' else 'commitment_breach_notice'
            try:
                delivery, federation_state = deps._deliver_federation_envelope(
                    org_id,
                    target_host_id,
                    target_org_id,
                    message_type,
                    payload=federated_payload,
                    actor_type='user',
                    actor_id=actor_id,
                    session_id=session_id or '',
                    warrant_id=(body.get('warrant_id') or '').strip(),
                    commitment_id=commitment_id,
                )
            except deps.FederationUnavailable as e:
                response['error'] = str(e)
                return handler._json(response, 503)
            except PermissionError as e:
                response['error'] = str(e)
                response['case'] = getattr(e, 'case_record', None)
                response['federation_peer'] = getattr(e, 'federation_peer', None)
                response['warrant'] = getattr(e, 'warrant', None)
                if response['case']:
                    return handler._json(response, 409)
                return handler._json(response, 403)
            except deps.FederationDeliveryError as e:
                response.update({
                    'error': str(e),
                    'peer_host_id': e.peer_host_id,
                    'claims': deps._federation_claims_dict(e.claims),
                    'case': getattr(e, 'case_record', None),
                    'federation_peer': getattr(e, 'federation_peer', None),
                    'warrant': getattr(e, 'warrant', None),
                })
                return handler._json(response, 502)
            response['delivery'] = delivery
            response['runtime_core'] = {'federation': federation_state}
        return handler._json(response)

    if path == '/api/cases/open':
        claim_type = (body.get('claim_type') or '').strip()
        if not claim_type:
            return handler._json({'error': 'claim_type is required'}, 400)
        if body.get('federate'):
            target_host_id, target_institution_id = deps._case_notice_delivery_context(
                {
                    'target_host_id': (body.get('target_host_id') or '').strip(),
                    'target_institution_id': (
                        body.get('target_institution_id') or body.get('target_org_id') or ''
                    ).strip(),
                },
                body,
            )
            if not target_host_id:
                return handler._json({'error': 'target_host_id is required for federated case_notice dispatch'}, 400)
            if not target_institution_id:
                return handler._json({'error': 'target_institution_id is required for federated case_notice dispatch'}, 400)
        case_record = deps.open_case(
            org_id,
            claim_type,
            actor_id,
            target_host_id=(body.get('target_host_id') or '').strip(),
            target_institution_id=(body.get('target_institution_id') or body.get('target_org_id') or '').strip(),
            linked_commitment_id=(body.get('linked_commitment_id') or '').strip(),
            linked_warrant_id=(body.get('linked_warrant_id') or '').strip(),
            evidence_refs=body.get('evidence_refs') or [],
            note=body.get('note', ''),
            metadata=body.get('metadata'),
        )
        deps.log_event(
            org_id,
            actor_id,
            'case_opened',
            outcome='success',
            resource=case_record['case_id'],
            details={
                'claim_type': claim_type,
                'linked_commitment_id': case_record.get('linked_commitment_id', ''),
                'linked_warrant_id': case_record.get('linked_warrant_id', ''),
            },
            session_id=session_id,
        )
        federation_peer = deps._maybe_suspend_peer_for_case(case_record, actor_id, org_id=org_id, session_id=session_id)
        warrant = deps._maybe_stay_warrant_for_case(
            case_record,
            actor_id,
            org_id=org_id,
            session_id=session_id,
            note=body.get('note', ''),
        )
        delivery = None
        if body.get('federate'):
            try:
                case_notice_delivery = deps._deliver_case_notice(
                    org_id,
                    case_record,
                    'open',
                    actor_id=actor_id,
                    session_id=session_id or '',
                    body=body,
                )
            except ValueError as e:
                return handler._json({'error': str(e), 'case': case_record}, 400)
            except deps.FederationUnavailable as e:
                return handler._json({'error': str(e), 'case': case_record}, 503)
            except PermissionError as e:
                response = {'error': str(e), 'case': case_record}
                response['federation_peer'] = getattr(e, 'federation_peer', None)
                response['warrant'] = getattr(e, 'warrant', None)
                return handler._json(response, 403)
            except deps.FederationDeliveryError as e:
                response = {
                    'error': str(e),
                    'case': case_record,
                    'peer_host_id': e.peer_host_id,
                    'claims': deps._federation_claims_dict(e.claims),
                    'federation_peer': getattr(e, 'federation_peer', None),
                    'warrant': getattr(e, 'warrant', None),
                }
                return handler._json(response, 502)
            delivery = case_notice_delivery['delivery']
        return handler._json({
            'message': f"Case opened: {case_record['case_id']}",
            'case': case_record,
            'summary': deps._case_snapshot(org_id),
            'federation_peer': federation_peer,
            'warrant': warrant,
            'delivery': delivery,
            **({'runtime_core': case_notice_delivery['runtime_core']} if body.get('federate') else {}),
        })

    if path in ('/api/cases/stay', '/api/cases/resolve'):
        case_id = (body.get('case_id') or '').strip()
        if not case_id:
            return handler._json({'error': 'case_id is required'}, 400)
        decision = path.rsplit('/', 1)[-1]
        event_name = {'stay': 'case_stayed', 'resolve': 'case_resolved'}[decision]
        prior_case = deps.get_case(case_id, org_id=org_id)
        if body.get('federate'):
            target_host_id, target_institution_id = deps._case_notice_delivery_context(prior_case or {}, body)
            if not target_host_id:
                return handler._json({'error': 'target_host_id is required for federated case_notice dispatch', 'case': prior_case}, 400)
            if not target_institution_id:
                return handler._json({'error': 'target_institution_id is required for federated case_notice dispatch', 'case': prior_case}, 400)
        case_record = {'stay': deps.stay_case, 'resolve': deps.resolve_case}[decision](
            case_id,
            actor_id,
            org_id=org_id,
            note=body.get('note', ''),
        )
        deps.log_event(
            org_id,
            actor_id,
            event_name,
            outcome='success',
            resource=case_id,
            details={'status': case_record['status']},
            session_id=session_id,
        )
        federation_peer = None
        warrant = None
        if decision == 'stay':
            federation_peer = deps._maybe_suspend_peer_for_case(case_record, actor_id, org_id=org_id, session_id=session_id)
            warrant = deps._maybe_stay_warrant_for_case(
                case_record,
                actor_id,
                org_id=org_id,
                session_id=session_id,
                note=body.get('note', ''),
            )
        elif decision == 'resolve':
            federation_peer = deps._maybe_restore_peer_for_case(case_record, actor_id, org_id=org_id, session_id=session_id)
        delivery = None
        if body.get('federate'):
            try:
                case_notice_delivery = deps._deliver_case_notice(
                    org_id,
                    case_record,
                    decision,
                    actor_id=actor_id,
                    session_id=session_id or '',
                    body=body,
                )
            except ValueError as e:
                return handler._json({'error': str(e), 'case': case_record}, 400)
            except deps.FederationUnavailable as e:
                return handler._json({'error': str(e), 'case': case_record}, 503)
            except PermissionError as e:
                response = {'error': str(e), 'case': case_record}
                response['federation_peer'] = getattr(e, 'federation_peer', None)
                response['warrant'] = getattr(e, 'warrant', None)
                return handler._json(response, 403)
            except deps.FederationDeliveryError as e:
                response = {
                    'error': str(e),
                    'case': case_record,
                    'peer_host_id': e.peer_host_id,
                    'claims': deps._federation_claims_dict(e.claims),
                    'federation_peer': getattr(e, 'federation_peer', None),
                    'warrant': getattr(e, 'warrant', None),
                }
                return handler._json(response, 502)
            delivery = case_notice_delivery['delivery']
        return handler._json({
            'message': f"Case {case_record['status']}: {case_id}",
            'case': case_record,
            'summary': deps._case_snapshot(org_id),
            'federation_peer': federation_peer,
            'warrant': warrant,
            'delivery': delivery,
            **({'runtime_core': case_notice_delivery['runtime_core']} if body.get('federate') else {}),
        })

    return NOT_HANDLED
