#!/usr/bin/env python3
"""Shared constitutional boundary descriptors for Meridian-facing surfaces."""

from __future__ import annotations

from typing import Dict, List


KERNEL_PRIMITIVES: List[str] = [
    'Institution',
    'Agent',
    'Authority',
    'Treasury',
    'Court',
]

PLATFORM_PRIMITIVES: List[str] = KERNEL_PRIMITIVES + ['Commitment']


def constitutional_model() -> Dict[str, object]:
    return {
        'kernel': {
            'name': 'Meridian Constitutional Kernel',
            'count': len(KERNEL_PRIMITIVES),
            'primitives': list(KERNEL_PRIMITIVES),
            'scope': 'runtime_neutral_governance_boundary',
        },
        'platform': {
            'name': 'Meridian Platform',
            'count': len(PLATFORM_PRIMITIVES),
            'primitives': list(PLATFORM_PRIMITIVES),
            'scope': 'governed_digital_labor_operating_system',
            'note': 'Commitment is the sixth platform primitive composed above the kernel and exercised through Meridian-facing services.',
        },
        'runtime': {
            'name': 'Meridian Loom',
            'runtime_id': 'loom_native',
            'role': 'execution_runtime',
            'status': 'live_on_this_host',
        },
    }
