"""
run_screener.py — CLI entry point.

    python run_screener.py --tickers AAPL,MSFT,NVDA
    python run_screener.py --tickers-file my_tickers.txt --notifier file --log-path alerts.jsonl
    python run_screener.py --basket --notifier console
"""

from __future__ import annotations

import argparse

from src.notifier import ConsoleNotifier, FileNotifier
from src.screener import scan_and_notify

DEFAULT_BASKET = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META",
    "JPM", "BAC", "GS", "XOM", "CVX",
    "JNJ", "PG", "KO", "PEP", "TSLA", "RIVN", "WMT", "COST",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", default=None, help="Comma-separated tickers")
    parser.add_argument("--tickers-file", default=None)
    parser.add_argument("--basket", action="store_true", help="Use the built-in sector-diverse default basket")
    parser.add_argument("--notifier", choices=["console", "file"], default="console",
                         help="Use 'console' for stdout, 'file' for a JSONL log. For webhook/email, "
                              "construct WebhookNotifier/EmailNotifier directly — see README.")
    parser.add_argument("--log-path", default="alerts_log.jsonl")
    parser.add_argument("--period", default="1y")
    args = parser.parse_args()

    if args.tickers_file:
        with open(args.tickers_file) as f:
            tickers = [line.strip().upper() for line in f if line.strip()]
    elif args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = DEFAULT_BASKET

    notifier = FileNotifier(args.log_path) if args.notifier == "file" else ConsoleNotifier()

    print(f"Scanning {len(tickers)} tickers across {6} rules...")
    alerts = scan_and_notify(tickers, notifier, period=args.period)

    print(f"\n{len(alerts)} alert(s) fired.")
    if args.notifier == "file":
        print(f"Written to: {args.log_path}")


if __name__ == "__main__":
    main()
