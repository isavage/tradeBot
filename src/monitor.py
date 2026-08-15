"""Deterministic position exit rules."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
@dataclass(frozen=True)
class ExitDecision: exit: bool; reason: str

def evaluate_exit(strategy: str, entry_value: float, current_value: float, entry_date: date, today: date, config: dict) -> ExitDecision:
    e, held = config["exits"], (today - entry_date).days
    credit = "credit" in strategy or strategy == "iron_condor"
    if credit and entry_value - current_value >= entry_value * e["credit_profit_take_pct"]: return ExitDecision(True, "credit_profit_target")
    if credit and current_value >= entry_value * (1 + e["stop_loss_pct"]): return ExitDecision(True, "credit_stop_loss")
    if not credit and current_value - entry_value >= entry_value * e["debit_profit_take_pct"]: return ExitDecision(True, "debit_profit_target")
    if not credit and current_value <= entry_value * (1 - e["stop_loss_pct"]): return ExitDecision(True, "debit_stop_loss")
    return ExitDecision(True, "time_stop") if held >= e["time_stop_days"] else ExitDecision(False, "hold")
