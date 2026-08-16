"""Pure pandas scanners; no broker calls or discretionary decisions."""
from __future__ import annotations
import logging
import pandas as pd

LOGGER = logging.getLogger(__name__)

def _rsi(close: pd.Series, period: int) -> pd.Series:
    change = close.diff()
    gain, loss = change.clip(lower=0), -change.clip(upper=0)
    rs = gain.ewm(alpha=1 / period, adjust=False).mean() / loss.ewm(alpha=1 / period, adjust=False).mean().replace(0, pd.NA)
    return 100 - (100 / (1 + rs))

def scan_breakouts(frame: pd.DataFrame, lookback_days: int = 60, volume_multiplier: float = 1.8,
                   rsi_period: int = 14, rsi_min: float = 55, rsi_max: float = 78,
                   min_breakout_pct: float = 0.005, require_trend_alignment: bool = True) -> pd.DataFrame:
    result = frame.copy()
    prior_high = result["high"].rolling(lookback_days).max().shift(1)
    average_volume = result["volume"].rolling(lookback_days).mean().shift(1)
    result["rsi"] = _rsi(result["close"], rsi_period)
    result["volume_ratio"] = result["volume"] / average_volume
    result["breakout_pct"] = result["close"] / prior_high - 1
    result["ma20"] = result["close"].rolling(20).mean()
    result["ma50"] = result["close"].rolling(50).mean()
    result["ma200"] = result["close"].rolling(200).mean()
    trend = (result["close"] > result["ma20"]) & (result["ma20"] > result["ma50"]) & (result["ma50"] > result["ma200"])
    breakout_pass = result["breakout_pct"] >= min_breakout_pct
    volume_pass = result["volume_ratio"] >= volume_multiplier
    rsi_pass = result["rsi"].between(rsi_min, rsi_max)
    mask = breakout_pass & volume_pass & rsi_pass
    if require_trend_alignment:
        mask &= trend
    result["score"] = (result["volume_ratio"].clip(upper=4) / 4 * 40
                        + result["breakout_pct"].clip(lower=0, upper=0.10) / 0.10 * 30
                        + ((result["rsi"] - rsi_min) / max(rsi_max - rsi_min, 1)).clip(0, 1) * 20
                        + trend.astype(int) * 10)
    result.attrs["filter_counts"] = {
        "total_bars": len(result),
        "breakout": int(breakout_pass.sum()),
        "volume": int((breakout_pass & volume_pass).sum()),
        "rsi": int((breakout_pass & volume_pass & rsi_pass).sum()),
        "trend": int((breakout_pass & volume_pass & rsi_pass & trend).sum()),
        "signals": int(mask.sum()),
    }
    return result.loc[mask].copy()

def scan_breakdowns(frame: pd.DataFrame, lookback_days: int = 60, volume_multiplier: float = 1.8) -> pd.DataFrame:
    result = frame.copy()
    prior_low = result["low"].rolling(lookback_days).min().shift(1)
    average_volume = result["volume"].rolling(lookback_days).mean().shift(1)
    result["volume_ratio"] = result["volume"] / average_volume
    result["breakdown_pct"] = 1 - result["close"] / prior_low
    result["score"] = result["volume_ratio"].clip(upper=4) / 4 * 60 + result["breakdown_pct"].clip(lower=0, upper=0.10) / 0.10 * 40
    return result.loc[(result["breakdown_pct"] >= 0.005) & (result["volume_ratio"] >= volume_multiplier)].copy()

def scan_range_bound(frame: pd.DataFrame, lookback_days: int = 20, max_atr_pct: float = 0.04) -> pd.DataFrame:
    result = frame.copy()
    true_range = pd.concat([result.high - result.low, (result.high - result.close.shift()).abs(), (result.low - result.close.shift()).abs()], axis=1).max(axis=1)
    result["atr_pct"] = true_range.rolling(lookback_days).mean() / result["close"]
    return result.loc[result["atr_pct"] <= max_atr_pct].copy()


def scan_intraday_breakout(frame: pd.DataFrame, lookback_bars: int = 60,
                           volume_multiplier: float = 1.5, rsi_period: int = 14,
                           rsi_min: float = 52, rsi_max: float = 82,
                           min_breakout_pct: float = 0.0025,
                           fast_ma: int = 10, slow_ma: int = 30) -> pd.DataFrame:
    """Evaluate only the latest completed same-session minute bar."""
    if len(frame) < lookback_bars + 2:
        return frame.iloc[0:0].copy()
    result = frame.copy()
    prior = result.iloc[:-1].copy()  # never trade on a potentially open minute
    prior_high = prior["high"].rolling(lookback_bars).max().shift(1)
    average_volume = prior["volume"].rolling(lookback_bars).mean().shift(1)
    prior["rsi"] = _rsi(prior["close"], rsi_period)
    prior["volume_ratio"] = prior["volume"] / average_volume
    prior["breakout_pct"] = prior["close"] / prior_high - 1
    prior["fast_ma"] = prior["close"].rolling(fast_ma).mean()
    prior["slow_ma"] = prior["close"].rolling(slow_ma).mean()
    latest = prior.iloc[[-1]]
    trend = latest["close"] > latest["fast_ma"]
    mask = ((latest["breakout_pct"] >= min_breakout_pct)
            & (latest["volume_ratio"] >= volume_multiplier)
            & latest["rsi"].between(rsi_min, rsi_max) & trend)
    return latest.loc[mask].copy()
