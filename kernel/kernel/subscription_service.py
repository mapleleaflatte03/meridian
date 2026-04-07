#!/usr/bin/env python3
"""Institution-owned subscription service for Meridian Kernel.

This module owns subscription state inside institution capsules.  It is
deliberately narrower than the live workspace-facing subscription helper:
it focuses on file-backed storage, delivery eligibility, and payment
evidence binding without depending on workspace routing.
"""
import contextlib
import datetime
import fcntl
import importlib.util
import json
import os
import tempfile
import uuid


TRIAL_DAYS = 7
PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(PLATFORM_DIR)
ECONOMY_DIR = os.path.join(WORKSPACE, 'economy')
REVENUE_PY = os.path.join(ECONOMY_DIR, 'revenue.py')
CAPSULE_PY = os.path.join(PLATFORM_DIR, 'capsule.py')

try:
    from capsule import capsule_path, ensure_capsule
except ImportError:
    _capsule_spec = importlib.util.spec_from_file_location('subscription_service_capsule', CAPSULE_PY)
    _capsule_mod = importlib.util.module_from_spec(_capsule_spec)
    _capsule_spec.loader.exec_module(_capsule_mod)
    capsule_path = _capsule_mod.capsule_path
    ensure_capsule = _capsule_mod.ensure_capsule

_revenue_spec = importlib.util.spec_from_file_location('subscription_service_revenue', REVENUE_PY)
_revenue_mod = importlib.util.module_from_spec(_revenue_spec)
_revenue_spec.loader.exec_module(_revenue_mod)

PLANS = {
    'premium-brief-monthly': {'price_usd': 9.99, 'duration_days': 30, 'type': 'recurring'},
    'premium-brief-weekly': {'price_usd': 2.99, 'duration_days': 7, 'type': 'recurring'},
    'deep-dive-single': {'price_usd': 9.99, 'duration_days': 0, 'type': 'one-time'},
    'trial': {'price_usd': 0.00, 'duration_days': TRIAL_DAYS, 'type': 'trial'},
}

PRIMARY_FILE = 'subscriptions.json'
BACKUP_FILE = 'subscriptions.json.bak'
LOCK_FILE = '.subscriptions.lock'


def now_ts():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def now_dt():
    return datetime.datetime.utcnow()


def _subscription_paths(org_id=None):
    ensure_capsule(org_id)
    return (
        capsule_path(org_id, PRIMARY_FILE),
        capsule_path(org_id, BACKUP_FILE),
        capsule_path(org_id, LOCK_FILE),
    )


def _default_subscriptions(org_id=None):
    return {
        'subscribers': {},
        'delivery_log': [],
        'updatedAt': now_ts(),
        '_meta': {
            'service_scope': 'institution_owned_subscription_service',
            'boundary_name': 'subscriptions',
            'identity_model': 'session',
            'storage_model': 'capsule_canonical',
            'bound_org_id': org_id or '',
            'internal_test_ids': [],
        },
    }


def _normalize_subscriptions(data, org_id=None):
    if not isinstance(data, dict):
        return _default_subscriptions(org_id)
    payload = dict(data)
    payload.setdefault('subscribers', {})
    payload.setdefault('delivery_log', [])
    payload.setdefault('updatedAt', now_ts())
    payload.setdefault('_meta', {})
    payload['_meta']['service_scope'] = 'institution_owned_subscription_service'
    payload['_meta']['boundary_name'] = 'subscriptions'
    payload['_meta']['identity_model'] = 'session'
    payload['_meta']['storage_model'] = 'capsule_canonical'
    payload['_meta']['bound_org_id'] = org_id or payload['_meta'].get('bound_org_id', '')
    payload['_meta'].setdefault('internal_test_ids', [])
    return payload


def _write_json_atomic(path, data):
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(path) + '.',
        suffix='.tmp',
        dir=directory,
    )
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
def _subscriptions_lock(org_id=None):
    _, _, lock_path = _subscription_paths(org_id)
    with open(lock_path, 'a+') as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def load_subscriptions(org_id=None):
    primary_path, backup_path, _ = _subscription_paths(org_id)
    for path in (primary_path, backup_path):
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path) as f:
                return _normalize_subscriptions(json.load(f), org_id)
    return _default_subscriptions(org_id)


def save_subscriptions(data, org_id=None):
    payload = _normalize_subscriptions(data, org_id)
    payload['updatedAt'] = now_ts()
    primary_path, backup_path, _ = _subscription_paths(org_id)
    with _subscriptions_lock(org_id):
        _write_json_atomic(primary_path, payload)
        _write_json_atomic(backup_path, payload)


