#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from test_federation import (  # noqa: E402
    _find_free_port,
    _http_json,
    _issue_workspace_session,
    _issue_workspace_warrant,
    _read_jsonl,
    _run_workspace,
    _seed_workspace_root,
)


def _run_three_host_federation_proof():
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
            assert proposal_status == 200, proposal_body
            assert proposal_body['delivery']['witness_archive']['attempted'] == 1
            assert proposal_body['delivery']['witness_archive']['created'] == 1
            assert proposal_body['delivery']['claims']['message_type'] == 'commitment_proposal'
            assert proposal_body['delivery']['claims']['warrant_id'] == proposal_warrant['warrant_id']
            commitment_id = proposal_body['commitment']['commitment_id']
            assert proposal_body['delivery']['claims']['commitment_id'] == commitment_id

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
            assert acceptance_body['delivery']['witness_archive']['attempted'] == 1
            assert acceptance_body['delivery']['witness_archive']['created'] == 1
            assert acceptance_body['delivery']['claims']['message_type'] == 'commitment_acceptance'

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
            assert execution_status == 200, execution_body
            assert execution_body['delivery']['witness_archive']['attempted'] == 1
            assert execution_body['delivery']['witness_archive']['created'] == 1
            assert execution_body['delivery']['claims']['message_type'] == 'execution_request'

            jobs_status, jobs_body = _http_json(
                'GET',
                beta['base_url'] + '/api/federation/execution-jobs',
                headers={'Authorization': beta['auth_header']},
            )
            assert jobs_status == 200, jobs_body
            assert jobs_body['summary']['pending_local_warrant'] == 1
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
            assert review_body['court_notice']['delivery']['witness_archive']['attempted'] == 1
            assert review_body['court_notice']['delivery']['witness_archive']['created'] == 1
            assert review_body['court_notice']['court_notice']['decision'] == 'stay'

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
            assert breach_body['delivery']['response']['processing']['federation_peer']['trust_state'] == 'suspended'
            assert breach_body['delivery']['witness_archive']['attempted'] == 1
            assert breach_body['delivery']['witness_archive']['created'] == 1

            alpha_cases_status, alpha_cases_body = _http_json(
                'GET',
                alpha['base_url'] + '/api/cases',
                headers={'Authorization': alpha['auth_header']},
            )
            assert alpha_cases_status == 200, alpha_cases_body
            assert alpha_cases_body['total'] == 1
            assert alpha_cases_body['open'] == 1
            assert alpha_cases_body['blocking_commitment_ids'] == [commitment_id]
            assert alpha_cases_body['blocked_peer_host_ids'] == ['host_beta']

            gamma_archive_status, gamma_archive_body = _http_json(
                'GET',
                gamma['base_url'] + '/api/federation/witness/archive',
                headers={'Authorization': gamma['auth_header']},
            )
            assert gamma_archive_status == 200, gamma_archive_body
            assert gamma_archive_body['summary']['total'] == 5
            assert gamma_archive_body['summary']['message_type_counts'] == {
                'commitment_acceptance': 1,
                'commitment_breach_notice': 1,
                'commitment_proposal': 1,
                'court_notice': 1,
                'execution_request': 1,
            }

        gamma_events = _read_jsonl(gamma['audit_log'])
        archived = [
            event for event in gamma_events
            if event.get('action') == 'federation_witness_observation_archived'
        ]
        assert len(archived) >= 5

        alpha_events = _read_jsonl(alpha['audit_log'])
        beta_events = _read_jsonl(beta['audit_log'])
        assert any(
            event.get('action') == 'federation_commitment_breach_notice_recorded'
            for event in alpha_events
        )
        assert any(
            event.get('action') == 'federation_witness_archive_sent'
            for event in beta_events
        )

        return {
            'commitment_id': commitment_id,
            'proposal_witness_archive': proposal_body['delivery']['witness_archive'],
            'acceptance_witness_archive': acceptance_body['delivery']['witness_archive'],
            'execution_witness_archive': execution_body['delivery']['witness_archive'],
            'review_witness_archive': review_body['court_notice']['delivery']['witness_archive'],
            'breach_witness_archive': breach_body['delivery']['witness_archive'],
            'gamma_archive_total': gamma_archive_body['summary']['total'],
        }


class ThreeHostFederationProofTest(unittest.TestCase):
    def test_three_host_federation_proof(self):
        summary = _run_three_host_federation_proof()
        self.assertEqual(summary['gamma_archive_total'], 5)
        self.assertEqual(summary['proposal_witness_archive']['created'], 1)
        self.assertEqual(summary['acceptance_witness_archive']['created'], 1)
        self.assertEqual(summary['execution_witness_archive']['created'], 1)
        self.assertEqual(summary['review_witness_archive']['created'], 1)
        self.assertEqual(summary['breach_witness_archive']['created'], 1)


if __name__ == '__main__':
    unittest.main()
