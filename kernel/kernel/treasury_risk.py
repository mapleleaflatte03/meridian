#!/usr/bin/env python3
"""Treasury predictive risk scoring for Meridian governance.

Deterministic risk assessment based on treasury balance, burn rate,
reserve floor, pending payouts, and active sanctions. Integrates with
court/authority warning gates without breaking existing flows.

No external model dependency — uses deterministic arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RISK_HEALTHY = 'healthy'
RISK_WARNING = 'warning'
RISK_CRITICAL = 'critical'

# Thresholds (configurable per institution in future)
FLOOR_BUFFER_RATIO = 1.5  # warn when balance < floor * this ratio
RUNWAY_WARNING_DAYS = 14
RUNWAY_CRITICAL_DAYS = 3


@dataclass(frozen=True)
class RiskInput:
    """Inputs for risk assessment."""
    balance_usd: float
    reserve_floor_usd: float
    burn_rate_per_day: float
    active_sanctions: int
    pending_payouts_usd: float


@dataclass(frozen=True)
class RiskResult:
    """Output of risk assessment."""
    level: str
    runway_days: int
    effective_balance_usd: float
    burn_rate_per_day: float
    court_warning: bool
    authority_gate: str
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            'level': self.level,
            'runway_days': self.runway_days,
            'effective_balance_usd': round(self.effective_balance_usd, 4),
            'burn_rate_per_day': round(self.burn_rate_per_day, 4),
            'court_warning': self.court_warning,
            'authority_gate': self.authority_gate,
            'reasons': list(self.reasons),
        }


def compute_burn_rate(transactions: list[dict[str, Any]], window_days: int = 30) -> float:
    """Compute daily burn rate from recent transactions.

    Only counts outflows (negative amount_usd). Deposits are ignored.
    Returns 0.0 if no outflows exist.
    """
    if not transactions or window_days <= 0:
        return 0.0
    total_outflow = sum(
        abs(float(tx.get('amount_usd', 0)))
        for tx in transactions
        if float(tx.get('amount_usd', 0)) < 0
    )
    if total_outflow == 0:
        return 0.0
    return total_outflow / window_days


def predict_runway_days(balance_usd: float, burn_rate_per_day: float) -> int:
    """Predict how many days the treasury can sustain at current burn rate.

    Returns -1 if burn rate is zero (infinite runway).
    Returns 0 if balance is zero or negative.
    """
    if balance_usd <= 0:
        return 0
    if burn_rate_per_day <= 0:
        return -1
    return int(balance_usd / burn_rate_per_day)


def assess_risk(inp: RiskInput) -> RiskResult:
    """Deterministic risk assessment for treasury health.

    Rules (evaluated in order, most severe wins):
    1. effective_balance < reserve_floor -> CRITICAL
    2. runway_days < RUNWAY_CRITICAL_DAYS -> CRITICAL
    3. effective_balance < reserve_floor * FLOOR_BUFFER_RATIO -> WARNING
    4. runway_days < RUNWAY_WARNING_DAYS -> WARNING
    5. Otherwise -> HEALTHY

    Court warning is triggered when active_sanctions > 0.
    Authority gate reflects whether payouts should be allowed.
    """
    effective_balance = inp.balance_usd - inp.pending_payouts_usd
    runway = predict_runway_days(effective_balance, inp.burn_rate_per_day)
    court_warning = inp.active_sanctions > 0

    reasons: list[str] = []
    level = RISK_HEALTHY

    # Critical checks
    if effective_balance < inp.reserve_floor_usd:
        level = RISK_CRITICAL
        reasons.append(f'effective_balance ${effective_balance:.2f} below reserve floor ${inp.reserve_floor_usd:.2f}')
    if runway >= 0 and runway < RUNWAY_CRITICAL_DAYS:
        level = RISK_CRITICAL
        reasons.append(f'runway {runway} days below critical threshold {RUNWAY_CRITICAL_DAYS}')

    # Warning checks (only if not already critical)
    if level != RISK_CRITICAL:
        warning_threshold = inp.reserve_floor_usd * FLOOR_BUFFER_RATIO
        if effective_balance < warning_threshold:
            level = RISK_WARNING
            reasons.append(f'effective_balance ${effective_balance:.2f} below warning threshold ${warning_threshold:.2f}')
        if runway >= 0 and runway < RUNWAY_WARNING_DAYS:
            level = RISK_WARNING
            reasons.append(f'runway {runway} days below warning threshold {RUNWAY_WARNING_DAYS}')

    if court_warning:
        reasons.append(f'{inp.active_sanctions} active sanction(s) require court review')

    # Authority gate
    if level == RISK_CRITICAL or court_warning:
        authority_gate = 'blocked'
    elif level == RISK_WARNING:
        authority_gate = 'restricted'
    else:
        authority_gate = 'allowed'

    return RiskResult(
        level=level,
        runway_days=runway,
        effective_balance_usd=effective_balance,
        burn_rate_per_day=inp.burn_rate_per_day,
        court_warning=court_warning,
        authority_gate=authority_gate,
        reasons=tuple(reasons),
    )
