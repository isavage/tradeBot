"""Option-chain filtering and defined-risk multi-leg structure construction."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

@dataclass(frozen=True)
class Contract:
    symbol: str; underlying: str; expiration: date; strike: float; option_type: str
    bid: float; ask: float; open_interest: int; delta: Optional[float] = None
    @property
    def mid(self) -> float: return (self.bid + self.ask) / 2

@dataclass(frozen=True)
class Leg:
    contract: Contract; side: str; ratio: int = 1

@dataclass(frozen=True)
class Structure:
    strategy: str; legs: tuple[Leg, ...]; max_profit: float; max_loss: float; limit_price: float

def liquid_contracts(contracts: Iterable[Contract], as_of: date, min_open_interest: int, max_spread_pct: float, min_dte: int, max_dte: int) -> list[Contract]:
    result = []
    for c in contracts:
        dte, mid = (c.expiration - as_of).days, max(c.mid, 0.01)
        if min_dte <= dte <= max_dte and c.open_interest >= min_open_interest and 0 <= (c.ask - c.bid) / mid <= max_spread_pct: result.append(c)
    return result

def select_by_delta(contracts: Iterable[Contract], target: float, option_type: str) -> Contract:
    candidates = [c for c in contracts if c.option_type.lower() == option_type.lower() and c.delta is not None]
    if not candidates: raise ValueError(f"No {option_type} contracts with delta available")
    return min(candidates, key=lambda c: abs(abs(c.delta) - target))

def _vertical(name: str, long: Contract, short: Contract) -> Structure:
    credit = short.mid - long.mid; width = abs(long.strike - short.strike)
    return Structure(name, (Leg(long, "buy"), Leg(short, "sell")), credit * 100, (width - credit) * 100, round(credit, 2))

def build_bull_put_spread(long_put: Contract, short_put: Contract) -> Structure:
    if not (long_put.option_type.lower() == short_put.option_type.lower() == "put" and long_put.strike < short_put.strike): raise ValueError("Invalid bull put strikes")
    return _vertical("bull_put_credit", long_put, short_put)

def build_bear_call_spread(long_call: Contract, short_call: Contract) -> Structure:
    if not (long_call.option_type.lower() == short_call.option_type.lower() == "call" and long_call.strike > short_call.strike): raise ValueError("Invalid bear call strikes")
    return _vertical("bear_call_credit", long_call, short_call)

def build_iron_condor(long_put: Contract, short_put: Contract, short_call: Contract, long_call: Contract) -> Structure:
    if not (long_put.strike < short_put.strike < short_call.strike < long_call.strike): raise ValueError("Iron-condor strikes must be ordered")
    credit = short_put.mid - long_put.mid + short_call.mid - long_call.mid
    width = max(short_put.strike - long_put.strike, long_call.strike - short_call.strike)
    return Structure("iron_condor", (Leg(long_put, "buy"), Leg(short_put, "sell"), Leg(short_call, "sell"), Leg(long_call, "buy")), credit * 100, (width - credit) * 100, round(credit, 2))

def fetch_option_chain(client, symbol: str, as_of: date, min_dte: int, max_dte: int):
    from alpaca.data.requests import OptionChainRequest
    request = OptionChainRequest(underlying_symbol=symbol.upper(), expiration_date_gte=as_of + timedelta(days=min_dte), expiration_date_lte=as_of + timedelta(days=max_dte))
    return client.get_option_chain(request)
