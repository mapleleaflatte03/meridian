#!/usr/bin/env python3
"""
Revenue operating layer — clients, orders, receivables.
State machine: proposed -> accepted -> in_progress -> delivered -> invoiced -> paid
Owner draws, reimbursements, and capital contributions are deployment-specific
treasury actions handled outside this revenue module.

This module also provides org-aware, idempotent settlement helpers for:
- externally settled customer payments
- externally settled support contributions
- payment evidence lookups against non-reclassified customer payments

Usage:
  python3 revenue.py client add --name "Client Name" --contact "email or chat"
  python3 revenue.py client list
  python3 revenue.py order create --client <id> --product <product> --amount <usd> [--note "..."]
  python3 revenue.py order advance <order_id>
  python3 revenue.py order reject <order_id> --note "reason"
  python3 revenue.py order list [--status <status>]
  python3 revenue.py order show <order_id>
  python3 revenue.py summary
"""
import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import uuid

ECONOMY_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(ECONOMY_DIR)
KERNEL_DIR = os.path.join(ROOT_DIR, 'kernel')
PAYMENT_LOCK = os.path.join(ECONOMY_DIR, '.payment_integrity.lock')

if KERNEL_DIR not in sys.path:
    sys.path.insert(0, KERNEL_DIR)

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(ECONOMY_DIR, filename)


def _revenue_path(org_id=None):
    return capsule_path(org_id, 'revenue.json')


def _ledger_path(org_id=None):
    return capsule_path(org_id, 'ledger.json')


def _tx_path(org_id=None):
    return capsule_path(org_id, 'transactions.jsonl')


def _missing_org_error(org_id):
    raise SystemExit(
        f"ERROR: institution '{org_id}' is not initialized. Run quickstart.py --init-only or bootstrap the capsule first."
    )


def _require_readable(path, org_id=None):
    if org_id and not os.path.exists(path):
        _missing_org_error(org_id)
    return path


def _require_writable(path, org_id=None):
    if org_id and not os.path.isdir(os.path.dirname(path)):
        _missing_org_error(org_id)
    return path

ORDER_STATES = ['proposed', 'accepted', 'in_progress', 'delivered', 'invoiced', 'paid']
ADVANCE_MAP  = {s: ORDER_STATES[i+1] for i, s in enumerate(ORDER_STATES[:-1])}
NON_CUSTOMER_PRODUCTS = {'owner-capital-contribution'}

def now_ts():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _write_json_atomic(path, data):
    directory = os.path.dirname(path) or '.'
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + '.', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@contextlib.contextmanager
def payment_lock():
    os.makedirs(ECONOMY_DIR, exist_ok=True)
    with open(PAYMENT_LOCK, 'a+') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def stable_short_id(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:8]

def load_revenue(org_id=None):
    path = _require_readable(_revenue_path(org_id), org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'clients': {}, 'orders': {}, 'receivables_usd': 0.0, 'updatedAt': now_ts()}

def save_revenue(data, org_id=None):
    data['updatedAt'] = now_ts()
    _write_json_atomic(_require_writable(_revenue_path(org_id), org_id), data)

def load_ledger(org_id=None):
    with open(_require_readable(_ledger_path(org_id), org_id)) as f:
        return json.load(f)

def save_ledger(data, org_id=None):
    data['updatedAt'] = now_ts()
    _write_json_atomic(_require_writable(_ledger_path(org_id), org_id), data)

def append_tx(entry, org_id=None):
    entry['ts'] = now_ts()
    with open(_require_writable(_tx_path(org_id), org_id), 'a') as f:
        f.write(json.dumps(entry) + '\n')


def load_transactions(org_id=None):
    path = _require_readable(_tx_path(org_id), org_id)
    if not os.path.exists(path):
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def is_customer_order(order):
    return order.get('product') not in NON_CUSTOMER_PRODUCTS and order.get('payment_kind') != 'owner_capital'


def customer_client_ids(revenue_data):
    return {
        order['client']
        for order in revenue_data.get('orders', {}).values()
        if is_customer_order(order)
    }


def customer_orders(revenue_data):
    return {
        oid: order
        for oid, order in revenue_data.get('orders', {}).items()
        if is_customer_order(order)
    }


