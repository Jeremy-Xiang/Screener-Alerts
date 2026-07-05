# screener-alerts

Scans a ticker universe against a set of technical rules, fires alerts
only on actual *events* (a crossover, a breakout, an outsized single-day
move) rather than "value currently above a threshold," and delivers them
through a pluggable notifier — console, a local JSONL log, a Slack/Discord
webhook, or email — without any rule or scanning code needing to know or
care which one.

## Why "event" matters more than "threshold"

A naive rule like "alert if RSI > 70" fires every single day for the two
or three weeks a stock spends overbought, which trains you to ignore the
feed. Every rule here that has a meaningful "before" state compares
**today against yesterday**, not just today against a fixed line:

| Rule | What actually triggers it |
|---|---|
| `rsi_extreme` | RSI14 >= 70 or <= 30 (the one rule where "currently extreme" is itself the useful signal) |
| `sma_crossover` | SMA20 actually crosses SMA50 today — not "is currently above/below" |
| `large_single_day_move` | One day's return exceeds the threshold |
| `volume_spike` | Today's volume vs. its own 20-day average |
| `fifty_two_week_breakout` | Today's close exceeds the 52-week high/low **as of yesterday** — fires once, on the day it actually happens, not every day after |
| `volatility_breakout` | Today's realized volatility vs. its own 60-day baseline |

`fifty_two_week_breakout` is the one most worth double-checking if you
extend this: comparing against `high_52w.shift(1)` (yesterday's trailing
high) instead of today's is what makes it fire exactly once per breakout
instead of every day the price happens to still be elevated.

## Verified, not just plausible

The crossover rule is checked directly against constructed cases, not just
trusted to work because it ran without an error:

```python
sma_crossover('TEST', df_with_an_actual_cross)        # -> fires
sma_crossover('TEST', df_already_above_for_3_weeks)   # -> None, correctly silent
```

And the full pipeline runs against a 19-ticker basket with synthetic data
that deliberately injects real events (a sharp move + volume spike, or a
short trend reversal) on about a third of tickers — so there's something
real to catch, not just noise that may or may not trip a rule by luck. A
sample run fired 15 alerts across 19 tickers, including a single-day move
on a ticker with a scripted event and a correlated volatility breakout on
the same ticker — which is exactly the kind of result that says the rules
are responding to a real signal, not coincidence.

## Running it

```bash
pip install -r requirements.txt

# One-off scan, prints to console
python run_screener.py --basket

# Log to a file instead
python run_screener.py --tickers AAPL,MSFT,NVDA --notifier file --log-path alerts.jsonl

# Your own ticker list (e.g. THESIS's full 53)
python run_screener.py --tickers-file my_tickers.txt --notifier file
```

Or as a scheduled service:
```bash
uvicorn app:app --reload --port 8005
curl http://localhost:8005/alerts?limit=20
curl "http://localhost:8005/alerts?severity=critical"
curl -X POST http://localhost:8005/admin/scan   # trigger a scan immediately
```

A cron job inside the app (`SCREENER_SCAN_HOUR`, default 6am server time)
runs the scan once a day automatically; `/alerts` reads from the resulting
log rather than re-scanning per request.

## Notifiers

```python
from src.notifier import ConsoleNotifier, FileNotifier, WebhookNotifier, EmailNotifier, MultiNotifier

# Slack (or Discord with payload_key="content")
WebhookNotifier("https://hooks.slack.com/services/...")

# Email — reads SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
# ALERT_EMAIL_TO, ALERT_EMAIL_FROM from the environment, never from code
EmailNotifier()

# Fan out to more than one at once
MultiNotifier([FileNotifier("alerts.jsonl"), WebhookNotifier(url)])
```

`ConsoleNotifier` and `FileNotifier` are exercised directly in testing
(zero config needed). `WebhookNotifier` and `EmailNotifier` are real,
complete implementations but need an actual webhook URL or SMTP
credentials to verify end-to-end — nothing this sandbox has access to.
Point one at a real Slack webhook and it'll work as written.

## Wiring into THESIS (verified against your actual code)

This was tested directly against your real `config.py` (all 52 tickers
across your 5 themes) and your real `main.py`/`scheduler.py` patterns —
not a generic template. Three steps:

