#!/usr/bin/env python3
"""
On-device Verifiable Agent Marketplace for Meridian.

Provides a bid/assign/settle lifecycle for agent task allocation
with proof receipt integration. All marketplace state is persisted
in the institution capsule.

Lifecycle:
  1. post_bid     — Agent posts a bid for a task
  2. assign_bid   — Owner assigns a bid to an agent
  3. settle_bid   — Settles an assignment with proof receipt
  4. cancel_bid   — Cancels an open/assigned bid
"""
import datetime
import hashlib
import json
import os
import uuid

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(PLATFORM_DIR, filename)


_MARKETPLACE_TAG = b'MARKETPLACE_RECEIPT_v1\x00'
BID_STATUSES = ('open', 'assigned', 'settled', 'cancelled')


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _marketplace_path(org_id=None):
    return capsule_path(org_id, 'marketplace.json')


def _load_marketplace(org_id=None):
    path = _marketplace_path(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'bids': {}, 'assignments': {}, 'settlements': {}, 'updatedAt': _now()}


def _save_marketplace(data, org_id=None):
    data['updatedAt'] = _now()
    path = _marketplace_path(org_id)
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _receipt_hash(bid_id, agent_id, task_description, amount_usd):
    """Compute a domain-separated receipt hash for a marketplace action."""
    h = hashlib.sha256()
    h.update(_MARKETPLACE_TAG)
    h.update(bid_id.encode())
    h.update(agent_id.encode())
    h.update(task_description.encode())
    h.update(str(amount_usd).encode())
    return h.hexdigest()


def post_bid(
    agent_id,
    task_description,
    amount_usd,
    org_id=None,
    action_ids=None,
):
    """Post a bid for a task."""
    data = _load_marketplace(org_id)
    bid_id = f'bid_{uuid.uuid4().hex[:8]}'

    receipt = _receipt_hash(bid_id, agent_id, task_description, amount_usd)
    data['bids'][bid_id] = {
        'id': bid_id,
        'agent_id': agent_id,
        'task_description': task_description,
        'amount_usd': float(amount_usd),
        'status': 'open',
        'receipt_hash': receipt,
        'action_ids': action_ids or [],
        'created_at': _now(),
        'assigned_at': None,
        'settled_at': None,
    }
    _save_marketplace(data, org_id)
    return bid_id, receipt


def assign_bid(bid_id, assigned_by, org_id=None):
    """Assign a bid to the posting agent."""
    data = _load_marketplace(org_id)
    bid = data['bids'].get(bid_id)
    if not bid:
        raise ValueError(f'Bid not found: {bid_id}')
    if bid['status'] != 'open':
        raise ValueError(f'Bid {bid_id} is not open (status={bid["status"]})')

    bid['status'] = 'assigned'
    bid['assigned_at'] = _now()
    bid['assigned_by'] = assigned_by

    assignment_id = f'asgn_{uuid.uuid4().hex[:8]}'
    data['assignments'][assignment_id] = {
        'id': assignment_id,
        'bid_id': bid_id,
        'agent_id': bid['agent_id'],
        'assigned_by': assigned_by,
        'created_at': _now(),
    }
    _save_marketplace(data, org_id)
    return assignment_id


def settle_bid(bid_id, proof_receipt, settled_by, org_id=None):
    """Settle an assigned bid with a proof receipt."""
    data = _load_marketplace(org_id)
    bid = data['bids'].get(bid_id)
    if not bid:
        raise ValueError(f'Bid not found: {bid_id}')
    if bid['status'] != 'assigned':
        raise ValueError(f'Bid {bid_id} is not assigned (status={bid["status"]})')

    bid['status'] = 'settled'
    bid['settled_at'] = _now()

    settlement_id = f'stl_{uuid.uuid4().hex[:8]}'
    # Compute settlement receipt hash
    settle_hash = hashlib.sha256()
    settle_hash.update(b'MARKETPLACE_SETTLE_v1\x00')
    settle_hash.update(bid_id.encode())
    settle_hash.update(bid['receipt_hash'].encode())
    settle_hash.update(proof_receipt.encode())
    settlement_receipt = settle_hash.hexdigest()

    data['settlements'][settlement_id] = {
        'id': settlement_id,
        'bid_id': bid_id,
        'agent_id': bid['agent_id'],
        'amount_usd': bid['amount_usd'],
        'proof_receipt': proof_receipt,
        'settlement_receipt': settlement_receipt,
        'settled_by': settled_by,
        'action_ids': bid.get('action_ids', []),
        'created_at': _now(),
    }
    _save_marketplace(data, org_id)
    return settlement_id, settlement_receipt


def cancel_bid(bid_id, cancelled_by, reason='', org_id=None):
    """Cancel an open or assigned bid."""
    data = _load_marketplace(org_id)
    bid = data['bids'].get(bid_id)
    if not bid:
        raise ValueError(f'Bid not found: {bid_id}')
    if bid['status'] not in ('open', 'assigned'):
        raise ValueError(f'Bid {bid_id} cannot be cancelled (status={bid["status"]})')

    bid['status'] = 'cancelled'
    bid['cancelled_at'] = _now()
    bid['cancelled_by'] = cancelled_by
    bid['cancel_reason'] = reason
    _save_marketplace(data, org_id)


def get_bids(status=None, agent_id=None, org_id=None):
    """List bids, optionally filtered by status and/or agent."""
    data = _load_marketplace(org_id)
    bids = list(data['bids'].values())
    if status:
        bids = [b for b in bids if b['status'] == status]
    if agent_id:
        bids = [b for b in bids if b['agent_id'] == agent_id]
    return bids


def get_settlements(org_id=None):
    """List all settlements."""
    data = _load_marketplace(org_id)
    return list(data['settlements'].values())


def marketplace_status(org_id=None):
    """Return marketplace status for the /api/status block."""
    data = _load_marketplace(org_id)
    bids = data.get('bids', {})
    open_bids = sum(1 for b in bids.values() if b['status'] == 'open')
    assigned = sum(1 for b in bids.values() if b['status'] == 'assigned')
    settled = len(data.get('settlements', {}))
    mode = 'active' if (bids or settled) else 'ready'
    return {
        'mode': mode,
        'open_bids': open_bids,
        'active_assignments': assigned,
        'settled_count': settled,
    }
