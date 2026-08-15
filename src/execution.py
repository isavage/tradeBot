"""Alpaca execution boundary for multi-leg orders."""
from __future__ import annotations
import logging
from .options import Structure
LOGGER = logging.getLogger(__name__)

class ExecutionEngine:
    def __init__(self, trading_client): self.client = trading_client
    @staticmethod
    def request_for(structure: Structure, quantity: int):
        from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce, OrderType
        from alpaca.trading.requests import LimitOrderRequest, OptionLegRequest
        legs = [OptionLegRequest(symbol=x.contract.symbol, side=OrderSide.BUY if x.side == "buy" else OrderSide.SELL, ratio_qty=x.ratio) for x in structure.legs]
        return LimitOrderRequest(order_class=OrderClass.MLEG, legs=legs, qty=quantity, type=OrderType.LIMIT, time_in_force=TimeInForce.DAY, limit_price=structure.limit_price)
    def submit(self, structure: Structure, quantity: int):
        if quantity < 1: raise ValueError("quantity must be positive")
        order = self.client.submit_order(self.request_for(structure, quantity)); LOGGER.info("Submitted %s x%d", structure.strategy, quantity); return order
