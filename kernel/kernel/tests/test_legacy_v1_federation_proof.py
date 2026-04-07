#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(THIS_DIR, '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, THIS_DIR)

from adapters import legacy_v1_compatible as legacy_v1_adapter  # noqa: E402
from test_federation import (  # noqa: E402
    _find_free_port,
    _http_json,
    _issue_workspace_session,
    _issue_workspace_warrant,
    _read_jsonl,
    _run_workspace,
    _seed_workspace_root,
)


def _run_legacy_v1_reference_adapter_federation_proof():
    orig_check_authority = legacy_v1_adapter.check_authority
    orig_check_budget = legacy_v1_adapter.check_budget
    orig_get_restrictions = legacy_v1_adapter.get_restrictions
    orig_meter_record = legacy_v1_adapter.meter_record
    orig_log_event = legacy_v1_adapter.log_event
    try:
        try:
            port_alpha = _find_free_port()
            port_beta = _find_free_port()
            port_gamma = _find_free_port()
        except PermissionError as exc:
            raise unittest.SkipTest(f'localhost socket bind unavailable in sandbox: {exc}')

        seen = {}
        legacy_v1_adapter.get_restrictions = lambda agent_id, org_id=None: []
        legacy_v1_adapter.check_authority = lambda agent_id, action_type, org_id=None: (True, 'ok')
        legacy_v1_adapter.check_budget = lambda agent_id, cost_usd, org_id=None: (True, 'ok')
        legacy_v1_adapter.meter_record = lambda org_id, agent_id, metric, quantity=1.0, unit='calls', cost_usd=0.0, run_id='', details=None: (
            seen.setdefault(
                'meter',
                {
                    'org_id': org_id,
                    'agent_id': agent_id,
                    'metric': metric,
                    'quantity': quantity,
                    'unit': unit,
                    'cost_usd': cost_usd,
                    'run_id': run_id,
                    'details': details or {},
                },
            ) or 'meter_legacy_v1_ref'
        )
        legacy_v1_adapter.log_event = lambda org_id, agent_id, action, resource='', outcome='success', actor_type='agent', details=None, policy_ref='', session_id=None: (
            seen.setdefault(
                'audit',
                {
                    'org_id': org_id,
                    'agent_id': agent_id,
                    'action': action,
                    'resource': resource,
                    'outcome': outcome,
                    'actor_type': actor_type,
                    'details': details or {},
                    'session_id': session_id,
                },
            ) or 'event_legacy_v1_ref'
        )

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
                adapter_envelope = legacy_v1_adapter.build_action_envelope(
                    'atlas',
                    'federated_execution',
                    'host_beta/shared_brief_review',
                    0.10,
                    run_id='run_three_host_proof',
                    session_id=alpha_session['token'][:16],
                    details={
                        'message_type': 'execution_request',
                        'target_host_id': 'host_beta',
                        'target_institution_id': 'org_beta',
                    },
                )
                action_gate = legacy_v1_adapter.pre_action_check('org_alpha', adapter_envelope)
                assert action_gate['allowed'], action_gate
                assert action_gate['stage'] == 'ok', action_gate

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
                assert proposal_status == 200, proposal_body
                assert proposal_body['delivery']['claims']['message_type'] == 'commitment_proposal', proposal_body
                assert proposal_body['delivery']['witness_archive']['created'] == 1, proposal_body
                commitment_id = proposal_body['commitment']['commitment_id']
                assert proposal_body['delivery']['claims']['commitment_id'] == commitment_id, proposal_body

                adapter_envelope['details']['commitment_id'] = commitment_id
                execution_request_payload = {
                    'task': 'shared brief review',
                    'adapter_envelope': adapter_envelope,
                }

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
                assert acceptance_status == 200, acceptance_body
                assert acceptance_body['delivery']['claims']['message_type'] == 'commitment_acceptance', acceptance_body
                assert acceptance_body['delivery']['witness_archive']['created'] == 1, acceptance_body

                execution_warrant = _issue_workspace_warrant(
                    alpha,
                    alpha_session['token'],
                    execution_request_payload,
                    action_class='federated_execution',
                )
                execution_status, execution_body = _http_json(
                    'POST',
                    alpha['base_url'] + '/api/federation/send',
                    payload={
                        'target_host_id': 'host_beta',
                        'target_org_id': 'org_beta',
                        'message_type': 'execution_request',
                        'payload': execution_request_payload,
                        'warrant_id': execution_warrant['warrant_id'],
                    },
                    headers={
                        'Authorization': f"Bearer {alpha_session['token']}",
                        'Content-Type': 'application/json',
                    },
                )
                assert execution_status == 200, execution_body
                assert execution_body['delivery']['claims']['message_type'] == 'execution_request', execution_body
                assert execution_body['delivery']['witness_archive']['created'] == 1, execution_body

                post_record = legacy_v1_adapter.post_action_record(
                    'org_alpha',
                    dict(
                        adapter_envelope,
                        details={
                            **adapter_envelope['details'],
                            'federation_envelope_id': execution_body['delivery']['claims']['envelope_id'],
                            'receiver_host_id': execution_body['delivery']['receipt']['receiver_host_id'],
                        },
                    ),
                    actual_cost_usd=0.04,
                    outcome='success',
                    actor_type='agent',
                )
                assert post_record['cost_usd'] == 0.04, post_record
                assert seen['meter']['org_id'] == 'org_alpha', seen['meter']
                assert seen['meter']['metric'] == 'runtime_action', seen['meter']
                assert seen['audit']['action'] == 'federated_execution', seen['audit']
                assert seen['audit']['resource'] == 'host_beta/shared_brief_review', seen['audit']

                jobs_status, jobs_body = _http_json(
                    'GET',
                    beta['base_url'] + '/api/federation/execution-jobs',
                    headers={'Authorization': beta['auth_header']},
                )
                assert jobs_status == 200, jobs_body
                assert jobs_body['summary']['pending_local_warrant'] == 1, jobs_body
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
                assert review_status == 200, review_body
                assert review_body['court_notice']['court_notice']['decision'] == 'stay', review_body
                assert review_body['court_notice']['delivery']['witness_archive']['created'] == 1, review_body

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
                assert breach_status == 200, breach_body
                assert (
                    breach_body['delivery']['response']['processing']['federation_peer']['trust_state'] == 'suspended'
                ), breach_body
                assert breach_body['delivery']['witness_archive']['created'] == 1, breach_body

                alpha_cases_status, alpha_cases_body = _http_json(
                    'GET',
                    alpha['base_url'] + '/api/cases',
                    headers={'Authorization': alpha['auth_header']},
                )
                assert alpha_cases_status == 200, alpha_cases_body
                assert alpha_cases_body['blocking_commitment_ids'] == [commitment_id], alpha_cases_body
                assert alpha_cases_body['blocked_peer_host_ids'] == ['host_beta'], alpha_cases_body

                gamma_archive_status, gamma_archive_body = _http_json(
                    'GET',
                    gamma['base_url'] + '/api/federation/witness/archive',
                    headers={'Authorization': gamma['auth_header']},
                )
                assert gamma_archive_status == 200, gamma_archive_body
                assert gamma_archive_body['summary']['total'] == 5, gamma_archive_body
                assert gamma_archive_body['summary']['message_type_counts'] == {
                    'commitment_acceptance': 1,
                    'commitment_breach_notice': 1,
                    'commitment_proposal': 1,
                    'court_notice': 1,
                    'execution_request': 1,
                }, gamma_archive_body

            alpha_events = _read_jsonl(alpha['audit_log'])
            beta_events = _read_jsonl(beta['audit_log'])
            gamma_events = _read_jsonl(gamma['audit_log'])
            archived = [
                event for event in gamma_events
                if event.get('action') == 'federation_witness_observation_archived'
            ]
            assert any(
                event.get('action') == 'federation_commitment_breach_notice_recorded'
                for event in alpha_events
            ), alpha_events
            assert any(
                event.get('action') == 'federation_witness_archive_sent'
                for event in beta_events
            ), beta_events
            assert len(archived) >= 5, gamma_events

            return {
                'runtime_id': 'legacy_v1_compatible',
                'adapter_kind': 'reference_adapter',
                'scope': 'kernel_side_reference_seam',
                'action_gate': action_gate,
                'commitment_id': commitment_id,
                'proposal': {
                    'status': proposal_status,
                    'body': proposal_body,
                },
                'acceptance': {
                    'status': acceptance_status,
                    'body': acceptance_body,
                },
                'execution': {
                    'status': execution_status,
                    'body': execution_body,
                },
                'jobs': {
                    'status': jobs_status,
                    'body': jobs_body,
                },
                'review': {
                    'status': review_status,
                    'body': review_body,
                },
                'breach': {
                    'status': breach_status,
                    'body': breach_body,
                },
                'cases': {
                    'status': alpha_cases_status,
                    'body': alpha_cases_body,
                },
                'witness_archive': {
                    'status': gamma_archive_status,
                    'body': gamma_archive_body,
                },
                'post_action_record': post_record,
                'meter': seen['meter'],
                'audit': seen['audit'],
                'audit_events': {
                    'alpha_actions': [event.get('action') for event in alpha_events],
                    'beta_actions': [event.get('action') for event in beta_events],
                    'gamma_archive_count': len(archived),
                },
            }
    finally:
        legacy_v1_adapter.check_authority = orig_check_authority
        legacy_v1_adapter.check_budget = orig_check_budget
        legacy_v1_adapter.get_restrictions = orig_get_restrictions
        legacy_v1_adapter.meter_record = orig_meter_record
        legacy_v1_adapter.log_event = orig_log_event


