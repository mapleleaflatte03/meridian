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
from decimal import Decimal, ROUND_HALF_UP

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(PLATFORM_DIR, filename)


_MARKETPLACE_TAG = b'MARKETPLACE_RECEIPT_v1\x00'
BID_STATUSES = ('open', 'assigned', 'settled', 'disputed', 'cancelled')
DISPUTE_STATUSES = ('open', 'resolved')
DISPUTE_DECISIONS = ('stay', 'refund', 'release')
_USD_QUANT = Decimal('0.0001')


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _marketplace_path(org_id=None):
    return capsule_path(org_id, 'marketplace.json')


def _load_marketplace(org_id=None):
    path = _marketplace_path(org_id)
    if os.path.exists(path):
        with open(path) as f:
            payload = json.load(f)
            payload.setdefault('bids', {})
            payload.setdefault('assignments', {})
            payload.setdefault('settlements', {})
            payload.setdefault('disputes', {})
            payload.setdefault('updatedAt', _now())
            return payload
    return {'bids': {}, 'assignments': {}, 'settlements': {}, 'disputes': {}, 'updatedAt': _now()}


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


def _quantize_usd(value):
    return float(Decimal(str(value)).quantize(_USD_QUANT, rounding=ROUND_HALF_UP))


def _deterministic_split(amount_usd, royalty_share=0.10):
    total = Decimal(str(amount_usd))
    royalty_ratio = Decimal(str(royalty_share))
    royalty = (total * royalty_ratio).quantize(_USD_QUANT, rounding=ROUND_HALF_UP)
    worker = (total - royalty).quantize(_USD_QUANT, rounding=ROUND_HALF_UP)
    # Enforce deterministic closure so split sum always equals settled total.
    correction = total.quantize(_USD_QUANT, rounding=ROUND_HALF_UP) - (worker + royalty)
    worker = (worker + correction).quantize(_USD_QUANT, rounding=ROUND_HALF_UP)
    return {
        'worker_usd': float(worker),
        'royalty_usd': float(royalty),
        'total_usd': float(total.quantize(_USD_QUANT, rounding=ROUND_HALF_UP)),
    }


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
        'amount_usd': _quantize_usd(amount_usd),
        'status': 'open',
        'receipt_hash': receipt,
        'action_ids': action_ids or [],
        'created_at': _now(),
        'assigned_at': None,
        'settled_at': None,
        'dispute_id': None,
    }
    _save_marketplace(data, org_id)
    return bid_id, receipt


def assign_bid(bid_id, assigned_by, org_id=None, reservation_id=''):
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
        'reservation_id': str(reservation_id or '').strip() or None,
        'created_at': _now(),
        'status': 'assigned',
    }
    _save_marketplace(data, org_id)
    return assignment_id


def settle_bid(
    bid_id,
    proof_receipt,
    settled_by,
    org_id=None,
    royalty_share=0.10,
    reservation_id='',
):
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
    split = _deterministic_split(bid['amount_usd'], royalty_share=royalty_share)
    # Compute settlement receipt hash
    settle_hash = hashlib.sha256()
    settle_hash.update(b'MARKETPLACE_SETTLE_v1\x00')
    settle_hash.update(bid_id.encode())
    settle_hash.update(bid['receipt_hash'].encode())
    settle_hash.update(proof_receipt.encode())
    settle_hash.update(json.dumps(split, sort_keys=True).encode())
    settlement_receipt = settle_hash.hexdigest()

    data['settlements'][settlement_id] = {
        'id': settlement_id,
        'bid_id': bid_id,
        'agent_id': bid['agent_id'],
        'amount_usd': split['total_usd'],
        'split': split,
        'royalty_share': float(royalty_share),
        'proof_receipt': proof_receipt,
        'settlement_receipt': settlement_receipt,
        'settled_by': settled_by,
        'reservation_id': str(reservation_id or '').strip() or None,
        'action_ids': bid.get('action_ids', []),
        'created_at': _now(),
        'status': 'settled',
    }
    _save_marketplace(data, org_id)
    return settlement_id, settlement_receipt, split


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