def reclassified_order_ids(transactions=None, org_id=None):
    transactions = transactions if transactions is not None else load_transactions(org_id)
    return {
        tx.get('order_id')
        for tx in transactions
        if tx.get('type') == 'reclassification'
        and tx.get('corrected_type')
        and tx.get('corrected_type') != 'customer_payment'
        and tx.get('order_id')
    }


def recent_customer_payment_metrics(since_days=7, transactions=None, org_id=None):
    transactions = transactions if transactions is not None else load_transactions(org_id)
    cutoff = (
        datetime.datetime.utcnow() - datetime.timedelta(days=since_days)
    ).strftime('%Y-%m-%dT%H:%M:%SZ')
    reclassified = reclassified_order_ids(transactions, org_id=org_id)
    total = 0
    payments = 0
    revenue = 0.0
    for tx in transactions:
        if tx.get('ts', '') < cutoff:
            continue
        total += 1
        if tx.get('type') == 'customer_payment' and tx.get('order_id') not in reclassified:
            payments += 1
            revenue += tx.get('amount', 0)
    return {'total': total, 'payments': payments, 'revenue_usd': revenue}


def _ensure_processed_payment_keys(ledger):
    treasury = ledger.setdefault('treasury', {})
    keys = treasury.get('processed_payment_keys')
    if not isinstance(keys, list):
        keys = []
        treasury['processed_payment_keys'] = keys
    return keys


def _payment_tx_exists(transactions, payment_key, tx_hash='', payment_ref=''):
    for entry in transactions:
        if entry.get('type') != 'customer_payment':
            continue
        if entry.get('payment_key') == payment_key:
            return True
        if tx_hash and entry.get('tx_hash') == tx_hash:
            return True
        if payment_ref and entry.get('payment_ref') == payment_ref:
            return True
    return False


def _support_tx_exists(transactions, payment_key, tx_hash='', payment_ref=''):
    for entry in transactions:
        if entry.get('type') != 'support_contribution':
            continue
        if entry.get('payment_key') == payment_key:
            return True
        if tx_hash and entry.get('tx_hash') == tx_hash:
            return True
        if payment_ref and entry.get('payment_ref') == payment_ref:
            return True
    return False


def find_customer_payment_evidence(*, payment_ref='', tx_hash='', min_amount_usd=0.0, transactions=None, org_id=None):
    """Return the matched non-reclassified customer payment entry, or None."""
    if not payment_ref and not tx_hash:
        return None
    transactions = transactions if transactions is not None else load_transactions(org_id)
    reclassified = reclassified_order_ids(transactions, org_id=org_id)
    min_amount = float(min_amount_usd or 0.0)
    expected_key = f'ref:{payment_ref}' if payment_ref else ''
    for entry in transactions:
        if entry.get('type') != 'customer_payment':
            continue
        if entry.get('order_id') in reclassified:
            continue
        if payment_ref:
            ref_matches = (
                entry.get('payment_ref') == payment_ref
                or entry.get('payment_key') == expected_key
                or entry.get('order_id') == payment_ref
            )
            if not ref_matches:
                continue
        if tx_hash and entry.get('tx_hash') != tx_hash:
            continue
        if float(entry.get('amount', 0.0) or 0.0) + 1e-9 < min_amount:
            continue
        return entry
    return None


def customer_payment_evidence_exists(*, payment_ref='', tx_hash='', min_amount_usd=0.0, transactions=None, org_id=None):
    return find_customer_payment_evidence(
        payment_ref=payment_ref,
        tx_hash=tx_hash,
        min_amount_usd=min_amount_usd,
        transactions=transactions,
        org_id=org_id,
    ) is not None


