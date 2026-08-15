"""
strategies.py

Define strategies: breakouts, range-bound, and regime-based.
"""
import pandas as pd

def find_breakouts(df: pd.DataFrame, lookback: int, volume_multiplier: float) -> pd.DataFrame:
    """Identify breakouts over lookback period with volume surge.
    """
    df['high_60d'] = df['high'].rolling(window=lookback).max()
    df['vol_mean'] = df['volume'].rolling(window=lookback).mean()
    recent_vol = df['volume'].iloc[-1]
    recent_high = df['high'].iloc[-1]
    recent_close = df['close'].iloc[-1]
    recent_vol_mean = df['vol_mean'].iloc[-1]
    if recent_close >= recent_high and recent_vol >= recent_vol_mean * volume_multiplier:
        return True
    return False
