"""Defined-risk sizing and portfolio guardrails."""
from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class RiskLimits:
    max_risk_per_trade_pct: float
    max_total_options_risk_pct: float
    max_open_positions: int

def contracts_for_risk(equity: float, risk_pct: float, max_loss_per_contract: float,
                       available_buying_power: float | None = None) -> int:
    if equity <= 0 or risk_pct <= 0 or max_loss_per_contract <= 0:
        return 0
    budget = equity * risk_pct / 100
    if available_buying_power is not None:
        budget = min(budget, available_buying_power)
    return max(0, math.floor(budget / max_loss_per_contract))

def can_open_trade(equity: float, max_loss_per_contract: float, quantity: int,
                   open_risk: float, open_positions: int, limits: RiskLimits,
                   buying_power: float | None = None) -> bool:
    if quantity <= 0 or open_positions >= limits.max_open_positions:
        return False
    trade_risk = max_loss_per_contract * quantity
    return (trade_risk <= equity * limits.max_risk_per_trade_pct / 100
            and open_risk + trade_risk <= equity * limits.max_total_options_risk_pct / 100
            and (buying_power is None or trade_risk <= buying_power))
