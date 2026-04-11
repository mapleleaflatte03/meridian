#!/usr/bin/env python3
"""
Lightweight Role-Based Access Control for Meridian institutions.

Roles (highest to lowest privilege):
  owner    — Full court/treasury/admin access, institution lifecycle
  admin    — Court actions, agent management, treasury reads, federation
  operator — Run agents, view dashboards, propose payouts
  member   — Vote on proposals, file appeals, request approvals
  viewer   — Read-only access to public surfaces

Permission model:
  Each role inherits all permissions of lower roles.
  Specific path-level overrides live in app.py WORKSPACE_MUTATION_ROLE_REQUIREMENTS.
"""

ROLE_HIERARCHY = {
    'owner': 5,
    'admin': 4,
    'operator': 3,
    'member': 2,
    'viewer': 1,
}

# Capability-based permissions per role
ROLE_CAPABILITIES = {
    'owner': {
        'treasury_write', 'treasury_read', 'court_admin', 'court_read',
        'agent_admin', 'agent_run', 'agent_read',
        'institution_admin', 'institution_read',
        'federation_admin', 'federation_read',
        'payout_execute', 'payout_approve', 'payout_propose',
        'admission_admin', 'vote', 'appeal',
    },
    'admin': {
        'treasury_read', 'court_admin', 'court_read',
        'agent_admin', 'agent_run', 'agent_read',
        'institution_read',
        'federation_admin', 'federation_read',
        'payout_propose', 'payout_approve',
        'vote', 'appeal',
    },
    'operator': {
        'treasury_read', 'court_read',
        'agent_run', 'agent_read',
        'institution_read',
        'federation_read',
        'payout_propose',
        'vote', 'appeal',
    },
    'member': {
        'court_read',
        'agent_read',
        'institution_read',
        'vote', 'appeal',
    },
    'viewer': {
        'institution_read',
        'agent_read',
    },
}


def role_level(role: str) -> int:
    """Return numeric privilege level for a role."""
    return ROLE_HIERARCHY.get(role, 0)


def has_minimum_role(user_role: str, required_role: str) -> bool:
    """Check if user_role meets or exceeds required_role."""
    return role_level(user_role) >= role_level(required_role)


def has_capability(role: str, capability: str) -> bool:
    """Check if role has a specific capability."""
    caps = ROLE_CAPABILITIES.get(role, set())
    return capability in caps


def get_capabilities(role: str) -> set:
    """Return all capabilities for a role."""
    return set(ROLE_CAPABILITIES.get(role, set()))


def get_user_role(org: dict, user_id: str) -> str | None:
    """Look up user's role within an institution."""
    for member in org.get('members', []):
        if member.get('user_id') == user_id:
            return member.get('role')
    return None


def enforce_capability(role: str, capability: str) -> None:
    """Raise PermissionError if role lacks capability."""
    if not has_capability(role, capability):
        raise PermissionError(
            f'Role {role!r} lacks capability {capability!r}'
        )


def permission_summary(role: str) -> dict:
    """Return a machine-readable permission summary for a role."""
    caps = get_capabilities(role)
    return {
        'role': role,
        'level': role_level(role),
        'capabilities': sorted(caps),
        'can_run_agents': 'agent_run' in caps,
        'can_admin_court': 'court_admin' in caps,
        'can_write_treasury': 'treasury_write' in caps,
        'can_vote': 'vote' in caps,
    }
