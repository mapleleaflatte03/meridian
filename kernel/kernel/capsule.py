"""
Institution-owned state capsule -- isolation boundary for governed institutions.

Each institution owns a capsule: a directory containing all of its governance
state (ledger, revenue, authority queue, court records, metering, transactions,
policies, phase state).  The capsule is the unit of multi-tenant isolation.

When org_id is None, paths resolve to the legacy shared economy/ directory
for backward compatibility with single-tenant deployments.

The founding institution's capsule can be aliased to economy/ via
register_capsule_alias() so that capsule_path(founding_org_id, ...) and
capsule_path(None, ...) resolve to the same file -- preventing split-brain.
"""

import json
import os

# -- Path layout -------------------------------------------------------------
# Capsules live under <workspace>/capsules/<org_id>/
# The economy/ directory at workspace root is the "default capsule" for
# single-tenant backward compatibility.

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_WORKSPACE = os.path.dirname(_THIS_DIR)
ECONOMY_DIR = os.path.join(_WORKSPACE, 'economy')
CAPSULES_DIR = os.path.join(_WORKSPACE, 'capsules')
ORGS_FILE = os.path.join(_THIS_DIR, 'organizations.json')

# Files every capsule contains
CAPSULE_FILES = (
    'ledger.json',
    'revenue.json',
    'authority_queue.json',
    'court_records.json',
    'commitments.json',
    'cases.json',
    'warrants.json',
    'federation_inbox.json',
    '.federation_inbox.lock',
    'federated_execution_jobs.json',
    '.federated_execution_jobs.lock',
    'federation_handoff_queue.json',
    '.federation_handoff_queue.lock',
    'federation_handoff_dispatch_queue.json',
    '.federation_handoff_dispatch_queue.lock',
    'payout_plan_preview_queue.json',
    '.payout_plan_preview_queue.lock',
    'payout_plan_approval_candidate_queue.json',
    '.payout_plan_approval_candidate_queue.lock',
    'subscriptions.json',
    'subscriptions.json.bak',
    '.subscriptions.lock',
    '.accounting.lock',
    'owner_ledger.json',
    'wallets.json',
    'treasury_accounts.json',
    'maintainers.json',
    'contributors.json',
    'payout_proposals.json',
    'funding_sources.json',
    'metering.jsonl',
    'transactions.jsonl',
    'policies.json',
    'phase_state.json',
)

# -- Alias registry ----------------------------------------------------------
# Maps org_id -> directory for institutions whose capsule is not under
# capsules/.  The founding org typically aliases to ECONOMY_DIR so that
# capsule_path(founding_org_id, f) == capsule_path(None, f).

_CAPSULE_ALIASES = {}


def register_capsule_alias(org_id, directory):
    """Register a custom capsule directory for an institution.

    Used for the founding org whose state lives in economy/ rather than
    capsules/<org_id>/.  After registration, capsule_path(org_id, ...) and
    capsule_path(None, ...) resolve to the same files.
    """
    _CAPSULE_ALIASES[org_id] = os.path.abspath(directory)


def unregister_capsule_alias(org_id):
    """Remove a capsule alias.  No-op if not registered."""
    _CAPSULE_ALIASES.pop(org_id, None)


def _load_orgs():
    if not os.path.exists(ORGS_FILE):
        return {}
    with open(ORGS_FILE) as f:
        return json.load(f).get('organizations', {})


def _legacy_alias_candidates():
    if not os.path.exists(os.path.join(ECONOMY_DIR, 'ledger.json')):
        return []
    orgs = _load_orgs()
    if not orgs:
        return []
    unscoped = [
        oid for oid in orgs
        if not os.path.isdir(os.path.join(CAPSULES_DIR, oid))
    ]
    return unscoped if len(unscoped) == 1 else []


def _maybe_auto_alias_legacy_org(org_id):
    """Alias the founding legacy org to economy/ when safe.

    Tranche A keeps the founding institution's state in economy/ to avoid
    split-brain during cutover. This helper auto-registers that alias when:
    - the org exists in organizations.json
    - the org does not yet have a dedicated capsule directory
    - exactly one org in the registry lacks a capsule directory
    - the legacy economy ledger exists
    """
    if org_id is None or org_id in _CAPSULE_ALIASES:
        return

    if not os.path.exists(os.path.join(ECONOMY_DIR, 'ledger.json')):
        return

    candidate_dir = os.path.join(CAPSULES_DIR, org_id)
    if os.path.isdir(candidate_dir):
        return

    if org_id in _legacy_alias_candidates():
        register_capsule_alias(org_id, ECONOMY_DIR)


