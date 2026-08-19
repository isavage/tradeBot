"""Pure regime-to-strategy routing."""
from __future__ import annotations
from dataclasses import dataclass
import logging
import pandas as pd
from .scanners import scan_breakdowns, scan_breakouts, scan_range_bound

LOGGER = logging.getLogger(__name__)

@dataclass(frozen=True)
class Candidate:
    symbol: str; strategy: str; signal_date: object; score: float; metrics: dict

def route(regime: str, symbol_frames: dict[str, pd.DataFrame], config: dict) -> list[Candidate]:
    result = []
    b = config["breakout"]
    for symbol, frame in symbol_frames.items():
        selection = config.get("selection", {})
        latest_only = selection.get("require_signal_on_latest_bar", True)
        max_age_days = int(selection.get("signal_max_age_days", 0))
        today = pd.Timestamp(frame.index[-1])

        scans = [(scan_breakouts(frame, **b), "bullish_breakout"),
                 (scan_breakdowns(frame, b["lookback_days"], b["volume_multiplier"],
                                  b.get("require_trend_alignment", True)), "bearish_breakdown")]
        for hits, strategy in scans:
            latest = None
            selected_signal_date = None
            counts = hits.attrs.get("filter_counts", {})
            if strategy == "bullish_breakout":
                LOGGER.info("Signal filters symbol=%s direction=bullish bars=%d breakout=%d volume=%d rsi=%d trend=%d signals=%d",
                            symbol, counts.get("total_bars", 0), counts.get("breakout", 0),
                            counts.get("volume", 0), counts.get("rsi", 0),
                            counts.get("trend", 0), counts.get("signals", 0))
            else:
                LOGGER.info("Signal filters symbol=%s direction=bearish bars=%d breakdown=%d volume=%d trend=%d signals=%d",
                            symbol, counts.get("total_bars", 0), counts.get("breakdown", 0),
                            counts.get("volume", 0), counts.get("trend", 0), counts.get("signals", 0))
            if not hits.empty:
            # A recent trigger can still be actionable, but only if the
            # breakout has held. This avoids treating a failed old breakout
            # as a fresh entry signal.
                candidates = hits.iloc[::-1]
                for signal_date, signal in candidates.iterrows():
                    age = (today.normalize() - pd.Timestamp(signal_date).normalize()).days
                    if latest_only and age != 0:
                        continue
                    if not latest_only and age > max_age_days:
                        continue
                    if age < 0:
                        continue
                    current = frame.iloc[-1]
                    if strategy == "bullish_breakout":
                        trend_holds = bool(current["close"] > current["ma20"] > current["ma50"] > current["ma200"])
                        if current["close"] < signal["close"] or not trend_holds:
                            continue
                    else:
                        trend_holds = bool(current["close"] < current["ma20"] < current["ma50"])
                        if current["close"] > signal["close"] or not trend_holds:
                            continue
                    latest = signal
                    selected_signal_date = signal_date
                    break
            if latest is not None:
                metrics = {key: float(latest[key]) for key in ("rsi", "volume_ratio", "breakout_pct", "breakdown_pct") if key in latest and pd.notna(latest[key])}
                result.append(Candidate(symbol, strategy, selected_signal_date, float(latest.get("score", 0.0)), metrics))
    return sorted(result, key=lambda candidate: candidate.score, reverse=True)[:int(config.get("selection", {}).get("max_candidates_per_day", 5))]
