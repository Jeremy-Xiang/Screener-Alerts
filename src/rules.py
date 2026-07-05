"""
rules.py — Each rule is a plain function: (ticker, indicator_df) -> Alert
or None. A rule fires based on a CHANGE (a crossover, a breakout, a
single-day move) wherever that distinction matters, not just "is the
value currently above some threshold" — the latter would fire every day
for weeks once a stock drifts past a level, which makes for a useless
alert feed.

Add new rules by writing a new function with this same signature and
adding it to ALL_RULES at the bottom — that's the intended extension point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd


@dataclass
class Alert:
    ticker: str
    rule: str
    severity: str  # "info" | "warning" | "critical"
    message: str
    data: dict


def _last_two_valid(series: pd.Series):
    """Last two non-NaN values, or None if there aren't two yet (e.g. early in a short series)."""
    valid = series.dropna()
    if len(valid) < 2:
        return None
    return valid.iloc[-2], valid.iloc[-1]


def rsi_extreme(ticker: str, df: pd.DataFrame) -> Optional[Alert]:
    rsi = df["rsi_14"].iloc[-1]
    if pd.isna(rsi):
        return None
    if rsi >= 70:
        return Alert(ticker, "rsi_extreme", "warning", f"RSI14={rsi:.1f} — overbought (>=70)", {"rsi_14": round(rsi, 1)})
    if rsi <= 30:
        return Alert(ticker, "rsi_extreme", "warning", f"RSI14={rsi:.1f} — oversold (<=30)", {"rsi_14": round(rsi, 1)})
    return None


def sma_crossover(ticker: str, df: pd.DataFrame) -> Optional[Alert]:
    diff = df["sma_20"] - df["sma_50"]
    pair = _last_two_valid(diff)
    if pair is None:
        return None
    yesterday, today = pair
    if yesterday <= 0 < today:
        return Alert(ticker, "sma_crossover", "info", "Golden cross — SMA20 crossed above SMA50", {"sma_20": round(df['sma_20'].iloc[-1], 2), "sma_50": round(df['sma_50'].iloc[-1], 2)})
    if yesterday >= 0 > today:
        return Alert(ticker, "sma_crossover", "info", "Death cross — SMA20 crossed below SMA50", {"sma_20": round(df['sma_20'].iloc[-1], 2), "sma_50": round(df['sma_50'].iloc[-1], 2)})
    return None


def large_single_day_move(ticker: str, df: pd.DataFrame, threshold_pct: float = 5.0) -> Optional[Alert]:
    move = df["daily_return_pct"].iloc[-1]
    if pd.isna(move):
        return None
    if abs(move) >= threshold_pct:
        direction = "up" if move > 0 else "down"
        return Alert(ticker, "large_single_day_move", "critical", f"Moved {direction} {abs(move):.1f}% in one day", {"daily_return_pct": round(move, 1)})
    return None


def volume_spike(ticker: str, df: pd.DataFrame, threshold_ratio: float = 3.0) -> Optional[Alert]:
    ratio = df["volume_ratio"].iloc[-1]
    if pd.isna(ratio):
        return None
    if ratio >= threshold_ratio:
        return Alert(ticker, "volume_spike", "warning", f"Volume {ratio:.1f}x its 20-day average", {"volume_ratio": round(ratio, 1)})
    return None


def fifty_two_week_breakout(ticker: str, df: pd.DataFrame) -> Optional[Alert]:
    # Compare today's close against the 52w high/low AS OF YESTERDAY (shifted),
    # so this only fires the day a new extreme is actually made, not every
    # day afterward that the price happens to still be near it.
    prior_high = df["high_52w"].shift(1).iloc[-1]
    prior_low = df["low_52w"].shift(1).iloc[-1]
    close = df["Close"].iloc[-1]

    if pd.isna(prior_high) or pd.isna(prior_low):
        return None
    if close > prior_high:
        return Alert(ticker, "fifty_two_week_breakout", "info", f"New 52-week high: {close:.2f}", {"close": round(close, 2), "prior_52w_high": round(prior_high, 2)})
    if close < prior_low:
        return Alert(ticker, "fifty_two_week_breakout", "info", f"New 52-week low: {close:.2f}", {"close": round(close, 2), "prior_52w_low": round(prior_low, 2)})
    return None


def volatility_breakout(ticker: str, df: pd.DataFrame, ratio_threshold: float = 1.6) -> Optional[Alert]:
    vol = df["volatility_21d"]
    baseline = vol.rolling(60).mean()
    today_vol = vol.iloc[-1]
    today_baseline = baseline.iloc[-1]
    if pd.isna(today_vol) or pd.isna(today_baseline) or today_baseline == 0:
        return None
    ratio = today_vol / today_baseline
    if ratio >= ratio_threshold:
        return Alert(ticker, "volatility_breakout", "warning", f"21d volatility {today_vol:.1f}% is {ratio:.1f}x its 60-day baseline", {"volatility_21d": round(today_vol, 1), "ratio_vs_baseline": round(ratio, 2)})
    return None


ALL_RULES: list[Callable[[str, pd.DataFrame], Optional[Alert]]] = [
    rsi_extreme,
    sma_crossover,
    large_single_day_move,
    volume_spike,
    fifty_two_week_breakout,
    volatility_breakout,
]
