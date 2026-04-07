#!/usr/bin/env python3
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

WORKSPACE = Path('/home/ubuntu/.meridian/workspace')
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

spec = importlib.util.spec_from_file_location('meridian_gateway_test', WORKSPACE / 'meridian_gateway.py')
meridian_gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meridian_gateway)


class GatewayTeamRouteTests(unittest.TestCase):
    def test_skill_registry_reads_frontmatter_description(self):
        registry = meridian_gateway.SkillRegistry(meridian_gateway.SKILLS_DIR)
        items = registry.load()
        skill = next(item for item in items if item['name'] == 'mvp-sprint-scope')
        self.assertNotEqual(skill['description'], '---')
        self.assertIn('MVP', skill['description'])

    def test_parse_telegram_command_modes(self):
        self.assertEqual(meridian_gateway._parse_telegram_command('/help'), {'mode': 'help', 'arg': ''})
        self.assertEqual(meridian_gateway._parse_telegram_command('/atlas OpenAI pricing'), {'mode': 'team', 'arg': 'OpenAI pricing'})
        self.assertEqual(meridian_gateway._parse_telegram_command('/aegis factual::hello'), {'mode': 'team', 'arg': 'factual::hello'})
        self.assertEqual(meridian_gateway._parse_telegram_command('plain text'), {'mode': 'team', 'arg': 'plain text'})

    def test_run_team_route_uses_specialists_and_returns_manager_answer(self):
        runtime = mock.Mock()
        runtime.run_goal.return_value = 'direct answer'

        with mock.patch.object(meridian_gateway, '_team_route_plan', return_value={
            'mode': 'team',
            'topic': 'pricing',
            'depth': 'standard',
            'criteria': 'factual',
            'workers': ['ATLAS', 'AEGIS'],
            'reason': 'needs coordination',
        }):
            with mock.patch.object(meridian_gateway, '_run_specialist_step', side_effect=[
                {'agent_id': 'agent_atlas', 'request_id': 'job-r', 'result': 'atlas research'},
                {'agent_id': 'agent_aegis', 'request_id': 'job-v', 'result': 'aegis verification'},
            ]) as specialist_mock:
                with mock.patch.object(meridian_gateway, '_manager_synthesis', return_value='manager answer'):
                    answer, meta = meridian_gateway._run_team_route('Please research pricing', 'telegram:123', runtime)

        self.assertEqual(answer, 'manager answer')
        self.assertEqual(meta['mode'], 'team')
        self.assertEqual(meta['job_id'], 'job-v')
        self.assertEqual(len(meta['steps']), 2)
        self.assertEqual(specialist_mock.call_args_list[0].args[0], 'ATLAS')
        self.assertEqual(specialist_mock.call_args_list[1].args[0], 'AEGIS')
        runtime.run_goal.assert_not_called()

    def test_run_team_route_direct_mode_uses_manager(self):
        runtime = mock.Mock()
        runtime.run_goal.return_value = 'direct answer'

        with mock.patch.object(meridian_gateway, '_team_route_plan', return_value={'mode': 'direct', 'reason': 'greeting'}):
            with mock.patch.object(meridian_gateway, '_manager_direct_response', return_value='manager answer'):
                answer, meta = meridian_gateway._run_team_route('hi', 'telegram:123', runtime)

        self.assertEqual(answer, 'manager answer')
        self.assertEqual(meta['mode'], 'direct')
        runtime.run_goal.assert_not_called()

    def test_planner_fallback_adds_quill_for_writer_request(self):
        with mock.patch.object(meridian_gateway, '_run_codex_exec', return_value={'ok': False, 'output_text': ''}):
            with mock.patch.object(meridian_gateway, '_skill_bundle_for_request', return_value={'matches': []}):
                plan = meridian_gateway._team_route_plan(
                    'Write a short Meridian founder answer explaining why users should talk to Leviathann instead of direct specialists.',
                    'web_api:org_48b05c21',
                )
        self.assertEqual(plan['mode'], 'team')
        self.assertEqual(plan['workers'], ['QUILL', 'AEGIS'])

    def test_short_prompt_skill_route_uses_existing_skill(self):
        plan = meridian_gateway._team_route_plan('mvp scope', 'telegram:123')
        self.assertEqual(plan['mode'], 'team')
        self.assertEqual(plan['reason'], 'skill_routed_request')
        self.assertIn('ATLAS', plan['workers'])
        self.assertIn('mvp-sprint-scope', [item['name'] for item in plan['skills']])

    def test_short_prompt_skill_route_adds_verified_facts_for_status_flows(self):
        plan = meridian_gateway._team_route_plan('ops snapshot', 'telegram:123')
        self.assertEqual(plan['reason'], 'skill_routed_request')
        self.assertIsInstance(plan.get('verified_facts'), dict)
        self.assertIn('runtime_id', plan['verified_facts'])

    def test_decision_grade_route_score_prefers_direct_for_short_ambiguous_prompt(self):
        bundle = {
            'matches': [
                {
                    'name': 'tra-loi-duy',
                    'score': 4,
                    'autogenerated': True,
                    'workers': ['FORGE', 'QUILL', 'AEGIS'],
                }
            ],
            'workers': ['FORGE', 'QUILL', 'AEGIS'],
        }
        with mock.patch.object(
            meridian_gateway,
            '_routing_runtime_load_snapshot',
            return_value={
                'pending_count': 0,
                'latency_p50_ms': 2000,
                'fail_rate': 0.05,
                'latest_status': 'delivered',
            },
        ):
            score = meridian_gateway._decision_grade_route_score('help', bundle)
        self.assertEqual(score['decision'], 'direct')
        self.assertTrue(score['short_prompt'])
        self.assertGreaterEqual(score['direct_score'], score['team_score'])

    def test_decision_grade_route_score_keeps_team_for_actionable_mail(self):
        bundle = {
            'matches': [
                {
                    'name': 'mail-gui',
                    'score': 21,
                    'autogenerated': True,
                    'workers': ['QUILL', 'AEGIS'],
                }
            ],
            'workers': ['QUILL', 'AEGIS'],
        }
        with mock.patch.object(
            meridian_gateway,
            '_routing_runtime_load_snapshot',
            return_value={
                'pending_count': 0,
                'latency_p50_ms': 1800,
                'fail_rate': 0.02,
                'latest_status': 'delivered',
            },
        ):
            score = meridian_gateway._decision_grade_route_score(
                'gửi mail cho tôi bản cập nhật meridian',
                bundle,
            )
        self.assertEqual(score['decision'], 'team')
        self.assertTrue(score['requires_team_execution'])

    def test_adaptive_thresholds_shift_under_high_load(self):
        thresholds = meridian_gateway._adaptive_route_thresholds(
            {
                'pending_count': 6,
                'latency_p50_ms': 16000,
                'fail_rate': 0.42,
            }
        )
        self.assertGreater(thresholds['team_margin_short'], meridian_gateway.ROUTE_SCORE_TEAM_MARGIN_SHORT)
        self.assertGreater(thresholds['team_margin_default'], meridian_gateway.ROUTE_SCORE_TEAM_MARGIN_DEFAULT)
        self.assertLess(thresholds['direct_guard_confidence'], meridian_gateway.ROUTE_SCORE_DIRECT_GUARD_CONFIDENCE)
        self.assertEqual(thresholds['load_tier'], 'high')

    def test_adaptive_thresholds_relax_under_low_load(self):
        thresholds = meridian_gateway._adaptive_route_thresholds(
            {
                'pending_count': 0,
                'latency_p50_ms': 1800,
                'fail_rate': 0.02,
            }
        )
        self.assertLessEqual(thresholds['team_margin_short'], meridian_gateway.ROUTE_SCORE_TEAM_MARGIN_SHORT)
        self.assertLessEqual(thresholds['team_margin_default'], meridian_gateway.ROUTE_SCORE_TEAM_MARGIN_DEFAULT)
        self.assertGreaterEqual(thresholds['direct_guard_confidence'], meridian_gateway.ROUTE_SCORE_DIRECT_GUARD_CONFIDENCE)
        self.assertEqual(thresholds['load_tier'], 'low')

    def test_team_route_plan_short_ambiguous_prompt_short_circuits_to_direct(self):
        bundle = {'matches': [], 'workers': [], 'guidance': '', 'created_skill': None, 'refined_skill': None}
        with mock.patch.object(meridian_gateway, '_skill_bundle_for_request', return_value=bundle):
            with mock.patch.object(meridian_gateway, '_skill_route_should_activate', return_value=False):
                with mock.patch.object(
                    meridian_gateway,
                    '_routing_runtime_load_snapshot',
                    return_value={
                        'pending_count': 0,
                        'latency_p50_ms': 1900,
                        'fail_rate': 0.01,
                    },
                ):
                    with mock.patch.object(meridian_gateway, '_run_codex_exec') as planner_mock:
                        plan = meridian_gateway._team_route_plan('hmm', 'telegram:route-score')
        self.assertEqual(plan['mode'], 'direct')
        self.assertEqual(plan['reason'], 'decision_grade_direct_short_ambiguous')
        self.assertIn('routing_score', plan)
        planner_mock.assert_not_called()

    def test_route_decision_trace_payload_includes_load_adaptive_thresholds(self):
        payload = meridian_gateway._route_decision_trace_payload(
            session_key='telegram:trace-1',
            request='gửi mail cho khách về Meridian',
            plan={
                'mode': 'team',
                'reason': 'skill_routed_request',
                'workers': ['QUILL', 'AEGIS'],
                'criteria': 'factual',
                'depth': 'standard',
            },
            routing_score={
                'decision': 'team',
                'confidence': 77,
                'reason': 'requires_structured_execution',
                'direct_score': 48,
                'team_score': 81,
                'margin_required': 9,
                'raw_margin': 33,
                'direct_guard_confidence': 55,
                'adaptive_thresholds': {
                    'team_margin_short': 14,
                    'team_margin_default': 9,
                    'direct_guard_confidence': 51,
                    'load_tier': 'high',
                    'notes': ['queue_high', 'latency_high'],
                },
                'load_snapshot': {
                    'pending_count': 6,
                    'latency_p50_ms': 16120,
                    'fail_rate': 0.22,
                    'latest_status': 'delivered',
                },
            },
            skill_names=['mail-gui'],
        )
        self.assertEqual(payload['schema_version'], 'route_decision_trace_v1')
        self.assertEqual(payload['session_key'], 'telegram:trace-1')
        self.assertEqual(payload['route']['mode'], 'team')
        self.assertEqual(payload['route']['decision'], 'team')
        self.assertEqual(payload['route']['adaptive_thresholds']['load_tier'], 'high')
        self.assertEqual(payload['route']['load_snapshot']['pending_count'], 6)
        self.assertEqual(payload['route']['workers'], ['QUILL', 'AEGIS'])
        self.assertEqual(payload['skills_used'], ['mail-gui'])

    def test_internal_status_detection_for_gateway_telegram_vietnamese(self):
        self.assertTrue(
            meridian_gateway._looks_like_meridian_internal_query(
                'trạng thái gateway và telegram delivery hiện tại ra sao'
            )
        )

    def test_autonomy_skill_candidate_skips_internal_status_queries(self):
        self.assertFalse(
            meridian_gateway._autonomy_skill_candidate(
                'trả lời ngắn 2 gạch đầu dòng về trạng thái gateway + telegram delivery hiện tại'
            )
        )

    def test_render_internal_answer_supports_two_bullet_compact_format(self):
        status_payload = {
            'runtime_id': 'loom_native',
            'preflight': 'CLEAR',
            'context': {'bound_org_id': 'org_demo'},
            'treasury': {'balance_usd': 52.47, 'reserve_floor_usd': 50.5},
            'authority': {'pending_approvals': []},
            'cases': {'open': 0},
            'observability': {'slo': {'status': 'healthy'}},
            'alert_queue': {'queue_count': 0},
        }
        proof_payload = {
            'runtime_surfaces': {
                'session_provenance': {'active_count': 2},
                'channel_runtime': {'active_delivery_count': 1},
            }
        }
        with mock.patch.object(meridian_gateway, '_workspace_api_get_json', side_effect=[
            {'ok': True, 'payload': status_payload},
            {'ok': True, 'payload': proof_payload},
        ]):
            with mock.patch.object(
                meridian_gateway,
                '_recent_telegram_delivery_summary',
                return_value={
                    'checked_count': 5,
                    'delivered_count': 4,
                    'failed_count': 1,
                    'latest_status': 'delivered',
                },
            ):
                text = meridian_gateway._render_meridian_internal_answer(
                    'trả lời ngắn 2 gạch đầu dòng về trạng thái gateway + telegram delivery hiện tại'
                )
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith('- Gateway runtime:'))
        self.assertTrue(lines[1].startswith('- Telegram delivery:'))

    def test_step_effective_status_defaults_to_ok_when_result_present(self):
        self.assertEqual(
            meridian_gateway._step_effective_status(
                {'agent_id': 'agent_atlas', 'result': 'artifact ready', 'status': ''}
            ),
            'ok',
        )

    def test_manager_synthesis_fallback_ignores_informational_qa_warning(self):
        steps = [
            {
                'agent_id': 'agent_quill',
                'task_kind': 'write',
                'status': 'ok',
                'result': 'Subject: Demo\\nBody: Test mail',
                'warnings': [],
            },
            {
                'agent_id': 'agent_aegis',
                'task_kind': 'qa_gate',
                'status': 'ok',
                'result': 'PASS',
                'warnings': [
                    'payout_execution_gate: Phase 0 (Founder-Backed Build) does not allow contributor payouts yet'
                ],
            },
        ]
        with mock.patch.object(meridian_gateway, '_run_codex_exec', return_value={'ok': False, 'output_text': ''}):
            with mock.patch.object(meridian_gateway, '_best_usable_step_artifact', return_value='Subject: Demo\\nBody: Test mail'):
                with mock.patch.object(meridian_gateway, 'append_session_event'):
                    answer = meridian_gateway._manager_synthesis(
                        'gửi mail test',
                        'telegram:test-synthesis',
                        steps,
                        plan={'skills': [{'name': 'mail-gui'}]},
                    )
        self.assertNotIn('verification step did not complete', answer.lower())

    def test_skill_registry_can_create_autonomous_skill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = meridian_gateway.SkillRegistry(Path(tmpdir))
            created = registry.create_autonomous_skill('founder update', session_key='telegram:proof', manager_brief='founder update')
            self.assertIsNotNone(created)
            self.assertTrue((Path(tmpdir) / 'founder-update' / 'SKILL.md').exists())
            self.assertEqual(created['name'], 'founder-update')

    def test_skill_registry_refines_autonomous_skill_with_new_variation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = meridian_gateway.SkillRegistry(Path(tmpdir))
            created = registry.create_autonomous_skill(
                'founder update',
                session_key='telegram:proof',
                manager_brief='founder update',
            )
            self.assertIsNotNone(created)
            refined = registry.create_autonomous_skill(
                'founder update brief for the team',
                session_key='telegram:proof',
                manager_brief='founder update brief for the team',
            )
            self.assertIsNotNone(refined)
            self.assertIn(refined.get('autonomy_status'), {'refined', 'reused', 'created'})
            content = (Path(tmpdir) / refined['name'] / 'SKILL.md').read_text(encoding='utf-8')
            self.assertIn('## Learned Variations', content)

    def test_skill_registry_reuses_autonomous_skill_for_exact_same_request(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = meridian_gateway.SkillRegistry(Path(tmpdir))
            created = registry.create_autonomous_skill(
                'protocol hồi sinh deal nguội',
                session_key='telegram:proof',
                manager_brief='protocol hồi sinh deal nguội',
            )
            self.assertIsNotNone(created)
            reused = registry.create_autonomous_skill(
                'protocol hồi sinh deal nguội',
                session_key='telegram:proof',
                manager_brief='protocol hồi sinh deal nguội',
            )
            self.assertIsNotNone(reused)
            self.assertEqual(reused.get('name'), created.get('name'))
            self.assertEqual(reused.get('autonomy_status'), 'reused')

    def test_governed_skill_autonomy_begin_reserves_budget_and_warrant(self):
        budget = {
            'allowed': True,
            'reason': 'ok',
            'reservation': {'reservation_id': 'bud_demo'},
        }
        warrant = {'warrant_id': 'war_demo'}
        with mock.patch.object(meridian_gateway, 'treasury_reserve_runtime_budget', return_value=budget) as reserve_mock:
            with mock.patch.object(meridian_gateway, 'warrants_issue_warrant', return_value=warrant) as issue_mock:
                with mock.patch.object(meridian_gateway, 'warrants_review_warrant', return_value={'warrant_id': 'war_demo', 'court_review_state': 'approved'}) as review_mock:
                    with mock.patch.object(meridian_gateway, 'warrants_validate_warrant_for_execution', return_value={'warrant_id': 'war_demo'}):
                        result = meridian_gateway._governed_skill_autonomy_begin(
                            request='protocol hồi sinh deal nguội',
                            session_key='telegram:123',
                            manager_brief='protocol hồi sinh deal nguội',
                            phase='create',
                            skill_name='protocol-deal-hoi',
                        )
        self.assertTrue(result['allowed'])
        self.assertEqual(result['reservation']['reservation_id'], 'bud_demo')
        self.assertEqual(result['warrant']['warrant_id'], 'war_demo')
        reserve_mock.assert_called_once()
        issue_mock.assert_called_once()
        review_mock.assert_called_once()

    def test_build_memory_packet_prefers_matching_section(self):
        state = {
            'entries': {
                'section/founder': {
                    'key': 'section/founder',
                    'heading': 'Founder',
                    'content': '- Founder-led positioning.\n- Buyer trust matters.',
                    'tokens': ['founder', 'buyer', 'trust'],
                    'accepted_count': 3,
                    'failure_count': 0,
                    'memory_value_score': 3,
                },
                'section/mission': {
                    'key': 'section/mission',
                    'heading': 'Mission',
                    'content': '- Governed operator.',
                    'tokens': ['mission', 'governed', 'operator'],
                    'accepted_count': 1,
                    'failure_count': 0,
                    'memory_value_score': 1,
                },
            },
            'session_packets': {},
        }
        with mock.patch.object(meridian_gateway, '_sync_memory_retrieval_index', return_value=state):
            with mock.patch.object(meridian_gateway, '_save_memory_recall_state'):
                packet = meridian_gateway._build_memory_packet(
                    'viết founder positioning cho buyer enterprise',
                    'telegram:123',
                    ['research-khach-hang'],
                )
        self.assertTrue(packet['entries'])
        self.assertEqual(packet['entries'][0]['key'], 'section/founder')
        self.assertIn('Founder', packet['context'])

    def test_build_memory_packet_ingests_explicit_user_email_fact(self):
        state = {
            'entries': {},
            'session_packets': {},
        }
        with mock.patch.object(meridian_gateway, '_sync_memory_retrieval_index', return_value=state):
            with mock.patch.object(meridian_gateway, '_save_memory_recall_state'):
                with mock.patch.object(meridian_gateway, '_run_loom_memory_command', return_value={'ok': True}):
                    packet = meridian_gateway._build_memory_packet(
                        'gửi mail cho tôi tới nguyensimon186@gmail.com về Meridian',
                        'telegram:123',
                        ['mail-gui'],
                    )
        keys = [item['key'] for item in packet['entries']]
        self.assertTrue(any(key.startswith('fact/email/') for key in keys))
        self.assertIn('nguyensimon186@gmail.com', packet['context'])

    def test_delivery_memory_entry_uses_shape_matched_successful_output_only(self):
        delivery_event = {
            'status': 'success',
            'artifact_source': 'manager_response',
            'final_artifact_usable': True,
            'request_text': 'research khách hàng cho Meridian',
            'text': (
                '**Status**\n\n'
                'Đây là research starter dạng giả thuyết cần kiểm chứng.\n\n'
                '**Likely buyer / user**\n- PMM\n\n'
                '**What must be validated**\n- Pain\n\n'
                '**Next move**\n- Phỏng vấn khách'
            ),
            'skills_used': ['research-khach-hang'],
            'session_key': 'web_api:test-memory-delivery',
            'event_id': 'evt-memory-delivery',
            'delivery_fingerprint': 'udf_memory_delivery',
            'recorded_at': '2026-03-31T13:40:00Z',
            'contributors': [
                {
                    'economy_key': 'atlas',
                    'task_kind': 'research',
                    'status': 'ok',
                    'usable_artifact': True,
                    'artifact_fit_score': 56,
                    'matches_final_artifact': True,
                    'best_fit_contributor': True,
                }
            ],
        }
        entry = meridian_gateway._delivery_memory_entry_from_event(delivery_event)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['category'], 'successful_output')
        self.assertEqual(entry['origin_agent'], 'atlas')
        self.assertIn('research-khach-hang', entry['source_skill_names'])
        self.assertTrue(entry['key'].startswith('delivery/'))
        self.assertEqual(entry['content_format'], meridian_gateway.MEMORY_RECALL_ARTIFACT_VERSION)
        self.assertNotEqual(entry['content'], delivery_event['text'].strip())
        self.assertLess(len(entry['content']), len(delivery_event['text']))
        self.assertIn('Likely buyer', entry['content'])
        self.assertIn('Next move', entry['content'])

    def test_delivery_memory_entry_assigns_writer_origin_for_manager_shaped_mail(self):
        delivery_event = {
            'status': 'success',
            'artifact_source': 'manager_response',
            'final_artifact_usable': True,
            'request_text': 'gửi mail cho khách về Meridian',
            'text': (
                '**Subject:** Meridian update\n\n'
                '**Body:**\n'
                'Hello [Name],\n\nI wanted to share a concise Meridian update and ask for a short follow-up call.'
            ),
            'skills_used': ['mail-gui'],
            'session_key': 'web_api:test-memory-delivery-mail',
            'event_id': 'evt-memory-delivery-mail',
            'delivery_fingerprint': 'udf_memory_delivery_mail',
            'recorded_at': '2026-03-31T13:41:00Z',
            'contributors': [
                {
                    'economy_key': 'quill',
                    'task_kind': 'write',
                    'status': 'ok',
                    'usable_artifact': True,
                    'artifact_fit_score': 61,
                    'matches_final_artifact': True,
                    'best_fit_contributor': True,
                }
            ],
        }
        entry = meridian_gateway._delivery_memory_entry_from_event(delivery_event)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['origin_agent'], 'quill')
        self.assertEqual(entry['origin_task_kind'], 'write')

    def test_delivery_memory_entry_assigns_execute_origin_for_manager_shaped_ops_snapshot(self):
        delivery_event = {
            'status': 'success',
            'artifact_source': 'manager_response',
            'final_artifact_usable': True,
            'request_text': 'ops snapshot',
            'text': 'Operational Meridian snapshot: runtime `loom_native` for `org_48b05c21` is up.',
            'skills_used': ['ops-snapshot'],
            'session_key': 'web_api:test-memory-delivery-ops',
            'event_id': 'evt-memory-delivery-ops',
            'delivery_fingerprint': 'udf_memory_delivery_ops',
            'recorded_at': '2026-04-01T05:40:00Z',
            'contributors': [
                {
                    'economy_key': 'forge',
                    'task_kind': 'execute',
                    'status': 'ok',
                    'usable_artifact': True,
                    'artifact_fit_score': 58,
                    'matches_final_artifact': True,
                    'best_fit_contributor': True,
                },
                {
                    'economy_key': 'pulse',
                    'task_kind': 'compress',
                    'status': 'ok',
                    'usable_artifact': True,
                    'artifact_fit_score': 34,
                    'matches_final_artifact': False,
                    'best_fit_contributor': False,
                },
            ],
        }
        entry = meridian_gateway._delivery_memory_entry_from_event(delivery_event)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['origin_agent'], 'forge')
        self.assertEqual(entry['origin_task_kind'], 'execute')

    def test_upsert_memory_entry_seeds_successful_output_value_from_first_delivery(self):
        state = {'entries': {}}
        record, changed = meridian_gateway._upsert_memory_entry(
            state,
            {
                'key': 'delivery/udf_seeded',
                'heading': 'Successful output: research-khach-hang',
                'category': 'successful_output',
                'content': (
                    '**Status**\n\nĐây là research starter dạng giả thuyết cần kiểm chứng.\n\n'
                    '**Likely buyer**\n- PMM\n\n'
                    '**Next move**\n- Interview buyers'
                ),
                'source_skill_names': ['research-khach-hang'],
                'source_quality_status': 'success',
                'origin_agent': 'atlas',
                'origin_delivery_fingerprint': 'udf_seeded',
            },
        )
        self.assertTrue(changed)
        self.assertIsNotNone(record)
        self.assertEqual(record['accepted_count'], 1)
        self.assertEqual(record['memory_value_score'], 1)
        self.assertEqual(record['support_delivery_fingerprints'], ['udf_seeded'])

    def test_upsert_memory_entry_merges_repeated_successful_output_pattern(self):
        state = {'entries': {}}
        first, _ = meridian_gateway._upsert_memory_entry(
            state,
            {
                'key': 'delivery/udf_merge_a',
                'heading': 'Successful output: research-khach-hang',
                'category': 'successful_output',
                'content': (
                    '**Status**\n\nĐây là research starter dạng giả thuyết cần kiểm chứng.\n\n'
                    '**Likely buyer**\n- PMM\n\n'
                    '**Next move**\n- Interview buyers'
                ),
                'source_skill_names': ['research-khach-hang'],
                'source_quality_status': 'success',
                'origin_agent': 'atlas',
                'origin_delivery_fingerprint': 'udf_merge_a',
            },
        )
        second, _ = meridian_gateway._upsert_memory_entry(
            state,
            {
                'key': 'delivery/udf_merge_b',
                'heading': 'Successful output: research-khach-hang',
                'category': 'successful_output',
                'content': (
                    '**Status**\n\nĐây là research starter dạng giả thuyết cần kiểm chứng.\n\n'
                    '**Likely buyer**\n- PMM\n\n'
                    '**Next move**\n- Interview buyers'
                ),
                'source_skill_names': ['research-khach-hang'],
                'source_quality_status': 'success',
                'origin_agent': 'atlas',
                'origin_delivery_fingerprint': 'udf_merge_b',
            },
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(len(state['entries']), 1)
        self.assertIn('delivery/udf_merge_a', state['entries'])
        self.assertEqual(second['key'], 'delivery/udf_merge_a')
        self.assertEqual(second['accepted_count'], 2)
        self.assertEqual(second['support_delivery_fingerprints'], ['udf_merge_a', 'udf_merge_b'])

    def test_build_memory_packet_penalizes_cross_skill_successful_output_memory(self):
        state = {
            'entries': {
                'delivery/udf_mail': {
                    'key': 'delivery/udf_mail',
                    'heading': 'Successful output: mail-gui',
                    'category': 'successful_output',
                    'content': '**Tiêu đề:** Chào khách',
                    'tokens': ['chao', 'khach', 'meridian', 'mail'],
                    'source_skill_names': ['mail-gui'],
                    'source_quality_status': 'success',
                    'origin_agent': 'quill',
                    'memory_value_score': 4,
                    'accepted_count': 2,
                    'failure_count': 0,
                    'updated_at': '2026-03-31T19:00:00Z',
                },
                'section/mission': {
                    'key': 'section/mission',
                    'heading': 'Mission',
                    'category': 'markdown_section',
                    'content': '- Governed operator.',
                    'tokens': ['mission', 'governed', 'operator', 'meridian'],
                    'accepted_count': 1,
                    'failure_count': 0,
                    'memory_value_score': 1,
                },
            },
            'session_packets': {},
        }
        with mock.patch.object(meridian_gateway, '_sync_memory_retrieval_index', return_value=state):
            with mock.patch.object(meridian_gateway, '_save_memory_recall_state'):
                packet = meridian_gateway._build_memory_packet(
                    'research khách hàng cho Meridian',
                    'web_api:test-memory-cross-skill',
                    ['research-khach-hang'],
                )
        keys = [item['key'] for item in packet['entries']]
        self.assertNotIn('delivery/udf_mail', keys)
        self.assertIn('section/mission', keys)

    def test_skill_registry_finds_trust_ops_skills(self):
        matches = meridian_gateway.TEAM_SKILLS.search('security questionnaire for AI governance review', limit=3)
        self.assertTrue(any(item['name'] == 'security-questionnaire' for item in matches))
        matches = meridian_gateway.TEAM_SKILLS.search('watch model pricing and policy changes this week', limit=3)
        self.assertTrue(any(item['name'] == 'ai-stack-watch' for item in matches))

    def test_skill_bundle_isolates_security_questionnaire_from_generic_matches(self):
        bundle = meridian_gateway._skill_bundle_for_request(
            'soạn security questionnaire cho Meridian về AI governance và data retention',
            'web_api:test-questionnaire-bundle',
            manager_brief='security questionnaire',
            allow_create=False,
        )
        self.assertTrue(bundle['matches'])
        self.assertEqual([item['name'] for item in bundle['matches']], ['security-questionnaire'])

    def test_skill_bundle_isolates_short_english_security_questionnaire_from_internal_status(self):
        bundle = meridian_gateway._skill_bundle_for_request(
            'Security questionnaire for Meridian: what AI governance controls are documented?',
            'web_api:test-questionnaire-bundle-en',
            manager_brief='security questionnaire',
            allow_create=False,
        )
        self.assertTrue(bundle['matches'])
        self.assertEqual([item['name'] for item in bundle['matches']], ['security-questionnaire'])
        self.assertFalse(
            meridian_gateway._looks_like_meridian_internal_query(
                'Security questionnaire for Meridian: what AI governance controls are documented?'
            )
        )

    def test_skill_bundle_isolates_ai_stack_watch_from_safe_web_research(self):
        bundle = meridian_gateway._skill_bundle_for_request(
            'watch thay đổi provider model pricing policy tuần này cho AI stack của Meridian',
            'web_api:test-watch-bundle',
            manager_brief='ai stack watch',
            allow_create=False,
        )
        self.assertTrue(bundle['matches'])
        self.assertEqual([item['name'] for item in bundle['matches']], ['ai-stack-watch'])

    def test_artifact_matches_trust_ops_shapes(self):
        questionnaire = (
            '**Status**\nDraft.\n\n'
            '**Approved evidence**\n- SOC 2 answer pending.\n\n'
            '**Draft answers**\n- Retention answer draft.\n\n'
            '**Open gaps**\n- Missing subprocessor proof.\n\n'
            '**Next move**\n- Escalate retention owner.'
        )
        watch = (
            '**Status**\nBounded watch.\n\n'
            '**Watched changes**\n- Provider pricing update.\n\n'
            '**Impact on trust answers**\n- Recheck pricing references.\n\n'
            '**Next move**\n- Verify official pricing page.'
        )
        self.assertTrue(
            meridian_gateway._artifact_matches_skill_shape(
                questionnaire,
                'soạn security questionnaire cho trust center',
                ['security-questionnaire'],
            )
        )
        self.assertTrue(
            meridian_gateway._artifact_matches_skill_shape(
                watch,
                'watch provider pricing and policy changes',
                ['ai-stack-watch'],
            )
        )

    def test_extract_questionnaire_items_uses_topics_when_request_is_inline(self):
        items = meridian_gateway._extract_questionnaire_items(
            'soạn security questionnaire cho Meridian về AI governance, data retention, subprocessors'
        )
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(any('governance' in item['text'].lower() for item in items))
        self.assertTrue(any('retention' in item['text'].lower() for item in items))
        self.assertTrue(any('subprocessor' in item['text'].lower() for item in items))
        self.assertTrue(all(bool(item['critical']) for item in items[:3]))

    def test_delivery_trust_evidence_entry_from_questionnaire_delivery(self):
        delivery_event = {
            'status': 'success',
            'artifact_source': 'manager_response',
            'final_artifact_usable': True,
            'request_text': 'soạn security questionnaire cho khách enterprise về Meridian AI governance và data retention',
            'text': (
                '**Status**\nDraft.\n\n'
                '**Approved evidence**\n- Existing approved AI governance note.\n\n'
                '**Draft answers**\n- Data retention answer needs confirmation.\n\n'
                '**Open gaps**\n- Missing subprocessor list.\n\n'
                '**Next move**\n- Escalate missing proof.'
            ),
            'skills_used': ['security-questionnaire'],
            'session_key': 'web_api:test-trust-evidence',
            'event_id': 'evt-trust-evidence',
            'delivery_fingerprint': 'udf_trust_evidence',
            'approval_gate_status': 'ready_for_final_delivery',
            'recorded_at': '2026-04-01T06:10:00Z',
            'contributors': [
                {
                    'economy_key': 'quill',
                    'task_kind': 'write',
                    'status': 'ok',
                    'usable_artifact': True,
                    'artifact_fit_score': 62,
                    'matches_final_artifact': True,
                    'best_fit_contributor': True,
                }
            ],
        }
        entry = meridian_gateway._delivery_trust_evidence_entry_from_event(delivery_event)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['kind'], 'questionnaire_answer_pack')
        self.assertEqual(entry['approval_status'], 'approved')
        self.assertEqual(entry['origin_agent'], 'quill')
        self.assertIn('ai_governance', entry['topic_tags'])
        self.assertIn('data_retention', entry['topic_tags'])

    def test_delivery_trust_evidence_entry_from_questionnaire_delivery_stays_draft_while_gate_pending(self):
        delivery_event = {
            'status': 'success',
            'artifact_source': 'manager_response',
            'final_artifact_usable': True,
            'request_text': 'soạn security questionnaire cho khách enterprise về Meridian AI governance và data retention',
            'text': (
                '**Status**\nDraft.\n\n'
                '**Approved evidence**\n- Existing approved AI governance note.\n\n'
                '**Draft answers**\n- Data retention answer needs confirmation.\n\n'
                '**Open gaps**\n- Missing subprocessor list.\n\n'
                '**Next move**\n- Escalate missing proof.'
            ),
            'skills_used': ['security-questionnaire'],
            'session_key': 'web_api:test-trust-evidence-pending',
            'event_id': 'evt-trust-evidence-pending',
            'delivery_fingerprint': 'udf_trust_evidence_pending',
            'approval_gate_status': 'pending_approval',
            'recorded_at': '2026-04-01T06:10:00Z',
        }
        entry = meridian_gateway._delivery_trust_evidence_entry_from_event(delivery_event)
        self.assertIsNotNone(entry)
        self.assertEqual(entry['approval_status'], 'draft')

    def test_build_trust_evidence_packet_prefers_approved_questionnaire_evidence(self):
        state = {
            'entries': {
                'trust/questionnaire/approved': {
                    'key': 'trust/questionnaire/approved',
                    'heading': 'Approved questionnaire answer pack',
                    'kind': 'questionnaire_answer_pack',
                    'content': '- Approved governance answer',
                    'tokens': ['security', 'questionnaire', 'governance'],
                    'approval_status': 'approved',
                    'topic_tags': ['ai_governance'],
                    'source_skill_names': ['security-questionnaire'],
                    'origin_agent': 'quill',
                    'source_recorded_at': '2026-04-01T06:00:00Z',
                    'accepted_count': 1,
                },
                'trust/watch/draft': {
                    'key': 'trust/watch/draft',
                    'heading': 'AI stack watch brief',
                    'kind': 'watch_brief',
                    'content': '- Draft provider watch note',
                    'tokens': ['watch', 'provider', 'policy'],
                    'approval_status': 'draft',
                    'topic_tags': ['model_vendor_changes'],
                    'source_skill_names': ['ai-stack-watch'],
                    'origin_agent': 'atlas',
                    'source_recorded_at': '2026-04-01T05:00:00Z',
                    'accepted_count': 0,
                },
            },
            'session_packets': {},
        }
        with mock.patch.object(meridian_gateway, '_load_trust_evidence_state', return_value=state):
            with mock.patch.object(meridian_gateway, '_save_trust_evidence_state'):
                packet = meridian_gateway._build_trust_evidence_packet(
                    'help me answer a security questionnaire about AI governance',
                    'web_api:test-trust-packet',
                    ['security-questionnaire'],
                )
        self.assertTrue(packet['entries'])
        self.assertEqual(packet['entries'][0]['key'], 'trust/questionnaire/approved')
        self.assertEqual(packet['entries'][0]['approval_status'], 'approved')

    def test_build_questionnaire_state_creates_pending_queue_for_unapproved_critical_questions(self):
        evidence_state = {
            'entries': {
                'trust/questionnaire/approved': {
                    'key': 'trust/questionnaire/approved',
                    'heading': 'Approved questionnaire answer pack',
                    'kind': 'questionnaire_answer_pack',
                    'content': '- Approved governance answer',
                    'tokens': ['security', 'questionnaire', 'governance'],
                    'approval_status': 'approved',
                    'topic_tags': ['ai_governance'],
                    'source_skill_names': ['security-questionnaire'],
                    'origin_agent': 'quill',
                    'source_recorded_at': '2026-04-01T06:00:00Z',
                    'accepted_count': 1,
                },
            },
            'session_packets': {},
        }
        assurance_state = {'version': 1, 'questionnaires': {}, 'approval_queue': {}}
        with mock.patch.object(meridian_gateway, '_load_trust_evidence_state', return_value=evidence_state):
            with mock.patch.object(meridian_gateway, '_load_trust_assurance_state', return_value=assurance_state):
                with mock.patch.object(meridian_gateway, '_save_trust_assurance_state'):
                    questionnaire = meridian_gateway._build_questionnaire_state(
                        'soạn security questionnaire cho Meridian về AI governance, data retention, subprocessors',
                        'web_api:test-questionnaire-state',
                        ['security-questionnaire'],
                    )
        self.assertEqual(questionnaire['approval_gate_status'], 'pending_approval')
        self.assertGreaterEqual(questionnaire['pending_approval_count'], 1)
        self.assertTrue(any(item['approval_required'] for item in questionnaire['approval_queue_entries']))

    def test_review_trust_approval_queue_can_approve_and_clear_gate(self):
        assurance_state = {
            'version': 1,
            'questionnaires': {
                'tq_demo': {
                    'questionnaire_id': 'tq_demo',
                    'source_session_key': 'web_api:test-review-queue',
                    'questions': [
                        {
                            'question_id': 'tqq_demo',
                            'ordinal': 1,
                            'text': 'What is Meridian data retention stance?',
                            'topic_tags': ['data_retention'],
                            'critical': True,
                            'answer_state': 'draft',
                            'approval_required': True,
                            'evidence_key': 'trust/questionnaire/demo',
                            'evidence_status': 'draft',
                            'queue_id': 'tqa_demo',
                        }
                    ],
                }
            },
            'approval_queue': {
                'tqa_demo': {
                    'queue_id': 'tqa_demo',
                    'questionnaire_id': 'tq_demo',
                    'question_id': 'tqq_demo',
                    'question_text': 'What is Meridian data retention stance?',
                    'critical': True,
                    'approval_required': True,
                    'evidence_key': 'trust/questionnaire/demo',
                    'evidence_status': 'draft',
                    'status': 'pending',
                }
            },
        }
        meridian_gateway._rollup_trust_questionnaire(assurance_state['questionnaires']['tq_demo'])
        evidence_state = {
            'entries': {
                'trust/questionnaire/demo': {
                    'key': 'trust/questionnaire/demo',
                    'heading': 'Approved questionnaire answer pack',
                    'kind': 'questionnaire_answer_pack',
                    'content': '- retention answer',
                    'approval_status': 'draft',
                    'topic_tags': ['data_retention'],
                }
            },
            'session_packets': {},
        }
        with mock.patch.object(meridian_gateway, '_load_trust_assurance_state', return_value=assurance_state):
            with mock.patch.object(meridian_gateway, '_load_trust_evidence_state', return_value=evidence_state):
                with mock.patch.object(meridian_gateway, '_save_trust_assurance_state'):
                    with mock.patch.object(meridian_gateway, '_save_trust_evidence_state'):
                        with mock.patch.object(meridian_gateway, 'append_session_event'):
                            reviewed = meridian_gateway._review_trust_approval_queue(
                                'tqa_demo',
                                'approve',
                                note='owner approved retention wording',
                                actor='owner',
                            )
        self.assertIsNotNone(reviewed)
        self.assertTrue(reviewed['questionnaire']['final_delivery_allowed'])
        self.assertEqual(reviewed['queue']['status'], 'approve')
        self.assertEqual(reviewed['question']['answer_state'], 'approved')
        self.assertEqual(evidence_state['entries']['trust/questionnaire/demo']['approval_status'], 'approved')

    def test_review_trust_approval_queue_revoke_files_court_violation(self):
        assurance_state = {
            'version': 1,
            'questionnaires': {
                'tq_demo': {
                    'questionnaire_id': 'tq_demo',
                    'source_session_key': 'web_api:test-review-queue-revoke',
                    'questions': [
                        {
                            'question_id': 'tqq_demo',
                            'ordinal': 1,
                            'text': 'Which subprocessors are in scope?',
                            'topic_tags': ['subprocessors'],
                            'critical': True,
                            'answer_state': 'approved',
                            'approval_required': False,
                            'evidence_key': 'trust/questionnaire/demo',
                            'evidence_status': 'approved',
                            'queue_id': 'tqa_demo',
                            'best_evidence_origin_agent': 'quill',
                        }
                    ],
                }
            },
            'approval_queue': {
                'tqa_demo': {
                    'queue_id': 'tqa_demo',
                    'questionnaire_id': 'tq_demo',
                    'question_id': 'tqq_demo',
                    'question_text': 'Which subprocessors are in scope?',
                    'critical': True,
                    'approval_required': False,
                    'evidence_key': 'trust/questionnaire/demo',
                    'evidence_status': 'approved',
                    'status': 'cleared',
                }
            },
        }
        meridian_gateway._rollup_trust_questionnaire(assurance_state['questionnaires']['tq_demo'])
        evidence_state = {
            'entries': {
                'trust/questionnaire/demo': {
                    'key': 'trust/questionnaire/demo',
                    'heading': 'Approved questionnaire answer pack',
                    'kind': 'questionnaire_answer_pack',
                    'content': '- subprocessor answer',
                    'approval_status': 'approved',
                    'topic_tags': ['subprocessors'],
                    'origin_agent': 'quill',
                }
            },
            'session_packets': {},
        }
        with mock.patch.object(meridian_gateway, '_load_trust_assurance_state', return_value=assurance_state):
            with mock.patch.object(meridian_gateway, '_load_trust_evidence_state', return_value=evidence_state):
                with mock.patch.object(meridian_gateway, '_save_trust_assurance_state'):
                    with mock.patch.object(meridian_gateway, '_save_trust_evidence_state'):
                        with mock.patch.object(meridian_gateway, 'append_session_event'):
                            with mock.patch.object(meridian_gateway, '_record_gateway_audit'):
                                with mock.patch.object(meridian_gateway, 'accounting_append_tx'):
                                    with mock.patch.object(meridian_gateway, 'court_file_violation', return_value='case_123'):
                                        reviewed = meridian_gateway._review_trust_approval_queue(
                                            'tqa_demo',
                                            'revoke',
                                            note='subprocessor claim revoked',
                                            actor='owner',
                                        )
        self.assertIsNotNone(reviewed)
        self.assertEqual(reviewed['queue']['court_violation_id'], 'case_123')
        self.assertEqual(reviewed['question']['answer_state'], 'revoked')
        self.assertEqual(evidence_state['entries']['trust/questionnaire/demo']['approval_status'], 'revoked')

    def test_build_trust_ops_operator_snapshot_defaults_to_actionable_queue(self):
        state = {
            'questionnaires': {
                'tq_pending': {
                    'questionnaire_id': 'tq_pending',
                    'approval_gate_status': 'pending_approval',
                    'pending_approval_count': 1,
                    'critical_count': 1,
                    'source_session_key': 'web_api:pending',
                    'final_delivery_allowed': False,
                    'questions': [
                        {
                            'question_id': 'tqq_pending',
                            'text': 'What retention guarantees exist?',
                            'critical': True,
                            'answer_state': 'stale',
                            'approval_required': True,
                            'evidence_key': 'trust/questionnaire/pending',
                            'evidence_status': 'stale',
                            'best_evidence_origin_agent': 'quill',
                        }
                    ],
                },
                'tq_ready': {
                    'questionnaire_id': 'tq_ready',
                    'approval_gate_status': 'ready_for_final_delivery',
                    'pending_approval_count': 0,
                    'critical_count': 1,
                    'source_session_key': 'web_api:ready',
                    'final_delivery_allowed': True,
                    'questions': [
                        {
                            'question_id': 'tqq_ready',
                            'text': 'What AI governance controls are documented?',
                            'critical': True,
                            'answer_state': 'approved',
                            'approval_required': False,
                            'evidence_key': 'trust/questionnaire/ready',
                            'evidence_status': 'approved',
                            'best_evidence_origin_agent': 'quill',
                        }
                    ],
                },
            },
            'approval_queue': {
                'tqa_pending': {
                    'queue_id': 'tqa_pending',
                    'questionnaire_id': 'tq_pending',
                    'question_id': 'tqq_pending',
                    'question_text': 'What retention guarantees exist?',
                    'critical': True,
                    'status': 'stale',
                    'approval_required': True,
                    'evidence_key': 'trust/questionnaire/pending',
                    'evidence_status': 'stale',
                },
                'tqa_ready': {
                    'queue_id': 'tqa_ready',
                    'questionnaire_id': 'tq_ready',
                    'question_id': 'tqq_ready',
                    'question_text': 'What AI governance controls are documented?',
                    'critical': True,
                    'status': 'cleared',
                    'approval_required': False,
                    'evidence_key': 'trust/questionnaire/ready',
                    'evidence_status': 'approved',
                },
            },
        }
        with mock.patch.object(meridian_gateway, '_load_trust_evidence_state', return_value={'entries': {}, 'session_packets': {}}):
            snapshot = meridian_gateway._build_trust_ops_operator_snapshot(state)
            all_snapshot = meridian_gateway._build_trust_ops_operator_snapshot(state, status_filter='all', include_cleared=True)
        self.assertEqual(snapshot['counts']['actionable'], 1)
        self.assertEqual(len(snapshot['queue']), 1)
        self.assertEqual(snapshot['queue'][0]['queue_id'], 'tqa_pending')
        self.assertEqual(snapshot['queue'][0]['bucket'], 'pending')
        self.assertEqual(snapshot['selected_questionnaire']['questionnaire_id'], 'tq_pending')
        self.assertEqual(len(all_snapshot['queue']), 2)

    def test_extract_operator_token_supports_bearer_and_header_fallback(self):
        bearer_headers = {'Authorization': 'Bearer secret-token'}
        basic_headers = {'Authorization': 'Basic b3BlcmF0b3I6YmFzaWMtc2VjcmV0'}
        header_headers = {'X-Meridian-Operator-Token': 'header-token'}
        self.assertEqual(meridian_gateway._extract_operator_token(bearer_headers), 'secret-token')
        self.assertEqual(meridian_gateway._extract_operator_token(basic_headers), 'basic-secret')
        self.assertEqual(meridian_gateway._extract_operator_token(header_headers), 'header-token')

    def test_operator_token_valid_uses_env_token(self):
        headers = {'Authorization': 'Bearer operator-secret'}
        with mock.patch.dict(meridian_gateway.os.environ, {'MERIDIAN_GATEWAY_TOKEN': 'operator-secret'}, clear=False):
            self.assertTrue(meridian_gateway._operator_token_valid(headers))
        with mock.patch.dict(meridian_gateway.os.environ, {'MERIDIAN_GATEWAY_TOKEN': 'different'}, clear=False):
            self.assertFalse(meridian_gateway._operator_token_valid(headers))

    def test_review_trust_approval_queue_bulk_aggregates_results(self):
        first_review = {
            'queue': {
                'queue_id': 'tqa_one',
                'source_session_key': 'web_api:tq-one',
            },
            'questionnaire': {
                'questionnaire_id': 'tq_one',
            },
            'question': {
                'critical': True,
            },
        }
        second_review = {
            'queue': {
                'queue_id': 'tqa_two',
                'source_session_key': 'web_api:tq-two',
            },
            'questionnaire': {
                'questionnaire_id': 'tq_two',
            },
            'question': {
                'critical': False,
            },
        }
        with mock.patch.object(meridian_gateway, '_review_trust_approval_queue', side_effect=[first_review, second_review]) as review_mock:
            with mock.patch.object(meridian_gateway, '_record_gateway_audit') as audit_mock:
                with mock.patch.object(meridian_gateway, 'accounting_append_tx') as tx_mock:
                    with mock.patch.object(meridian_gateway, '_build_trust_assurance_summary', return_value={'queue_count': 2}):
                        bulk = meridian_gateway._review_trust_approval_queue_bulk(
                            ['tqa_one', 'tqa_two', 'tqa_one'],
                            'approve',
                            note='bulk approve',
                            actor='owner',
                        )
        self.assertIsNotNone(bulk)
        self.assertEqual(review_mock.call_count, 2)
        self.assertEqual(bulk['summary']['requested_count'], 2)
        self.assertEqual(bulk['summary']['reviewed_count'], 2)
        self.assertEqual(bulk['summary']['critical_reviewed_count'], 1)
        self.assertEqual(sorted(bulk['summary']['questionnaire_ids']), ['tq_one', 'tq_two'])
        audit_mock.assert_called_once()
        tx_mock.assert_called_once()

    def test_normalize_memory_entries_decays_stale_successful_output_value(self):
        state = {
            'entries': {
                'delivery/udf_old': {
                    'key': 'delivery/udf_old',
                    'heading': 'Successful output: research-khach-hang',
                    'category': 'successful_output',
                    'content': '**Likely buyer**\n- PMM\n\n**Next move**\n- Interview buyers',
                    'source_skill_names': ['research-khach-hang'],
                    'accepted_count': 4,
                    'failure_count': 0,
                    'memory_value_score': 4,
                    'source_recorded_at': '2026-03-20T00:00:00Z',
                    'updated_at': '2026-03-20T00:00:00Z',
                    'recall_count': 1,
                },
            },
            'session_packets': {},
        }
        now_epoch = meridian_gateway._memory_timestamp_epoch('2026-03-31T00:00:00Z')
        with mock.patch.object(meridian_gateway, '_run_loom_memory_command', return_value={'ok': True}):
            meridian_gateway._normalize_memory_entries(state, now_epoch=now_epoch)
        record = state['entries']['delivery/udf_old']
        self.assertLess(record['memory_value_score'], 4)
        self.assertEqual(record['content_format'], meridian_gateway.MEMORY_RECALL_ARTIFACT_VERSION)

    def test_normalize_memory_entries_evicts_stale_low_value_successful_output(self):
        state = {
            'entries': {
                'delivery/udf_bad': {
                    'key': 'delivery/udf_bad',
                    'heading': 'Successful output: research-khach-hang',
                    'category': 'successful_output',
                    'content': '**Likely buyer**\n- PMM',
                    'source_skill_names': ['research-khach-hang'],
                    'accepted_count': 0,
                    'failure_count': 2,
                    'memory_value_score': -2,
                    'source_recorded_at': '2026-03-01T00:00:00Z',
                    'updated_at': '2026-03-01T00:00:00Z',
                    'recall_count': 0,
                },
            },
            'session_packets': {},
        }
        now_epoch = meridian_gateway._memory_timestamp_epoch('2026-03-31T00:00:00Z')
        with mock.patch.object(meridian_gateway, '_run_loom_memory_command', return_value={'ok': True}) as loom_mock:
            meridian_gateway._normalize_memory_entries(state, now_epoch=now_epoch)
        self.assertNotIn('delivery/udf_bad', state['entries'])
        self.assertTrue(any('remove' in str(call.args[0]) for call in loom_mock.call_args_list))

    def test_actionable_end_user_request_creates_skill_routed_team_plan(self):
        prompt = 'bạn có thể gửi mail cho tôi về trạng thái cập nhật mới nhất của Meridian thông qua mail của chính tôi là nguyensimon186@gmail.com.'
        with tempfile.TemporaryDirectory() as tmpdir:
            original_registry = meridian_gateway.TEAM_SKILLS
            registry = meridian_gateway.SkillRegistry(Path(tmpdir))
            registry.load()
            meridian_gateway.TEAM_SKILLS = registry
            try:
                plan = meridian_gateway._team_route_plan(prompt, 'telegram:5322393870')
            finally:
                meridian_gateway.TEAM_SKILLS = original_registry
            self.assertEqual(plan['mode'], 'team')
            self.assertEqual(plan['reason'], 'skill_routed_request')
            self.assertTrue(plan['skills'])
            self.assertTrue(any(('email' in item['name'] or 'mail' in item['name']) for item in plan['skills']))
            self.assertIn('QUILL', plan['workers'])
            self.assertIn('prioritize the user-facing artifact', plan['manager_brief'])

    def test_follow_up_after_demo_materializes_new_skill_instead_of_council_match(self):
        prompt = 'soạn follow up cho khách sau demo hôm qua'
        self.assertTrue(meridian_gateway._autonomy_skill_candidate(prompt))
        with tempfile.TemporaryDirectory() as tmpdir:
            original_registry = meridian_gateway.TEAM_SKILLS
            registry = meridian_gateway.SkillRegistry(Path(tmpdir))
            registry.load()
            meridian_gateway.TEAM_SKILLS = registry
            try:
                bundle = meridian_gateway._skill_bundle_for_request(
                    prompt,
                    'web_api:test-follow-up',
                    manager_brief=prompt,
                    allow_create=True,
                )
            finally:
                meridian_gateway.TEAM_SKILLS = original_registry
            self.assertIsNotNone(bundle['created_skill'])
            created_name = str(bundle['created_skill']['name'])
            self.assertNotEqual(created_name, 'council-meeting')
            self.assertTrue(created_name.startswith('follow-') or 'follow' in created_name)
            self.assertTrue(any(item['name'] == created_name for item in bundle['matches']))

    def test_protocol_request_materializes_new_skill_instead_of_reusing_council_skill(self):
        prompt = (
            'hãy tạo cho tôi một protocol hồi sinh deal nguội trong 9 phút: gồm 2 giả thuyết đảo ngược, '
            '4 câu hỏi loại bỏ ngụy biện, 1 tin nhắn kéo khách quay lại bàn đàm phán, và 1 tiêu chí dừng rõ ràng.'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            council_dir = root / 'council-meeting'
            council_dir.mkdir(parents=True, exist_ok=True)
            (council_dir / 'SKILL.md').write_text(
                """---
name: council-meeting
description: "Use when Meridian needs a board-style council discussion about customer readiness, open-source intent, strategic clarity, or whether the current product is truly buyable."
category: "strategy"
---

# Council Meeting

Use when the user asks for:
- council meeting
- board review
- why would a customer buy this
""",
                encoding='utf-8',
            )
            original_registry = meridian_gateway.TEAM_SKILLS
            registry = meridian_gateway.SkillRegistry(root)
            registry.load()
            meridian_gateway.TEAM_SKILLS = registry
            try:
                bundle = meridian_gateway._skill_bundle_for_request(
                    prompt,
                    'telegram:5322393870',
                    manager_brief=prompt,
                    allow_create=True,
                )
            finally:
                meridian_gateway.TEAM_SKILLS = original_registry
            self.assertIsNotNone(bundle['created_skill'])
            self.assertNotEqual(bundle['created_skill']['name'], 'council-meeting')
            self.assertIn('protocol', bundle['created_skill']['name'])
            self.assertIn('QUILL', bundle['workers'])
            self.assertIn('FORGE', bundle['workers'])
            self.assertTrue(any(item['name'] == bundle['created_skill']['name'] for item in bundle['matches']))

    def test_protocol_request_reuses_existing_autonomous_protocol_skill(self):
        prompt = (
            'hãy tạo cho tôi một protocol hồi sinh deal nguội trong 9 phút: gồm 2 giả thuyết đảo ngược, '
            '4 câu hỏi loại bỏ ngụy biện, 1 tin nhắn kéo khách quay lại bàn đàm phán, và 1 tiêu chí dừng rõ ràng.'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            original_registry = meridian_gateway.TEAM_SKILLS
            registry = meridian_gateway.SkillRegistry(Path(tmpdir))
            registry.load()
            meridian_gateway.TEAM_SKILLS = registry
            try:
                first = meridian_gateway._skill_bundle_for_request(
                    prompt,
                    'telegram:5322393870',
                    manager_brief=prompt,
                    allow_create=True,
                )
                second = meridian_gateway._skill_bundle_for_request(
                    prompt,
                    'telegram:5322393870',
                    manager_brief=prompt,
                    allow_create=True,
                )
            finally:
                meridian_gateway.TEAM_SKILLS = original_registry
            self.assertIsNotNone(first['created_skill'])
            self.assertIsNone(second['created_skill'])
            self.assertIsNone(second['refined_skill'])
            self.assertTrue(second['matches'])
            self.assertEqual(len(second['matches']), 1)
            self.assertEqual(second['matches'][0]['name'], first['created_skill']['name'])

    def test_research_customer_prompt_creates_specific_skill_instead_of_refining_follow_up_skill(self):
        prompt = 'research khách hàng cho sản phẩm competitor intelligence'
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            follow_dir = root / 'follow-demo-soan'
            follow_dir.mkdir(parents=True, exist_ok=True)
            (follow_dir / 'SKILL.md').write_text(
                """---
name: follow-demo-soan
description: "Use when a request like 'soạn follow up cho khách sau demo hôm qua' needs a reusable Meridian workflow instead of an ad hoc reply."
metadata:
  created_by: meridian_skill_autonomy
  session_key: "web_api:test"
  category: "communication"
---

# Follow Demo Soan

Use this skill when the user gives a short prompt such as:
- soạn follow up cho khách sau demo hôm qua
""",
                encoding='utf-8',
            )
            original_registry = meridian_gateway.TEAM_SKILLS
            registry = meridian_gateway.SkillRegistry(root)
            registry.load()
            meridian_gateway.TEAM_SKILLS = registry
            try:
                bundle = meridian_gateway._skill_bundle_for_request(
                    prompt,
                    'web_api:test-research-customer',
                    manager_brief=prompt,
                    allow_create=True,
                )
            finally:
                meridian_gateway.TEAM_SKILLS = original_registry
            self.assertIsNotNone(bundle['created_skill'])
            self.assertNotEqual(bundle['created_skill']['name'], 'follow-demo-soan')
            self.assertIn('research', bundle['created_skill']['name'])

    def test_atlas_placeholder_citations_are_sanitized_to_customer_research_starter(self):
        plan = {
            'manager_brief': 'Research customer demand for competitor intelligence.',
            'topic': 'research khách hàng cho sản phẩm competitor intelligence',
            'criteria': 'factual',
            'skills': [
                {
                    'name': 'research-khach-hang',
                    'description': 'Customer research starter pack',
                    'workers': ['ATLAS', 'AEGIS'],
                    'category': 'research',
                }
            ],
        }
        result = {
            'research': "[{'finding':'Fake claim','citations':[{'url':'https://example.com/fake'}]}]",
            'job_id': 'job-atlas',
            'error': '',
        }
        with mock.patch.object(meridian_gateway, 'append_session_event'):
            with mock.patch.object(meridian_gateway.mcp_server, 'do_on_demand_research_route', return_value=result):
                receipt = meridian_gateway._run_specialist_step(
                    'ATLAS',
                    'research khách hàng cho sản phẩm competitor intelligence',
                    'web_api:test-research-customer',
                    plan,
                )
        self.assertEqual(receipt['status'], 'ok')
        self.assertIn('giả thuyết cần kiểm chứng', receipt['result'])
        self.assertIn('placeholder_citations_detected_in_research_output', receipt['warnings'])
        self.assertIn('customer_research_starter_salvaged_after_unverified_research', receipt['warnings'])

    def test_atlas_research_route_receives_memory_shortlist(self):
        plan = {
            'manager_brief': 'Research paid customer demand for Meridian.',
            'topic': 'research khách hàng trả tiền cho Meridian',
            'criteria': 'factual',
            'memory_packet': {
                'entries': [
                    {
                        'key': 'delivery/udf_old_research',
                        'heading': 'Successful output: research-khach-hang',
                        'category': 'successful_output',
                        'content': 'Reusable pattern (research-khach-hang)\n- Likely buyer: PMM | operator\n- Next move: interview 5 buyers',
                        'fit_score': 42,
                        'memory_value_score': 5,
                        'source_skill_names': ['research-khach-hang'],
                    },
                    {
                        'key': 'fact/email/demo',
                        'heading': 'User Contact',
                        'category': 'user_fact',
                        'content': 'User contact email: nguyensimon186@gmail.com',
                        'fit_score': 18,
                        'memory_value_score': 1,
                        'source_skill_names': [],
                    },
                ],
                'context': '...',
            },
            'skills': [
                {
                    'name': 'research-khach-hang',
                    'description': 'Customer research starter pack',
                    'workers': ['ATLAS', 'AEGIS'],
                    'category': 'research',
                }
            ],
        }
        result = {
            'research': '**Status**\n\nĐây là research starter dạng giả thuyết cần kiểm chứng.',
            'job_id': 'job-atlas',
            'error': '',
        }
        with mock.patch.object(meridian_gateway, 'append_session_event'):
            with mock.patch.object(meridian_gateway, '_atlas_should_use_internal_analysis', return_value=False):
                with mock.patch.object(meridian_gateway.mcp_server, 'do_on_demand_research_route', return_value=result) as route_mock:
                    receipt = meridian_gateway._run_specialist_step(
                        'ATLAS',
                        'research khách hàng trả tiền cho Meridian',
                        'web_api:test-atlas-memory-shortlist',
                        plan,
                    )
        self.assertEqual(receipt['status'], 'ok')
        research_prompt = route_mock.call_args.args[0]
        self.assertIn('Governed memory shortlist for research planning', research_prompt)
        self.assertIn('Reusable prior pattern', research_prompt)
        self.assertIn('Known user fact', research_prompt)
        self.assertIn('Do not treat it as live evidence', research_prompt)

    def test_complex_governance_request_does_not_collapse_to_internal_status(self):
        prompt = (
            'Leviathann, handle this as an operator crisis workflow. '
            'I need a truthful response that explains the current Meridian governance posture, '
            'states what happens if Sentinel is sanction-restricted while QA is still required, '
            'and produces an internal remediation plan for Telegram delivery and founder-facing messaging.'
        )
        plan = meridian_gateway._team_route_plan(prompt, 'telegram:5322393870')
        self.assertEqual(plan['mode'], 'team')
        self.assertEqual(plan['reason'], 'meridian_operator_workflow')
        self.assertIn('FORGE', plan['workers'])
        self.assertIn('AEGIS', plan['workers'])
        self.assertIn('QUILL', plan['workers'])

    def test_forge_receipt_backfills_from_runtime_result_when_worker_result_missing(self):
        plan = {
            'manager_brief': 'Draft the operational remediation sequence.',
            'topic': 'operator crisis',
            'criteria': 'consistency',
        }
        loom_result = {'ok': True, 'job_id': 'job-forge', 'worker_result': {}}
        backfill = {
            'host_response_json': {
                'output_text': '```json\n{"result":"forge sequence","confidence":0.8,"citations":[],"warnings":["host warning"]}\n```'
            }
        }
        with mock.patch.object(meridian_gateway, 'append_session_event'):
            with mock.patch.object(meridian_gateway.mcp_server, '_shared_run_loom_capability', return_value=loom_result):
                with mock.patch.object(meridian_gateway, '_load_runtime_job_result', return_value=backfill):
                    receipt = meridian_gateway._run_specialist_step('FORGE', 'Need remediation plan', 'telegram:5322393870', plan)
        self.assertEqual(receipt['status'], 'ok')
        self.assertEqual(receipt['result'], 'forge sequence')
        self.assertEqual(receipt['warnings'], ['host warning'])

    def test_specialist_receipt_surfaces_skills_used(self):
        plan = {
            'manager_brief': 'Create a host snapshot.',
            'topic': 'ops snapshot',
            'criteria': 'consistency',
            'skills': [
                {
                    'name': 'ops-snapshot',
                    'description': 'Use when Leviathann needs a fast local health snapshot.',
                    'body_excerpt': '1. Check local health.\n2. Summarize actionable issues.',
                    'workers': ['FORGE', 'PULSE'],
                }
            ],
        }
        loom_result = {
            'ok': True,
            'job_id': 'job-forge',
            'worker_result': {
                'host_response_json': {
                    'output_text': '```json\n{"result":"host snapshot ready","confidence":"high","citations":[],"warnings":[]}\n```'
                }
            },
        }
        with mock.patch.object(meridian_gateway, 'append_session_event'):
            with mock.patch.object(meridian_gateway.mcp_server, '_shared_run_loom_capability', return_value=loom_result):
                receipt = meridian_gateway._run_specialist_step('FORGE', 'ops snapshot', 'telegram:5322393870', plan)
        self.assertEqual(receipt['skills_used'], ['ops-snapshot'])

    def test_quality_marks_recoverable_action_flow_as_partial(self):
        steps = [
            {
                'agent_id': 'agent_quill',
                'task_kind': 'write',
                'status': 'ok',
                'result': "{'type':'meeting-plan','status':'draft','time':'sáng mai'}",
                'warnings': ['Meeting details are minimal and may need further clarification from the host.'],
            },
            {
                'agent_id': 'agent_forge',
                'task_kind': 'execute',
                'status': 'ok',
                'result': 'Unable to book meeting due to lack of information. 1. Confirm exact time. 2. Check availability.',
                'warnings': ['Loom job timed out (120s limit)'],
            },
            {
                'agent_id': 'agent_aegis',
                'task_kind': 'qa_gate',
                'status': 'ok',
                'result': 'FAIL',
                'warnings': ['Request lacks concrete details (time, participants, purpose)'],
            },
        ]
        status, reasons = meridian_gateway._assess_skill_quality_outcome(steps)
        self.assertEqual(status, 'partial')
        self.assertIn('QA gate returned FAIL.', reasons)

    def test_quality_marks_unusable_timed_out_flow_as_failure(self):
        steps = [
            {
                'agent_id': 'agent_atlas',
                'task_kind': 'research',
                'status': 'error',
                'result': '',
                'warnings': ['Loom job timed out (150s limit)'],
            },
            {
                'agent_id': 'agent_aegis',
                'task_kind': 'qa_gate',
                'status': 'error',
                'result': 'Loom job timed out (90s limit)',
                'warnings': ['Loom job timed out (90s limit)'],
            },
        ]
        status, reasons = meridian_gateway._assess_skill_quality_outcome(steps)
        self.assertEqual(status, 'failure')
        self.assertTrue(any('agent_atlas status=error' in reason for reason in reasons))

    def test_short_skill_routed_requests_do_not_pull_noisy_history_into_specialists(self):
        plan = {'reason': 'skill_routed_request'}
        with mock.patch.object(meridian_gateway, 'imported_history_context', return_value='noisy prior context'):
            context = meridian_gateway._specialist_history_context(
                'gửi mail cho tôi nội dung chào khách',
                'telegram:proof',
                plan,
            )
        self.assertEqual(context, '')

    def test_mail_skill_addendum_forbids_product_scope_output(self):
        addendum = meridian_gateway._skill_specific_execution_addendum(
            'gửi mail cho tôi nội dung chào khách',
            [{'name': 'mail-gui'}],
        )
        self.assertIn('send-ready email or message draft', addendum)
        self.assertIn('Do not return product goals, scope, acceptance criteria', addendum)

    def test_communication_profile_prefers_quill_and_aegis_only(self):
        self.assertEqual(meridian_gateway.AUTONOMY_WORKER_PROFILES['communication'], ['QUILL', 'AEGIS'])

    def test_salvage_user_artifact_rewrites_mail_scope_drift(self):
        salvaged = meridian_gateway._salvage_user_artifact(
            'gửi mail cho tôi nội dung chào khách và hỏi lịch hẹn ngày mai',
            ['mail-gui'],
        )
        self.assertIn('Tiêu đề', salvaged)
        self.assertIn('[Tên khách]', salvaged)

    def test_meeting_output_with_internal_attendees_needs_salvage(self):
        raw = "{'subject': 'Meeting Invitation', 'to': 'FORGE, AEGIS', 'attendees': ['Atlas', 'Quill', 'Forge']}"
        self.assertTrue(meridian_gateway._meeting_output_needs_salvage(raw))

    def test_web_request_session_prefers_explicit_session_id(self):
        resolved = meridian_gateway._resolve_web_request_session(
            {'goal': 'book meeting', 'session_id': 'Team Demo 01'},
            {},
            'book meeting',
        )
        self.assertEqual(resolved['session_id'], 'team-demo-01')
        self.assertEqual(resolved['session_key'], 'web_api:team-demo-01')
        self.assertFalse(resolved['generated'])

    def test_web_request_session_generates_isolated_id_when_missing(self):
        resolved_a = meridian_gateway._resolve_web_request_session({'goal': 'book meeting'}, {}, 'book meeting')
        resolved_b = meridian_gateway._resolve_web_request_session({'goal': 'founder update'}, {}, 'founder update')
        self.assertTrue(str(resolved_a['session_id']).startswith('ws-'))
        self.assertTrue(str(resolved_b['session_id']).startswith('ws-'))
        self.assertNotEqual(resolved_a['session_id'], resolved_b['session_id'])
        self.assertNotEqual(resolved_a['session_key'], resolved_b['session_key'])
        self.assertTrue(resolved_a['generated'])
        self.assertTrue(resolved_b['generated'])

    def test_effective_web_session_key_ignores_legacy_shared_ingress_key(self):
        session_key = meridian_gateway._effective_web_session_key(
            'ws-demo1234',
            {'session_key': f'web_api:{meridian_gateway.LOOM_ORG_ID}'},
        )
        self.assertEqual(session_key, 'web_api:ws-demo1234')

    def test_effective_web_session_key_keeps_specific_ingress_key(self):
        session_key = meridian_gateway._effective_web_session_key(
            'ws-demo1234',
            {'session_key': 'web_api:thread-abc'},
        )
        self.assertEqual(session_key, 'web_api:thread-abc')

    def test_book_meeting_without_execution_details_downshifts_to_quill_and_aegis(self):
        workers = meridian_gateway._refine_skill_routed_workers(
            'book meeting với khách hàng tiềm năng vào sáng mai',
            [{'name': 'book-meeting'}],
            ['QUILL', 'FORGE', 'AEGIS'],
        )
        self.assertEqual(workers, ['QUILL', 'AEGIS'])

    def test_book_meeting_with_execution_details_keeps_forge(self):
        workers = meridian_gateway._refine_skill_routed_workers(
            'book meeting với demo@acme.com lúc 09:30 trên Zoom',
            [{'name': 'book-meeting'}],
            ['QUILL', 'FORGE', 'AEGIS'],
        )
        self.assertEqual(workers, ['QUILL', 'FORGE', 'AEGIS'])

    def test_protocol_skill_route_downshifts_forge_for_protocol_artifact(self):
        workers = meridian_gateway._refine_skill_routed_workers(
            'hãy tạo cho tôi một protocol kéo deal quay lại bàn đàm phán',
            [{'name': 'protocol-deal-hoi'}],
            ['QUILL', 'FORGE', 'AEGIS'],
        )
        self.assertEqual(workers, ['QUILL', 'AEGIS'])

    def test_customer_research_starter_downshifts_quill_when_no_writer_cue(self):
        workers = meridian_gateway._refine_skill_routed_workers(
            'research khách hàng trả tiền cho Meridian',
            [{'name': 'research-khach-hang'}],
            ['ATLAS', 'QUILL', 'AEGIS'],
        )
        self.assertEqual(workers, ['ATLAS'])

    def test_customer_research_brief_keeps_quill_when_writer_cue_present(self):
        workers = meridian_gateway._refine_skill_routed_workers(
            'viết customer research brief cho Meridian',
            [{'name': 'research-khach-hang'}],
            ['ATLAS', 'QUILL', 'AEGIS'],
        )
        self.assertEqual(workers, ['ATLAS', 'QUILL', 'AEGIS'])

    def test_bounded_competitor_scan_downshifts_quill_when_report_not_requested(self):
        workers = meridian_gateway._refine_skill_routed_workers(
            'scan đối thủ openai tuần này',
            [{'name': 'scan-doi-thu'}],
            ['ATLAS', 'QUILL', 'AEGIS'],
        )
        self.assertEqual(workers, ['ATLAS', 'AEGIS'])

    def test_communication_skills_use_fast_specialist_timeouts(self):
        self.assertEqual(
            meridian_gateway._specialist_timeout_for_request('AEGIS', 'gửi mail cho khách', ['mail-gui']),
            25,
        )
        self.assertEqual(
            meridian_gateway._specialist_timeout_for_request('QUILL', 'book meeting', ['book-meeting']),
            30,
        )

    def test_communication_skills_prefer_direct_provider_first(self):
        self.assertTrue(meridian_gateway._prefer_direct_provider_first('QUILL', 'gửi mail cho khách', ['mail-gui']))
        self.assertTrue(meridian_gateway._prefer_direct_provider_first('AEGIS', 'book meeting với khách', ['book-meeting']))
        self.assertTrue(meridian_gateway._prefer_direct_provider_first('QUILL', 'soạn follow up cho khách sau demo hôm qua', ['follow-demo-soan']))
        self.assertFalse(meridian_gateway._prefer_direct_provider_first('FORGE', 'book meeting với khách', ['book-meeting']))
        self.assertTrue(meridian_gateway._prefer_direct_provider_first('QUILL', 'check link này giúp tôi https://example.com', ['safe-web-research']))
        self.assertTrue(
            meridian_gateway._prefer_direct_provider_first(
                'QUILL',
                'hãy tạo cho tôi một protocol kéo deal quay lại bàn đàm phán',
                ['protocol-deal-hoi'],
            )
        )

    def test_direct_provider_timeout_uses_fail_fast_budget_for_protocol_lane(self):
        timeout = meridian_gateway._direct_provider_timeout_for_request(
            'QUILL',
            'hãy tạo cho tôi một protocol kéo deal quay lại bàn đàm phán',
            ['protocol-deal-hoi'],
            22,
        )
        self.assertEqual(timeout, 11)

    def test_artifact_source_from_best_worker_repair_maps_to_worker_artifact(self):
        self.assertEqual(
            meridian_gateway._artifact_source_from_repairs(['manager_response_repaired_from_best_worker_artifact']),
            'worker_artifact',
        )

    def test_safe_web_requests_are_detected_from_public_url(self):
        self.assertTrue(
            meridian_gateway._request_prefers_safe_web_research(
                'đọc source này giúp tôi https://openai.com/index/introducing-gpt-5/'
            )
        )

    def test_email_address_does_not_trigger_safe_web_route(self):
        self.assertFalse(
            meridian_gateway._request_prefers_safe_web_research(
                'gửi mail cho tôi tới nguyensimon186@gmail.com về tình hình Meridian'
            )
        )

    def test_trang_thai_phrase_does_not_trigger_safe_web_route(self):
        self.assertFalse(
            meridian_gateway._request_prefers_safe_web_research(
                'gửi mail cho tôi về trạng thái cập nhật mới nhất của Meridian'
            )
        )

    def test_skill_bundle_prefers_safe_web_research_for_url_prompt(self):
        with mock.patch.object(
            meridian_gateway.TEAM_SKILLS,
            'search',
            return_value=[
                {'name': 'ai-intelligence', 'description': 'generic research', 'score': 13},
                {'name': 'safe-web-research', 'description': 'safe url fetch', 'score': 12},
            ],
        ):
            bundle = meridian_gateway._skill_bundle_for_request(
                'check link này giúp tôi https://example.com',
                'web_api:test-safe-web',
                manager_brief='check link này giúp tôi https://example.com',
                allow_create=True,
            )
        self.assertEqual([item['name'] for item in bundle['matches']], ['safe-web-research'])

    def test_skill_bundle_isolates_customer_research_from_protocol_like_skill(self):
        with mock.patch.object(
            meridian_gateway.TEAM_SKILLS,
            'search',
            return_value=[
                {'name': 'research-khach-hang', 'description': 'customer research', 'score': 19},
                {'name': 'khach-hay-tao', 'description': 'protocol builder', 'score': 18},
            ],
        ):
            bundle = meridian_gateway._skill_bundle_for_request(
                'research khách hàng trả tiền cho Meridian, tập trung trigger mua hàng và willingness to pay',
                'web_api:test-customer-research-isolated',
                manager_brief='research khách hàng trả tiền cho Meridian, tập trung trigger mua hàng và willingness to pay',
                allow_create=True,
            )
        self.assertEqual([item['name'] for item in bundle['matches']], ['research-khach-hang'])

    def test_salvaged_competitor_scan_names_follow_up_targets_and_narrower_query(self):
        artifact = meridian_gateway._salvage_competitor_scan_artifact('scan đối thủ openai tuần này')
        self.assertIn('Official-source', artifact)
        self.assertIn('Narrower next query', artifact)
        self.assertIn('OPENAI', artifact)

    def test_competitor_scan_artifact_needs_salvage_when_follow_up_targets_missing(self):
        artifact = """**Status**\nNo verified findings.\n\n**Verified findings**\nNone.\n\n**Unknowns**\nStill unknown.\n\n**Next move**\nTry again later."""
        self.assertTrue(meridian_gateway._competitor_scan_artifact_needs_salvage(artifact))
        self.assertFalse(
            meridian_gateway._competitor_scan_artifact_needs_salvage(
                meridian_gateway._salvage_competitor_scan_artifact('scan đối thủ openai tuần này')
            )
        )

    def test_scan_doi_thu_quality_uses_final_artifact_when_worker_qa_is_recoverable(self):
        steps = [
            {
                'agent_id': 'agent_atlas',
                'task_kind': 'research',
                'status': 'ok',
                'result': "{'Status':'Search completed','Verified findings':[],'Unknowns':'unverified competitor moves'}",
                'warnings': [],
            },
            {
                'agent_id': 'agent_aegis',
                'task_kind': 'qa_gate',
                'status': 'ok',
                'result': 'FAIL',
                'warnings': [
                    'Missing required follow-up targets in unknowns section',
                    'No narrower next query specified for bounded scan',
                    'Verified findings remain empty without explicit source limitations documented',
                ],
            },
        ]
        artifact = meridian_gateway._salvage_competitor_scan_artifact('scan đối thủ openai tuần này')
        status, reasons = meridian_gateway._assess_skill_quality_outcome(
            steps,
            ['scan-doi-thu'],
            final_artifact=artifact,
        )
        self.assertEqual(status, 'success')
        self.assertEqual(reasons, [])

    def test_ops_snapshot_warnings_are_informational_for_quality(self):
        steps = [
            {
                'agent_id': 'agent_forge',
                'task_kind': 'execute',
                'status': 'ok',
                'result': 'Operational Meridian snapshot: runtime `loom_native` for `org_48b05c21` is up.',
                'warnings': [
                    'payout_execution_gate: Phase 0 (Founder-Backed Build) does not allow contributor payouts yet',
                    'disk pressure and scheduled-job status were not independently verified in this snapshot',
                ],
            },
            {
                'agent_id': 'agent_pulse',
                'task_kind': 'compress',
                'status': 'ok',
                'result': 'Compressed Meridian snapshot: `loom_native` on `org_48b05c21`, preflight `CLEAR`.',
                'warnings': [],
            },
        ]
        status, reasons = meridian_gateway._assess_skill_quality_outcome(steps, ['ops-snapshot'])
        self.assertEqual(status, 'success')
        self.assertEqual(reasons, [])

    def test_scope_document_is_not_treated_as_usable_artifact(self):
        step = {
            'agent_id': 'agent_quill',
            'task_kind': 'write',
            'status': 'ok',
            'result': '**Product Goal:** Make a new feature page. **Acceptance Criteria:** ...',
            'warnings': [],
        }
        self.assertFalse(meridian_gateway._step_has_usable_artifact(step))

    def test_qa_fail_with_only_informational_warnings_is_recoverable(self):
        step = {
            'agent_id': 'agent_aegis',
            'task_kind': 'qa_gate',
            'status': 'ok',
            'result': 'FAIL',
            'warnings': ['bounded llm host call completed against https://example.com via provider profile aegis_specialist (openai_compatible)'],
        }
        self.assertTrue(meridian_gateway._qa_fail_is_recoverable(step))

    def test_follow_up_skill_addendum_forbids_scope_output(self):
        addendum = meridian_gateway._skill_specific_execution_addendum(
            'soạn follow up cho khách sau demo hôm qua',
            [{'name': 'follow-demo-soan'}],
        )
        self.assertIn('customer follow-up message or email', addendum)
        self.assertIn('Do not return product goals, feature scope', addendum)

    def test_salvage_user_artifact_rewrites_follow_up_scope_drift(self):
        salvaged = meridian_gateway._salvage_user_artifact(
            'soạn follow up cho khách sau demo hôm qua',
            ['follow-demo-soan'],
        )
        self.assertIn('Cảm ơn anh/chị đã dành thời gian tham gia buổi demo hôm qua', salvaged)

    def test_protocol_request_keeps_manager_protocol_answer_over_mail_follow_worker_artifact(self):
        request = (
            'hãy tạo cho tôi một protocol cứu deal chết trong 7 phút: gồm 3 giả thuyết, '
            '5 câu hỏi bóc tách, 1 tin nhắn follow-up gửi khách, và 1 tiêu chí dừng rõ ràng.'
        )
        manager_answer = (
            '**Protocol cứu deal chết trong 7 phút**\n\n'
            '**3 giả thuyết**\n'
            '1. Deal kẹt ở ưu tiên nội bộ.\n'
            '2. Deal kẹt ở rủi ro quyết định.\n'
            '3. Deal kẹt ở timing hoặc ngân sách.\n\n'
            '**5 câu hỏi bóc tách**\n'
            '1. Điều gì đang chặn quyết định?\n'
            '2. Ưu tiên nào đang đứng trước deal này?\n'
            '3. Ai còn chưa đồng ý?\n'
            '4. Rủi ro lớn nhất là gì?\n'
            '5. Điều gì cần đổi để deal chạy lại?\n\n'
            '**1 tin nhắn follow-up gửi khách**\n'
            'Anh/chị cho em hỏi đâu là điểm lớn nhất đang chặn quyết định để bên em xử lý ngay.\n\n'
            '**1 tiêu chí dừng rõ ràng**\n'
            'Nếu không có người chịu trách nhiệm và không có mốc thời gian rõ trong 7 ngày thì đóng deal.'
        )
        steps = [
            {
                'status': 'ok',
                'task_kind': 'write',
                'result': '**Tiêu đề:** Chào anh/chị\\n\\n**Nội dung:** Xin lịch hẹn ngày mai.',
                'warnings': [],
            }
        ]
        repaired, warnings = meridian_gateway._repair_manager_answer(
            request,
            manager_answer,
            steps,
            ['follow-demo-soan', 'mail-gui'],
        )
        self.assertEqual(repaired, manager_answer)
        self.assertEqual(warnings, [])

    def test_protocol_request_salvage_prefers_protocol_template_over_mail_template(self):
        request = (
            'hãy tạo cho tôi một protocol cứu deal chết trong 7 phút: gồm 3 giả thuyết, '
            '5 câu hỏi bóc tách, 1 tin nhắn follow-up gửi khách, và 1 tiêu chí dừng rõ ràng.'
        )
        salvaged = meridian_gateway._salvage_user_artifact(request, ['follow-demo-soan', 'mail-gui'])
        self.assertIn('giả thuyết', salvaged.lower())
        self.assertIn('tiêu chí dừng', salvaged.lower())
        self.assertNotIn('**tiêu đề:**', salvaged.lower())

    def test_mail_request_salvage_prefers_status_update_template(self):
        request = 'gửi mail cho tôi về trạng thái hiện tại của bạn và các Agent khác. Mail tôi là nguyensimon186@gmail.com'
        salvaged = meridian_gateway._salvage_user_artifact(request, ['mail-gui'])
        lowered = salvaged.lower()
        self.assertIn('cập nhật trạng thái hiện tại của meridian', lowered)
        self.assertIn('leviathann', lowered)
        self.assertNotIn('xin lịch hẹn ngày mai', lowered)

    def test_mail_request_salvage_keeps_meeting_template_for_meeting_prompt(self):
        request = 'gửi mail cho tôi nội dung chào khách và hỏi lịch hẹn ngày mai'
        salvaged = meridian_gateway._salvage_user_artifact(request, ['mail-gui'])
        lowered = salvaged.lower()
        self.assertIn('xin lịch hẹn ngày mai', lowered)
        self.assertNotIn('cập nhật trạng thái hiện tại của meridian', lowered)

    def test_protocol_request_repairs_from_worker_payload_dict(self):
        request = (
            'hãy tạo cho tôi một protocol kéo deal im lặng quay lại trong 11 phút: gồm 3 giả thuyết, '
            '4 câu hỏi phá ngụy biện, 1 tin nhắn follow-up kéo khách trả lời, và 1 tiêu chí dừng rõ ràng.'
        )
        steps = [
            {
                'status': 'ok',
                'task_kind': 'write',
                'result': "{'protocol': {'hypotheses': ['H1', 'H2'], 'debiasing_questions': ['Q1', 'Q2'], 'follow_up_message': 'Ping khách ngay.', 'stop_rule': 'Dừng nếu không có owner.'}}",
                'warnings': [],
            }
        ]
        repaired, warnings = meridian_gateway._repair_manager_answer(
            request,
            'LLM endpoint returned HTTP 400:',
            steps,
            ['protocol-deal-hoi'],
        )
        self.assertIn('giả thuyết', repaired.lower())
        self.assertIn('câu hỏi', repaired.lower())
        self.assertIn('tiêu chí dừng', repaired.lower())
        self.assertIn('manager_response_repaired_from_best_worker_artifact', warnings)

    def test_repair_manager_answer_prefers_high_fit_worker_artifact_over_later_generic_step(self):
        request = (
            'hãy tạo cho tôi một protocol kéo deal im lặng quay lại trong 13 phút: gồm 3 giả thuyết, '
            '4 câu hỏi bóc ngụy biện, 1 tin nhắn follow-up kéo khách trả lời, và 1 tiêu chí dừng rõ ràng.'
        )
        steps = [
            {
                'agent_id': 'agent_quill',
                'status': 'ok',
                'task_kind': 'write',
                'confidence': 'high',
                'result': (
                    '**Protocol xử lý**\n\n'
                    '**Giả thuyết**\n1. H1\n2. H2\n\n'
                    '**Câu hỏi bóc tách**\n1. Q1\n2. Q2\n\n'
                    '**Tin nhắn follow-up**\nPing khách ngay.\n\n'
                    '**Tiêu chí dừng**\nDừng nếu không có owner.'
                ),
                'warnings': [],
                'citations': [],
            },
            {
                'agent_id': 'agent_atlas',
                'status': 'ok',
                'task_kind': 'research',
                'confidence': 'medium',
                'result': (
                    '**Status**\n\n'
                    'Đây là research starter dạng giả thuyết cần kiểm chứng.\n\n'
                    '**Likely buyer**\n- PMM\n\n'
                    '**What must be validated**\n- Pain\n\n'
                    '**Next move**\n- Phỏng vấn khách'
                ),
                'warnings': [],
                'citations': [],
            },
        ]
        repaired, warnings = meridian_gateway._repair_manager_answer(
            request,
            'LLM endpoint returned HTTP 400:',
            steps,
            ['protocol-deal-hoi'],
        )
        self.assertIn('giả thuyết', repaired.lower())
        self.assertIn('tiêu chí dừng', repaired.lower())
        self.assertNotIn('likely buyer', repaired.lower())
        self.assertIn('manager_response_repaired_from_best_worker_artifact', warnings)

    def test_manager_synthesis_fastpaths_bounded_scan_without_codex(self):
        steps = [
            {
                'agent_id': 'agent_atlas',
                'status': 'ok',
                'task_kind': 'research',
                'result': meridian_gateway._salvage_competitor_scan_artifact('scan đối thủ openai tuần này'),
                'warnings': [],
                'citations': [],
            },
            {
                'agent_id': 'agent_aegis',
                'status': 'ok',
                'task_kind': 'qa_gate',
                'result': 'PASS',
                'warnings': ['Fast direct QA lane used for low-latency communication skill.'],
            },
        ]
        with mock.patch.object(meridian_gateway, '_run_codex_exec', side_effect=AssertionError('should not call codex')):
            answer = meridian_gateway._manager_synthesis(
                'scan đối thủ openai tuần này',
                'web_api:test-fastpath-scan',
                steps,
                {'skills': [{'name': 'scan-doi-thu'}]},
            )
        self.assertIn('Verified findings', answer)

    def test_manager_synthesis_fastpaths_customer_research_starter_without_codex(self):
        steps = [
            {
                'agent_id': 'agent_atlas',
                'status': 'ok',
                'task_kind': 'research',
                'result': '# Meridian Paid-Customer Research Starter Pack\n\n## 1. Objective\n- Validate buyers',
                'warnings': [],
                'citations': [],
            },
            {
                'agent_id': 'agent_aegis',
                'status': 'ok',
                'task_kind': 'qa_gate',
                'result': 'PASS',
                'warnings': [
                    'No explicit timeline or resource allocation is provided for execution of research methods.',
                    'Sample size justification for surveys/interviews is not included (e.g., power analysis or margin of error calculations).',
                ],
            },
        ]
        with mock.patch.object(meridian_gateway, '_run_codex_exec', side_effect=AssertionError('should not call codex')):
            answer = meridian_gateway._manager_synthesis(
                'research khách hàng trả tiền cho Meridian',
                'web_api:test-fastpath-research',
                steps,
                {'skills': [{'name': 'research-khach-hang'}]},
            )
        self.assertIn('Likely buyer', answer)
        self.assertIn('What must be validated', answer)

    def test_manager_synthesis_fastpaths_customer_research_starter_without_qa_step(self):
        steps = [
            {
                'agent_id': 'agent_atlas',
                'status': 'ok',
                'task_kind': 'research',
                'result': (
                    '**Status**\n\nĐây là research starter dạng giả thuyết cần kiểm chứng.\n\n'
                    '**Likely buyer**\n- PMM\n\n'
                    '**What must be validated**\n- Pain\n\n'
                    '**Next move**\n- Phỏng vấn khách'
                ),
                'warnings': [],
                'citations': [],
            },
        ]
        with mock.patch.object(meridian_gateway, '_run_codex_exec', side_effect=AssertionError('should not call codex')):
            answer = meridian_gateway._manager_synthesis(
                'research khách hàng trả tiền cho Meridian',
                'web_api:test-fastpath-research-no-qa',
                steps,
                {'skills': [{'name': 'research-khach-hang'}]},
            )
        self.assertIn('Likely buyer', answer)
        self.assertIn('What must be validated', answer)

    def test_delivery_contributors_snapshot_marks_best_fit_and_final_artifact_match(self):
        request = (
            'hãy tạo cho tôi một protocol kéo deal im lặng quay lại trong 13 phút: gồm 3 giả thuyết, '
            '4 câu hỏi bóc ngụy biện, 1 tin nhắn follow-up kéo khách trả lời, và 1 tiêu chí dừng rõ ràng.'
        )
        final_artifact = (
            '**Protocol xử lý**\n\n'
            '**Giả thuyết**\n1. H1\n2. H2\n\n'
            '**Câu hỏi bóc tách**\n1. Q1\n2. Q2\n\n'
            '**Tin nhắn follow-up**\nPing khách ngay.\n\n'
            '**Tiêu chí dừng**\nDừng nếu không có owner.'
        )
        contributors = meridian_gateway._delivery_contributors_snapshot(
            [
                {
                    'agent_id': 'agent_quill',
                    'role': 'Writer',
                    'task_kind': 'write',
                    'status': 'ok',
                    'result': final_artifact,
                    'confidence': 'high',
                    'citations': [],
                    'warnings': [],
                },
                {
                    'agent_id': 'agent_atlas',
                    'role': 'Research',
                    'task_kind': 'research',
                    'status': 'ok',
                    'result': (
                        '**Status**\n\n'
                        'Đây là research starter dạng giả thuyết cần kiểm chứng.\n\n'
                        '**Likely buyer**\n- PMM\n\n'
                        '**What must be validated**\n- Pain\n\n'
                        '**Next move**\n- Phỏng vấn khách'
                    ),
                    'confidence': 'medium',
                    'citations': [],
                    'warnings': [],
                },
            ],
            request_text=request,
            skill_names=['protocol-deal-hoi'],
            final_artifact=final_artifact,
        )
        quill = next(item for item in contributors if item['economy_key'] == 'quill')
        atlas = next(item for item in contributors if item['economy_key'] == 'atlas')
        self.assertTrue(quill['best_fit_contributor'])
        self.assertTrue(quill['matches_final_artifact'])
        self.assertGreater(quill['artifact_fit_score'], atlas['artifact_fit_score'])

    def test_score_user_session_delivery_rewards_primary_writer_over_generic_support(self):
        request = (
            'hãy tạo cho tôi một protocol kéo deal im lặng quay lại trong 13 phút: gồm 3 giả thuyết, '
            '4 câu hỏi bóc ngụy biện, 1 tin nhắn follow-up kéo khách trả lời, và 1 tiêu chí dừng rõ ràng.'
        )
        final_artifact = (
            '**Protocol xử lý**\n\n'
            '**Giả thuyết**\n1. H1\n2. H2\n\n'
            '**Câu hỏi bóc tách**\n1. Q1\n2. Q2\n\n'
            '**Tin nhắn follow-up**\nPing khách ngay.\n\n'
            '**Tiêu chí dừng**\nDừng nếu không có owner.'
        )
        delivery_event = {
            'event_id': 'evt-protocol-score',
            'status': 'success',
            'artifact_source': 'manager_response',
            'request_text': request,
            'text': final_artifact,
            'skills_used': ['protocol-deal-hoi'],
            'contributors': [
                {
                    'economy_key': 'quill',
                    'task_kind': 'write',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 62,
                    'artifact_matches_shape': True,
                    'matches_final_artifact': True,
                    'citation_count': 0,
                    'confidence_bonus': 4,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': True,
                },
                {
                    'economy_key': 'atlas',
                    'task_kind': 'research',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 12,
                    'artifact_matches_shape': False,
                    'matches_final_artifact': False,
                    'citation_count': 0,
                    'confidence_bonus': 2,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': False,
                },
                {
                    'economy_key': 'aegis',
                    'task_kind': 'qa_gate',
                    'status': 'ok',
                    'usable_artifact': False,
                    'qa_pass': True,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': -8,
                    'artifact_matches_shape': False,
                    'matches_final_artifact': False,
                    'citation_count': 0,
                    'confidence_bonus': 0,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': False,
                },
            ],
        }
        ledger = {
            'agents': {
                'main': {'reputation_units': 90, 'authority_units': 90},
                'quill': {'reputation_units': 90, 'authority_units': 90},
                'atlas': {'reputation_units': 90, 'authority_units': 90},
                'aegis': {'reputation_units': 90, 'authority_units': 90},
            }
        }
        txs = []
        state = {'scored_events': {}, 'scored_fingerprints': {}, 'agent_outcomes': {}, 'court_actions': {}}
        with mock.patch.object(meridian_gateway, 'load_session_events', return_value={'events': [delivery_event]}):
            with mock.patch.object(meridian_gateway, 'accounting_load_ledger', return_value=ledger):
                with mock.patch.object(meridian_gateway, 'accounting_save_ledger'):
                    with mock.patch.object(meridian_gateway, 'accounting_append_tx', side_effect=lambda item: txs.append(item)):
                        with mock.patch.object(meridian_gateway, '_load_user_session_score_state', return_value=state):
                            with mock.patch.object(meridian_gateway, '_save_user_session_score_state'):
                                with mock.patch.object(meridian_gateway, '_apply_user_session_court_actions', return_value=[]):
                                    summary = meridian_gateway._score_user_session_delivery(
                                        'web_api:protocol-score',
                                        'evt-protocol-score',
                                    )
        self.assertIsNotNone(summary)
        self.assertIn('quill', summary['agents'])
        self.assertGreater(summary['agents']['quill']['rep_delta'], 0)
        self.assertGreater(summary['agents']['quill']['auth_delta'], 0)
        self.assertNotIn('atlas', summary['agents'])

    def test_score_user_session_delivery_rewards_cited_best_fit_researcher(self):
        final_artifact = (
            '**Status**\n\n'
            'Đây là research starter dạng giả thuyết cần kiểm chứng.\n\n'
            '**Likely buyer**\n- PMM\n\n'
            '**What must be validated**\n- Pain\n\n'
            '**Next move**\n- Phỏng vấn khách'
        )
        delivery_event = {
            'event_id': 'evt-research-score',
            'status': 'success',
            'artifact_source': 'manager_response',
            'request_text': 'research khách hàng cho Meridian',
            'text': final_artifact,
            'skills_used': ['research-khach-hang'],
            'contributors': [
                {
                    'economy_key': 'atlas',
                    'task_kind': 'research',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 58,
                    'artifact_matches_shape': True,
                    'matches_final_artifact': True,
                    'citation_count': 2,
                    'confidence_bonus': 4,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': True,
                },
                {
                    'economy_key': 'quill',
                    'task_kind': 'write',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 18,
                    'artifact_matches_shape': False,
                    'matches_final_artifact': False,
                    'citation_count': 0,
                    'confidence_bonus': 2,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': False,
                },
            ],
        }
        ledger = {
            'agents': {
                'main': {'reputation_units': 90, 'authority_units': 90},
                'quill': {'reputation_units': 90, 'authority_units': 90},
                'atlas': {'reputation_units': 90, 'authority_units': 90},
            }
        }
        state = {'scored_events': {}, 'scored_fingerprints': {}, 'agent_outcomes': {}, 'court_actions': {}}
        with mock.patch.object(meridian_gateway, 'load_session_events', return_value={'events': [delivery_event]}):
            with mock.patch.object(meridian_gateway, 'accounting_load_ledger', return_value=ledger):
                with mock.patch.object(meridian_gateway, 'accounting_save_ledger'):
                    with mock.patch.object(meridian_gateway, 'accounting_append_tx'):
                        with mock.patch.object(meridian_gateway, '_load_user_session_score_state', return_value=state):
                            with mock.patch.object(meridian_gateway, '_save_user_session_score_state'):
                                with mock.patch.object(meridian_gateway, '_apply_user_session_court_actions', return_value=[]):
                                    summary = meridian_gateway._score_user_session_delivery(
                                        'web_api:research-score',
                                        'evt-research-score',
                                    )
        self.assertIsNotNone(summary)
        self.assertGreater(summary['agents']['atlas']['rep_delta'], summary['agents']['quill']['rep_delta'])
        self.assertGreater(summary['agents']['atlas']['auth_delta'], summary['agents']['quill']['auth_delta'])

    def test_score_user_session_delivery_keeps_partial_credit_for_usable_research_input(self):
        delivery_event = {
            'event_id': 'evt-research-partial-credit',
            'status': 'partial',
            'artifact_source': 'worker_artifact',
            'request_text': 'research khách hàng cho Meridian',
            'text': '**Status**\n\nĐây là research starter dạng giả thuyết cần kiểm chứng.',
            'skills_used': ['research-khach-hang'],
            'contributors': [
                {
                    'economy_key': 'atlas',
                    'task_kind': 'research',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 25,
                    'artifact_matches_shape': False,
                    'matches_final_artifact': False,
                    'citation_count': 0,
                    'confidence_bonus': 0,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': False,
                },
                {
                    'economy_key': 'quill',
                    'task_kind': 'write',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': True,
                    'warnings': ['quill_output_drift_rewritten_to_user_artifact'],
                    'artifact_fit_score': 58,
                    'artifact_matches_shape': True,
                    'matches_final_artifact': True,
                    'citation_count': 0,
                    'confidence_bonus': 0,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 1,
                    'best_fit_contributor': True,
                },
            ],
        }
        ledger = {
            'agents': {
                'main': {'reputation_units': 90, 'authority_units': 90},
                'quill': {'reputation_units': 90, 'authority_units': 90},
                'atlas': {'reputation_units': 90, 'authority_units': 90},
            }
        }
        state = {'scored_events': {}, 'scored_fingerprints': {}, 'agent_outcomes': {}, 'court_actions': {}}
        with mock.patch.object(meridian_gateway, 'load_session_events', return_value={'events': [delivery_event]}):
            with mock.patch.object(meridian_gateway, 'accounting_load_ledger', return_value=ledger):
                with mock.patch.object(meridian_gateway, 'accounting_save_ledger'):
                    with mock.patch.object(meridian_gateway, 'accounting_append_tx'):
                        with mock.patch.object(meridian_gateway, '_load_user_session_score_state', return_value=state):
                            with mock.patch.object(meridian_gateway, '_save_user_session_score_state'):
                                with mock.patch.object(meridian_gateway, '_apply_user_session_court_actions', return_value=[]):
                                    summary = meridian_gateway._score_user_session_delivery(
                                        'web_api:research-partial-credit',
                                        'evt-research-partial-credit',
                                    )
        self.assertIsNotNone(summary)
        self.assertIn('atlas', summary['agents'])
        self.assertGreaterEqual(summary['agents']['atlas']['rep_delta'], 1)

    def test_score_user_session_delivery_rewards_successful_output_memory_owner(self):
        delivery_event = {
            'event_id': 'evt-memory-supported-score',
            'status': 'success',
            'artifact_source': 'manager_response',
            'request_text': 'research khách hàng cho Meridian',
            'text': '**Status**\n\nĐây là research starter dạng giả thuyết cần kiểm chứng.',
            'skills_used': ['research-khach-hang'],
            'memory_entries': [
                {
                    'key': 'delivery/udf_old_research',
                    'heading': 'Successful output: research-khach-hang',
                    'category': 'successful_output',
                    'fit_score': 41,
                    'memory_value_score': 5,
                    'origin_agent': 'atlas',
                    'source_skill_names': ['research-khach-hang'],
                    'source_quality_status': 'success',
                }
            ],
            'contributors': [
                {
                    'economy_key': 'main',
                    'task_kind': 'manage',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 44,
                    'artifact_matches_shape': True,
                    'matches_final_artifact': True,
                    'citation_count': 0,
                    'confidence_bonus': 0,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': True,
                }
            ],
        }
        ledger = {
            'agents': {
                'main': {'reputation_units': 90, 'authority_units': 90},
                'atlas': {'reputation_units': 90, 'authority_units': 90},
            }
        }
        state = {'scored_events': {}, 'scored_fingerprints': {}, 'agent_outcomes': {}, 'court_actions': {}}
        with mock.patch.object(meridian_gateway, 'load_session_events', return_value={'events': [delivery_event]}):
            with mock.patch.object(meridian_gateway, 'accounting_load_ledger', return_value=ledger):
                with mock.patch.object(meridian_gateway, 'accounting_save_ledger'):
                    with mock.patch.object(meridian_gateway, 'accounting_append_tx'):
                        with mock.patch.object(meridian_gateway, '_load_user_session_score_state', return_value=state):
                            with mock.patch.object(meridian_gateway, '_save_user_session_score_state'):
                                with mock.patch.object(meridian_gateway, '_apply_user_session_court_actions', return_value=[]):
                                    summary = meridian_gateway._score_user_session_delivery(
                                        'web_api:memory-supported-score',
                                        'evt-memory-supported-score',
                                    )
        self.assertIsNotNone(summary)
        self.assertIn('atlas', summary['agents'])
        self.assertGreaterEqual(summary['agents']['atlas']['rep_delta'], 3)
        self.assertGreaterEqual(summary['agents']['atlas']['auth_delta'], 2)
        self.assertIn('memory_recall_supported_delivery_supporting', summary['agents']['atlas']['reasons'])

    def test_score_user_session_delivery_rewards_primary_memory_recall_more_strongly(self):
        delivery_event = {
            'event_id': 'evt-memory-primary-score',
            'status': 'success',
            'artifact_source': 'manager_response',
            'request_text': 'research khách hàng trả tiền cho Meridian thêm lần nữa để tái dùng pattern',
            'text': '**Status**\n\nĐây là research starter dạng giả thuyết cần kiểm chứng.',
            'skills_used': ['research-khach-hang'],
            'memory_entries': [
                {
                    'key': 'delivery/udf_primary_research',
                    'heading': 'Successful output: research-khach-hang',
                    'category': 'successful_output',
                    'fit_score': 122,
                    'memory_value_score': 5,
                    'origin_agent': 'atlas',
                    'source_skill_names': ['research-khach-hang'],
                    'source_quality_status': 'success',
                }
            ],
            'contributors': [
                {
                    'economy_key': 'main',
                    'task_kind': 'manage',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 44,
                    'artifact_matches_shape': True,
                    'matches_final_artifact': True,
                    'citation_count': 0,
                    'confidence_bonus': 0,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': True,
                },
                {
                    'economy_key': 'atlas',
                    'task_kind': 'research',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 25,
                    'artifact_matches_shape': False,
                    'matches_final_artifact': False,
                    'citation_count': 0,
                    'confidence_bonus': 0,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': True,
                }
            ],
        }
        ledger = {
            'agents': {
                'main': {'reputation_units': 90, 'authority_units': 90},
                'atlas': {'reputation_units': 90, 'authority_units': 90},
            }
        }
        state = {'scored_events': {}, 'scored_fingerprints': {}, 'agent_outcomes': {}, 'court_actions': {}}
        with mock.patch.object(meridian_gateway, 'load_session_events', return_value={'events': [delivery_event]}):
            with mock.patch.object(meridian_gateway, 'accounting_load_ledger', return_value=ledger):
                with mock.patch.object(meridian_gateway, 'accounting_save_ledger'):
                    with mock.patch.object(meridian_gateway, 'accounting_append_tx'):
                        with mock.patch.object(meridian_gateway, '_load_user_session_score_state', return_value=state):
                            with mock.patch.object(meridian_gateway, '_save_user_session_score_state'):
                                with mock.patch.object(meridian_gateway, '_apply_user_session_court_actions', return_value=[]):
                                    summary = meridian_gateway._score_user_session_delivery(
                                        'web_api:memory-primary-score',
                                        'evt-memory-primary-score',
                                    )
        self.assertIsNotNone(summary)
        self.assertIn('atlas', summary['agents'])
        self.assertGreaterEqual(summary['agents']['atlas']['rep_delta'], 5)
        self.assertGreaterEqual(summary['agents']['atlas']['auth_delta'], 3)
        self.assertIn('memory_recall_supported_delivery_primary', summary['agents']['atlas']['reasons'])

    def test_score_user_session_delivery_rewards_trust_evidence_support_and_creation(self):
        delivery_event = {
            'event_id': 'evt-trust-score',
            'status': 'success',
            'artifact_source': 'manager_response',
            'request_text': 'soạn security questionnaire cho Meridian AI governance và data retention',
            'text': (
                '**Status**\nDraft.\n\n'
                '**Approved evidence**\n- Existing governance note.\n\n'
                '**Draft answers**\n- Retention answer pending.\n\n'
                '**Open gaps**\n- Missing subprocessor list.\n\n'
                '**Next move**\n- Escalate unresolved proof.'
            ),
            'skills_used': ['security-questionnaire'],
            'evidence_entries': [
                {
                    'key': 'trust/questionnaire/old',
                    'heading': 'Approved questionnaire answer pack',
                    'kind': 'questionnaire_answer_pack',
                    'fit_score': 82,
                    'approval_status': 'approved',
                    'origin_agent': 'atlas',
                    'origin_task_kind': 'research',
                    'topic_tags': ['ai_governance'],
                    'source_skill_names': ['security-questionnaire'],
                }
            ],
            'contributors': [
                {
                    'economy_key': 'quill',
                    'task_kind': 'write',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 58,
                    'artifact_matches_shape': True,
                    'matches_final_artifact': True,
                    'citation_count': 0,
                    'confidence_bonus': 2,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': True,
                },
                {
                    'economy_key': 'atlas',
                    'task_kind': 'research',
                    'status': 'ok',
                    'usable_artifact': True,
                    'qa_pass': False,
                    'qa_fail': False,
                    'drift_rewritten': False,
                    'warnings': [],
                    'artifact_fit_score': 32,
                    'artifact_matches_shape': False,
                    'matches_final_artifact': False,
                    'citation_count': 1,
                    'confidence_bonus': 1,
                    'hard_blocker_count': 0,
                    'runtime_failure_count': 0,
                    'recoverable_gap_count': 0,
                    'informational_warning_count': 0,
                    'best_fit_contributor': False,
                },
            ],
        }
        trust_update = {
            'history_type': 'trust_evidence_update',
            'evidence_entries': [
                {
                    'key': 'trust/questionnaire/new',
                    'heading': 'Approved questionnaire answer pack',
                    'kind': 'questionnaire_answer_pack',
                    'approval_status': 'approved',
                    'origin_agent': 'quill',
                    'origin_task_kind': 'write',
                    'topic_tags': ['data_retention'],
                    'source_skill_names': ['security-questionnaire'],
                }
            ],
        }
        ledger = {
            'agents': {
                'main': {'reputation_units': 90, 'authority_units': 90},
                'atlas': {'reputation_units': 90, 'authority_units': 90},
                'quill': {'reputation_units': 90, 'authority_units': 90},
            }
        }
        state = {'scored_events': {}, 'scored_fingerprints': {}, 'agent_outcomes': {}, 'court_actions': {}}
        with mock.patch.object(meridian_gateway, 'load_session_events', return_value={'events': [delivery_event, trust_update]}):
            with mock.patch.object(meridian_gateway, 'accounting_load_ledger', return_value=ledger):
                with mock.patch.object(meridian_gateway, 'accounting_save_ledger'):
                    with mock.patch.object(meridian_gateway, 'accounting_append_tx'):
                        with mock.patch.object(meridian_gateway, '_load_user_session_score_state', return_value=state):
                            with mock.patch.object(meridian_gateway, '_save_user_session_score_state'):
                                with mock.patch.object(meridian_gateway, '_apply_user_session_court_actions', return_value=[]):
                                    summary = meridian_gateway._score_user_session_delivery(
                                        'web_api:trust-score',
                                        'evt-trust-score',
                                    )
        self.assertIsNotNone(summary)
        self.assertIn('atlas', summary['agents'])
        self.assertIn('quill', summary['agents'])
        self.assertIn('trust_evidence_supported_delivery_primary', summary['agents']['atlas']['reasons'])
        self.assertIn('trust_evidence_written_questionnaire_answer_pack', summary['agents']['quill']['reasons'])


if __name__ == '__main__':
    unittest.main()
