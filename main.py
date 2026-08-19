"""Daily pipeline: local data -> regime -> signals."""
from __future__ import annotations
import argparse
import logging
import os
import re
from pathlib import Path
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import pandas as pd
from src.data_manager import DataManager
from src.regime import detect_regime
from src.strategy_router import route
from src.utils import load_config, setup_logging, recent_frame
from src.notifications import send_ntfy
from src.scanners import scan_intraday_breakout

LOGGER = logging.getLogger(__name__)

def _decode_occ(symbol: str) -> tuple[str, str] | None:
    match = re.search(r"([A-Z0-9.]{1,6})(\d{6})([CP])(\d{8})$", symbol)
    if not match:
        return None
    expiry = "20" + match.group(2)[:2] + "-" + match.group(2)[2:4] + "-" + match.group(2)[4:]
    strike = f"{int(match.group(4)) / 1000:.2f}"
    return expiry, strike

def _option_log(symbol: str, direction: str, config: dict) -> None:
    """Log a read-only option candidate from Alpaca's current option snapshots."""
    try:
        from alpaca.data.historical.option import OptionHistoricalDataClient
        from alpaca.data.requests import OptionChainRequest
        from alpaca.trading.enums import ContractType
        key, secret = os.getenv("APCA_API_KEY_ID"), os.getenv("APCA_API_SECRET_KEY")
        client = OptionHistoricalDataClient(key, secret)
        today = date.today()
        options = config["options"]
        request = OptionChainRequest(underlying_symbol=symbol, expiration_date_gte=today + timedelta(days=options["min_dte"]), expiration_date_lte=today + timedelta(days=options["max_dte"]))
        snapshots = client.get_option_chain(request)
        desired_type = ContractType.CALL if direction == "bullish" else ContractType.PUT
        target_delta = float(options["long_delta"])
        selected = []
        for contract_symbol, snapshot in snapshots.items():
            suffix = contract_symbol[-9:]
            if len(suffix) != 9 or suffix[0] not in ("C", "P"):
                continue
            if suffix[0] != ("C" if desired_type == ContractType.CALL else "P"):
                continue
            quote = getattr(snapshot, "latest_quote", None)
            greeks = getattr(snapshot, "greeks", None)
            bid, ask = getattr(quote, "bid_price", None), getattr(quote, "ask_price", None)
            delta = getattr(greeks, "delta", None)
            if bid is None or ask is None or delta is None or ask <= 0:
                continue
            selected.append((abs(abs(float(delta)) - target_delta), contract_symbol, bid, ask, delta))
        if selected:
            _, contract_symbol, bid, ask, delta = min(selected)
            decoded = _decode_occ(contract_symbol)
            expiry, strike = decoded if decoded else ("unknown", "unknown")
            LOGGER.info("OPTION candidate underlying=%s type=%s contract=%s expiry=%s strike=%s bid=%.2f ask=%.2f mid=%.2f delta=%.3f", symbol, desired_type.value, contract_symbol, expiry, strike, bid, ask, (bid + ask) / 2, delta)
    except Exception as exc:  # option logging must not stop a data scan
        LOGGER.warning("Option-chain logging failed for %s: %s", symbol, exc)

def _intraday_window(config: dict, calendar) -> tuple[datetime, datetime] | None:
    now = datetime.now(ZoneInfo("America/New_York"))
    settings = config["intraday"]
    if calendar is None:
        LOGGER.info("No Alpaca market calendar entry; intraday skipped")
        return None
    configured_start = time.fromisoformat(settings.get("start_time", "10:30"))
    market_open = calendar.open.replace(tzinfo=now.tzinfo).time()
    market_close = calendar.close.replace(tzinfo=now.tzinfo).time()
    start = max(configured_start, market_open)
    cutoff = min(time.fromisoformat(settings.get("cutoff_time", "14:00")), market_close)
    if not (start <= now.time() <= cutoff):
        return None
    session_start = datetime.combine(now.date(), market_open, tzinfo=now.tzinfo)
    return session_start, now


def _update_intraday_file(manager: DataManager, symbol: str, session_start: datetime,
                          now: datetime) -> pd.DataFrame:
    """Keep only the current session in each symbol's intraday Parquet file."""
    path = manager.intraday_path_for(symbol)
    existing = None
    if path.exists():
        existing = pd.read_parquet(path)
        existing.index = pd.to_datetime(existing.index).tz_localize(None)
        if existing.empty or existing.index[-1].date() != now.date():
            existing = None  # New day: overwrite yesterday's session.

    start = session_start
    if existing is not None and not existing.empty:
        start = existing.index[-1].to_pydatetime().replace(
            tzinfo=ZoneInfo("America/New_York")) + timedelta(minutes=1)
    incoming = manager.fetch_intraday_bars(symbol, start, now)
    if existing is None:
        combined = incoming
    elif incoming.empty:
        combined = existing
    else:
        combined = pd.concat([existing, incoming])
        combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    if combined is not None and not combined.empty:
        combined.to_parquet(path, index=True)
    return combined if combined is not None else pd.DataFrame()


