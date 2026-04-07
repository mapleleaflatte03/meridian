#!/usr/bin/env python3
"""Workspace treasury and payout control plane routes."""

NOT_HANDLED = object()


def handle_get(handler, path, *, org_id, deps, **_ignored):
    if path == '/api/treasury':
        return handler._json(deps.treasury_snapshot(org_id))
    if path == '/api/treasury/wallets':
        return handler._json(deps.load_wallets(org_id))
    if path == '/api/treasury/accounts':
        return handler._json(deps.load_treasury_accounts(org_id))
    if path == '/api/treasury/maintainers':
        return handler._json(deps.load_maintainers(org_id))
    if path == '/api/treasury/contributors':
        return handler._json(deps.load_contributors(org_id))
    if path == '/api/treasury/proposals':
        return handler._json(deps.load_payout_proposals(org_id))
    if path == '/api/treasury/settlement-adapters':
        host_identity, _admission_registry = deps._runtime_host_state(org_id)
        return handler._json({
            'bound_org_id': org_id,
            'summary': deps.settlement_adapter_summary(
                org_id,
                host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
            ),
            'adapters': deps.list_settlement_adapters(org_id),
        })
    if path == '/api/treasury/settlement-adapters/readiness':
        host_identity, _admission_registry = deps._runtime_host_state(org_id)
        return handler._json(deps._settlement_adapter_readiness_snapshot(
            org_id,
            host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
        ))
    if path == '/api/treasury/funding-sources':
        return handler._json(deps.load_funding_sources(org_id))
    if path == '/api/treasury/payout-plan-preview-queue':
        return handler._json(deps._payout_plan_preview_queue_snapshot(org_id))
    if path == '/api/treasury/payout-plan-preview-queue/inspect':
        return handler._json(deps._payout_plan_preview_queue_inspection(org_id))
    if path == '/api/treasury/payout-plan-approval-candidate-queue':
        return handler._json(deps.payout_plan_approval_candidate_queue_snapshot(org_id))
    if path == '/api/treasury/payout-execution-queue':
        return handler._json(deps.payout_execution_queue_snapshot(org_id))
    if path == '/api/treasury/payout-plan-approval-candidate-queue/inspect':
        return handler._json(deps.inspect_payout_plan_approval_candidate_queue(org_id))
    if path == '/api/payouts':
        host_identity, _admission_registry = deps._runtime_host_state(org_id)
        return handler._json(deps._payout_snapshot(
            org_id,
            host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
        ))
    return NOT_HANDLED