def record_external_customer_payment(product, amount_usd, *, payment_key, client_name,
                                     client_contact, note='', tx_hash='',
                                     payment_ref='', payment_source='external',
                                     org_id=None):
    """Idempotently record an externally settled customer payment."""
    if not payment_key:
        raise ValueError('payment_key is required')
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('amount_usd must be greater than 0')

    with payment_lock():
        revenue_data = load_revenue(org_id)
        ledger = load_ledger(org_id)
        transactions = load_transactions(org_id)

        client_id = stable_short_id(f'client:{client_contact or client_name or payment_key}')
        order_id = stable_short_id(f'order:{product}:{payment_key}')
        now = now_ts()

        revenue_changed = False
        ledger_changed = False

        client = revenue_data['clients'].get(client_id)
        if client is None:
            revenue_data['clients'][client_id] = {
                'name': client_name,
                'contact': client_contact,
                'created_at': now,
            }
            revenue_changed = True

        order = revenue_data['orders'].get(order_id)
        if order is None:
            revenue_data['orders'][order_id] = {
                'client': client_id,
                'product': product,
                'amount_usd': amount,
                'status': 'paid',
                'note': note,
                'payment_key': payment_key,
                'payment_ref': payment_ref,
                'tx_hash': tx_hash,
                'payment_source': payment_source,
                'history': [
                    {'status': 'proposed', 'at': now},
                    {'status': 'paid', 'at': now},
                ],
                'created_at': now,
            }
            revenue_changed = True
        else:
            if abs(float(order.get('amount_usd', 0.0)) - amount) > 1e-9:
                raise ValueError(f'order {order_id} amount mismatch for {payment_key}')
            if order.get('status') != 'paid':
                order['status'] = 'paid'
                order.setdefault('history', []).append({'status': 'paid', 'at': now})
                revenue_changed = True
            for key, value in (
                ('payment_key', payment_key),
                ('payment_ref', payment_ref),
                ('tx_hash', tx_hash),
                ('payment_source', payment_source),
            ):
                if value and order.get(key) != value:
                    order[key] = value
                    revenue_changed = True
            if note and order.get('note') != note:
                order['note'] = note
                revenue_changed = True

        processed_keys = _ensure_processed_payment_keys(ledger)
        if payment_key not in processed_keys:
            treasury = ledger['treasury']
            treasury['cash_usd'] += amount
            treasury['total_revenue_usd'] = treasury.get('total_revenue_usd', 0) + amount
            processed_keys.append(payment_key)
            ledger_changed = True

        tx_exists = _payment_tx_exists(transactions, payment_key, tx_hash=tx_hash, payment_ref=payment_ref)

        if revenue_changed:
            save_revenue(revenue_data, org_id)
        if ledger_changed:
            save_ledger(ledger, org_id)
        if not tx_exists:
            append_tx({
                'type': 'customer_payment',
                'order_id': order_id,
                'amount': amount,
                'client': client_id,
                'product': product,
                'payment_key': payment_key,
                'payment_ref': payment_ref,
                'tx_hash': tx_hash,
                'payment_source': payment_source,
                'note': note,
            }, org_id)

        return {
            'client_id': client_id,
            'order_id': order_id,
            'payment_key': payment_key,
            'duplicate': not revenue_changed and not ledger_changed and tx_exists,
        }


def record_external_support_contribution(amount_usd, *, payment_key, supporter_name='',
                                         supporter_contact='', note='', tx_hash='',
                                         payment_ref='', payment_source='external_support',
                                         org_id=None):
    """Idempotently record externally received support without creating customer traction."""
    if not payment_key:
        raise ValueError('payment_key is required')
    amount = float(amount_usd)
    if amount <= 0:
        raise ValueError('amount_usd must be greater than 0')

    with payment_lock():
        ledger = load_ledger(org_id)
        transactions = load_transactions(org_id)
        treasury = ledger['treasury']
        processed_keys = _ensure_processed_payment_keys(ledger)

        ledger_changed = False
        if payment_key not in processed_keys:
            treasury['cash_usd'] += amount
            treasury['support_received_usd'] = treasury.get('support_received_usd', 0) + amount
            processed_keys.append(payment_key)
            ledger_changed = True

        tx_exists = _support_tx_exists(transactions, payment_key, tx_hash=tx_hash, payment_ref=payment_ref)
        if ledger_changed:
            save_ledger(ledger, org_id)
        if not tx_exists:
            append_tx({
                'type': 'support_contribution',
                'amount': amount,
                'payment_key': payment_key,
                'payment_ref': payment_ref,
                'tx_hash': tx_hash,
                'payment_source': payment_source,
                'supporter_name': supporter_name,
                'supporter_contact': supporter_contact,
                'note': note,
            }, org_id)

        return {
            'payment_key': payment_key,
            'duplicate': not ledger_changed and tx_exists,
        }