class LegacyV1FederationProofTests(unittest.TestCase):
    def test_legacy_v1_reference_adapter_wraps_three_host_federation_execution(self):
        proof = _run_legacy_v1_reference_adapter_federation_proof()
        self.assertEqual(proof['runtime_id'], 'legacy_v1_compatible')
        self.assertEqual(proof['adapter_kind'], 'reference_adapter')
        self.assertTrue(proof['action_gate']['allowed'])
        self.assertEqual(proof['action_gate']['stage'], 'ok')
        self.assertEqual(proof['proposal']['status'], 200)
        self.assertEqual(proof['acceptance']['status'], 200)
        self.assertEqual(proof['execution']['status'], 200)
        self.assertEqual(
            proof['execution']['body']['delivery']['claims']['message_type'],
            'execution_request',
        )
        self.assertEqual(proof['execution']['body']['delivery']['witness_archive']['created'], 1)
        self.assertEqual(proof['post_action_record']['cost_usd'], 0.04)
        self.assertEqual(proof['meter']['metric'], 'runtime_action')
        self.assertEqual(proof['audit']['action'], 'federated_execution')
        self.assertEqual(proof['review']['body']['court_notice']['court_notice']['decision'], 'stay')
        self.assertEqual(
            proof['breach']['body']['delivery']['response']['processing']['federation_peer']['trust_state'],
            'suspended',
        )
        self.assertEqual(proof['cases']['body']['blocking_commitment_ids'], [proof['commitment_id']])
        self.assertEqual(proof['witness_archive']['body']['summary']['total'], 5)
        self.assertIn('federation_commitment_breach_notice_recorded', proof['audit_events']['alpha_actions'])
        self.assertIn('federation_witness_archive_sent', proof['audit_events']['beta_actions'])
        self.assertGreaterEqual(proof['audit_events']['gamma_archive_count'], 5)


if __name__ == '__main__':
    unittest.main()
