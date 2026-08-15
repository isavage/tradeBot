"""Deterministic SPY market-regime classification."""
from __future__ import annotations
import pandas as pd

REGIMES = ("Bullish", "Sideways", "Bearish")

def regime_frame(frame: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.DataFrame:
    result = frame.copy()
    result["ma_fast"] = result["close"].rolling(fast, min_periods=fast).mean()
    result["ma_slow"] = result["close"].rolling(slow, min_periods=slow).mean()
    return result

def detect_regime(frame: pd.DataFrame, ma_fast: int = 50, ma_slow: int = 200) -> str:
    if len(frame) < ma_slow:
        raise ValueError(f"At least {ma_slow} bars are required")
    latest = regime_frame(frame, ma_fast, ma_slow).iloc[-1]
    if latest.close > latest.ma_fast > latest.ma_slow:
        return "Bullish"
    if latest.close < latest.ma_fast < latest.ma_slow:
        return "Bearish"
    return "Sideways"