# ── Client management ────────────────────────────────────────────────────────

def cmd_client_add(args):
    org_id = getattr(args, 'org_id', None)
    data = load_revenue(org_id)
    cid = str(uuid.uuid4())[:8]
    data['clients'][cid] = {
        'name': args.name,
        'contact': args.contact,
        'created_at': now_ts(),
    }
    save_revenue(data, org_id)
    print(f"Client added: {cid} ({args.name})")

def cmd_client_list(args):
    data = load_revenue(getattr(args, 'org_id', None))
    if not data['clients']:
        print("No clients registered.")
        return
    for cid, c in data['clients'].items():
        print(f"  {cid}  {c['name']:<30} {c.get('contact','')}")

# ── Order state machine ──────────────────────────────────────────────────────

def cmd_order_create(args):
    org_id = getattr(args, 'org_id', None)
    data = load_revenue(org_id)
    if args.client not in data['clients']:
        print(f"ERROR: unknown client '{args.client}'"); return
    oid = str(uuid.uuid4())[:8]
    data['orders'][oid] = {
        'client':     args.client,
        'product':    args.product,
        'amount_usd': float(args.amount),
        'status':     'proposed',
        'note':       args.note or '',
        'history':    [{'status': 'proposed', 'at': now_ts()}],
        'created_at': now_ts(),
    }
    data['receivables_usd'] += float(args.amount)
    save_revenue(data, org_id)
    append_tx({'type': 'order_created', 'order_id': oid, 'amount': float(args.amount),
               'client': args.client, 'product': args.product}, org_id)
    print(f"Order created: {oid} (${args.amount} — {args.product})")

def cmd_order_advance(args):
    org_id = getattr(args, 'org_id', None)
    data = load_revenue(org_id)
    oid = args.order_id
    if oid not in data['orders']:
        print(f"ERROR: unknown order '{oid}'"); return
    order = data['orders'][oid]
    cur = order['status']
    if cur not in ADVANCE_MAP:
        print(f"ERROR: order '{oid}' is already in terminal state '{cur}'"); return
    nxt = ADVANCE_MAP[cur]
    order['status'] = nxt
    order['history'].append({'status': nxt, 'at': now_ts()})

    # When status becomes 'paid', credit treasury
    if nxt == 'paid':
        ledger = load_ledger(org_id)
        amount = order['amount_usd']
        ledger['treasury']['cash_usd'] += amount
        ledger['treasury']['total_revenue_usd'] = ledger['treasury'].get('total_revenue_usd', 0) + amount
        save_ledger(ledger, org_id)
        data['receivables_usd'] = max(0, data['receivables_usd'] - amount)
        append_tx({'type': 'customer_payment', 'order_id': oid, 'amount': amount,
                   'client': order['client'], 'product': order['product'],
                   'note': f"Order {oid} paid — treasury credited"}, org_id)
        print(f"PAID: ${amount} credited to treasury. Order {oid} complete.")
    else:
        append_tx({'type': 'order_advanced', 'order_id': oid,
                   'from': cur, 'to': nxt}, org_id)
        print(f"Order {oid}: {cur} → {nxt}")

    save_revenue(data, org_id)

def cmd_order_reject(args):
    org_id = getattr(args, 'org_id', None)
    data = load_revenue(org_id)
    oid = args.order_id
    if oid not in data['orders']:
        print(f"ERROR: unknown order '{oid}'"); return
    order = data['orders'][oid]
    order['status'] = 'rejected'
    order['history'].append({'status': 'rejected', 'at': now_ts(), 'note': args.note})
    data['receivables_usd'] = max(0, data['receivables_usd'] - order['amount_usd'])
    save_revenue(data, org_id)
    append_tx({'type': 'order_rejected', 'order_id': oid, 'note': args.note}, org_id)
    print(f"Order {oid}: REJECTED — {args.note}")

def cmd_order_list(args):
    data = load_revenue(getattr(args, 'org_id', None))
    if not data['orders']:
        print("No orders."); return
    for oid, o in data['orders'].items():
        if args.status and o['status'] != args.status:
            continue
        cname = data['clients'].get(o['client'], {}).get('name', '?')
        print(f"  {oid}  ${o['amount_usd']:<10.2f} {o['status']:<14} {o['product']:<30} client={cname}")

