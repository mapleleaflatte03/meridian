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
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _parse_ts(value):
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.datetime.strptime(raw, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return None


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


def append_node(
    key,
    value,
    org_id=None,
    tags=None,
    action_id=None,
    agent_id=None,
    timestamp=None,
):
    """Append a memory node to the chain. Returns (node_hash, depth)."""
    graph = _load_graph(org_id)
    prev_hash = graph['head_hash']
    depth = len(graph['nodes'])
    timestamp = str(timestamp or _now())
    value_json = json.dumps(value, sort_keys=True)

    node_hash = _compute_node_hash(prev_hash, key, value_json, timestamp, depth)

    node = {
        'hash': node_hash,
        'prev_hash': prev_hash,
        'key': key,
        'value': value,
        'depth': depth,
        'timestamp': timestamp,
        'agent_id': str(agent_id or (value.get('agent_id') if isinstance(value, dict) else '') or ''),
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


def query_nodes(key=None, tag=None, org_id=None, agent_id=None, start_ts=None, end_ts=None):
    """Query memory nodes by key/tag/agent/time range."""
    graph = _load_graph(org_id)
    nodes = graph.get('nodes', [])
    if key:
        nodes = [n for n in nodes if n['key'] == key]
    if tag:
        nodes = [n for n in nodes if tag in n.get('tags', [])]
    if agent_id:
        lookup = str(agent_id).strip().lower()
        nodes = [n for n in nodes if str(n.get('agent_id') or '').strip().lower() == lookup]
    start_dt = _parse_ts(start_ts)
    end_dt = _parse_ts(end_ts)
    if start_dt or end_dt:
        filtered = []
        for node in nodes:
            node_dt = _parse_ts(node.get('timestamp'))
            if node_dt is None:
                continue
            if start_dt and node_dt < start_dt:
                continue
            if end_dt and node_dt > end_dt:
                continue
            filtered.append(node)
        nodes = filtered
    return nodes


def temporal_query_with_proof(org_id=None, *, agent_id=None, start_ts=None, end_ts=None):
    """Return timeline query + integrity proof for 'who knew what when' checks."""
    valid, error_detail = verify_chain(org_id)
    if not valid:
        raise ValueError(f'memory_integrity_mismatch:{json.dumps(error_detail, sort_keys=True)}')
    nodes = query_nodes(
        org_id=org_id,
        agent_id=agent_id,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    graph = _load_graph(org_id)
    proof_nodes = [
        {
            'hash': node.get('hash'),
            'prev_hash': node.get('prev_hash'),
            'depth': node.get('depth'),
            'timestamp': node.get('timestamp'),
        }
        for node in nodes
    ]
    return {
        'events': nodes,
        'proof': {
            'chain_valid': True,
            'head_hash': graph.get('head_hash'),
            'index_version': graph.get('index_version'),
            'selected_count': len(nodes),
            'proof_nodes': proof_nodes,
        },
    }


def verify_temporal_proof(proof, org_id=None):
    """Verify a temporal proof payload against the current memory graph."""
    valid, error_detail = verify_chain(org_id)
    if not valid:
        return False, {
            'reason': 'chain_invalid',
            'detail': error_detail,
        }

    if not isinstance(proof, dict):
        return False, {
            'reason': 'proof_missing',
        }

    graph = _load_graph(org_id)
    expected_head = str(graph.get('head_hash') or '')
    expected_index_version = int(graph.get('index_version') or 0)

    def _coerce_int(value):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    provided_head = str(proof.get('head_hash') or '').strip()
    if provided_head and provided_head != expected_head:
        return False, {
            'reason': 'head_hash_mismatch',
            'expected': expected_head,
            'actual': provided_head,
        }

    provided_event_hash = str(proof.get('event_hash') or '').strip()
    if provided_event_hash and provided_event_hash != expected_head:
        return False, {
            'reason': 'event_hash_mismatch',
            'expected': expected_head,
            'actual': provided_event_hash,
        }

    provided_index = _coerce_int(proof.get('index_version'))
    if provided_index is not None and provided_index != expected_index_version:
        return False, {
            'reason': 'index_version_mismatch',
            'expected': expected_index_version,
            'actual': provided_index,
        }

    proof_nodes = proof.get('proof_nodes')
    if proof_nodes is None:
        proof_nodes = []
    if not isinstance(proof_nodes, list):
        return False, {
            'reason': 'proof_nodes_invalid',
        }

    selected_count = _coerce_int(proof.get('selected_count'))
    if selected_count is not None and selected_count != len(proof_nodes):
        return False, {
            'reason': 'selected_count_mismatch',
            'expected': len(proof_nodes),
            'actual': selected_count,
        }

    nodes_by_hash = {str(node.get('hash') or ''): node for node in graph.get('nodes', [])}
    for index, proof_node in enumerate(proof_nodes):
        if not isinstance(proof_node, dict):
            return False, {
                'reason': 'proof_node_invalid',
                'index': index,
            }

        candidate_hash = str(proof_node.get('hash') or proof_node.get('event_hash') or '').strip()
        if not candidate_hash:
            return False, {
                'reason': 'proof_node_missing_hash',
                'index': index,
            }

        node = nodes_by_hash.get(candidate_hash)
        if not node:
            return False, {
                'reason': 'proof_node_not_found',
                'index': index,
                'hash': candidate_hash,
            }

        expected_prev = str(node.get('prev_hash') or '')
        provided_prev = str(proof_node.get('prev_hash') or '').strip()
        if provided_prev and provided_prev != expected_prev:
            return False, {
                'reason': 'proof_node_prev_hash_mismatch',
                'index': index,
                'expected': expected_prev,
                'actual': provided_prev,
            }

        expected_depth = int(node.get('depth') or 0)
        provided_depth = _coerce_int(proof_node.get('depth'))
        if provided_depth is not None and provided_depth != expected_depth:
            return False, {
                'reason': 'proof_node_depth_mismatch',
                'index': index,
                'expected': expected_depth,
                'actual': provided_depth,
            }

        expected_timestamp = str(node.get('timestamp') or '')
        provided_timestamp = str(proof_node.get('timestamp') or '').strip()
        if provided_timestamp and provided_timestamp != expected_timestamp:
            return False, {
                'reason': 'proof_node_timestamp_mismatch',
                'index': index,
                'expected': expected_timestamp,
                'actual': provided_timestamp,
            }

    return True, None


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