**1. Copy the package in**, renamed `screener/` to match your existing
sibling packages (`data/`, `portfolio/`, `prediction/`):

```
thesis-dashboard/
├── main.py
├── scheduler.py
├── config.py
├── data/
├── portfolio/
├── prediction/
└── screener/          ← this project's src/, renamed
    ├── __init__.py
    ├── data.py, indicators.py, rules.py, notifier.py, screener.py, seed.py
    └── thesis_router.py
```

**2. Two lines in `main.py`** — one import near your other imports, one
`include_router` call after your existing `CORSMiddleware` block:

```python
from screener.thesis_router import build_router as build_screener_router
# ...
app.include_router(build_screener_router(limiter), prefix="/api/screener")
```

`build_router(limiter)` takes your existing `limiter` object rather than
creating a second `Limiter` instance — slowapi tracks rate-limit state
per instance, so a second one would track its own counts independently of
every other endpoint's, which isn't what you want for one shared policy.

**3. Two lines in `scheduler.py`** — inside `start_scheduler()`, right
before `scheduler.start()`:

```python
from screener.thesis_router import register_screener_job
# ... inside start_scheduler(state), before scheduler.start():
register_screener_job(scheduler)
```

This adds the screener's daily scan to the **same** `BackgroundScheduler`
instance `start_scheduler()` already creates and returns — no second
scheduler, no second process.

**One real data-pipeline gap, not silently worked around:** your
`PriceFetcher` (`app.state.prices`) only carries Close prices — every
feature in `prediction/features.py` confirms this, it's Close-only end to
end. The screener's `volume_spike` rule needs Volume, which isn't in that
pipeline. Rather than guess at extending `data/prices.py` without having
seen it, `thesis_router.py` keeps the screener on its own self-contained
yfinance fetch instead of trying to share `app.state.prices`. That means
one additional external fetch path running alongside your existing
`PriceFetcher`, not a shared one — a deliberate, stated tradeoff. If you
later extend `PriceFetcher` to carry full OHLCV, point `screener/data.py`'s
`load_ohlcv()` at it instead and every rule (volume_spike included)
benefits immediately.

**Verified end to end** with a test harness built from your actual
`config.py` and matching your real `main.py`/`scheduler.py` structure:
`GET /api/screener/health` correctly reports all 52 real tickers,
`POST /api/screener/admin/scan` fired 34 real alerts across real names
(AMD oversold, NVDA single-day move + volatility breakout, TMO golden
cross, etc.), `GET /api/screener/alerts` returns them newest-first with
working severity/ticker filters, and an invalid ticker returns the exact
same `400 {"detail": "Invalid ticker symbol."}` shape your other endpoints
already use — not a different error format bolted on.

New React tab: an alert feed hitting `/api/screener/alerts` (severity-
colored, newest first), with a filter by severity/ticker and a manual
"scan now" button wired to `/api/screener/admin/scan`.

## Project structure

```
screener-alerts/
├── run_screener.py      # CLI
├── app.py               # FastAPI + scheduled scanning
└── src/
    ├── data.py            # OHLCV (yfinance + synthetic fallback w/ scripted events)
    ├── indicators.py       # full indicator time series (not just a snapshot)
    ├── rules.py             # the six screening rules
    ├── notifier.py           # pluggable delivery backends
    ├── screener.py            # orchestrates rules -> notifier
    └── seed.py                 # shared deterministic seeding
```

## Running the tests

```bash
pytest tests/ -v
```

The suite pins the behaviors that actually caught bugs during development
(see the sections above), not ceremony coverage — every test encodes a
check where the wrong answer was at some point the actual behavior.

## Possible next steps

- Add a per-ticker cooldown so the same rule firing two days in a row
  (e.g. RSI staying above 70) doesn't spam the feed — currently
  `rsi_extreme` is the one rule that can legitimately fire on consecutive
  days, by design, but a configurable cooldown would be a reasonable
  addition for that specific rule.
- Add a rule that uses the multi-agent-analyst project's fundamentals
  data — e.g. alert when a stock crosses into "extreme valuation" territory,
  not just on price/volume action.
- Track each alert's outcome (did the stock keep moving the direction the
  alert implied, over the following N days) to start building an actual
  track record of which rules are worth keeping.