def cmd_order_show(args):
    data = load_revenue(getattr(args, 'org_id', None))
    if args.order_id not in data['orders']:
        print(f"ERROR: unknown order '{args.order_id}'"); return
    o = data['orders'][args.order_id]
    cname = data['clients'].get(o['client'], {}).get('name', '?')
    print(json.dumps({**o, 'id': args.order_id, 'client_name': cname}, indent=2))

# ── Summary ──────────────────────────────────────────────────────────────────
# NOTE: Owner draws, reimbursements, and capital contributions are handled by
#       deployment-specific accounting workflows. This file handles revenue
#       operations only (clients, orders, receivables).

def cmd_summary(args):
    org_id = getattr(args, 'org_id', None)
    data = load_revenue(org_id)
    ledger = load_ledger(org_id)
    t = ledger['treasury']
    orders = data.get('orders', {})
    n_by_status = {}
    for o in orders.values():
        n_by_status[o['status']] = n_by_status.get(o['status'], 0) + 1

    print(f"\n=== Revenue Summary ===")
    print(f"Treasury cash:       ${t['cash_usd']:.2f}")
    print(f"Total revenue:       ${t.get('total_revenue_usd', 0):.2f}")
    print(f"Owner capital in:    ${t.get('owner_capital_contributed_usd', 0):.2f}")
    print(f"Owner draws:         ${t.get('owner_draws_usd', 0):.2f}")
    print(f"  (Owner draw/reimburse breakdown: deployment-specific accounting workflow)")
    print(f"Reserve floor:       ${t.get('reserve_floor_usd', 50):.2f}")
    print(f"Receivables:         ${data.get('receivables_usd', 0):.2f}")
    print(f"Clients:             {len(data.get('clients', {}))}")
    print(f"Orders:              {len(orders)}")
    for status, count in sorted(n_by_status.items()):
        print(f"  {status}: {count}")

# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description='Revenue operating layer')
    sub = p.add_subparsers(dest='command')

    def add_org_arg(parser):
        parser.add_argument('--org_id', default=None,
                            help='Institution context. Defaults to the legacy founding institution.')

    # client
    csub = sub.add_parser('client').add_subparsers(dest='client_cmd')
    ca = csub.add_parser('add')
    add_org_arg(ca)
    ca.add_argument('--name', required=True)
    ca.add_argument('--contact', default='')
    cl = csub.add_parser('list')
    add_org_arg(cl)

    # order
    osub = sub.add_parser('order').add_subparsers(dest='order_cmd')
    oc = osub.add_parser('create')
    add_org_arg(oc)
    oc.add_argument('--client', required=True)
    oc.add_argument('--product', required=True)
    oc.add_argument('--amount', required=True)
    oc.add_argument('--note', default='')
    oa = osub.add_parser('advance')
    add_org_arg(oa)
    oa.add_argument('order_id')
    orj = osub.add_parser('reject')
    add_org_arg(orj)
    orj.add_argument('order_id')
    orj.add_argument('--note', default='rejected')
    ol = osub.add_parser('list')
    add_org_arg(ol)
    ol.add_argument('--status', default=None)
    osh = osub.add_parser('show')
    add_org_arg(osh)
    osh.add_argument('order_id')

    summary = sub.add_parser('summary')
    add_org_arg(summary)

    args = p.parse_args()
    if   args.command == 'client':
        if   args.client_cmd == 'add':  cmd_client_add(args)
        elif args.client_cmd == 'list': cmd_client_list(args)
        else: p.print_help()
    elif args.command == 'order':
        if   args.order_cmd == 'create':  cmd_order_create(args)
        elif args.order_cmd == 'advance': cmd_order_advance(args)
        elif args.order_cmd == 'reject':  cmd_order_reject(args)
        elif args.order_cmd == 'list':    cmd_order_list(args)
        elif args.order_cmd == 'show':    cmd_order_show(args)
        else: p.print_help()
    elif args.command == 'summary':
        cmd_summary(args)
    else:
        p.print_help()

if __name__ == '__main__':
    main()