def handle_post(handler, path, *, body, org_id, actor_id, session_id, auth_context, deps, **_ignored):
    if path == '/api/treasury/contribute':
        result = deps.contribute_owner_capital(
            body['amount'],
            body.get('note', ''),
            actor_id,
            org_id=org_id,
        )
        deps.log_event(
            org_id,
            actor_id,
            'treasury_owner_capital',
            outcome='success',
            details=result,
            session_id=session_id,
        )
        return handler._json({
            'message': f'Owner capital recorded: +${result["amount_usd"]:.2f}',
            'snapshot': deps.treasury_snapshot(org_id),
        })

    if path == '/api/treasury/reserve-floor':
        result = deps.set_reserve_floor_policy(
            body['amount'],
            body.get('note', ''),
            actor_id,
            org_id=org_id,
        )
        deps.log_event(
            org_id,
            actor_id,
            'treasury_reserve_floor_updated',
            outcome='success',
            details=result,
            session_id=session_id,
        )
        return handler._json({
            'message': 'Reserve floor updated',
            'snapshot': deps.treasury_snapshot(org_id),
        })

    if path == '/api/treasury/settlement-adapters/preflight':
        host_identity, _admission_registry = deps._runtime_host_state(org_id)
        result = deps.preflight_settlement_adapter(
            (body.get('adapter_id') or '').strip(),
            org_id=org_id,
            currency=body.get('currency') or 'USDC',
            tx_hash=(body.get('tx_hash') or '').strip(),
            settlement_proof=body.get('settlement_proof'),
            host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
        )
        deps.log_event(
            org_id,
            actor_id,
            'settlement_adapter_preflight_checked',
            outcome=('success' if result.get('preflight_ok') else 'warning'),
            details={
                'requested_adapter_id': result.get('requested_adapter_id', ''),
                'preflight_ok': result.get('preflight_ok', False),
                'error_type': result.get('error_type', ''),
                'error': result.get('error', ''),
            },
            session_id=session_id,
        )
        return handler._json(result)

    if path == '/api/payouts/propose':
        proposal = deps.create_payout_proposal(
            (body.get('contributor_id') or '').strip(),
            body.get('amount_usd'),
            (body.get('contribution_type') or '').strip(),
            proposed_by=actor_id,
            org_id=org_id,
            evidence=body.get('evidence'),
            recipient_wallet_id=(body.get('recipient_wallet_id') or '').strip(),
            currency=body.get('currency') or 'USDC',
            settlement_adapter=(body.get('settlement_adapter') or 'internal_ledger').strip(),
            note=body.get('note', ''),
            metadata=body.get('metadata'),
            linked_commitment_id=(body.get('linked_commitment_id') or '').strip(),
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_proposal_created',
            outcome='success',
            resource=proposal['proposal_id'],
            details={
                'contributor_id': proposal['contributor_id'],
                'amount_usd': proposal['amount_usd'],
                'recipient_wallet_id': proposal['recipient_wallet_id'],
                'settlement_adapter': proposal['settlement_adapter'],
                'linked_commitment_id': proposal.get('linked_commitment_id', ''),
            },
            session_id=session_id,
        )
        return handler._json({
            'message': f"Payout proposal created: {proposal['proposal_id']}",
            'proposal': proposal,
            'summary': deps.payout_proposal_summary(org_id),
        })

    if path == '/api/payouts/submit':
        proposal_id = (body.get('proposal_id') or '').strip()
        if not proposal_id:
            return handler._json({'error': 'proposal_id is required'}, 400)
        proposal = deps.submit_payout_proposal(
            proposal_id,
            actor_id,
            org_id=org_id,
            note=body.get('note', ''),
            owner_override=(auth_context.get('role') == 'owner'),
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_proposal_submitted',
            outcome='success',
            resource=proposal_id,
            details={'status': proposal['status']},
            session_id=session_id,
        )
        return handler._json({
            'message': f'Payout proposal submitted: {proposal_id}',
            'proposal': proposal,
            'summary': deps.payout_proposal_summary(org_id),
        })

    if path == '/api/payouts/review':
        proposal_id = (body.get('proposal_id') or '').strip()
        if not proposal_id:
            return handler._json({'error': 'proposal_id is required'}, 400)
        proposal = deps.review_payout_proposal(
            proposal_id,
            actor_id,
            org_id=org_id,
            note=body.get('note', ''),
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_proposal_under_review',
            outcome='success',
            resource=proposal_id,
            details={'status': proposal['status']},
            session_id=session_id,
        )
        return handler._json({
            'message': f'Payout proposal under review: {proposal_id}',
            'proposal': proposal,
            'summary': deps.payout_proposal_summary(org_id),
        })

    if path == '/api/payouts/approve':
        proposal_id = (body.get('proposal_id') or '').strip()
        if not proposal_id:
            return handler._json({'error': 'proposal_id is required'}, 400)
        proposal = deps.approve_payout_proposal(
            proposal_id,
            actor_id,
            org_id=org_id,
            note=body.get('note', ''),
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_proposal_approved',
            outcome='success',
            resource=proposal_id,
            details={'status': proposal['status']},
            session_id=session_id,
        )
        return handler._json({
            'message': f'Payout proposal approved: {proposal_id}',
            'proposal': proposal,
            'summary': deps.payout_proposal_summary(org_id),
        })

    if path == '/api/payouts/open-dispute-window':
        proposal_id = (body.get('proposal_id') or '').strip()
        if not proposal_id:
            return handler._json({'error': 'proposal_id is required'}, 400)
        proposal = deps.open_payout_dispute_window(
            proposal_id,
            actor_id,
            org_id=org_id,
            note=body.get('note', ''),
            dispute_window_hours=body.get('dispute_window_hours'),
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_dispute_window_opened',
            outcome='success',
            resource=proposal_id,
            details={
                'status': proposal['status'],
                'dispute_window_ends_at': proposal.get('dispute_window_ends_at', ''),
            },
            session_id=session_id,
        )
        return handler._json({
            'message': f'Payout dispute window opened: {proposal_id}',
            'proposal': proposal,
            'summary': deps.payout_proposal_summary(org_id),
        })

    if path == '/api/payouts/reject':
        proposal_id = (body.get('proposal_id') or '').strip()
        if not proposal_id:
            return handler._json({'error': 'proposal_id is required'}, 400)
        proposal = deps.reject_payout_proposal(
            proposal_id,
            actor_id,
            org_id=org_id,
            note=body.get('note', ''),
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_proposal_rejected',
            outcome='success',
            resource=proposal_id,
            details={'status': proposal['status']},
            session_id=session_id,
        )
        return handler._json({
            'message': f'Payout proposal rejected: {proposal_id}',
            'proposal': proposal,
            'summary': deps.payout_proposal_summary(org_id),
        })

    if path == '/api/payouts/cancel':
        proposal_id = (body.get('proposal_id') or '').strip()
        if not proposal_id:
            return handler._json({'error': 'proposal_id is required'}, 400)
        proposal = deps.cancel_payout_proposal(
            proposal_id,
            actor_id,
            org_id=org_id,
            note=body.get('note', ''),
            owner_override=(auth_context.get('role') == 'owner'),
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_proposal_cancelled',
            outcome='success',
            resource=proposal_id,
            details={'status': proposal['status']},
            session_id=session_id,
        )
        return handler._json({
            'message': f'Payout proposal cancelled: {proposal_id}',
            'proposal': proposal,
            'summary': deps.payout_proposal_summary(org_id),
        })

    if path == '/api/treasury/payout-plan-approval-candidate-queue/promote':
        preview_id = (body.get('preview_id') or '').strip()
        if not preview_id:
            return handler._json({'error': 'preview_id is required'}, 400)
        candidate = deps.promote_payout_plan_preview_to_approval_candidate(
            preview_id,
            actor_id,
            org_id=org_id,
            promotion_note=body.get('note', ''),
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_plan_preview_promoted_to_approval_candidate',
            outcome='success',
            resource=preview_id,
            details={
                'proposal_id': candidate.get('proposal_id', ''),
                'candidate_id': candidate.get('candidate_id', ''),
                'promoted_at': candidate.get('promoted_at', ''),
            },
            session_id=session_id,
        )
        return handler._json({
            'message': f'Payout-plan approval candidate promoted: {preview_id}',
            'candidate': candidate,
            'summary': deps.payout_plan_approval_candidate_queue_snapshot(org_id)['summary'],
        })

    if path == '/api/payouts/execute':
        proposal_id = (body.get('proposal_id') or '').strip()
        warrant_id = (body.get('warrant_id') or '').strip()
        if not proposal_id:
            return handler._json({'error': 'proposal_id is required'}, 400)
        if not warrant_id:
            return handler._json({'error': 'warrant_id is required'}, 400)
        proposal_record = deps.get_payout_proposal(proposal_id, org_id=org_id)
        linked_commitment_id = (proposal_record or {}).get('linked_commitment_id', '').strip()
        if linked_commitment_id:
            case_record, settlement_warrant = deps._maybe_block_commitment_settlement(
                linked_commitment_id,
                actor_id,
                org_id=org_id,
                session_id=session_id,
                note=body.get('note', ''),
            )
            if case_record:
                return handler._json({
                    'error': (
                        f"Linked commitment '{linked_commitment_id}' cannot settle while case "
                        f"'{case_record.get('case_id', '')}' is {case_record.get('status', '')}"
                    ),
                    'case': case_record,
                    'warrant': settlement_warrant,
                    'linked_commitment_id': linked_commitment_id,
                    'summary': deps.payout_proposal_summary(org_id),
                }, 409)
        host_identity, _admission_registry = deps._runtime_host_state(org_id)
        request_payload = {
            'proposal_id': proposal_id,
            'settlement_adapter': (body.get('settlement_adapter') or 'internal_ledger').strip(),
            'tx_hash': (body.get('tx_hash') or '').strip(),
        }
        if linked_commitment_id:
            request_payload['linked_commitment_id'] = linked_commitment_id
        if 'settlement_proof' in body:
            request_payload['settlement_proof'] = body.get('settlement_proof')
        warrant = deps.validate_warrant_for_execution(
            warrant_id,
            org_id=org_id,
            action_class='payout_execution',
            boundary_name='payouts',
            actor_id=actor_id,
            session_id=session_id or '',
            request_payload=request_payload,
        )
        dry_run = bool(body.get('dry_run'))
        proposal = deps.execute_payout_proposal(
            proposal_id,
            actor_id,
            org_id=org_id,
            warrant_id=warrant_id,
            settlement_adapter=request_payload['settlement_adapter'],
            tx_hash=request_payload['tx_hash'],
            note=body.get('note', ''),
            allow_early=bool(body.get('allow_early')),
            settlement_proof=body.get('settlement_proof'),
            host_supported_adapters=getattr(host_identity, 'settlement_adapters', []),
            dry_run=dry_run,
        )
        if dry_run:
            deps.log_event(
                org_id,
                actor_id,
                'payout_execution_previewed',
                outcome='success',
                resource=proposal_id,
                details={
                    'amount_usd': proposal['execution_plan']['amount_usd'],
                    'recipient_wallet_id': proposal['execution_plan']['recipient_wallet_id'],
                    'warrant_id': warrant_id,
                    'tx_ref': proposal['execution_plan']['tx_ref'],
                    'linked_commitment_id': linked_commitment_id,
                },
                session_id=session_id,
            )
            return handler._json({
                'message': f'Payout execution previewed: {proposal_id}',
                'proposal': proposal,
                'warrant': warrant,
                'summary': deps.payout_proposal_summary(org_id),
            })
        warrant = deps.mark_warrant_executed(
            warrant_id,
            org_id=org_id,
            execution_refs={
                **dict(proposal.get('execution_refs') or {}),
                'proposal_id': proposal_id,
            },
        )
        deps.log_event(
            org_id,
            actor_id,
            'payout_executed',
            outcome='success',
            resource=proposal_id,
            details={
                'amount_usd': proposal['amount_usd'],
                'recipient_wallet_id': proposal['recipient_wallet_id'],
                'warrant_id': warrant_id,
                'tx_ref': (proposal.get('execution_refs') or {}).get('tx_ref', ''),
                'linked_commitment_id': linked_commitment_id,
            },
            session_id=session_id,
        )
        return handler._json({
            'message': f'Payout executed: {proposal_id}',
            'proposal': proposal,
            'warrant': warrant,
            'summary': deps.payout_proposal_summary(org_id),
        })

    return NOT_HANDLED
