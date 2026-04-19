#!/usr/bin/env python3
"""
Federated Proof Marketplace for Meridian.

Enables cross-institution agent/proof rental via PoGE v5:
  - Institution A publishes available agents/proofs to the federation manifest
  - Institution B browses the federated catalog and submits rental bids
  - Settlement flows through existing marketplace + proof chain

This module adds:
  1. federated_catalog    — Aggregates available agents across all institutions
  2. publish_offering     — An institution publishes agent capacity for rent
  3. request_rental       — Cross-institution rental request via federation
  4. rental_settlement    — Settle a federated rental with proof receipt
"""
import datetime
import hashlib
import json
import os
import uuid

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from capsule import capsule_path, ensure_capsule
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(PLATFORM_DIR, filename)
    def ensure_capsule(org_id):
        return PLATFORM_DIR

try:
    from organizations import list_orgs, get_org
except ImportError:
    def list_orgs(status_filter=None):
        return []
    def get_org(org_id):
        return None

_FEDERATED_RECEIPT_TAG = b'FEDERATED_MARKETPLACE_v1\x00'


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _catalog_path(org_id=None):
    return capsule_path(org_id, 'federated_offerings.json')


def _load_catalog(org_id=None):
    path = _catalog_path(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'offerings': {}, 'updatedAt': _now()}


def _save_catalog(data, org_id=None):
    data['updatedAt'] = _now()
    path = _catalog_path(org_id)
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def publish_offering(
    org_id: str,
    agent_id: str,
    capability: str,
    price_usd_per_run: float,
    description: str = '',
) -> dict:
    """Publish an agent's capability for federated rental."""
    catalog = _load_catalog(org_id)
    offering_id = f'off_{uuid.uuid4().hex[:8]}'
    offering = {
        'id': offering_id,
        'org_id': org_id,
        'agent_id': agent_id,
        'capability': capability,
        'price_usd_per_run': price_usd_per_run,
        'description': description,
        'status': 'active',
        'created_at': _now(),
    }
    catalog['offerings'][offering_id] = offering
    _save_catalog(catalog, org_id)
    return offering


def federated_catalog() -> list:
    """Aggregate all active offerings across all institutions."""
    all_offerings = []
    for org in list_orgs(status_filter='active'):
        org_id = org.get('id', '')
        try:
            catalog = _load_catalog(org_id)
        except Exception:
            continue
        for offering in catalog.get('offerings', {}).values():
            if offering.get('status') == 'active':
                entry = dict(offering)
                entry['institution_name'] = org.get('name', '')
                entry['institution_slug'] = org.get('slug', '')
                all_offerings.append(entry)
    all_offerings.sort(key=lambda o: o.get('price_usd_per_run', 0))
    return all_offerings


def request_rental(
    requester_org_id: str,
    offering_id: str,
    provider_org_id: str,
    task_description: str,
) -> dict:
    """Submit a rental request for a federated offering."""
    catalog = _load_catalog(provider_org_id)
    offering = catalog.get('offerings', {}).get(offering_id)
    if not offering or offering.get('status') != 'active':
        raise ValueError(f'Offering {offering_id} not found or inactive')

    rental_id = f'rental_{uuid.uuid4().hex[:8]}'
    h = hashlib.sha256()
    h.update(_FEDERATED_RECEIPT_TAG)
    h.update(rental_id.encode())
    h.update(requester_org_id.encode())
    h.update(provider_org_id.encode())
    h.update(offering_id.encode())
    request_hash = h.hexdigest()

    return {
        'rental_id': rental_id,
        'requester_org_id': requester_org_id,
        'provider_org_id': provider_org_id,
        'offering_id': offering_id,
        'offering': offering,
        'task_description': task_description,
        'status': 'requested',
        'request_hash': request_hash,
        'created_at': _now(),
    }


def rental_settlement(rental: dict, proof_receipt: str, result_summary: str) -> dict:
    """Settle a federated rental with proof receipt."""
    h = hashlib.sha256()
    h.update(_FEDERATED_RECEIPT_TAG)
    h.update(rental.get('rental_id', '').encode())
    h.update(proof_receipt.encode())
    h.update(result_summary.encode())
    settlement_hash = h.hexdigest()

    return {
        'rental_id': rental.get('rental_id', ''),
        'status': 'settled',
        'proof_receipt': proof_receipt,
        'result_summary': result_summary,
        'settlement_hash': settlement_hash,
        'settled_at': _now(),
    }