def _payment_evidence(sub, *, org_id=None):
    if sub.get('plan') == 'trial':
        return {'type': 'trial', 'payment_ref': ''}
    payment_ref = (sub.get('payment_ref') or '').strip()
    if not payment_ref:
        return None
    return _revenue_mod.find_customer_payment_evidence(
        payment_ref=payment_ref,
        min_amount_usd=float(sub.get('price_usd', 0.0) or 0.0),
        org_id=org_id,
    )


def _payment_evidence_ok(sub, *, org_id=None):
    if sub.get('plan') == 'trial':
        return True
    evidence = _payment_evidence(sub, org_id=org_id)
    if not evidence:
        return False
    bound = sub.get('payment_evidence', {})
    if bound:
        if bound.get('order_id') and evidence.get('order_id') != bound.get('order_id'):
            return False
        if bound.get('payment_key') and evidence.get('payment_key') != bound.get('payment_key'):
            return False
        if bound.get('tx_hash') and evidence.get('tx_hash') != bound.get('tx_hash'):
            return False
    return True


def _subscription_delivery_eligible(sub, *, org_id=None, now=None):
    now = now or now_dt()
    if sub.get('status') != 'active':
        return False
    if sub.get('plan') not in ('premium-brief-monthly', 'premium-brief-weekly', 'trial', 'deep-dive-single'):
        return False
    expires_at = (sub.get('expires_at') or '').strip()
    if expires_at:
        expires = datetime.datetime.strptime(expires_at, '%Y-%m-%dT%H:%M:%SZ')
        if expires < now:
            return False
    if sub.get('plan') != 'trial' and (
        not sub.get('payment_verified', False) or not _payment_evidence_ok(sub, org_id=org_id)
    ):
        return False
    return True


def active_delivery_targets(org_id=None, *, external_only=False):
    payload = load_subscriptions(org_id)
    internal_ids = {
        str(value) for value in payload.get('_meta', {}).get('internal_test_ids', [])
    }
    targets = set()
    for telegram_id, records in payload.get('subscribers', {}).items():
        tid = str(telegram_id)
        if external_only and tid in internal_ids:
            continue
        for record in records:
            if _subscription_delivery_eligible(record, org_id=org_id):
                targets.add(tid)
                break
    return sorted(targets)


def _require_payment_evidence(payment_ref, amount_usd, *, org_id=None):
    payment_ref = (payment_ref or '').strip()
    if not payment_ref:
        raise ValueError('payment_ref is required for paid subscription verification')
    evidence = _revenue_mod.find_customer_payment_evidence(
        payment_ref=payment_ref,
        min_amount_usd=float(amount_usd or 0.0),
        org_id=org_id,
    )
    if not evidence:
        raise ValueError(
            f'no customer_payment evidence found for payment_ref={payment_ref} amount>={float(amount_usd or 0.0):.2f}'
        )
    return evidence


def _bind_payment_evidence(subscription, payment_ref=None, *, org_id=None):
    ref = (payment_ref if payment_ref is not None else subscription.get('payment_ref', '')) or ''
    evidence = _require_payment_evidence(
        ref,
        subscription.get('price_usd', 0.0),
        org_id=org_id,
    )
    subscription['payment_ref'] = ref
    subscription['payment_verified'] = True
    subscription['payment_verified_at'] = now_ts()
    subscription['payment_evidence'] = {
        'order_id': evidence.get('order_id', ''),
        'payment_key': evidence.get('payment_key', ''),
        'payment_ref': evidence.get('payment_ref', ref),
        'tx_hash': evidence.get('tx_hash', ''),
        'amount_usd': float(evidence.get('amount', 0.0) or 0.0),
    }
    return evidence


