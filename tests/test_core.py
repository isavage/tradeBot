from datetime import date
import pandas as pd
from src.data_manager import DataManager
from src.regime import detect_regime
from src.risk import contracts_for_risk
from src.scanners import scan_intraday_breakout

def bars(n=220):
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    close = pd.Series(range(n), index=idx, dtype=float) + 100
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1_000_000}, index=idx)

def test_incremental_update_starts_after_metadata(tmp_path):
    config = {"data": {"data_dir": str(tmp_path / "daily"), "metadata_file": str(tmp_path / "metadata.json"), "history_years": 1}}
    calls = []
    def fetch(symbol, start, end): calls.append((symbol, start, end)); return bars(2)
    manager = DataManager(config, fetcher=fetch)
    manager.update_data(["ABC"], today=date(2024, 1, 10)); manager.update_data(["ABC"], today=date(2024, 1, 12))
    assert calls[1][1] == date(2020, 1, 3)

def test_bullish_regime(): assert detect_regime(bars(), 5, 20) == "Bullish"
def test_risk_sizing(): assert contracts_for_risk(100_000, 1, 500) == 2

def test_intraday_requires_lookback_plus_completed_bar():
    frame = bars(61)
    assert scan_intraday_breakout(frame, lookback_bars=60).empty

def test_intraday_returns_only_latest_completed_bar():
    frame = bars(80)
    # Make the latest completed bar break its preceding 60-bar high with volume.
    frame.iloc[-3, frame.columns.get_loc("close")] = 150
    frame.iloc[-2, frame.columns.get_loc("close")] = 200
    frame.iloc[-2, frame.columns.get_loc("high")] = 201
    frame.iloc[-2, frame.columns.get_loc("volume")] = 10_000_000
    result = scan_intraday_breakout(frame, lookback_bars=60, min_breakout_pct=0.001,
                                    volume_multiplier=1.5, rsi_min=0, rsi_max=100,
                                    fast_ma=10, slow_ma=30)
    assert len(result) == 1
    assert result.index[-1] == frame.index[-2]