# -- Path resolution ---------------------------------------------------------

def capsule_path(org_id, filename):
    """Resolve a state file path for an institution.

    Resolution order:
      1. org_id is None  -> economy/<filename>  (legacy default)
      2. org_id in alias registry -> <alias_dir>/<filename>
      3. otherwise -> capsules/<org_id>/<filename>
    """
    if org_id is None:
        return os.path.join(ECONOMY_DIR, filename)
    _maybe_auto_alias_legacy_org(org_id)
    if org_id in _CAPSULE_ALIASES:
        return os.path.join(_CAPSULE_ALIASES[org_id], filename)
    return os.path.join(CAPSULES_DIR, org_id, filename)


def capsule_dir(org_id):
    """Return the capsule directory for an institution (or ECONOMY_DIR if None)."""
    if org_id is None:
        return ECONOMY_DIR
    _maybe_auto_alias_legacy_org(org_id)
    if org_id in _CAPSULE_ALIASES:
        return _CAPSULE_ALIASES[org_id]
    return os.path.join(CAPSULES_DIR, org_id)


def ensure_capsule(org_id):
    """Create the capsule directory for *org_id* if it does not exist.

    Returns the capsule directory path.  Does nothing for org_id=None
    (legacy mode) or aliased orgs (directory already exists).
    """
    if org_id is None:
        return ECONOMY_DIR
    _maybe_auto_alias_legacy_org(org_id)
    if org_id in _CAPSULE_ALIASES:
        return _CAPSULE_ALIASES[org_id]
    target = os.path.join(CAPSULES_DIR, org_id)
    os.makedirs(target, exist_ok=True)
    return target


# -- Capsule lifecycle -------------------------------------------------------

_EMPTY_LEDGER = {
    'version': 1,
    'schema': 'meridian-kernel-economy-v1',
    'updatedAt': '',
    'agents': {},
    'treasury': {
        'cash_usd': 0.0,
        'reserve_floor_usd': 50.0,
        'total_revenue_usd': 0.0,
        'support_received_usd': 0.0,
        'owner_capital_contributed_usd': 0.0,
        'expenses_recorded_usd': 0.0,
        'owner_draws_usd': 0.0,
    },
    'bonus_pool': {'available_usd': 0.0},
    'epoch': {'number': 0, 'started_at': '', 'auth_decay_per_epoch': 5},
    'transactions': [],
}

_EMPTY_REVENUE = {'clients': {}, 'orders': {}, 'receivables_usd': 0.0}

_EMPTY_AUTHORITY_QUEUE = {
    'pending_approvals': {},
    'delegations': {},
    'kill_switch': {'engaged': False, 'reason': '', 'engaged_by': '', 'engaged_at': ''},
}

