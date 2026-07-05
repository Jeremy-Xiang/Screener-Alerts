"""
thesis_router.py — Real integration for THESIS, written against your
actual main.py / scheduler.py / config.py, not a generic template.

Lives inside src/, alongside notifier.py and screener.py — its relative
imports (`.notifier`, `.screener`) depend on that, so when you copy this
project's src/ folder into your THESIS backend (e.g. as
`backend/screener/`), this file comes along with it unchanged.

Matches your existing conventions on purpose:
  - every route is @limiter.limit(...)'d, same as every route in main.py
  - ticker validation mirrors main.py's `all(c.isalpha() or c in "-." for
    c in ticker)` pattern used on /api/analyze/{ticker} and
    /api/signals/ticker/{ticker}
  - errors raise HTTPException with the same plain-detail style as the
    rest of main.py, not a different error shape

A NOTE ON DATA, READ BEFORE WIRING THIS IN:
Your PriceFetcher (`app.state.prices`) only carries Close prices — every
feature in prediction/features.py is Close-only, no Volume. The screener's
`volume_spike` rule needs Volume, which isn't in that pipeline. Rather than
guess at extending data/prices.py without having seen it, this router keeps
the screener on its OWN data fetch (same yfinance-based src/data.py this
project already uses) instead of trying to share app.state.prices. That
means one additional fetch path running alongside your existing
PriceFetcher, not a shared one — a deliberate tradeoff, not an oversight.
If you later extend PriceFetcher to carry OHLCV instead of Close-only,
swap src/data.py's `load_ohlcv()` to read from `app.state.prices` instead
and every rule benefits, volume_spike included.
"""

from __future__ import annotations

import logging
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import APIRouter, HTTPException, Query, Request

from .notifier import ConsoleNotifier, FileNotifier, MultiNotifier, WebhookNotifier
from .screener import scan_and_notify

logger = logging.getLogger(__name__)

LOG_PATH = os.environ.get("SCREENER_LOG_PATH", "screener_alerts_log.jsonl")
SCAN_HOUR = int(os.environ.get("SCREENER_SCAN_HOUR", "7"))  # 7am ET — after your 9:31 open job would be redundant with yesterday's close data


def _screener_universe() -> list[str]:
    """Real 52-ticker universe, derived from config.THEMES exactly like
    main.py's own VALID_TICKERS — not a second hardcoded list living
    out of sync with the real one."""
    from config import THEMES

    return sorted({t for cfg in THEMES.values() for t in cfg["tickers"]})


def _build_notifier() -> MultiNotifier:
    notifiers = [FileNotifier(LOG_PATH), ConsoleNotifier()]
    webhook_url = os.environ.get("NOTIFIER_WEBHOOK_URL")
    if webhook_url:
        notifiers.append(WebhookNotifier(webhook_url))
    return MultiNotifier(notifiers)


def run_scheduled_scan() -> None:
    alerts = scan_and_notify(_screener_universe(), _build_notifier())
    logger.info("Screener scan complete: %d alert(s).", len(alerts))


def register_screener_job(scheduler: BackgroundScheduler) -> None:
    """
    Call this from scheduler.py's start_scheduler(), on the SAME
    BackgroundScheduler instance it already creates — see the literal
    one-line addition in the integration notes. Don't construct a second
    BackgroundScheduler here; start_scheduler() already owns the one
    scheduler this whole backend uses.
    """
    scheduler.add_job(run_scheduled_scan, CronTrigger(hour=SCAN_HOUR), id="screener_daily_scan", replace_existing=True)


def build_router(limiter) -> APIRouter:
    """
    Takes main.py's existing `limiter` object as a parameter rather than
    constructing a second Limiter here — slowapi tracks rate-limit state
    per Limiter instance, so a second instance would track its own
    request counts independently of every other endpoint's, which isn't
    what you want for a shared rate-limit policy.
    """
    router = APIRouter()

    @router.get("/health")
    @limiter.limit("30/minute")
    async def screener_health(request: Request):
        return {"status": "ok", "tickers_watched": len(_screener_universe()), "scan_hour": SCAN_HOUR}

    @router.get("/alerts")
    @limiter.limit("60/minute")
    async def get_screener_alerts(
        request: Request,
        limit: int = Query(50, ge=1, le=500),
        severity: str = Query(None, max_length=20),
        ticker: str = Query(None, max_length=10),
    ):
        import json

        if ticker:
            ticker = ticker.upper().strip()
            if not all(c.isalpha() or c in "-." for c in ticker):
                raise HTTPException(400, "Invalid ticker symbol.")

        if not os.path.exists(LOG_PATH):
            return {"alerts": [], "count": 0}

        records = []
        with open(LOG_PATH) as f:
            for line in f:
                record = json.loads(line)
                if severity and record["severity"] != severity:
                    continue
                if ticker and record["ticker"] != ticker:
                    continue
                records.append(record)

        records = records[-limit:][::-1]
        return {"alerts": records, "count": len(records)}

    @router.post("/admin/scan")
    @limiter.limit("5/minute")
    async def trigger_screener_scan(request: Request):
        alerts = scan_and_notify(_screener_universe(), _build_notifier())
        return {"alerts_fired": len(alerts)}

    return router
