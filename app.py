"""
app.py — FastAPI service: scheduled scans + queryable alert history.

Same APScheduler pattern as stock-forecast-bench's app.py: a cron job runs
the scan once a day and appends to a JSONL log via FileNotifier; API reads
serve from that log rather than re-scanning on every request.

    uvicorn app:app --reload --port 8005
    curl http://localhost:8005/alerts?limit=20
    ADMIN_TOKEN=... uvicorn app:app --port 8005   # enable admin routes
    curl -X POST http://localhost:8005/admin/scan -H "X-Admin-Token: $ADMIN_TOKEN"

Set NOTIFIER_WEBHOOK_URL to also fan alerts out to Slack/Discord on every
scheduled scan (see notifier.py) — leave unset to log to file only.

Security env vars:
  ADMIN_TOKEN       shared secret for /admin/*; unset => admin routes disabled.
  ALLOWED_ORIGINS   comma-separated CORS allowlist; unset => "*" (dev only).
"""

from __future__ import annotations

import json
import os

import secrets

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.notifier import ConsoleNotifier, FileNotifier, MultiNotifier, WebhookNotifier
from src.screener import scan_and_notify
from run_screener import DEFAULT_BASKET

TICKERS = os.environ.get("SCREENER_TICKERS", ",".join(DEFAULT_BASKET)).split(",")
SCAN_HOUR = int(os.environ.get("SCREENER_SCAN_HOUR", "6"))  # 6am server time, before market open
LOG_PATH = os.environ.get("SCREENER_LOG_PATH", "alerts_log.jsonl")

# Comma-separated allowlist of browser origins, e.g. "https://thesis.jeremyxiang.com".
# Falls back to "*" for local dev; set it in production to lock the API to your frontend.
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]

# Shared secret guarding the /admin/* endpoints. Unset => admin routes are disabled
# (fail closed) so a manual scan can never be triggered by an anonymous caller.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")


def _require_admin(token: str | None) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin endpoints disabled: set ADMIN_TOKEN to enable them.")
    if not token or not secrets.compare_digest(token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token.")

scheduler = BackgroundScheduler()


def _build_notifier():
    notifiers = [FileNotifier(LOG_PATH), ConsoleNotifier()]
    webhook_url = os.environ.get("NOTIFIER_WEBHOOK_URL")
    if webhook_url:
        notifiers.append(WebhookNotifier(webhook_url))
    return MultiNotifier(notifiers)


def run_scheduled_scan():
    notifier = _build_notifier()
    alerts = scan_and_notify(TICKERS, notifier)
    print(f"[app] Scheduled scan complete: {len(alerts)} alert(s).")


from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app_: FastAPI):
    # Lifespan pattern (matches THESIS's own main.py; @app.on_event is deprecated)
    scheduler.add_job(run_scheduled_scan, CronTrigger(hour=SCAN_HOUR), id="daily_scan", replace_existing=True)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="Screener Alerts API", version="1.0", lifespan=_lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "tickers_watched": len(TICKERS), "scan_hour": SCAN_HOUR}


@app.get("/alerts")
def get_alerts(limit: int = 50, severity: str | None = None, ticker: str | None = None):
    if not os.path.exists(LOG_PATH):
        return {"alerts": [], "count": 0}

    records = []
    with open(LOG_PATH) as f:
        for line in f:
            record = json.loads(line)
            if severity and record["severity"] != severity:
                continue
            if ticker and record["ticker"] != ticker.upper():
                continue
            records.append(record)

    records = records[-limit:][::-1]  # most recent first
    return {"alerts": records, "count": len(records)}


@app.post("/admin/scan")
def trigger_scan(x_admin_token: str | None = Header(default=None)):
    _require_admin(x_admin_token)
    notifier = _build_notifier()
    alerts = scan_and_notify(TICKERS, notifier)
    return {"alerts_fired": len(alerts)}
