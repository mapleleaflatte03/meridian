#!/usr/bin/env python3
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

WORKSPACE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
COMPANY_DIR = os.path.join(WORKSPACE, 'company')

for path in (COMPANY_DIR, os.path.join(COMPANY_DIR, 'meridian_platform')):
    if path not in sys.path:
        sys.path.insert(0, path)

_fake_brief_quality = types.ModuleType('brief_quality')
_fake_brief_quality.analyze_brief = lambda path: {'passed': True}
sys.modules.setdefault('brief_quality', _fake_brief_quality)

_fake_treasury = types.ModuleType('treasury')
_fake_treasury.check_budget = lambda *args, **kwargs: (True, 'ok')
_fake_treasury.treasury_snapshot = lambda *args, **kwargs: {
    'balance_usd': 0.0,
    'reserve_floor_usd': 0.0,
    'runway_usd': 0.0,
    'shortfall_usd': 0.0,
    'above_reserve': True,
}
sys.modules.setdefault('treasury', _fake_treasury)

_fake_authority = types.ModuleType('authority')
_fake_authority.check_authority = lambda *args, **kwargs: True
_fake_authority.is_kill_switch_engaged = lambda *args, **kwargs: False
sys.modules.setdefault('authority', _fake_authority)

_fake_organizations = types.ModuleType('organizations')
_fake_organizations.load_orgs = lambda: {'organizations': {'org_founding': {'id': 'org_founding', 'slug': 'meridian', 'name': 'Meridian'}}}
_fake_organizations.get_org = lambda org_id: _fake_organizations.load_orgs()['organizations'].get(org_id)
sys.modules.setdefault('organizations', _fake_organizations)


def _load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mcp_server = _load_module(os.path.join(COMPANY_DIR, 'mcp_server.py'), 'company_mcp_runtime_adapter_test')


class McpRuntimeAdapterTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        cache_file = os.path.join(self._tmpdir.name, 'research_cache.json')
        cache_patch = mock.patch.object(mcp_server, 'RESEARCH_CACHE_FILE', cache_file)
        cache_patch.start()
        self.addCleanup(cache_patch.stop)

    def test_company_info_payload_exposes_live_host_truth(self):
        context = {
            'org_id': 'org_48b05c21',
            'institution_name': 'Meridian',
            'institution_slug': 'meridian',
            'context_source': 'configured_org',
            'identity_model': 'x402_payment',
            'boundary_scope': 'founding_service_only',
            'boundary_name': 'mcp_service',
            'is_admitted': True,
            'lifecycle_state': 'active',
            'source': 'configured_org',
            'service_scope': 'founding_meridian_service',
            'supports_institution_routing': False,
        }
        info = mcp_server._company_info_payload(context, '0xwallet')
        self.assertEqual(info['company'], 'Meridian')
        self.assertEqual(info['commercial_wedge']['name'], 'Competitive Intelligence')
        self.assertIn('sixth platform primitive', info['description'].lower())
        self.assertIn('Commitment', info['primitives'])
        self.assertEqual(info['constitutional_model']['kernel']['count'], 5)
        self.assertEqual(info['constitutional_model']['platform']['count'], 6)
        self.assertEqual(info['live_host_truth']['runtime_id'], 'loom_native')
        self.assertEqual(info['live_host_truth']['public_mcp_endpoint'], 'https://app.welliam.codes/sse')
        self.assertEqual(info['live_host_truth']['public_mcp_transport'], 'sse_bootstrap_plus_messages_session_channel')
        self.assertEqual(info['live_host_truth']['payment_mode'], 'x402_fail_closed_for_paid_tools')
        self.assertEqual(info['institution_scope']['org_id'], 'org_48b05c21')

    def test_research_defaults_to_loom(self):
        submit = mock.Mock(returncode=0, stdout=json.dumps({'job_id': 'job-default'}), stderr='')
        inspect = mock.Mock(returncode=0, stdout=json.dumps({'job_status': 'completed'}), stderr='')
        worker_result = {'summary': 'fallback summary', 'skill_output': {'research': 'loom default result'}}
        env = {'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'company.research.v0', 'MERIDIAN_LOOM_SERVICE_TOKEN': 'loom-local-token'}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[submit, inspect]) as run_mock:
                with mock.patch.object(mcp_server, '_load_json_file', return_value=worker_result):
                    with mock.patch.object(mcp_server.time, 'sleep', return_value=None):
                        result = mcp_server.do_on_demand_research('OpenAI pricing', 'quick')

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['research'], 'loom default result')
        submit_cmd = next(call.args[0] for call in run_mock.call_args_list if '--payload-json' in call.args[0])
        self.assertEqual(submit_cmd[1:3], ['service', 'submit'])

    def test_research_uses_loom_when_enabled(self):
        submit = mock.Mock(returncode=0, stdout=json.dumps({'job_id': 'job-123'}), stderr='')
        inspect = mock.Mock(returncode=0, stdout=json.dumps({'job_status': 'completed'}), stderr='')
        worker_result = {
            'summary': 'fallback summary',
            'skill_output': {'research': 'loom research result'},
        }
        env = {
            'MERIDIAN_INTELLIGENCE_RESEARCH_RUNTIME': 'loom',
            'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'company.research.v0',
            'MERIDIAN_LOOM_SERVICE_TOKEN': 'loom-local-token',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[submit, inspect]) as run_mock:
                with mock.patch.object(mcp_server, '_load_json_file', return_value=worker_result):
                    with mock.patch.object(mcp_server.time, 'sleep', return_value=None):
                        result = mcp_server.do_on_demand_research('Anthropic context window', 'deep')

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['capability_name'], 'company.research.v0')
        self.assertEqual(result['job_id'], 'job-123')
        self.assertEqual(result['research'], 'loom research result')
        submit_cmd = next(call.args[0] for call in run_mock.call_args_list if '--payload-json' in call.args[0])
        inspect_cmd = run_mock.call_args_list[1].args[0]
        self.assertEqual(submit_cmd[1:3], ['service', 'submit'])
        self.assertEqual(inspect_cmd[1:3], ['job', 'inspect'])

    def test_research_loom_url_payload_extracts_normalized_text(self):
        submit = mock.Mock(returncode=0, stdout=json.dumps({'job_id': 'job-url'}), stderr='')
        inspect = mock.Mock(returncode=0, stdout=json.dumps({'job_status': 'completed'}), stderr='')
        worker_result = {
            'summary': 'safe-web-research',
            'skill_output': {
                'results': [
                    {'url': 'https://example.com/', 'normalized_text': 'example domain text'}
                ]
            },
        }
        env = {
            'MERIDIAN_INTELLIGENCE_RESEARCH_RUNTIME': 'loom',
            'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'clawskill.safe-web-research.v0',
            'MERIDIAN_LOOM_SERVICE_TOKEN': 'loom-local-token',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[submit, inspect]) as run_mock:
                with mock.patch.object(mcp_server, '_load_json_file', return_value=worker_result):
                    with mock.patch.object(mcp_server.time, 'sleep', return_value=None):
                        result = mcp_server.do_on_demand_research('https://example.com', 'quick')

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['research'], 'example domain text')
        submit_cmd = next(call.args[0] for call in run_mock.call_args_list if '--payload-json' in call.args[0])
        payload = json.loads(submit_cmd[submit_cmd.index('--payload-json') + 1])
        self.assertEqual(payload['url'], 'https://example.com')
        self.assertEqual(payload['urls'], ['https://example.com'])


    def test_research_loom_plain_text_topic_uses_search_url_payload(self):
        service_status = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'running': True,
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
            }),
            stderr='',
        )
        capability_show = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'enabled': True,
                'verification_status': 'verified',
                'promotion_state': 'promoted',
                'worker_kind': 'python',
                'worker_entry': 'workers/python/imported-clawskill-safe-web-research-v0.py',
                'payload_mode': 'json',
                'adapter_kind': 'url_report_v0',
                'runtime_lane': 'python_host_process/imported_workspace_skill',
                'env_contract': 'host python3',
            }),
            stderr='',
        )
        submit = mock.Mock(returncode=0, stdout=json.dumps({'job_id': 'job-text'}), stderr='')
        inspect = mock.Mock(returncode=0, stdout=json.dumps({'job_status': 'completed'}), stderr='')
        worker_result = {
            'summary': 'safe-web-research',
            'skill_output': {
                'results': [
                    {'url': 'https://duckduckgo.com/html/?q=OpenAI+pricing', 'normalized_text': 'search result text'}
                ]
            },
        }
        env = {
            'MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME': 'loom',
            'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'clawskill.safe-web-research.v0',
            'MERIDIAN_LOOM_SERVICE_TOKEN': 'loom-local-token',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[service_status, capability_show, submit, inspect]) as run_mock:
                with mock.patch.object(mcp_server, '_load_json_file', return_value=worker_result):
                    with mock.patch.object(mcp_server.time, 'sleep', return_value=None):
                        result = mcp_server.do_on_demand_research_route('OpenAI pricing', 'quick')

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['research'], 'search result text')
        submit_cmd = next(call.args[0] for call in run_mock.call_args_list if '--payload-json' in call.args[0])
        payload = json.loads(submit_cmd[submit_cmd.index('--payload-json') + 1])
        self.assertEqual(payload['topic'], 'OpenAI pricing')
        self.assertEqual(payload['url'], 'https://duckduckgo.com/html/?q=OpenAI+pricing')
        self.assertEqual(payload['urls'], ['https://duckduckgo.com/html/?q=OpenAI+pricing'])

    def test_on_demand_research_route_override_legacy_fails_closed(self):
        env = {
            'MERIDIAN_INTELLIGENCE_RESEARCH_RUNTIME': 'loom',
            'MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME': 'legacy',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = mcp_server.do_on_demand_research_route('OpenAI pricing', 'quick')

        self.assertEqual(result['runtime'], 'blocked')
        self.assertEqual(result['route_cutover']['requested_runtime'], 'legacy')
        self.assertEqual(result['route_cutover']['selected_runtime'], 'blocked')
        self.assertFalse(result['route_cutover']['fallback_enabled'])
        self.assertIn('requested=legacy', result['route_cutover']['transcript'])
        self.assertIn('selected=blocked', result['route_cutover']['transcript'])
        self.assertIn('not enabled on this host', result['error'])

    def test_on_demand_research_route_uses_loom_with_cutover_metadata(self):
        service_status = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'running': True,
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
                'service_target': '127.0.0.1:18910',
            }),
            stderr='',
        )
        capability_show = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'enabled': True,
                'verification_status': 'verified',
                'promotion_state': 'promoted',
                'worker_kind': 'python',
                'worker_entry': 'workers/python/imported-clawskill-safe-web-research-v0.py',
                'payload_mode': 'json',
                'adapter_kind': 'url_report_v0',
                'runtime_lane': 'python_host_process/imported_workspace_skill',
                'env_contract': 'host python3',
            }),
            stderr='',
        )
        submit = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'job_id': 'job-route',
                'transport': 'socket+http',
                'service_target': '127.0.0.1:18910',
                'queue_path': '/tmp/queue.json',
                'ingress_request_path': '/tmp/request.json',
                'ingress_receipt_path': '/tmp/receipt.json',
                'policy_class': 'standard',
            }),
            stderr='',
        )
        inspect = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'job_status': 'completed',
                'job_stage': 'ok',
                'runtime_outcome': 'worker_executed',
                'worker_status': 'completed',
                'job_path': '/tmp/jobs/job-route/job.json',
                'event_path': '/tmp/jobs/job-route/event.json',
                'audit_log_path': '/tmp/jobs/job-route/audit.jsonl',
                'parity_report_path': '/tmp/jobs/job-route/parity.json',
            }),
            stderr='',
        )
        worker_result = {
            'summary': 'safe-web-research',
            'skill_output': {'results': [{'normalized_text': 'loom route result'}]},
        }
        env = {
            'MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME': 'loom',
            'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'clawskill.safe-web-research.v0',
            'MERIDIAN_LOOM_SERVICE_TOKEN': 'loom-local-token',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[service_status, capability_show, submit, inspect]):
                with mock.patch.object(mcp_server, '_load_json_file', return_value=worker_result):
                    with mock.patch.object(mcp_server.time, 'sleep', return_value=None):
                        result = mcp_server.do_on_demand_research_route('https://example.com', 'quick')

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['research'], 'loom route result')
        self.assertEqual(result['route_cutover']['requested_runtime'], 'loom')
        self.assertEqual(result['route_cutover']['selected_runtime'], 'loom')
        self.assertTrue(result['route_cutover']['loom_preflight']['ok'])
        self.assertIn('preflight=ok', result['route_cutover']['transcript'])
        self.assertIn('requested=loom', result['route_cutover']['transcript'])
        self.assertIn('selected=loom', result['route_cutover']['transcript'])
        self.assertEqual(result['route_cutover']['loom']['job_id'], 'job-route')
        self.assertEqual(result['route_cutover']['loom']['result_path_hint'], '/tmp/jobs/job-route/result.json')

    def test_on_demand_research_route_uses_cache_hit_without_loom_calls(self):
        cached = {
            'topic': 'OpenAI pricing',
            'depth': 'quick',
            'research': 'cached bounded scan',
            'runtime': 'loom',
        }
        env = {
            'MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME': 'loom',
            'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'clawskill.safe-web-research.v0',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server, '_research_cache_get', return_value=cached):
                with mock.patch.object(mcp_server, '_loom_research_preflight') as preflight_mock:
                    with mock.patch.object(mcp_server, '_run_loom_on_demand_research') as run_mock:
                        result = mcp_server.do_on_demand_research_route('OpenAI pricing', 'quick')
        self.assertEqual(result['research'], 'cached bounded scan')
        self.assertEqual(result['cache_state'], 'hit')
        preflight_mock.assert_not_called()
        run_mock.assert_not_called()

    def test_quick_research_uses_lower_token_budget(self):
        with mock.patch.object(mcp_server, '_specialist_llm_payload', return_value={'provider_profile': 'atlas', 'model': 'demo'}) as payload_mock:
            with mock.patch.object(mcp_server, '_run_loom_capability', return_value={'ok': False, 'error': 'boom'}):
                mcp_server._run_loom_on_demand_research('OpenAI pricing', 'quick', 'prompt')
        self.assertEqual(payload_mock.call_args.kwargs['max_tokens'], 700)

    def test_on_demand_research_route_loom_preflight_failure_fails_closed(self):
        service_status = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'running': True,
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
            }),
            stderr='',
        )
        capability_show = mock.Mock(returncode=1, stdout='', stderr='missing capability')
        env = {
            'MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME': 'loom',
            'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'missing.capability.v0',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[service_status, capability_show]) as run_mock:
                result = mcp_server.do_on_demand_research_route('OpenAI pricing', 'quick')

        self.assertEqual(result['runtime'], 'loom')
        self.assertIn('Loom research preflight failed', result['error'])
        self.assertEqual(result['route_cutover']['requested_runtime'], 'loom')
        self.assertEqual(result['route_cutover']['selected_runtime'], 'loom')
        self.assertFalse(result['route_cutover']['fallback_enabled'])
        self.assertIn('preflight=blocked', result['route_cutover']['transcript'])
        self.assertIn('fallback=off', result['route_cutover']['transcript'])
        self.assertEqual(result['route_cutover']['fallback']['used'], False)
        self.assertEqual(result['route_cutover']['fallback']['from_runtime'], 'loom')
        self.assertEqual(result['route_cutover']['fallback']['state'], 'preflight_failed')
        self.assertIn('missing capability', result['route_cutover']['fallback']['reason'])
        commands = [call.args[0][1:3] for call in run_mock.call_args_list]
        self.assertGreaterEqual(len(commands), 2)
        self.assertEqual(commands[-2:], [['service', 'status'], ['capability', 'show']])

    def test_research_loom_plugin_skill_import_metadata_is_normalized(self):
        service_status = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'running': True,
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
            }),
            stderr='',
        )
        capability_show = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'enabled': True,
                'verification_status': 'verified',
                'promotion_state': 'promoted',
                'worker_kind': 'python',
                'worker_entry': 'workers/python/imported-clawskill-safe-web-research-v0.py',
                'payload_mode': 'json',
                'adapter_kind': 'url_report_v0',
                'runtime_lane': 'python_host_process/imported_workspace_skill',
                'dependency_mode': 'workspace_host_python',
                'import_provenance': 'clawfamily_skill_contract_v0/workspace_python_entrypoint',
                'source_kind': 'legacy_workspace_skill',
                'source_manifest': '/home/ubuntu/.meridian/workspace/skills/safe-web-research/SKILL.md',
                'source_path': '/home/ubuntu/.meridian/workspace/skills/safe-web-research',
                'env_contract': 'host python3 + source skill root /home/ubuntu/.meridian/workspace/skills/safe-web-research + wrapper workers/python/imported-clawskill-safe-web-research-v0.py',
            }),
            stderr='',
        )
        with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[service_status, capability_show]):
            with mock.patch.dict(os.environ, {'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'clawskill.safe-web-research.v0'}, clear=False):
                preflight = mcp_server._loom_research_preflight('clawskill.safe-web-research.v0')

        self.assertTrue(preflight['ok'])
        normalized = preflight['normalized_import_metadata']
        self.assertTrue(normalized['supported'])
        self.assertEqual(normalized['subset'], 'loom_plugin_skill_subset')
        self.assertEqual(normalized['skill_slug'], 'safe-web-research')
        self.assertEqual(normalized['source_kind'], 'loom_workspace_skill_import')
        self.assertEqual(preflight['capability']['source_kind'], 'loom_workspace_skill_import')
        self.assertEqual(normalized['source_manifest'], '/home/ubuntu/.meridian/workspace/skills/safe-web-research/SKILL.md')
        self.assertEqual(normalized['source_path'], '/home/ubuntu/.meridian/workspace/skills/safe-web-research')
        self.assertEqual(normalized['worker_kind'], 'python')
        self.assertEqual(normalized['worker_entry'], 'workers/python/imported-clawskill-safe-web-research-v0.py')
        self.assertEqual(normalized['runtime_lane'], 'python_host_process/imported_workspace_skill')
        self.assertEqual(normalized['isolation_lane'], 'python_host_process/imported_workspace_skill')
        self.assertEqual(normalized['payload_mode'], 'json')
        self.assertEqual(normalized['adapter_kind'], 'url_report_v0')
        self.assertEqual(normalized['dependency_mode'], 'workspace_host_python')
        self.assertEqual(normalized['import_provenance'], 'clawfamily_skill_contract_v0/workspace_python_entrypoint')
        self.assertEqual(normalized['env_contract'], 'host python3 + source skill root /home/ubuntu/.meridian/workspace/skills/safe-web-research + wrapper workers/python/imported-clawskill-safe-web-research-v0.py')

    def test_research_loom_plugin_skill_import_metadata_reports_unsupported_reasons(self):
        service_status = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'running': True,
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
            }),
            stderr='',
        )
        capability_show = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'enabled': True,
                'verification_status': 'verified',
                'promotion_state': 'promoted',
                'worker_kind': 'python',
                'worker_entry': 'workers/python/imported-clawskill-safe-web-research-v0-extra.py',
                'payload_mode': 'json',
                'adapter_kind': 'url_report_v0',
                'runtime_lane': 'python_host_process/legacy_skill',
                'dependency_mode': 'workspace_host_python',
                'import_provenance': 'clawfamily_skill_contract_v0/workspace_python_entrypoint',
                'source_kind': 'legacy_workspace_skill',
                'source_manifest': '/home/ubuntu/.meridian/workspace/skills/safe-web-research/SKILL.md',
                'source_path': '/home/ubuntu/.meridian/workspace/skills/safe-web-research',
                'env_contract': 'host python3 + source skill root /home/ubuntu/.meridian/workspace/skills/safe-web-research + wrapper workers/python/imported-clawskill-safe-web-research-v0-extra.py',
            }),
            stderr='',
        )
        with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[service_status, capability_show]):
            preflight = mcp_server._loom_research_preflight('clawskill.safe-web-research.v0')

        self.assertFalse(preflight['ok'])
        normalized = preflight['normalized_import_metadata']
        self.assertFalse(normalized['supported'])
        self.assertIn('runtime_lane=python_host_process/legacy_skill', normalized['unsupported_reasons'])
        self.assertIn('loom imported skill subset unsupported:', preflight['errors'][0])

    def test_qa_defaults_to_loom_when_no_qa_override_is_set(self):
        submit = mock.Mock(returncode=0, stdout=json.dumps({'job_id': 'job-qa-default'}), stderr='')
        inspect = mock.Mock(returncode=0, stdout=json.dumps({'job_status': 'completed'}), stderr='')
        worker_result = {'summary': 'PASS', 'skill_output': {'verification': 'PASS with confidence 88'}}
        env = {'MERIDIAN_INTELLIGENCE_RESEARCH_RUNTIME': 'loom', 'MERIDIAN_LOOM_QA_CAPABILITY': 'company.qa.v0', 'MERIDIAN_LOOM_SERVICE_TOKEN': 'loom-local-token'}
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[submit, inspect]):
                with mock.patch.object(mcp_server, '_load_json_file', return_value=worker_result):
                    with mock.patch.object(mcp_server.time, 'sleep', return_value=None):
                        result = mcp_server.do_qa_verify('text to verify', 'factual')

        self.assertEqual(result['runtime'], 'loom')
        self.assertIn('PASS', result['verification'])

    def test_qa_uses_loom_when_enabled(self):
        submit = mock.Mock(returncode=0, stdout=json.dumps({'job_id': 'job-qa'}), stderr='')
        inspect = mock.Mock(returncode=0, stdout=json.dumps({'job_status': 'completed'}), stderr='')
        worker_result = {
            'summary': 'PASS',
            'skill_output': {'verification': 'PASS with confidence 92'},
        }
        env = {
            'MERIDIAN_INTELLIGENCE_QA_RUNTIME': 'loom',
            'MERIDIAN_LOOM_QA_CAPABILITY': 'company.qa.v0',
            'MERIDIAN_LOOM_SERVICE_TOKEN': 'loom-local-token',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[submit, inspect]):
                with mock.patch.object(mcp_server, '_load_json_file', return_value=worker_result):
                    with mock.patch.object(mcp_server.time, 'sleep', return_value=None):
                        result = mcp_server.do_qa_verify('text to verify', 'factual')

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['capability_name'], 'company.qa.v0')
        self.assertEqual(result['job_id'], 'job-qa')
        self.assertEqual(result['verification'], 'PASS with confidence 92')


    def test_qa_route_override_legacy_fails_closed(self):
        env = {
            'MERIDIAN_INTELLIGENCE_QA_RUNTIME': 'loom',
            'MERIDIAN_INTELLIGENCE_QA_VERIFY_RUNTIME': 'legacy',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = mcp_server.do_qa_verify_route('text to verify', 'factual')

        self.assertEqual(result['runtime'], 'blocked')
        self.assertEqual(result['route_cutover']['requested_runtime'], 'legacy')
        self.assertEqual(result['route_cutover']['selected_runtime'], 'blocked')
        self.assertFalse(result['route_cutover']['fallback_enabled'])
        self.assertIn('requested=legacy', result['route_cutover']['transcript'])
        self.assertIn('selected=blocked', result['route_cutover']['transcript'])
        self.assertIn('not enabled on this host', result['error'])

    def test_qa_route_uses_loom_with_cutover_metadata(self):
        service_status = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'running': True,
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
            }),
            stderr='',
        )
        capability_show = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'enabled': True,
                'verification_status': 'verified',
                'promotion_state': 'promoted',
                'worker_kind': 'python',
                'worker_entry': 'workers/python/imported-company-qa-v0.py',
                'payload_mode': 'json',
                'adapter_kind': 'url_report_v0',
                'runtime_lane': 'python_host_process/imported_workspace_skill',
                'env_contract': 'host python3',
            }),
            stderr='',
        )
        submit = mock.Mock(returncode=0, stdout=json.dumps({'job_id': 'job-qa-route'}), stderr='')
        inspect = mock.Mock(returncode=0, stdout=json.dumps({'job_status': 'completed', 'job_path': '/tmp/jobs/job-qa-route/job.json', 'worker_status': 'completed'}), stderr='')
        worker_result = {
            'summary': 'PASS',
            'skill_output': {'verification': 'PASS with confidence 88'},
        }
        env = {
            'MERIDIAN_INTELLIGENCE_QA_VERIFY_RUNTIME': 'loom',
            'MERIDIAN_LOOM_QA_CAPABILITY': 'company.qa.v0',
            'MERIDIAN_LOOM_SERVICE_TOKEN': 'loom-local-token',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[service_status, capability_show, submit, inspect]):
                with mock.patch.object(mcp_server, '_load_json_file', return_value=worker_result):
                    with mock.patch.object(mcp_server.time, 'sleep', return_value=None):
                        result = mcp_server.do_qa_verify_route('text to verify', 'factual')

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['capability_name'], 'company.qa.v0')
        self.assertEqual(result['job_id'], 'job-qa-route')
        self.assertEqual(result['verification'], 'PASS with confidence 88')
        self.assertTrue(result['route_cutover']['loom_preflight']['ok'])
        self.assertEqual(result['route_cutover']['requested_runtime'], 'loom')
        self.assertEqual(result['route_cutover']['selected_runtime'], 'loom')
        self.assertIn('preflight=ok', result['route_cutover']['transcript'])
        self.assertIn('requested=loom', result['route_cutover']['transcript'])
        self.assertIn('selected=loom', result['route_cutover']['transcript'])
        self.assertEqual(result['route_cutover']['loom']['job_id'], 'job-qa-route')
        self.assertEqual(result['route_cutover']['loom']['result_path_hint'], '/tmp/jobs/job-qa-route/result.json')

    def test_qa_route_preflight_failure_fails_closed(self):
        service_status = mock.Mock(
            returncode=0,
            stdout=json.dumps({
                'running': True,
                'service_status': 'running',
                'health': 'healthy',
                'transport': 'socket+http',
            }),
            stderr='',
        )
        capability_show = mock.Mock(returncode=1, stdout='', stderr='missing qa capability')
        env = {
            'MERIDIAN_INTELLIGENCE_QA_VERIFY_RUNTIME': 'loom',
            'MERIDIAN_INTELLIGENCE_QA_VERIFY_ALLOW_FALLBACK': '1',
            'MERIDIAN_LOOM_QA_CAPABILITY': 'missing.capability.v0',
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server.subprocess, 'run', side_effect=[service_status, capability_show]) as run_mock:
                result = mcp_server.do_qa_verify_route('text to verify', 'factual')

        self.assertEqual(result['runtime'], 'loom')
        self.assertIn('Loom QA preflight failed', result['error'])
        self.assertEqual(result['route_cutover']['requested_runtime'], 'loom')
        self.assertEqual(result['route_cutover']['selected_runtime'], 'loom')
        self.assertFalse(result['route_cutover']['fallback_enabled'])
        self.assertEqual(result['route_cutover']['fallback']['used'], False)
        self.assertEqual(result['route_cutover']['fallback']['from_runtime'], 'loom')
        self.assertEqual(result['route_cutover']['fallback']['state'], 'preflight_failed')
        self.assertIn('missing qa capability', result['route_cutover']['fallback']['reason'])
        self.assertIn('fallback=off', result['route_cutover']['transcript'])
        self.assertIn('preflight=blocked', result['route_cutover']['transcript'])
        commands = [call.args[0][1:3] for call in run_mock.call_args_list]
        self.assertGreaterEqual(len(commands), 2)
        self.assertEqual(commands[-2:], [['service', 'status'], ['capability', 'show']])


    def test_research_route_forwards_agent_and_session_to_loom_runtime(self):
        env = {
            'MERIDIAN_INTELLIGENCE_ON_DEMAND_RESEARCH_RUNTIME': 'loom',
            'MERIDIAN_LOOM_RESEARCH_CAPABILITY': 'company.research.v0',
        }
        captured: dict[str, object] = {}

        def fake_run(capability_name, payload, timeout, **kwargs):
            captured['capability_name'] = capability_name
            captured['payload'] = payload
            captured['timeout'] = timeout
            captured.update(kwargs)
            return {
                'ok': True,
                'capability_name': capability_name,
                'job_id': 'job-route-agent',
                'worker_result': {'skill_output': {'research': 'route result'}},
                'submit': {},
                'snapshot': {'job_status': 'completed'},
            }

        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server, '_loom_research_preflight', return_value={'ok': True, 'capability_name': 'company.research.v0'}):
                with mock.patch.object(mcp_server, '_run_loom_capability', side_effect=fake_run):
                    result = mcp_server.do_on_demand_research_route(
                        'OpenAI pricing',
                        'quick',
                        agent_id='agent_atlas',
                        session_id='telegram:123',
                    )

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['research'], 'route result')
        self.assertEqual(captured['agent_id'], 'agent_atlas')
        self.assertEqual(captured['session_id'], 'telegram:123')
        self.assertEqual(captured['action_type'], 'research')
        self.assertEqual(captured['resource'], 'telegram:123')

    def test_qa_route_forwards_agent_and_session_to_loom_runtime(self):
        env = {
            'MERIDIAN_INTELLIGENCE_QA_VERIFY_RUNTIME': 'loom',
            'MERIDIAN_LOOM_QA_CAPABILITY': 'company.qa.v0',
        }
        captured: dict[str, object] = {}

        def fake_run(capability_name, payload, timeout, **kwargs):
            captured['capability_name'] = capability_name
            captured['payload'] = payload
            captured['timeout'] = timeout
            captured.update(kwargs)
            return {
                'ok': True,
                'capability_name': capability_name,
                'job_id': 'job-qa-agent',
                'worker_result': {'skill_output': {'verification': 'PASS'}},
                'submit': {},
                'snapshot': {'job_status': 'completed'},
            }

        with mock.patch.dict(os.environ, env, clear=False):
            with mock.patch.object(mcp_server, '_loom_qa_preflight', return_value={'ok': True, 'capability_name': 'company.qa.v0'}):
                with mock.patch.object(mcp_server, '_run_loom_capability', side_effect=fake_run):
                    result = mcp_server.do_qa_verify_route(
                        'text to verify',
                        'factual',
                        agent_id='agent_aegis',
                        session_id='telegram:123',
                    )

        self.assertEqual(result['runtime'], 'loom')
        self.assertEqual(result['verification'], 'PASS')
        self.assertEqual(captured['agent_id'], 'agent_aegis')
        self.assertEqual(captured['session_id'], 'telegram:123')
        self.assertEqual(captured['action_type'], 'verify')
        self.assertEqual(captured['resource'], 'telegram:123')


if __name__ == '__main__':
    unittest.main()