_EMPTY_COURT_RECORDS = {'violations': {}, 'appeals': {}}
_EMPTY_COMMITMENTS = {
    'commitments': {},
    'states': ['proposed', 'accepted', 'rejected', 'breached', 'settled'],
}
_EMPTY_CASES = {
    'cases': {},
    'states': ['open', 'stayed', 'resolved'],
    'claim_types': [
        'non_delivery',
        'fraudulent_proof',
        'breach_of_commitment',
        'invalid_settlement_notice',
        'misrouted_execution',
    ],
}
_EMPTY_WARRANTS = {
    'warrants': {},
    'action_classes': [
        'routine_internal',
        'budget_spend',
        'payout_execution',
        'cross_institution_commitment',
        'sanction_execution',
        'federated_execution',
    ],
    'risk_classes': ['low', 'moderate', 'high', 'critical'],
    'court_review_states': ['auto_issued', 'pending_review', 'approved', 'stayed', 'revoked'],
    'execution_states': ['ready', 'executed'],
}
_EMPTY_FEDERATION_INBOX = {
    'version': 1,
    'updatedAt': '',
    'entries': {},
    'states': ['received', 'processed'],
    '_meta': {
        'service_scope': 'institution_owned_service',
        'bound_org_id': '',
    },
}
_EMPTY_FEDERATED_EXECUTION_JOBS = {
    'version': 1,
    'updatedAt': '',
    'jobs': {},
    'states': [
        'pending_local_warrant',
        'ready',
        'executed',
        'blocked',
        'rejected',
    ],
    '_meta': {
        'service_scope': 'institution_owned_service',
        'bound_org_id': '',
    },
}
_EMPTY_SUBSCRIPTIONS = {
    'subscribers': {},
    'delivery_log': [],
    'updatedAt': '',
    '_meta': {
        'service_scope': 'institution_owned_service',
        'bound_org_id': '',
        'internal_test_ids': [],
    },
}
_EMPTY_OWNER_LEDGER = {
    'version': 1,
    'owner': '',
    'created_at': '',
    'capital_contributed_usd': 0.0,
    'expenses_paid_usd': 0.0,
    'reimbursements_received_usd': 0.0,
    'draws_taken_usd': 0.0,
    'entries': [],
    '_meta': {
        'service_scope': 'institution_owned_service',
        'bound_org_id': '',
    },
}
_EMPTY_WALLETS = {
    'wallets': {},
    'verification_levels': {
        '0': {'label': 'observed_only', 'description': 'Seen on-chain, no ownership proof', 'payout_eligible': False},
        '1': {'label': 'linked', 'description': 'Owner claims ownership, no crypto proof', 'payout_eligible': False},
        '2': {'label': 'exchange_linked', 'description': 'Exchange deposit screen, NOT self-custody', 'payout_eligible': False},
        '3': {'label': 'self_custody_verified', 'description': 'SIWE signature or equivalent', 'payout_eligible': True},
        '4': {'label': 'multisig_controlled', 'description': 'Safe or similar multisig', 'payout_eligible': True},
    },
}
_EMPTY_TREASURY_ACCOUNTS = {
    'accounts': {},
    'transfer_policy': {
        'requires_owner_approval': True,
        'must_maintain_reserve': True,
        'audit_required': True,
    },
}
_EMPTY_MAINTAINERS = {
    'maintainers': {},
    'roles': {
        'bdfl': 'Benevolent Dictator For Life -- final authority on project direction and treasury',
        'core': 'Core maintainer with merge rights and payout eligibility',
        'maintainer': 'Active maintainer with review and triage rights',
    },
}
_EMPTY_CONTRIBUTORS = {
    'contributors': {},
    'contribution_types': [
        'code',
        'documentation',
        'security_report',
        'bug_report',
        'design',
        'vertical_example',
        'test_coverage',
        'review',
        'community',
    ],
    'registration_requirements': {
        'github_account': True,
        'signed_commits': False,
        'payout_wallet_level': 3,
        'notes': 'Contributors register by submitting accepted PRs. Payout eligibility requires a Level 3+ verified wallet.',
    },
}
_EMPTY_PAYOUT_PROPOSALS = {
    'proposals': {},
    'state_machine': {
        'states': ['draft', 'submitted', 'under_review', 'approved', 'dispute_window', 'executed', 'rejected', 'cancelled'],
        'transitions': {
            'draft': ['submitted', 'cancelled'],
            'submitted': ['under_review', 'rejected', 'cancelled'],
            'under_review': ['approved', 'rejected'],
            'approved': ['dispute_window'],
            'dispute_window': ['executed', 'rejected'],
            'executed': [],
            'rejected': [],
            'cancelled': [],
        },
        'dispute_window_hours': 72,
        'notes': 'Proposals require evidence of contribution, a reviewer, and owner approval. 72-hour dispute window between approval and execution.',
    },
    'proposal_schema': {
        'id': 'string -- unique proposal ID',
        'contributor_id': 'string -- references contributors.json',
        'amount_usd': 'number -- payout amount',
        'currency': 'string -- USDC or other',
        'contribution_type': 'string -- from contribution_types list',
        'evidence': {
            'pr_urls': ['list of PR URLs'],
            'commit_hashes': ['list of commit hashes'],
            'issue_refs': ['list of issue references'],
            'description': 'string -- summary of contribution',
        },
        'recipient_wallet_id': 'string -- references wallets.json, must be Level 3+',
        'proposed_by': 'string -- who created the proposal',
        'reviewed_by': 'string -- who reviewed',
        'approved_by': 'string -- who approved (must be owner or delegated authority)',
        'status': 'string -- from state_machine.states',
        'created_at': 'ISO 8601 timestamp',
        'updated_at': 'ISO 8601 timestamp',
        'dispute_window_ends_at': 'ISO 8601 timestamp or null',
        'executed_at': 'ISO 8601 timestamp or null',
        'tx_hash': 'string or null -- on-chain transaction hash',
    },
}
_EMPTY_FUNDING_SOURCES = {
    'sources': {},
    'source_types': {
        'owner_capital': 'Direct capital contribution from project owner',
        'github_sponsors': 'Recurring or one-time sponsorship via GitHub Sponsors',
        'direct_crypto': 'Direct stablecoin transfer from identified sponsor',
        'customer_payment': 'Payment for a product or service',
        'grant': 'Grant from a foundation or organization',
        'reimbursement': 'Reimbursement of expenses previously paid out-of-pocket',
    },
}

