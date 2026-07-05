"""
indicators.py — Computes a full indicator time series (not just a single
latest-day snapshot). Rules that care about a *crossover* (SMA20 crossing
SMA50, volatility breaking out of its recent range) need yesterday's value
as well as today's — a snapshot of "SMA20 is currently above SMA50" can't
distinguish "crossed today" from "has been above for three weeks," and
those are very different signals to alert on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)  # neutral where undefined (e.g. avg_loss==0 early on)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with added columns: sma_20, sma_50, rsi_14, volatility_21d,
    daily_return_pct, avg_volume_20d, volume_ratio, high_52w, low_52w."""
    out = df.copy()
    close = out["Close"]

    out["sma_20"] = close.rolling(20).mean()
    out["sma_50"] = close.rolling(50).mean()
    out["rsi_14"] = _rsi(close, 14)

    daily_returns = close.pct_change()
    out["daily_return_pct"] = daily_returns * 100
    out["volatility_21d"] = daily_returns.rolling(21).std() * np.sqrt(252) * 100

    out["avg_volume_20d"] = out["Volume"].rolling(20).mean()
    out["volume_ratio"] = out["Volume"] / out["avg_volume_20d"].replace(0, np.nan)

    out["high_52w"] = close.rolling(252, min_periods=1).max()
    out["low_52w"] = close.rolling(252, min_periods=1).min()

    return out
