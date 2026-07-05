"""
data.py — OHLCV loader. Same yfinance-first, synthetic-fallback pattern as
every sibling project in this series. The synthetic fallback occasionally
injects a deliberate "event" (a multi-day trend break or volume spike) so
the screener has something real to catch when testing offline — see
_inject_event() below.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .seed import stable_seed


def load_ohlcv(ticker: str, period: str = "1y") -> pd.DataFrame:
    try:
        import yfinance as yf

        df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if df is None or df.empty:
            raise RuntimeError("yfinance returned no data")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    except Exception as exc:  # noqa: BLE001
        print(f"[data.py] Live fetch failed for {ticker} ({exc}). Using synthetic fallback.")
        return _synthetic_ohlcv(seed=stable_seed(ticker))


def _synthetic_ohlcv(n_days: int = 300, seed: int = 0, start_price: float = 100.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n_days)

    drift = rng.uniform(-0.0003, 0.0008)
    vol = rng.uniform(0.010, 0.025)
    daily_returns = rng.normal(loc=drift, scale=vol, size=n_days)
    close = start_price * np.exp(np.cumsum(daily_returns))
    volume = rng.integers(1_000_000, 20_000_000, size=n_days).astype(float)

    close, volume = _inject_event(close, volume, rng)

    open_ = np.empty(n_days)
    open_[0] = start_price
    open_[1:] = close[:-1] * (1 + rng.normal(0, 0.003, size=n_days - 1))
    intraday_range = np.abs(rng.normal(0.006, 0.004, size=n_days)) * close
    high = np.maximum(open_, close) + intraday_range
    low = np.minimum(open_, close) - intraday_range

    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume}, index=dates
    )


def _inject_event(close: np.ndarray, volume: np.ndarray, rng: np.random.Generator):
    """
    About 1 in 3 synthetic tickers gets a deliberate event in the last 10
    trading days — either a sharp single-day move + volume spike, or a
    short trend reversal. Without this, every screener rule would either
    always fire (random walk drifts trip RSI eventually) or basically
    never fire in an interesting, attributable way on synthetic data,
    making it hard to tell "the rule works" from "nothing happened."
    """
    n = len(close)
    if rng.random() > 0.33:
        return close, volume  # most tickers: no scripted event, just noise

    event_day = n - rng.integers(3, 10)
    event_type = rng.choice(["spike", "reversal"])

    if event_type == "spike":
        shock = rng.uniform(0.06, 0.14) * rng.choice([-1, 1])
        close[event_day:] = close[event_day:] * (1 + shock)
        volume[event_day] *= rng.uniform(3, 6)
    else:
        direction = rng.choice([-1, 1])
        trend = np.linspace(0, direction * rng.uniform(0.08, 0.15), n - event_day)
        close[event_day:] = close[event_day:] * (1 + trend)

    return close, volume
