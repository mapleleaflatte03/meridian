#!/usr/bin/env python3
"""
Ready-to-use Hands (agents) for Meridian institutions.

Each Hand is a pre-configured agent template that can be provisioned
into any institution's agent registry with a single call.

Available Hands:
  1. Researcher      — Deep web + codebase research
  2. Twitter Manager  — Social media content pipeline
  3. Daily Brief      — Morning digest compiler
  4. Treasury Auditor — Financial compliance checker
  5. Code Reviewer    — Automated code review agent
"""
import os
import sys

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PLATFORM_DIR)

from agent_registry import register_agent, load_registry


HAND_TEMPLATES = {
    'researcher': {
        'name': 'Researcher',
        'role': 'analyst',
        'purpose': 'Deep research across web sources, codebases, and documentation. Synthesizes findings into structured briefs with citations.',
        'scopes': ['research', 'read', 'analyze', 'web_search'],
        'budget': {'max_per_run_usd': 0.80, 'max_per_day_usd': 8.00, 'max_per_month_usd': 160.00},
    },
    'twitter_manager': {
        'name': 'TwitterManager',
        'role': 'writer',
        'purpose': 'Content pipeline for X/Twitter: drafts threads, schedules posts, monitors engagement, and manages brand voice consistency.',
        'scopes': ['write', 'read', 'social_publish', 'schedule'],
        'budget': {'max_per_run_usd': 0.30, 'max_per_day_usd': 3.00, 'max_per_month_usd': 60.00},
    },
    'daily_brief': {
        'name': 'DailyBrief',
        'role': 'compressor',
        'purpose': 'Compiles morning digest from treasury state, court activity, agent performance, and external signals into a structured operator briefing.',
        'scopes': ['read', 'compress', 'summarize', 'deliver'],
        'budget': {'max_per_run_usd': 0.25, 'max_per_day_usd': 1.00, 'max_per_month_usd': 30.00},
    },
    'treasury_auditor': {
        'name': 'TreasuryAuditor',
        'role': 'verifier',
        'purpose': 'Automated financial compliance: verifies ledger integrity, flags anomalous transactions, checks reserve floor adherence, and produces audit reports.',
        'scopes': ['verify', 'read', 'audit', 'treasury_read'],
        'budget': {'max_per_run_usd': 0.40, 'max_per_day_usd': 4.00, 'max_per_month_usd': 80.00},
    },
    'code_reviewer': {
        'name': 'CodeReviewer',
        'role': 'qa_gate',
        'purpose': 'Automated code review: checks for security issues, style violations, test coverage gaps, and architectural conformance.',
        'scopes': ['verify', 'read', 'qa', 'code_review'],
        'budget': {'max_per_run_usd': 0.60, 'max_per_day_usd': 6.00, 'max_per_month_usd': 120.00},
    },
}


def list_hand_templates():
    """Return all available Hand templates."""
    return [
        {'key': key, **{k: v for k, v in tpl.items()}}
        for key, tpl in HAND_TEMPLATES.items()
    ]


def provision_hand(org_id: str, hand_key: str) -> dict:
    """Provision a Hand into an institution's agent registry.

    Returns the registered agent record or raises ValueError if hand_key unknown.
    """
    tpl = HAND_TEMPLATES.get(hand_key)
    if not tpl:
        raise ValueError(
            f'Unknown hand: {hand_key}. Available: {list(HAND_TEMPLATES.keys())}'
        )

    # Check if already registered for this org
    registry = load_registry()
    for agent in registry['agents'].values():
        if agent.get('org_id') == org_id and agent.get('name') == tpl['name']:
            return agent

    agent_id = register_agent(
        org_id=org_id,
        name=tpl['name'],
        role=tpl['role'],
        purpose=tpl['purpose'],
        scopes=tpl['scopes'],
        budget=tpl['budget'],
    )
    registry = load_registry()
    return registry['agents'].get(agent_id, {'id': agent_id})


def provision_all_hands(org_id: str) -> list:
    """Provision all 5 Hands into an institution. Returns list of agent records."""
    results = []
    for key in HAND_TEMPLATES:
        agent = provision_hand(org_id, key)
        results.append(agent)
    return results
