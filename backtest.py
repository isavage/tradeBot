"""Historical underlying-signal backtest.

This evaluates whether scanner signals were followed by a meaningful underlying
move. It does not pretend to model option fills, spreads, or Greeks.
"""
from __future__ import annotations
import argparse
import logging
from pathlib import Path
import pandas as pd
from src.scanners import scan_breakdowns, scan_breakouts
from src.utils import load_config

LOGGER = logging.getLogger(__name__)

def evaluate_symbol(frame: pd.DataFrame, symbol: str, side: str, config: dict, horizon: int) -> list[dict]:
    frame = frame.sort_index().copy()
    breakout = config["breakout"]
    warmup = max(200, int(breakout["lookback_days"]))
    trades: list[dict] = []
    signals = (scan_breakouts(frame, **breakout) if side == "bullish"
               else scan_breakdowns(frame, breakout["lookback_days"], breakout["volume_multiplier"]))
    signal_positions = [frame.index.get_loc(signal_date) for signal_date in signals.index]
    for position in signal_positions:
        if position < warmup or position + horizon + 1 >= len(frame):
            continue
        entry = frame.iloc[position + 1]
        exit_bar = frame.iloc[position + 1 + horizon]
        entry_price = float(entry["open"])
        exit_price = float(exit_bar["close"])
        underlying_return = exit_price / entry_price - 1
        strategy_return = underlying_return if side == "bullish" else -underlying_return
        signal = signals.loc[frame.index[position]]
        trades.append({"symbol": symbol, "signal_date": pd.Timestamp(frame.index[position]).date().isoformat(),
                       "entry_date": pd.Timestamp(frame.index[position + 1]).date().isoformat(),
                       "exit_date": pd.Timestamp(frame.index[position + 1 + horizon]).date().isoformat(),
                       "entry_price": entry_price, "exit_price": exit_price,
                       "underlying_return": underlying_return, "strategy_directional_return": strategy_return,
                       "score": float(signal.get("score", 0.0)),
                       "volume_ratio": float(signal.get("volume_ratio", 0.0))})
    return trades

def summarize(trades: pd.DataFrame, side: str, horizon: int) -> None:
    if trades.empty:
        print(f"No {side} signals with {horizon} forward bars were found.")
        return
    returns = trades["strategy_directional_return"]
    print(f"Signals: {len(trades)}")
    print(f"Symbols: {trades['symbol'].nunique()}")
    print(f"Directional win rate: {(returns > 0).mean():.1%}")
    print(f"Average forward return: {returns.mean():.2%}")
    print(f"Median forward return: {returns.median():.2%}")
    print(f"Average winner: {returns[returns > 0].mean():.2%}" if (returns > 0).any() else "Average winner: n/a")
    print(f"Average loser: {returns[returns <= 0].mean():.2%}" if (returns <= 0).any() else "Average loser: n/a")
    print(f"Best / worst: {returns.max():.2%} / {returns.min():.2%}")

def run(config_path: str = "config/config.yaml", side: str = "bullish", horizon: int = 20,
        data_dir: str | None = None, output: str | None = None) -> pd.DataFrame:
    config = load_config(config_path)
    directory = Path(data_dir or config["data"]["data_dir"])
    rows: list[dict] = []
    for path in sorted(directory.glob("*.parquet")):
        try:
            frame = pd.read_parquet(path)
            rows.extend(evaluate_symbol(frame, path.stem, side, config, horizon))
        except (ValueError, KeyError) as exc:
            LOGGER.warning("Skipping %s: %s", path.name, exc)
    trades = pd.DataFrame(rows)
    if not trades.empty:
        trades = trades.sort_values(["signal_date", "score"], ascending=[True, False]).reset_index(drop=True)
    summarize(trades, side, horizon)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        trades.to_csv(output, index=False)
        print(f"Wrote detailed results to {output}")
    return trades

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest underlying scanner signals using local Parquet data")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--side", choices=["bullish", "bearish"], default="bullish")
    parser.add_argument("--horizon", type=int, default=20, help="Forward trading bars")
    parser.add_argument("--data-dir")
    parser.add_argument("--output", default="backtest_results.csv")
    args = parser.parse_args()
    if args.horizon < 1:
        parser.error("--horizon must be positive")
    run(args.config, args.side, args.horizon, args.data_dir, args.output)