_CAPSULE_DEFAULTS = {
    'ledger.json': _EMPTY_LEDGER,
    'revenue.json': _EMPTY_REVENUE,
    'authority_queue.json': _EMPTY_AUTHORITY_QUEUE,
    'court_records.json': _EMPTY_COURT_RECORDS,
    'commitments.json': _EMPTY_COMMITMENTS,
    'cases.json': _EMPTY_CASES,
    'warrants.json': _EMPTY_WARRANTS,
    'federation_inbox.json': _EMPTY_FEDERATION_INBOX,
    '.federation_inbox.lock': '',
    'federated_execution_jobs.json': _EMPTY_FEDERATED_EXECUTION_JOBS,
    '.federated_execution_jobs.lock': '',
    'federation_handoff_queue.json': {
        'version': 1,
        'updatedAt': '',
        'handoff_previews': {},
        'states': [
            'previewed',
            'blocked',
            'superseded',
        ],
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': '',
        },
    },
    '.federation_handoff_queue.lock': '',
    'federation_handoff_dispatch_queue.json': {
        'version': 1,
        'updatedAt': '',
        'handoff_dispatch_records': {},
        'states': [
            'dispatchable',
            'dispatched',
            'blocked',
            'superseded',
        ],
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': '',
        },
    },
    '.federation_handoff_dispatch_queue.lock': '',
    'payout_plan_preview_queue.json': {
        'version': 1,
        'updatedAt': '',
        'payout_plan_previews': {},
        'states': [
            'previewed',
            'blocked',
            'superseded',
        ],
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': '',
        },
    },
    '.payout_plan_preview_queue.lock': '',
    'payout_plan_approval_candidate_queue.json': {
        'version': 1,
        'updatedAt': '',
        'payout_plan_approval_candidates': {},
        'states': [
            'candidate',
            'blocked',
            'superseded',
        ],
        '_meta': {
            'service_scope': 'institution_owned_service',
            'bound_org_id': '',
        },
    },
    '.payout_plan_approval_candidate_queue.lock': '',
    'subscriptions.json': _EMPTY_SUBSCRIPTIONS,
    'subscriptions.json.bak': _EMPTY_SUBSCRIPTIONS,
    '.subscriptions.lock': '',
    '.accounting.lock': '',
    'owner_ledger.json': _EMPTY_OWNER_LEDGER,
    'wallets.json': _EMPTY_WALLETS,
    'treasury_accounts.json': _EMPTY_TREASURY_ACCOUNTS,
    'maintainers.json': _EMPTY_MAINTAINERS,
    'contributors.json': _EMPTY_CONTRIBUTORS,
    'payout_proposals.json': _EMPTY_PAYOUT_PROPOSALS,
    'funding_sources.json': _EMPTY_FUNDING_SOURCES,
    'policies.json': {'policies': []},
    'phase_state.json': {},
}


