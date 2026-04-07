#!/usr/bin/env python3
"""Workspace execution-job control plane routes."""

NOT_HANDLED = object()


def handle_get(handler, path, *, org_id, deps, **_ignored):
    if path == '/api/federation/execution-jobs':
        return handler._json(deps._federation_execution_jobs_snapshot(org_id))
    return NOT_HANDLED


def handle_post(handler, path, *, body, org_id, actor_id, session_id, deps, **_ignored):
    if path != '/api/federation/execution-jobs/execute':
        return NOT_HANDLED

    job_ref = (
        body.get('job_id')
        or body.get('envelope_id')
        or body.get('local_warrant_id')
        or ''
    ).strip()
    if not job_ref:
        return handler._json({'error': 'job_id is required'}, 400)
    if body.get('execution_refs'):
        return handler._json({
            'error': (
                'execution_refs are not accepted; the settlement proof is derived '
                'from the linked payout proposal'
            )
        }, 400)

    job = (
        deps.get_execution_job(job_ref, org_id=org_id)
        or deps.get_execution_job_by_local_warrant(job_ref, org_id)
    )
    if not job:
        return handler._json({'error': f'Execution job not found: {job_ref}'}, 404)

    try:
        execution = deps._complete_federated_execution_job(
            org_id,
            job,
            actor_id=actor_id,
            session_id=session_id,
        )
    except deps.FederationUnavailable as e:
        return handler._json({'error': str(e)}, 503)
    except deps.FederationDeliveryError as e:
        return handler._json({
            'error': str(e),
            'peer_host_id': e.peer_host_id,
            'claims': deps._federation_claims_dict(e.claims),
        }, 502)
    except PermissionError as e:
        return handler._json({'error': str(e)}, 403)
    except LookupError as e:
        return handler._json({'error': str(e)}, 404)
    except ValueError as e:
        return handler._json({'error': str(e)}, 400)

    return handler._json({
        'message': 'Federated execution job executed',
        **execution,
    })
