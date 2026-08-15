"""Daily pipeline: local data -> regime -> signals."""
from __future__ import annotations
import argparse
import logging
import os
import re
from datetime import date, timedelta
from src.data_manager import DataManager
from src.regime import detect_regime
from src.strategy_router import route
from src.utils import load_config, setup_logging
from src.notifications import send_ntfy

LOGGER = logging.getLogger(__name__)

def _decode_occ(symbol: str) -> tuple[str, str] | None:
    match = re.search(r"([A-Z0-9.]{1,6})(\d{6})([CP])(\d{8})$", symbol)
    if not match:
        return None
    expiry = "20" + match.group(2)[:2] + "-" + match.group(2)[2:4] + "-" + match.group(2)[4:]
    strike = f"{int(match.group(4)) / 1000:.2f}"
    return expiry, strike

def _option_log(symbol: str, regime: str, config: dict) -> None:
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
        desired_type = ContractType.CALL if regime == "Bullish" else ContractType.PUT
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

def run(config_path: str, force_refresh: bool = False, submit: bool = False) -> str:
    config = load_config(config_path); setup_logging(config.get("safety", {}).get("log_file", "logs/trade_bot.log"))
    if config.get("safety", {}).get("kill_switch", False): raise RuntimeError("Kill switch is enabled")
    if submit and not config.get("execution", {}).get("enabled", False):
        raise RuntimeError("Order submission is disabled; set execution.enabled=true only after review")
    manager = DataManager(config)
    symbols = manager.discover_symbols() if config["universe"].get("discover_via_alpaca", True) else list(config["universe"].get("symbols", []))
    symbols = list(dict.fromkeys([config["regime"]["symbol"], *symbols]))
    logging.getLogger(__name__).info("Selected %d symbols", len(symbols))
    manager.update_data(symbols, force_refresh=force_refresh)
    spy = manager.read(config["regime"]["symbol"], config["regime"]["ma_slow"])
    regime = detect_regime(spy, config["regime"]["ma_fast"], config["regime"]["ma_slow"])
    frames = {s: manager.read(s) for s in symbols if manager.path_for(s).exists()}
    candidates = route(regime, frames, config)
    LOGGER.info("Regime=%s candidates=%s submit=%s", regime, len(candidates), submit)
    if candidates:
        names = ", ".join(candidate.symbol for candidate in candidates)
        send_ntfy(f"Regime: {regime}\nCandidates ({len(candidates)}): {names}",
                  title="TradeBot candidates")
    for candidate in candidates:
        row = frames[candidate.symbol].loc[candidate.signal_date]
        LOGGER.info("CANDIDATE rank_score=%.1f symbol=%s strategy=%s signal_date=%s close=%.2f high=%.2f volume=%d metrics=%s", candidate.score, candidate.symbol, candidate.strategy, candidate.signal_date, row["close"], row["high"], row["volume"], candidate.metrics)
    for candidate in candidates[:int(config.get("execution", {}).get("max_option_logs", 20))]:
        _option_log(candidate.symbol, regime, config)
    LOGGER.info("Order submission remains disabled=%s", not config.get("execution", {}).get("enabled", False))
    return regime

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--config", default="config/config.yaml"); parser.add_argument("--force-refresh", action="store_true"); parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    try:
        run(args.config, args.force_refresh, args.submit)
    except Exception as exc:
        logging.basicConfig(level=logging.ERROR)
        logging.getLogger(__name__).exception("TradeBot run failed")
        send_ntfy(f"TradeBot run failed: {type(exc).__name__}: {exc}",
                  title="TradeBot failure", priority=5)
        raise
