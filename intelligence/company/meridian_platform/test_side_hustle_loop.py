#!/usr/bin/env python3
"""RED tests for Slice 7: Autonomous Side Hustle Agent Loop.

Simulates an agent checking budget, ensuring no court restrictions,
bidding on a side hustle, getting assigned, and settling with proof.
"""
import os
import sys
import unittest
from unittest import mock

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS_DIR)

from agent_registry import register_agent, check_budget, set_budget, load_registry, save_registry
from court import file_violation, get_violations
from marketplace import post_bid, assign_bid, settle_bid
from treasury import load_ledger

class AutonomousSideHustleLoopTest(unittest.TestCase):
    def setUp(self):
        self.org_id = 'meridian'
        
        # Fresh in-memory state for testing
        self.registry_store = {'agents': {}}
        self.marketplace_store = {'bids': {}, 'assignments': {}, 'settlements': {}, 'disputes': {}}
        self.court_store = {'violations': {}, 'appeals': {}}
        
        # Patch registry
        self.reg_load_patcher = mock.patch('agent_registry.load_registry')
        self.reg_save_patcher = mock.patch('agent_registry.save_registry')
        self.mock_reg_load = self.reg_load_patcher.start()
        self.mock_reg_save = self.reg_save_patcher.start()
        self.mock_reg_load.return_value = self.registry_store
        def fake_reg_save(data): self.registry_store = data
        self.mock_reg_save.side_effect = fake_reg_save

        # Patch marketplace
        self.mkt_load_patcher = mock.patch('marketplace._load_marketplace')
        self.mkt_save_patcher = mock.patch('marketplace._save_marketplace')
        self.mock_mkt_load = self.mkt_load_patcher.start()
        self.mock_mkt_save = self.mkt_save_patcher.start()
        self.mock_mkt_load.return_value = self.marketplace_store
        def fake_mkt_save(data, org_id): self.marketplace_store = data
        self.mock_mkt_save.side_effect = fake_mkt_save

        # Patch court
        self.court_load_patcher = mock.patch('court._load_records')
        self.court_save_patcher = mock.patch('court._save_records')
        self.mock_court_load = self.court_load_patcher.start()
        self.mock_court_save = self.court_save_patcher.start()
        self.mock_court_load.return_value = self.court_store
        def fake_court_save(data, org_id): self.court_store = data
        self.mock_court_save.side_effect = fake_court_save

        # Create autonomous agent
        self.agent_id = register_agent(
            self.org_id, 
            name='SideHustlerBot', 
            role='executor', 
            purpose='Autonomous content generation'
        )

    def tearDown(self):
        self.reg_load_patcher.stop()
        self.reg_save_patcher.stop()
        self.mkt_load_patcher.stop()
        self.mkt_save_patcher.stop()
        self.court_load_patcher.stop()
        self.court_save_patcher.stop()

    def test_side_hustle_lifecycle_happy_path(self):
        # 1. Budget Request/Check
        cost = 0.40
        allowed, reason = check_budget(self.agent_id, cost)
        self.assertTrue(allowed, f"Expected budget allowed, got: {reason}")
        
        # 2. Governance check (No active court violations restricting work)
        violations = get_violations(agent_id=self.agent_id, status='open', org_id=self.org_id)
        self.assertEqual(len(violations), 0, "Agent should have no open violations")

        # 3. Execution/Post Bid (Agent bids on external side hustle task)
        task_desc = "Write comprehensive SEO article about Meridian"
        bid_id, receipt = post_bid(self.agent_id, task_desc, amount_usd=15.0, org_id=self.org_id)
        self.assertTrue(bid_id.startswith('bid_'))
        
        # 4. External client assigns the bid (mocking the external assignment)
        assignment_id = assign_bid(bid_id, assigned_by='external_client_01', org_id=self.org_id)
        self.assertTrue(assignment_id.startswith('asgn_'))
        
        # 5. Proof-of-Execution & Settlement (Agent earns income into Treasury)
        proof_payload = 'poge_payload_xyz_123'
        settlement_id, settle_receipt, split = settle_bid(
            bid_id, proof_receipt=proof_payload, settled_by='external_client_01', org_id=self.org_id
        )
        
        self.assertTrue(settlement_id.startswith('stl_'))
        self.assertEqual(split['total_usd'], 15.0)
        self.assertTrue('worker_usd' in split)
        self.assertTrue('royalty_usd' in split)

    def test_governance_blocks_hustle(self):
        # Simulate a critical court violation
        file_violation(self.agent_id, self.org_id, 'critical_failure', severity=6, evidence='Spammed external client')

        from side_hustle import can_hustle

        allowed, reason = can_hustle(self.agent_id, self.org_id, cost_usd=0.20)
        self.assertFalse(allowed)
        self.assertIn("violation", reason.lower())

    def test_run_side_hustle_orchestration_end_to_end(self):
        """Test the full orchestration: governance check -> bid -> assign -> settle."""
        from side_hustle import run_side_hustle

        with mock.patch('side_hustle.brain_router') as mock_br, \
             mock.patch('side_hustle.memory_graph') as mock_mg:

            mock_br.execute_manager.return_value = {
                'ok': True,
                'output_text': 'Generated blog post about AI governance',
                'model': 'grok-beta',
            }
            mock_mg.append_node.return_value = ('proof_xyz_blog_post', 1)

            # Execute full side hustle loop
            result = run_side_hustle(
                agent_id=self.agent_id,
                org_id=self.org_id,
                task_description='Generate blog post about AI governance',
                amount_usd=25.0,
                proof_receipt='proof_xyz_blog_post',
                assigned_by='external_platform',
                settled_by='external_platform',
            )

        # Verify orchestration result
        self.assertEqual(result['status'], 'settled')
        self.assertIn('bid_id', result)
        self.assertIn('assignment_id', result)
        self.assertIn('settlement_id', result)
        self.assertIn('settlement_receipt', result)
        self.assertIn('split', result)
        self.assertEqual(result['split']['total_usd'], 25.0)

    def test_run_side_hustle_blocked_by_court(self):
        """Test that orchestration fails when agent has court violations."""
        from side_hustle import run_side_hustle

        # Create blocking violation
        file_violation(self.agent_id, self.org_id, 'token_waste', severity=4, evidence='Excessive retries')

        result = run_side_hustle(
            agent_id=self.agent_id,
            org_id=self.org_id,
            task_description='Generate content',
            amount_usd=10.0,
            proof_receipt='proof_abc',
            assigned_by='client',
            settled_by='client',
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('reason', result)
        self.assertIn('violation', result['reason'].lower())

    def test_run_side_hustle_budget_blocked(self):
        """Test orchestration blocks when budget check fails."""
        from side_hustle import run_side_hustle

        # Force tiny per-run budget
        set_budget(self.agent_id, max_per_run_usd=0.05)

        result = run_side_hustle(
            agent_id=self.agent_id,
            org_id=self.org_id,
            task_description='Affiliate promotion post',
            amount_usd=10.0,
            proof_receipt='proof_affiliate',
            assigned_by='affiliate_network',
            settled_by='affiliate_network',
            estimated_cost_usd=0.20,
        )

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('budget', result.get('reason', '').lower())

    def test_run_side_hustle_includes_verifiable_proof_chain(self):
        """Settlement payload should include a verifiable receipt chain markers."""
        from side_hustle import run_side_hustle

        with mock.patch('side_hustle.brain_router') as mock_br, \
             mock.patch('side_hustle.memory_graph') as mock_mg:

            mock_br.execute_manager.return_value = {
                'ok': True,
                'output_text': 'Freelance task output',
                'model': 'grok-beta',
            }
            mock_mg.append_node.return_value = ('memory_freelance_777', 3)

            result = run_side_hustle(
                agent_id=self.agent_id,
                org_id=self.org_id,
                task_description='Freelance task execution',
                amount_usd=12.5,
                proof_receipt='proof_freelance_777',
                assigned_by='freelance_client',
                settled_by='freelance_client',
            )

        self.assertEqual(result['status'], 'settled')
        self.assertIn('proof_chain', result)
        self.assertEqual(result['proof_chain']['proof_receipt'], 'proof_freelance_777')
        self.assertEqual(result['proof_chain']['settlement_receipt'], result['settlement_receipt'])

    def test_side_hustle_status_summary_counts_settled_and_blocked(self):
        """Status summary should expose practical counters for UI/API surfaces."""
        from side_hustle import side_hustle_status

        sample_runs = [
            {'status': 'settled'},
            {'status': 'blocked'},
            {'status': 'settled'},
            {'status': 'blocked'},
            {'status': 'settled'},
        ]

        summary = side_hustle_status(sample_runs)
        self.assertEqual(summary['total_runs'], 5)
        self.assertEqual(summary['settled_runs'], 3)
        self.assertEqual(summary['blocked_runs'], 2)
        self.assertEqual(summary['success_rate'], 0.6)

    def test_run_side_hustle_executes_work_via_brain_router(self):
        """Slice 9: run_side_hustle should execute work via brain_router.execute_manager."""
        from side_hustle import run_side_hustle

        with mock.patch('side_hustle.brain_router') as mock_br, \
             mock.patch('side_hustle.memory_graph') as mock_mg:

            # Mock brain_router.execute_manager to return successful work output
            mock_br.execute_manager.return_value = {
                'ok': True,
                'output_text': 'Generated blog post content about AI governance',
                'model': 'grok-beta',
            }

            # Mock memory_graph.append_node to return hash and depth
            mock_mg.append_node.return_value = ('abc123hash', 5)

            result = run_side_hustle(
                agent_id=self.agent_id,
                org_id=self.org_id,
                task_description='Write blog post about AI governance',
                amount_usd=20.0,
                proof_receipt='proof_initial',
                assigned_by='external_client',
                settled_by='external_client',
            )

            # Verify brain_router.execute_manager was called
            mock_br.execute_manager.assert_called_once()
            call_kwargs = mock_br.execute_manager.call_args[1]
            self.assertIn('system_prompt', call_kwargs)
            self.assertIn('user_prompt', call_kwargs)
            self.assertIn('Write blog post about AI governance', call_kwargs['user_prompt'])

            # Verify memory_graph.append_node was called with execution result
            mock_mg.append_node.assert_called_once()
            mem_call_kwargs = mock_mg.append_node.call_args[1]
            self.assertEqual(mem_call_kwargs['org_id'], self.org_id)
            self.assertEqual(mem_call_kwargs['agent_id'], self.agent_id)
            self.assertIn('side_hustle_execution', mem_call_kwargs['tags'])

            # Verify result includes work output and memory hash
            self.assertEqual(result['status'], 'settled')
            self.assertIn('work_output', result)
            self.assertIn('memory_hash', result)
            self.assertEqual(result['memory_hash'], 'abc123hash')

    def test_run_side_hustle_includes_memory_hash_in_proof_chain(self):
        """Slice 9: proof_chain should include memory_hash for verifiable execution."""
        from side_hustle import run_side_hustle

        with mock.patch('side_hustle.brain_router') as mock_br, \
             mock.patch('side_hustle.memory_graph') as mock_mg:

            mock_br.execute_manager.return_value = {
                'ok': True,
                'output_text': 'Content output',
                'model': 'grok-beta',
            }
            mock_mg.append_node.return_value = ('memory_xyz789', 10)

            result = run_side_hustle(
                agent_id=self.agent_id,
                org_id=self.org_id,
                task_description='Generate content',
                amount_usd=15.0,
                proof_receipt='proof_base',
                assigned_by='client',
                settled_by='client',
            )

            # Verify proof_chain includes memory_hash
            self.assertIn('proof_chain', result)
            self.assertIn('memory_hash', result['proof_chain'])
            self.assertEqual(result['proof_chain']['memory_hash'], 'memory_xyz789')

    def test_run_side_hustle_execution_failure_returns_execution_failed(self):
        """Slice 9: When brain_router returns ok=False, side hustle must not settle."""
        from side_hustle import run_side_hustle

        with mock.patch('side_hustle.brain_router') as mock_br, \
             mock.patch('side_hustle.memory_graph') as mock_mg:

            mock_br.execute_manager.return_value = {
                'ok': False,
                'stderr': 'key pool exhausted without successful response',
                'output_text': '',
            }

            result = run_side_hustle(
                agent_id=self.agent_id,
                org_id=self.org_id,
                task_description='Task that fails',
                amount_usd=10.0,
                proof_receipt='proof_fail',
                assigned_by='client',
                settled_by='client',
            )

            self.assertEqual(result['status'], 'execution_failed')
            self.assertIn('reason', result)
            self.assertIn('bid_id', result)
            # memory_graph should NOT have been called
            mock_mg.append_node.assert_not_called()

    def test_run_side_hustle_uses_provider_agnostic_model(self):
        """Slice 9: brain_router must be called with empty model (config-driven)."""
        from side_hustle import run_side_hustle

        with mock.patch('side_hustle.brain_router') as mock_br, \
             mock.patch('side_hustle.memory_graph') as mock_mg:

            mock_br.execute_manager.return_value = {
                'ok': True,
                'output_text': 'Provider-agnostic output',
                'model': 'resolved-by-config',
            }
            mock_mg.append_node.return_value = ('hash_agnostic', 0)

            run_side_hustle(
                agent_id=self.agent_id,
                org_id=self.org_id,
                task_description='Agnostic task',
                amount_usd=5.0,
                proof_receipt='proof_agnostic',
                assigned_by='client',
                settled_by='client',
            )

            call_kwargs = mock_br.execute_manager.call_args[1]
            # model must be empty string — config-driven, never hardcoded
            self.assertEqual(call_kwargs['model'], '')

    def test_capsule_resolves_slug_meridian_to_real_org_id(self):
        """Slice 9: capsule.resolve_org_id must accept slug 'meridian'."""
        from capsule import resolve_org_id, default_org_id

        founding_id = default_org_id()
        self.assertIsNotNone(founding_id, "Founding org must exist in organizations.json")

        # Slug resolution
        resolved = resolve_org_id('meridian')
        self.assertEqual(resolved, founding_id)

        # Direct org_id
        resolved_direct = resolve_org_id(founding_id)
        self.assertEqual(resolved_direct, founding_id)

        # None defaults to founding
        resolved_none = resolve_org_id(None)
        self.assertEqual(resolved_none, founding_id)

        # Unknown org rejected
        with self.assertRaises(ValueError):
            resolve_org_id('unknown_org_xyz')

    def test_ensure_hustle_agent_returns_existing_agent(self):
        """Slice 10: ensure_hustle_agent must return existing agent_id unchanged."""
        from side_hustle import ensure_hustle_agent

        result = ensure_hustle_agent(self.agent_id, self.org_id)
        self.assertEqual(result, self.agent_id)

    def test_ensure_hustle_agent_registers_missing_agent(self):
        """Slice 10: ensure_hustle_agent must auto-register unknown agent."""
        from side_hustle import ensure_hustle_agent

        new_id = ensure_hustle_agent('nonexistent_worker', self.org_id)
        self.assertNotEqual(new_id, 'nonexistent_worker')
        self.assertTrue(new_id.startswith('agent_'))

        # Verify agent now exists in registry
        registry = self.registry_store
        self.assertIn(new_id, registry['agents'])
        self.assertEqual(registry['agents'][new_id]['role'], 'executor')

    def test_run_side_hustle_auto_registers_unknown_agent(self):
        """Slice 10: run_side_hustle with unknown agent_id registers it automatically."""
        from side_hustle import run_side_hustle

        with mock.patch('side_hustle.brain_router') as mock_br, \
             mock.patch('side_hustle.memory_graph') as mock_mg:

            mock_br.execute_manager.return_value = {
                'ok': True,
                'output_text': 'Auto-registered agent output',
                'model': 'config-driven',
            }
            mock_mg.append_node.return_value = ('hash_auto', 0)

            result = run_side_hustle(
                agent_id='brand_new_worker',
                org_id=self.org_id,
                task_description='Task from unknown agent',
                amount_usd=5.0,
                proof_receipt='proof_auto',
                assigned_by='operator',
                settled_by='operator',
            )

            self.assertEqual(result['status'], 'settled')
            # The new agent should exist in registry now
            found = False
            for aid, agent in self.registry_store['agents'].items():
                if agent.get('name') == 'brand_new_worker':
                    found = True
                    break
            self.assertTrue(found, "Auto-registered agent not found in registry")

    def test_execution_failed_status_not_counted_as_settled(self):
        """Slice 10: execution_failed must not be counted as settled in status summary."""
        from side_hustle import side_hustle_status

        runs = [
            {'status': 'settled'},
            {'status': 'execution_failed'},
            {'status': 'blocked'},
            {'status': 'settled'},
        ]
        summary = side_hustle_status(runs)
        self.assertEqual(summary['settled_runs'], 2)
        self.assertEqual(summary['blocked_runs'], 1)
        self.assertEqual(summary['total_runs'], 4)

    def test_dashboard_js_uses_real_agent_id(self):
        """Slice 10: meridian.js must not use demo_agent_01."""
        js_path = os.path.join(
            os.path.dirname(THIS_DIR),
            'www', 'assets', 'meridian.js'
        )
        with open(js_path, 'r') as f:
            js_content = f.read()
        self.assertNotIn('demo_agent_01', js_content,
                         "meridian.js still references fake demo_agent_01")
        self.assertNotIn('public_demo_user', js_content,
                         "meridian.js still references fake public_demo_user")

if __name__ == '__main__':
    unittest.main()
