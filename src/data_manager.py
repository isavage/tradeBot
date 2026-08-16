"""Local, incremental daily-bar storage backed by Alpaca and Parquet."""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

import pandas as pd

LOGGER = logging.getLogger(__name__)
REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class DataManager:
    """Maintain one normalized Parquet file per symbol.

    ``client`` and ``fetcher`` are injectable so update logic can be tested without
    network access. The fetcher signature is ``(symbol, start, end) -> DataFrame``.
    """

    def __init__(self, config: dict, client=None, fetcher: Optional[Callable] = None):
        self.config = config
        self.data_dir = Path(config["data"]["data_dir"])
        self.metadata_file = Path(config["data"]["metadata_file"])
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        self.client = client
        self.fetcher = fetcher

    def load_metadata(self) -> dict[str, str]:
        if not self.metadata_file.exists():
            return {}
        with self.metadata_file.open(encoding="utf-8") as handle:
            return json.load(handle)

    def save_metadata(self, metadata: dict[str, str]) -> None:
        temporary = self.metadata_file.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, indent=2, sort_keys=True)
        temporary.replace(self.metadata_file)

    def path_for(self, symbol: str) -> Path:
        return self.data_dir / f"{symbol.upper()}.parquet"

    def intraday_path_for(self, symbol: str) -> Path:
        path = Path(self.config["intraday"].get("data_dir", "data/intraday"))
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{symbol.upper()}.parquet"

    def get_last_stored_date(self, symbol: str) -> Optional[date]:
        value = self.load_metadata().get(symbol.upper())
        if value:
            return date.fromisoformat(value)
        path = self.path_for(symbol)
        if not path.exists():
            return None
        frame = pd.read_parquet(path)
        return self._date_index(frame).max().date() if not frame.empty else None

    @staticmethod
    def _date_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
        index = frame.index.get_level_values(-1) if isinstance(frame.index, pd.MultiIndex) else frame.index
        return pd.to_datetime(index, utc=True).tz_localize(None).normalize()

    @classmethod
    def validate(cls, frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        result = frame.copy()
        result.columns = [str(column).lower() for column in result.columns]
        missing = set(REQUIRED_COLUMNS) - set(result.columns)
        if missing:
            raise ValueError(f"Daily bars missing columns: {sorted(missing)}")
        result.index = cls._date_index(result)
        result = result[~result.index.duplicated(keep="last")].sort_index()
        if (result[["high", "low", "close"]] <= 0).any().any():
            raise ValueError("Daily bars contain non-positive prices")
        if (result["high"] < result["low"]).any():
            raise ValueError("Daily bars contain high below low")
        return result

    def fetch_new_bars(self, symbol: str, start: date, end: date) -> pd.DataFrame:
        if self.fetcher:
            return self.validate(self.fetcher(symbol, start, end))
        if self.client is None:
            from alpaca.data import StockHistoricalDataClient
            key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
            if not key or not secret:
                raise RuntimeError("APCA_API_KEY_ID and APCA_API_SECRET_KEY are required")
            self.client = StockHistoricalDataClient(key, secret)
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import Adjustment, DataFeed
        feed_name = str(self.config["data"].get("feed", "iex")).lower()
        try:
            feed = DataFeed(feed_name)
        except ValueError as exc:
            raise ValueError("data.feed must be either 'iex' or 'sip'") from exc
        request = StockBarsRequest(symbol_or_symbols=symbol.upper(), start=start,
                                   end=end + timedelta(days=1), timeframe=TimeFrame.Day,
                                   adjustment=Adjustment.ALL, feed=feed)
        return self.validate(self.client.get_stock_bars(request).df)

    def fetch_intraday_bars(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Fetch minute bars without normalizing timestamps to daily dates."""
        if self.client is None:
            from alpaca.data import StockHistoricalDataClient
            key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
            if not key or not secret:
                raise RuntimeError("APCA_API_KEY_ID and APCA_API_SECRET_KEY are required")
            self.client = StockHistoricalDataClient(key, secret)
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
        from alpaca.data.enums import DataFeed
        feed_name = str(self.config["data"].get("feed", "iex")).lower()
        try:
            feed = DataFeed(feed_name)
        except ValueError as exc:
            raise ValueError("data.feed must be either 'iex' or 'sip'") from exc
        request = StockBarsRequest(symbol_or_symbols=symbol.upper(), start=start, end=end,
                                   timeframe=TimeFrame(1, TimeFrameUnit.Minute), feed=feed)
        frame = self.client.get_stock_bars(request).df
        if frame.empty:
            return frame
        if isinstance(frame.index, pd.MultiIndex):
            frame = frame.xs(symbol.upper(), level="symbol", drop_level=True)
        frame = frame.copy()
        frame.columns = [str(column).lower() for column in frame.columns]
        frame.index = pd.to_datetime(frame.index, utc=True).tz_convert("America/New_York").tz_localize(None)
        return frame[~frame.index.duplicated(keep="last")].sort_index()

    def append_data(self, symbol: str, frame: pd.DataFrame) -> None:
        incoming = self.validate(frame)
        if incoming.empty:
            return
        path = self.path_for(symbol)
        existing = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        combined = self.validate(pd.concat([existing, incoming]))
        combined.to_parquet(path, index=True)

    def update_data(self, symbols: Iterable[str], force_refresh: bool = False,
                    today: Optional[date] = None) -> dict[str, date]:
        today = today or date.today()
        metadata = self.load_metadata()
        updated: dict[str, date] = {}
        for raw_symbol in symbols:
            symbol = raw_symbol.upper()
            last = None if force_refresh else self.get_last_stored_date(symbol)
            start = today - timedelta(days=365 * int(self.config["data"]["history_years"])) if last is None else last + timedelta(days=1)
            if start > today:
                continue
            bars = self.fetch_new_bars(symbol, start, today)
            if not bars.empty:
                self.append_data(symbol, bars)
                last_saved = self._date_index(bars).max().date()
                metadata[symbol] = last_saved.isoformat()
                updated[symbol] = last_saved
                LOGGER.info("Updated %s through %s", symbol, last_saved)
        self.save_metadata(metadata)
        return updated

    def read(self, symbol: str, minimum_rows: int = 1) -> pd.DataFrame:
        frame = pd.read_parquet(self.path_for(symbol))
        if len(frame) < minimum_rows:
            raise ValueError(f"{symbol} has only {len(frame)} rows; need {minimum_rows}")
        return self.validate(frame)

    def discover_symbols(self, as_of: Optional[date] = None) -> list[str]:
        """Discover liquid, active US equities from Alpaca.

        Alpaca does not expose a universal pre-ranked ``most active`` equity list
        through the Trading API. We therefore obtain the active asset universe,
        download a short daily window in batches, and rank by average dollar
        volume. This avoids hardcoded tickers while keeping the ranking
        reproducible and based on actual Alpaca market data.
        """
        universe = self.config["universe"]
        if not universe.get("discover_via_alpaca", True):
            return [str(s).upper() for s in universe.get("symbols", [])]
        key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("Alpaca credentials are required for symbol discovery")
        from alpaca.trading.client import TradingClient
        from alpaca.trading.enums import AssetClass, AssetStatus
        trading = TradingClient(key, secret, paper=bool(self.config.get("paper", True)))
        assets = trading.get_all_assets()
        candidates = [a.symbol for a in assets if a.asset_class == AssetClass.US_EQUITY
                      and a.status == AssetStatus.ACTIVE and a.tradable
                      and (not universe.get("require_shortable", False) or a.shortable)]
        if self.client is None:
            from alpaca.data import StockHistoricalDataClient
            self.client = StockHistoricalDataClient(key, secret)
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed
        feed_name = str(self.config["data"].get("feed", "iex")).lower()
        try:
            feed = DataFeed(feed_name)
        except ValueError as exc:
            raise ValueError("data.feed must be either 'iex' or 'sip'") from exc
        end = as_of or date.today()
        start = end - timedelta(days=int(universe.get("discovery_lookback_days", 20)) * 2)
        rows: list[pd.DataFrame] = []
        batch_size = 500
        for offset in range(0, len(candidates), batch_size):
            request = StockBarsRequest(symbol_or_symbols=candidates[offset:offset + batch_size], start=start, end=end + timedelta(days=1), timeframe=TimeFrame.Day, feed=feed)
            batch = self.client.get_stock_bars(request).df
            if not batch.empty:
                rows.append(batch)
        if not rows:
            return [str(s).upper() for s in universe.get("symbols", [])]
        bars = pd.concat(rows).reset_index()
        bars["symbol"] = bars["symbol"].str.upper()
        ranked = bars.groupby("symbol").agg(last_close=("close", "last"), avg_volume=("volume", "mean"))
        ranked = ranked[(ranked.last_close >= float(universe["min_price"])) & (ranked.last_close <= float(universe["max_price"])) & (ranked.avg_volume >= float(universe["min_avg_volume"]))]
        ranked["dollar_volume"] = ranked.last_close * ranked.avg_volume
        discovered = ranked.sort_values("dollar_volume", ascending=False).head(int(universe.get("max_discovered_symbols", 100))).index.tolist()
        anchor = str(self.config["regime"]["symbol"]).upper()
        return list(dict.fromkeys([anchor, *discovered]))

    def market_calendar(self, day: date):
        """Return Alpaca's US equity calendar entry for a date, if any."""
        key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("APCA_API_KEY_ID and APCA_API_SECRET_KEY are required")
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import GetCalendarRequest
        trading = TradingClient(key, secret, paper=bool(self.config.get("paper", True)))
        entries = trading.get_calendar(GetCalendarRequest(start=day, end=day))
        return entries[0] if entries else None