def open_dispute(bid_id, opened_by, reason='', org_id=None, action_ids=None):
    data = _load_marketplace(org_id)
    bid = data['bids'].get(bid_id)
    if not bid:
        raise ValueError(f'Bid not found: {bid_id}')
    if bid['status'] not in ('assigned', 'settled'):
        raise ValueError(f'Bid {bid_id} cannot be disputed (status={bid["status"]})')
    dispute_id = f'dsp_{uuid.uuid4().hex[:8]}'
    dispute = {
        'id': dispute_id,
        'bid_id': bid_id,
        'status': 'open',
        'opened_by': opened_by,
        'reason': reason or 'operator_dispute',
        'decision': None,
        'resolved_by': None,
        'court_decision_ref': '',
        'action_ids': action_ids or [],
        'created_at': _now(),
        'resolved_at': None,
    }
    bid['status'] = 'disputed'
    bid['dispute_id'] = dispute_id
    data['disputes'][dispute_id] = dispute
    _save_marketplace(data, org_id)
    return dispute_id


def resolve_dispute(
    dispute_id,
    decision,
    resolved_by,
    org_id=None,
    court_decision_ref='',
    note='',
):
    normalized = str(decision or '').strip().lower()
    if normalized not in DISPUTE_DECISIONS:
        raise ValueError(f'Invalid dispute decision: {decision}')
    data = _load_marketplace(org_id)
    dispute = data.get('disputes', {}).get(dispute_id)
    if not dispute:
        raise ValueError(f'Dispute not found: {dispute_id}')
    if dispute.get('status') != 'open':
        raise ValueError(f'Dispute {dispute_id} is already {dispute.get("status")}')
    bid_id = dispute.get('bid_id')
    bid = data.get('bids', {}).get(bid_id)
    if not bid:
        raise ValueError(f'Bid not found for dispute: {bid_id}')

    dispute['decision'] = normalized
    dispute['court_decision_ref'] = str(court_decision_ref or '').strip()
    dispute['note'] = note

    if normalized == 'stay':
        # 'stay' halts proceedings — dispute remains open for future resolution.
        # The bid stays 'disputed' because the dispute is still active.
        _save_marketplace(data, org_id)
        return dict(dispute)

    dispute['status'] = 'resolved'
    dispute['resolved_by'] = resolved_by
    dispute['resolved_at'] = _now()

    if normalized == 'refund':
        bid['status'] = 'cancelled'
        bid['cancel_reason'] = note or 'dispute_refund'
    elif normalized == 'release':
        bid['status'] = 'settled'

    # Mirror decision into latest settlement when present.
    for settlement in data.get('settlements', {}).values():
        if settlement.get('bid_id') == bid_id:
            settlement['status'] = 'refunded' if normalized == 'refund' else settlement.get('status', 'settled')
            settlement['dispute_id'] = dispute_id
            settlement['court_decision_ref'] = dispute.get('court_decision_ref', '')

    _save_marketplace(data, org_id)
    return dict(dispute)


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


def get_disputes(status=None, org_id=None):
    data = _load_marketplace(org_id)
    disputes = list(data.get('disputes', {}).values())
    if status:
        disputes = [d for d in disputes if d.get('status') == status]
    return disputes


def marketplace_snapshot(org_id=None):
    data = _load_marketplace(org_id)
    status = marketplace_status(org_id)
    return {
        # Keep backward compatibility for existing clients that read nested status.
        'status': status,
        # Flatten status fields for contracts that expect top-level counters.
        'mode': status.get('mode'),
        'open_bids': status.get('open_bids', 0),
        'active_assignments': status.get('active_assignments', 0),
        'settled_count': status.get('settled_count', 0),
        'open_disputes': status.get('open_disputes', 0),
        'bids': list(data.get('bids', {}).values()),
        'assignments': list(data.get('assignments', {}).values()),
        'settlements': list(data.get('settlements', {}).values()),
        'disputes': list(data.get('disputes', {}).values()),
    }


def marketplace_status(org_id=None):
    """Return marketplace status for the /api/status block."""
    data = _load_marketplace(org_id)
    bids = data.get('bids', {})
    open_bids = sum(1 for b in bids.values() if b['status'] == 'open')
    assigned = sum(1 for b in bids.values() if b['status'] == 'assigned')
    settled = len(data.get('settlements', {}))
    disputes_open = sum(1 for d in data.get('disputes', {}).values() if d.get('status') == 'open')
    mode = 'active' if (bids or settled) else 'ready'
    return {
        'mode': mode,
        'open_bids': open_bids,
        'active_assignments': assigned,
        'settled_count': settled,
        'open_disputes': disputes_open,
    }