def run_intraday(config_path: str) -> str:
    config = load_config(config_path)
    setup_logging(config.get("safety", {}).get("log_file", "logs/trade_bot.log"))
    manager = DataManager(config)
    calendar = manager.market_calendar(datetime.now(ZoneInfo("America/New_York")).date())
    window = _intraday_window(config, calendar)
    if window is None:
        LOGGER.info("Intraday outside trading window; skipping")
        return "Outside intraday window"
    symbols = manager.discover_symbols() if config["universe"].get("discover_via_alpaca", True) else list(config["universe"].get("symbols", []))
    symbols = list(dict.fromkeys([config["regime"]["symbol"], *symbols]))
    settings = config["intraday"]
    candidates = []
    for symbol in symbols:
        frame = _update_intraday_file(manager, symbol, *window)
        hits = scan_intraday_breakout(frame, **{key: settings[key] for key in (
            "lookback_bars", "volume_multiplier", "rsi_period", "rsi_min",
            "rsi_max", "min_breakout_pct", "fast_ma", "slow_ma")})
        if not hits.empty:
            row = hits.iloc[-1]
            candidates.append((symbol, row))
    LOGGER.info("Intraday candidates=%d symbols=%d", len(candidates), len(symbols))
    if candidates:
        names = ", ".join(symbol for symbol, _ in candidates)
        send_ntfy(f"Intraday candidates ({len(candidates)}): {names}", title="TradeBot intraday")
    return "Intraday"


def run(config_path: str, force_refresh: bool = False, submit: bool = False) -> str:
    config = load_config(config_path); setup_logging(config.get("safety", {}).get("log_file", "logs/trade_bot.log"))
    if config.get("safety", {}).get("kill_switch", False): raise RuntimeError("Kill switch is enabled")
    if submit and not config.get("execution", {}).get("enabled", False):
        raise RuntimeError("Order submission is disabled; set execution.enabled=true only after review")
    manager = DataManager(config)
    now_et = datetime.now(ZoneInfo("America/New_York"))
    calendar = manager.market_calendar(now_et.date())
    if calendar is None:
        LOGGER.info("No Alpaca market calendar entry; daily scan skipped")
        return "Non-trading day"
    market_open = calendar.open.replace(tzinfo=now_et.tzinfo)
    if now_et < market_open:
        LOGGER.info("Daily scan waits for market open at %s; skipping", market_open)
        return "Before market open"
    market_close = calendar.close.replace(tzinfo=now_et.tzinfo)
    if now_et > market_close:
        LOGGER.info("Daily scan window closed at %s; skipping", market_close)
        return "After market close"
    marker = Path(config.get("data", {}).get("daily_signal_marker", "data/daily/.last_signal_date"))
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == now_et.date().isoformat():
        LOGGER.info("Daily signal already evaluated for %s; skipping", now_et.date())
        return "Already evaluated"
    # At the open, yesterday is the latest completed daily candle.
    completed_date = now_et.date() - timedelta(days=1)
    symbols = manager.discover_symbols(as_of=completed_date) if config["universe"].get("discover_via_alpaca", True) else list(config["universe"].get("symbols", []))
    symbols = list(dict.fromkeys([config["regime"]["symbol"], *symbols]))
    logging.getLogger(__name__).info("Selected %d symbols", len(symbols))
    manager.update_data(symbols, force_refresh=force_refresh, today=completed_date)
    spy = manager.read(config["regime"]["symbol"], config["regime"]["ma_slow"])
    regime = detect_regime(spy, config["regime"]["ma_fast"], config["regime"]["ma_slow"])
    live_bars = int(config.get("selection", {}).get("live_scan_bars", 300))
    frames = {s: recent_frame(manager.read(s), live_bars) for s in symbols if manager.path_for(s).exists()}
    candidates = route(regime, frames, config)
    LOGGER.info("Regime=%s candidates=%s submit=%s", regime, len(candidates), submit)
    if candidates:
        names = ", ".join(f"{candidate.symbol} ({'bullish' if candidate.strategy == 'bullish_breakout' else 'bearish'})" for candidate in candidates)
        send_ntfy(f"Regime: {regime}\nCandidates ({len(candidates)}): {names}",
                  title="TradeBot daily candidates")
    for candidate in candidates:
        row = frames[candidate.symbol].loc[candidate.signal_date]
        LOGGER.info("CANDIDATE rank_score=%.1f symbol=%s strategy=%s signal_date=%s close=%.2f high=%.2f volume=%d metrics=%s", candidate.score, candidate.symbol, candidate.strategy, candidate.signal_date, row["close"], row["high"], row["volume"], candidate.metrics)
    for candidate in candidates[:int(config.get("execution", {}).get("max_option_logs", 20))]:
        direction = "bullish" if candidate.strategy == "bullish_breakout" else "bearish"
        _option_log(candidate.symbol, direction, config)
    LOGGER.info("Order submission remains disabled=%s", not config.get("execution", {}).get("enabled", False))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(now_et.date().isoformat(), encoding="utf-8")
    return regime

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--config", default="config/config.yaml"); parser.add_argument("--force-refresh", action="store_true"); parser.add_argument("--submit", action="store_true"); parser.add_argument("--mode", choices=("daily", "intraday"), default="daily")
    args = parser.parse_args()
    try:
        run_intraday(args.config) if args.mode == "intraday" else run(args.config, args.force_refresh, args.submit)
    except Exception as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).exception("TradeBot run failed")
        send_ntfy(f"TradeBot {args.mode} run failed: {type(exc).__name__}: {exc}",
                  title=f"TradeBot {args.mode} failure", priority=5)
        raise