def add_subscription(telegram_id, plan='trial', *, duration_days=None,
                     payment_method=None, payment_ref=None,
                     confirm_payment=False, trial=False, email=None,
                     org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    tid = str(telegram_id or '').strip()
    if not tid:
        raise ValueError('telegram_id is required')
    plan_name = 'trial' if trial else (plan or 'trial')
    if plan_name not in PLANS:
        raise ValueError(
            f"unknown plan '{plan_name}'. Available: {', '.join(sorted(PLANS.keys()))}"
        )

    if plan_name == 'trial':
        existing = payload.get('subscribers', {}).get(tid, [])
        for record in existing:
            if record.get('plan') == 'trial':
                raise ValueError(f'telegram:{tid} already used a trial subscription')

    plan_info = PLANS[plan_name]
    duration = duration_days if duration_days is not None else plan_info['duration_days']
    expires = None
    if duration > 0:
        expires = (now_dt() + datetime.timedelta(days=duration)).strftime('%Y-%m-%dT%H:%M:%SZ')

    payment_ref = (payment_ref or '').strip()
    payment_verified = plan_name == 'trial'
    payment_verified_at = now_ts() if plan_name == 'trial' else ''
    payment_evidence = {'type': 'trial'} if plan_name == 'trial' else {}
    if plan_name != 'trial' and bool(confirm_payment):
        evidence = _require_payment_evidence(
            payment_ref,
            plan_info['price_usd'],
            org_id=org_id,
        )
        payment_verified = True
        payment_verified_at = now_ts()
        payment_evidence = {
            'order_id': evidence.get('order_id', ''),
            'payment_key': evidence.get('payment_key', ''),
            'payment_ref': evidence.get('payment_ref', payment_ref),
            'tx_hash': evidence.get('tx_hash', ''),
            'amount_usd': float(evidence.get('amount', 0.0) or 0.0),
        }

    subscription = {
        'id': str(uuid.uuid4())[:8],
        'plan': plan_name,
        'price_usd': plan_info['price_usd'],
        'started_at': now_ts(),
        'expires_at': expires,
        'status': 'active',
        'payment_method': payment_method or ('trial' if plan_name == 'trial' else 'manual'),
        'payment_ref': payment_ref,
        'payment_verified': payment_verified,
        'payment_verified_at': payment_verified_at,
        'payment_evidence': payment_evidence,
        'email': email or '',
        'created_by': actor or '',
    }
    payload.setdefault('subscribers', {}).setdefault(tid, []).append(subscription)
    save_subscriptions(payload, org_id)
    return {
        'telegram_id': tid,
        'subscription': subscription,
    }


def list_subscriptions(org_id=None, telegram_id=None, *, active_only=False):
    payload = load_subscriptions(org_id)
    if telegram_id is None:
        rows = []
        for tid, records in payload.get('subscribers', {}).items():
            for record in records:
                if active_only and record.get('status') != 'active':
                    continue
                rows.append({'telegram_id': tid, 'subscription': record})
        return rows
    tid = str(telegram_id).strip()
    records = list(payload.get('subscribers', {}).get(tid, []))
    if active_only:
        records = [record for record in records if record.get('status') == 'active']
    return records


def convert_trial_subscription(telegram_id, plan, *, payment_method=None,
                               payment_ref=None, confirm_payment=False,
                               email=None, org_id=None, actor=''):
    tid = str(telegram_id or '').strip()
    if not tid:
        raise ValueError('telegram_id is required')
    if plan not in PLANS or plan == 'trial':
        raise ValueError(f"invalid conversion plan '{plan}'. Use a paid plan.")

    payload = load_subscriptions(org_id)
    if tid not in payload.get('subscribers', {}):
        raise LookupError(f'No subscriptions for telegram:{tid}')

    had_trial = False
    for sub in payload['subscribers'][tid]:
        if sub.get('plan') == 'trial' and sub.get('status') == 'active':
            had_trial = True
            sub['status'] = 'converted'
            sub['converted_at'] = now_ts()
            sub['converted_by'] = actor or ''
            break
    if not had_trial:
        raise LookupError(f'No active trial found for telegram:{tid}')

    save_subscriptions(payload, org_id)
    result = add_subscription(
        tid,
        plan=plan,
        payment_method=payment_method,
        payment_ref=payment_ref,
        confirm_payment=confirm_payment,
        email=email,
        org_id=org_id,
        actor=actor,
    )
    payload = load_subscriptions(org_id)
    for idx, record in enumerate(payload.get('subscribers', {}).get(tid, [])):
        if record.get('id') == result['subscription']['id']:
            record['converted_from_trial'] = True
            result['subscription'] = record
            payload['subscribers'][tid][idx] = record
            break
    save_subscriptions(payload, org_id)
    return result


def check_subscription(telegram_id, *, org_id=None):
    tid = str(telegram_id or '').strip()
    if not tid:
        raise ValueError('telegram_id is required')
    payload = load_subscriptions(org_id)
    records = list(payload.get('subscribers', {}).get(tid, []))
    active = [record for record in records if record.get('status') == 'active']
    latest = records[-1] if records else None
    return {
        'telegram_id': tid,
        'found': bool(records),
        'active': bool(active),
        'eligible_for_delivery': any(
            _subscription_delivery_eligible(record, org_id=org_id)
            for record in active
        ),
        'subscription_count': len(records),
        'active_count': len(active),
        'latest_subscription': latest,
    }


def verify_payment(telegram_id, *, subscription_id=None, payment_ref=None, org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    tid = str(telegram_id or '').strip()
    if not tid:
        raise ValueError('telegram_id is required')
    if tid not in payload.get('subscribers', {}) or not payload['subscribers'][tid]:
        raise LookupError(f'No subscriptions for telegram:{tid}')

    candidates = [
        sub for sub in payload['subscribers'][tid]
        if sub.get('status') == 'active' and sub.get('plan') != 'trial'
    ]
    if subscription_id:
        candidates = [sub for sub in candidates if sub.get('id') == subscription_id]
    if not candidates:
        raise LookupError(f'No active paid subscription found for telegram:{tid}')

    target = candidates[-1]
    if payment_ref:
        target['payment_ref'] = payment_ref
    _bind_payment_evidence(
        target,
        payment_ref=target.get('payment_ref'),
        org_id=org_id,
    )
    target['payment_verified_by'] = actor or ''
    save_subscriptions(payload, org_id)
    return {
        'telegram_id': tid,
        'subscription': target,
    }


def verify_subscription_payment(telegram_id, *, subscription_id=None, payment_ref=None, org_id=None, actor=''):
    return verify_payment(
        telegram_id,
        subscription_id=subscription_id,
        payment_ref=payment_ref,
        org_id=org_id,
        actor=actor,
    )


def record_delivery(telegram_id, product, *, brief_date='', org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    entry = {
        'telegram_id': str(telegram_id).strip(),
        'product': (product or '').strip(),
        'delivered_at': now_ts(),
        'recorded_by': actor or '',
    }
    if not entry['telegram_id']:
        raise ValueError('telegram_id is required')
    if not entry['product']:
        raise ValueError('product is required')
    if brief_date:
        entry['brief_date'] = brief_date
    payload.setdefault('delivery_log', []).append(entry)
    if len(payload['delivery_log']) > 500:
        payload['delivery_log'] = payload['delivery_log'][-500:]
    save_subscriptions(payload, org_id)
    return entry


def set_email(telegram_id, email, *, org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    tid = str(telegram_id).strip()
    if tid not in payload.get('subscribers', {}) or not payload['subscribers'][tid]:
        raise LookupError(f'No subscriptions for telegram:{tid}')
    candidates = [sub for sub in payload['subscribers'][tid] if sub.get('status') == 'active']
    target = candidates[-1] if candidates else payload['subscribers'][tid][-1]
    target['email'] = email
    target['email_updated_at'] = now_ts()
    target['email_updated_by'] = actor or ''
    save_subscriptions(payload, org_id)
    return target


def cancel_active_subscriptions(telegram_id, *, org_id=None, actor=''):
    payload = load_subscriptions(org_id)
    tid = str(telegram_id).strip()
    if tid not in payload.get('subscribers', {}):
        raise LookupError(f'No subscriptions for telegram:{tid}')
    cancelled = 0
    for sub in payload['subscribers'][tid]:
        if sub.get('status') == 'active':
            sub['status'] = 'cancelled'
            sub['cancelled_at'] = now_ts()
            sub['cancelled_by'] = actor or ''
            cancelled += 1
    if cancelled == 0:
        raise ValueError(f'No active subscriptions for telegram:{tid}')
    save_subscriptions(payload, org_id)
    return {'telegram_id': tid, 'cancelled_count': cancelled}


def remove_subscription(telegram_id, *, org_id=None, actor=''):
    return cancel_active_subscriptions(telegram_id, org_id=org_id, actor=actor)


def cancel_active(telegram_id, *, org_id=None, actor=''):
    return cancel_active_subscriptions(telegram_id, org_id=org_id, actor=actor)


def subscription_summary(org_id=None):
    payload = load_subscriptions(org_id)
    rows = list(payload.get('subscribers', {}).values())
    all_subs = [sub for records in rows for sub in records]
    active = [sub for sub in all_subs if sub.get('status') == 'active']
    verified = [
        sub for sub in active
        if sub.get('plan') != 'trial' and sub.get('payment_verified')
    ]
    return {
        'subscriber_count': len(payload.get('subscribers', {})),
        'subscription_count': len(all_subs),
        'active_subscription_count': len(active),
        'verified_paid_subscription_count': len(verified),
        'delivery_log_count': len(payload.get('delivery_log', [])),
        'internal_test_id_count': len(payload.get('_meta', {}).get('internal_test_ids', [])),
        'external_target_count': len(active_delivery_targets(org_id, external_only=True)),
    }
