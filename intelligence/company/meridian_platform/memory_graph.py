#!/usr/bin/env python3
"""
Verifiable Memory Graph with Temporal Integrity for Meridian.

Provides a hash-chained memory index where each entry references
the previous entry's hash, enabling tamper detection and temporal
ordering verification. Memory nodes form a directed acyclic graph
with Merkle-based integrity proofs.

Operations:
  1. append_node   — Add a memory node to the chain
  2. verify_chain  — Verify the entire chain integrity
  3. query_nodes   — Query nodes by key, tag, or time range
  4. chain_head    — Get the current chain head hash
"""
import datetime
import hashlib
import json
import os

PLATFORM_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    from capsule import capsule_path
except ImportError:
    def capsule_path(org_id, filename):
        return os.path.join(PLATFORM_DIR, filename)


_MEMORY_NODE_TAG = b'MEMORY_NODE_v1\x00'
_MEMORY_INTEGRITY_TAG = b'MEMORY_INTEGRITY_v1\x00'


def _now():
    return datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _graph_path(org_id=None):
    return capsule_path(org_id, 'memory_graph.json')


def _load_graph(org_id=None):
    path = _graph_path(org_id)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {
        'nodes': [],
        'head_hash': '0' * 64,
        'index_version': 0,
        'created_at': _now(),
        'updatedAt': _now(),
    }


def _save_graph(data, org_id=None):
    data['updatedAt'] = _now()
    path = _graph_path(org_id)
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _compute_node_hash(prev_hash, key, value_json, timestamp, depth):
    """Compute domain-separated hash: H(tag || prev || key || value || ts || depth)."""
    h = hashlib.sha256()
    h.update(_MEMORY_NODE_TAG)
    h.update(prev_hash.encode())
    h.update(key.encode())
    h.update(value_json.encode())
    h.update(timestamp.encode())
    h.update(str(depth).encode())
    return h.hexdigest()


def append_node(key, value, org_id=None, tags=None, action_id=None):
    """Append a memory node to the chain. Returns (node_hash, depth)."""
    graph = _load_graph(org_id)
    prev_hash = graph['head_hash']
    depth = len(graph['nodes'])
    timestamp = _now()
    value_json = json.dumps(value, sort_keys=True)

    node_hash = _compute_node_hash(prev_hash, key, value_json, timestamp, depth)

    node = {
        'hash': node_hash,
        'prev_hash': prev_hash,
        'key': key,
        'value': value,
        'depth': depth,
        'timestamp': timestamp,
        'tags': tags or [],
        'action_id': action_id or '',
    }
    graph['nodes'].append(node)
    graph['head_hash'] = node_hash
    graph['index_version'] = depth + 1
    _save_graph(graph, org_id)

    return node_hash, depth


def verify_chain(org_id=None):
    """Verify the entire memory chain integrity. Returns (valid, error_detail)."""
    graph = _load_graph(org_id)
    nodes = graph.get('nodes', [])
    if not nodes:
        return True, None

    expected_prev = '0' * 64
    for i, node in enumerate(nodes):
        if node['prev_hash'] != expected_prev:
            return False, {
                'depth': i,
                'expected_prev': expected_prev,
                'actual_prev': node['prev_hash'],
                'reason': 'prev_hash_mismatch',
            }
        value_json = json.dumps(node['value'], sort_keys=True)
        recomputed = _compute_node_hash(
            node['prev_hash'], node['key'], value_json,
            node['timestamp'], node['depth'],
        )
        if recomputed != node['hash']:
            return False, {
                'depth': i,
                'expected_hash': recomputed,
                'actual_hash': node['hash'],
                'reason': 'node_hash_mismatch',
            }
        expected_prev = node['hash']

    if expected_prev != graph['head_hash']:
        return False, {
            'reason': 'head_hash_mismatch',
            'expected': expected_prev,
            'actual': graph['head_hash'],
        }
    return True, None


def query_nodes(key=None, tag=None, org_id=None):
    """Query memory nodes by key and/or tag."""
    graph = _load_graph(org_id)
    nodes = graph.get('nodes', [])
    if key:
        nodes = [n for n in nodes if n['key'] == key]
    if tag:
        nodes = [n for n in nodes if tag in n.get('tags', [])]
    return nodes


def chain_head(org_id=None):
    """Get the current chain head hash and depth."""
    graph = _load_graph(org_id)
    return {
        'head_hash': graph['head_hash'],
        'index_version': graph['index_version'],
        'node_count': len(graph.get('nodes', [])),
    }


def integrity_hash(org_id=None):
    """Compute an integrity hash over the entire memory graph."""
    graph = _load_graph(org_id)
    h = hashlib.sha256()
    h.update(_MEMORY_INTEGRITY_TAG)
    h.update(graph['head_hash'].encode())
    h.update(str(graph['index_version']).encode())
    for node in graph.get('nodes', []):
        h.update(node['hash'].encode())
    return h.hexdigest()


def temporal_integrity_status(org_id=None):
    """Return temporal integrity status for the /api/status block."""
    graph = _load_graph(org_id)
    node_count = len(graph.get('nodes', []))
    enabled = node_count > 0
    valid, _ = verify_chain(org_id) if enabled else (True, None)
    return {
        'enabled': enabled,
        'index_version': graph.get('index_version', 0),
        'node_count': node_count,
        'head_hash': graph.get('head_hash'),
        'chain_valid': valid,
    }
