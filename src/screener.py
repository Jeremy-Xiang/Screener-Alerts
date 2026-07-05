"""
screener.py — Runs every rule in rules.ALL_RULES against every ticker in a
universe, and hands whatever fires to a Notifier. This is the only
function the CLI, the scheduled job, and the API all call.
"""

from __future__ import annotations

from .data import load_ohlcv
from .indicators import compute_indicators
from .notifier import Notifier
from .rules import ALL_RULES, Alert


def scan_ticker(ticker: str, period: str = "1y") -> list[Alert]:
    df = load_ohlcv(ticker, period=period)
    if len(df) < 60:
        print(f"[screener.py] Skipping {ticker}: not enough history ({len(df)} rows)")
        return []

    indicators = compute_indicators(df)
    alerts = []
    for rule in ALL_RULES:
        alert = rule(ticker, indicators)
        if alert is not None:
            alerts.append(alert)
    return alerts


def scan_universe(tickers: list[str], period: str = "1y") -> list[Alert]:
    all_alerts = []
    for ticker in tickers:
        all_alerts.extend(scan_ticker(ticker, period=period))
    return all_alerts


def scan_and_notify(tickers: list[str], notifier: Notifier, period: str = "1y") -> list[Alert]:
    alerts = scan_universe(tickers, period=period)
    notifier.send(alerts)
    return alerts