def init_capsule(org_id, ledger_template=None):
    """Initialize a new capsule with empty state files.

    Creates the capsule directory and writes initial state for all files.
    Uses *ledger_template* if provided; otherwise uses a minimal empty ledger.
    Raises FileExistsError if the capsule already has a ledger.json.
    Returns the capsule directory path.
    """
    target = ensure_capsule(org_id)
    ledger_path = os.path.join(target, 'ledger.json')
    if os.path.exists(ledger_path):
        raise FileExistsError(f'Capsule already initialized: {ledger_path}')

    for filename in CAPSULE_FILES:
        path = os.path.join(target, filename)
        if filename.endswith('.jsonl'):
            # Append-only files start empty
            if not os.path.exists(path):
                open(path, 'a').close()
        else:
            if filename == 'ledger.json' and ledger_template is not None:
                data = ledger_template
            else:
                data = _CAPSULE_DEFAULTS.get(filename, {})
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)

    return target


def ledger_path(org_id=None):
    return capsule_path(org_id, 'ledger.json')


def revenue_path(org_id=None):
    return capsule_path(org_id, 'revenue.json')


def transactions_path(org_id=None):
    return capsule_path(org_id, 'transactions.jsonl')


def subscriptions_path(org_id=None):
    return capsule_path(org_id, 'subscriptions.json')


def subscriptions_backup_path(org_id=None):
    return capsule_path(org_id, 'subscriptions.json.bak')


def subscriptions_lock_path(org_id=None):
    return capsule_path(org_id, '.subscriptions.lock')


def owner_ledger_path(org_id=None):
    return capsule_path(org_id, 'owner_ledger.json')


def federation_inbox_path(org_id=None):
    return capsule_path(org_id, 'federation_inbox.json')


def federated_execution_jobs_path(org_id=None):
    return capsule_path(org_id, 'federated_execution_jobs.json')


def ensure_subscription_aliases(org_id=None):
    target = ensure_capsule(org_id)
    payload = dict(_EMPTY_SUBSCRIPTIONS)
    payload['_meta'] = dict(payload.get('_meta', {}))
    payload['_meta']['bound_org_id'] = org_id or ''
    primary = os.path.join(target, 'subscriptions.json')
    backup = os.path.join(target, 'subscriptions.json.bak')
    lock = os.path.join(target, '.subscriptions.lock')
    if not os.path.exists(primary):
        with open(primary, 'w') as f:
            json.dump(payload, f, indent=2)
    if not os.path.exists(backup):
        with open(backup, 'w') as f:
            json.dump(payload, f, indent=2)
    if not os.path.exists(lock):
        open(lock, 'a').close()
    return {
        'subscriptions': primary,
        'subscriptions_backup': backup,
        'subscriptions_lock': lock,
    }


def ensure_accounting_aliases(org_id=None):
    target = ensure_capsule(org_id)
    payload = dict(_EMPTY_OWNER_LEDGER)
    payload['_meta'] = dict(payload.get('_meta', {}))
    payload['_meta']['bound_org_id'] = org_id or ''
    owner = os.path.join(target, 'owner_ledger.json')
    if not os.path.exists(owner):
        with open(owner, 'w') as f:
            json.dump(payload, f, indent=2)
    return {
        'owner_ledger': owner,
    }


def ensure_federation_inbox_aliases(org_id=None):
    target = ensure_capsule(org_id)
    payload = dict(_EMPTY_FEDERATION_INBOX)
    payload['_meta'] = dict(payload.get('_meta', {}))
    payload['_meta']['bound_org_id'] = org_id or ''
    inbox = os.path.join(target, 'federation_inbox.json')
    lock = os.path.join(target, '.federation_inbox.lock')
    if not os.path.exists(inbox):
        with open(inbox, 'w') as f:
            json.dump(payload, f, indent=2)
    if not os.path.exists(lock):
        open(lock, 'a').close()
    return {
        'federation_inbox': inbox,
        'federation_inbox_lock': lock,
    }


def list_capsules():
    """Return org_ids with real capsule directories plus the legacy aliased org."""
    dirs = []
    if os.path.isdir(CAPSULES_DIR):
        dirs = [
            d for d in os.listdir(CAPSULES_DIR)
            if os.path.isdir(os.path.join(CAPSULES_DIR, d))
        ]
    ids = set(dirs)
    ids.update(_CAPSULE_ALIASES.keys())
    ids.update(_legacy_alias_candidates())
    return sorted(ids)
