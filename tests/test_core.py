"""
Tests for screener-alerts. Run: pytest tests/ -v

The core promise of this project is EVENT semantics — a crossover fires
the day it crosses and never again, a breakout fires the day the new
extreme is made and never again. These tests pin that behavior with
constructed cases where the right answer is unambiguous.
"""

import json

import numpy as np
import pandas as pd
import pytest

from src.data import load_ohlcv
from src.indicators import compute_indicators
from src.notifier import ConsoleNotifier, FileNotifier, MultiNotifier
from src.rules import (
    Alert,
    fifty_two_week_breakout,
    large_single_day_move,
    rsi_extreme,
    sma_crossover,
)
from src.screener import scan_ticker


def test_crossover_fires_only_on_actual_cross():
    golden = pd.DataFrame({"sma_20": [45, 46, 48, 51], "sma_50": [50] * 4})
    death = pd.DataFrame({"sma_20": [55, 53, 51, 48], "sma_50": [50] * 4})
    no_event = pd.DataFrame({"sma_20": [55, 56, 57, 58], "sma_50": [50] * 4})

    assert sma_crossover("T", golden).message.startswith("Golden cross")
    assert sma_crossover("T", death).message.startswith("Death cross")
    assert sma_crossover("T", no_event) is None  # already above ≠ crossed today


def test_breakout_fires_once_not_every_day_after():
    """close exceeds yesterday's 52w high -> fires; close still elevated but
    below the NEW high the next day -> silent."""
    n = 300
    close = np.linspace(100, 120, n)
    close[-1] = 125  # new high made today
    df = pd.DataFrame({"Close": close})
    df["high_52w"] = df["Close"].rolling(252, min_periods=1).max()
    df["low_52w"] = df["Close"].rolling(252, min_periods=1).min()
    assert fifty_two_week_breakout("T", df) is not None

    # next day: below the new high — must NOT fire again
    close2 = np.append(close, 124.0)
    df2 = pd.DataFrame({"Close": close2})
    df2["high_52w"] = df2["Close"].rolling(252, min_periods=1).max()
    df2["low_52w"] = df2["Close"].rolling(252, min_periods=1).min()
    assert fifty_two_week_breakout("T", df2) is None


def test_large_move_threshold():
    df_big = pd.DataFrame({"daily_return_pct": [1.0, -6.2]})
    df_small = pd.DataFrame({"daily_return_pct": [1.0, 3.0]})
    a = large_single_day_move("T", df_big)
    assert a is not None and a.severity == "critical"
    assert large_single_day_move("T", df_small) is None


def test_rsi_extremes_and_neutral():
    assert rsi_extreme("T", pd.DataFrame({"rsi_14": [50, 75]})) is not None
    assert rsi_extreme("T", pd.DataFrame({"rsi_14": [50, 25]})) is not None
    assert rsi_extreme("T", pd.DataFrame({"rsi_14": [50, 55]})) is None


def test_indicators_complete():
    df = compute_indicators(load_ohlcv("AAPL"))
    for col in ("sma_20", "sma_50", "rsi_14", "volatility_21d", "volume_ratio", "high_52w"):
        assert col in df.columns
    assert df["rsi_14"].dropna().between(0, 100).all()


def test_scan_returns_alert_objects():
    alerts = scan_ticker("NVDA")
    assert all(isinstance(a, Alert) for a in alerts)
    assert all(a.severity in {"info", "warning", "critical"} for a in alerts)


def test_file_notifier_and_fanout(tmp_path):
    path = str(tmp_path / "log.jsonl")
    alerts = [Alert("AAPL", "rsi_extreme", "warning", "m", {"rsi_14": 75.0})]
    MultiNotifier([ConsoleNotifier(), FileNotifier(path)]).send(alerts)
    lines = open(path).readlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["ticker"] == "AAPL" and "timestamp" in record
