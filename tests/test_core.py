from datetime import date
import pandas as pd
from src.data_manager import DataManager
from src.regime import detect_regime
from src.risk import contracts_for_risk

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
