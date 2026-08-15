# Regime-Adaptive Options Income System

Systematic Alpaca paper-trading framework for local daily bars, SPY regime detection, breakout/breakdown scanning, defined-risk option structures, sizing, and deterministic exits. There is no LLM or discretionary decision layer.

## Safety

Paper trading is enabled by `paper: true`. Use a dedicated Alpaca account and validate every multi-leg order in paper mode. This is not financial advice. The daily runner intentionally does not submit orders until chain selection, account checks, persisted trade metadata, and risk approval are wired around the execution adapter.

## Setup

Use Python 3.10+, install `requirements.txt`, and create `.env` with `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`. Run from the repository root. Daily data is stored in `data/daily/<SYMBOL>.parquet`; `data/metadata.json` records the last successful bar date.

- `python main.py --force-refresh`
- `python main.py`
- `python monitor_positions.py`
- `pytest -q`
- `python backtest.py --side bullish --horizon 20 --output results/bullish.csv`

## Modules

- `src/data_manager.py`: validated incremental Parquet storage.
- `src/regime.py`: exact SPY 50/200 moving-average rules.
- `src/scanners.py`: pure breakout, breakdown, and low-ATR scans.
- `src/options.py`: liquidity filters, delta selection, credit spreads, and iron-condor max-profit/loss math.
- `src/risk.py`: equity-based per-trade and portfolio risk limits.
- `src/execution.py`: Alpaca MLEG limit-order adapter.
- `src/monitor.py`: profit, stop, and time-stop decisions.
- `backtest.py`: evaluates historical scanner signals against forward underlying returns.

## Signal backtest

The backtest walks each local Parquet file chronologically. For every date it
uses only data available through that date, applies the configured breakout or
breakdown scanner, enters at the next bar's open, and exits after the requested
number of trading bars at the close. It reports signal count, win rate, average,
median, best, and worst directional returns and can write every trade to CSV.

This is an underlying-price test, not an options-profit test. It is useful for
answering whether the 56 historical setups were followed by meaningful moves,
but it does not model option premium, implied volatility, bid/ask spread,
slippage, theta, or contract selection. A later options backtest must use
historical option quotes for the exact contracts selected on each signal date.

## Dynamic universe discovery

By default, the daily runner calls Alpaca's Trading API for active, tradable US
equity assets, then calls Alpaca's historical data API in batches. It filters by
the configured price and average-volume thresholds and ranks the result by
average dollar volume over `discovery_lookback_days`. `max_discovered_symbols`
limits the scan, and SPY is always retained for regime detection. Set
`discover_via_alpaca: false` to use the configured `symbols` fallback. Discovery
requires the same API credentials as historical data and is performed before
the local incremental update.

Before live use, add persistent trade metadata (strategy, entry value/date, legs, quantity), order-status reconciliation, buying-power checks, and a daily-loss circuit breaker around execution. Never infer entry values from current broker positions.
