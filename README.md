# screener-alerts

Six technical screening rules that fire on events, not thresholds. The distinction matters: a rule like "RSI > 70" fires every day for the two or three weeks a stock spends overbought, which teaches you to ignore the feed. Every rule here that has a meaningful "before" state compares today against yesterday.

## The six rules

`rsi_extreme` fires when RSI14 crosses above 70 or below 30 — this one is genuinely state-based, not crossover-based, because "currently overbought" is the signal.

`sma_crossover` fires when SMA20 crosses SMA50. Specifically: `(sma20 - sma50)` was negative yesterday, positive today (golden cross) or vice versa (death cross). "SMA20 has been above SMA50 for three weeks" produces nothing.

`large_single_day_move` fires when a single day's return exceeds 5% in either direction.

`volume_spike` fires when today's volume exceeds 3x its 20-day average.

`fifty_two_week_breakout` fires when today's close exceeds the 52-week high or low *as of yesterday* — `high_52w.shift(1)`. This means it fires exactly once, the day the breakout happens, not every subsequent day the price happens to still be elevated.

`volatility_breakout` fires when 21-day realized volatility exceeds 1.6x its own 60-day baseline.

## The crossover test

The SMA crossover rule is verified directly against constructed cases, not just trusted because it ran without errors:

```python
sma_crossover("T", df_with_actual_cross)     # → fires
sma_crossover("T", df_already_above_for_weeks) # → None, correctly silent
```

That test is in `tests/test_core.py` and runs on every `pytest` invocation.

## Notifiers

Four delivery backends behind one interface (`send(alerts: list[Alert]) -> None`):

`ConsoleNotifier` prints to stdout. `FileNotifier` appends one JSON line per alert to a JSONL log — the format the THESIS integration's `/api/screener/alerts` endpoint reads from. `WebhookNotifier` POSTs a Slack-compatible payload to any webhook URL; pass `payload_key="content"` for Discord. `EmailNotifier` sends via SMTP, reading credentials from environment variables.

`MultiNotifier` fans out to several at once.

## Running it

```bash
pip install -r requirements.txt

python run_screener.py --basket                  # 19-ticker sector-diverse universe
python run_screener.py --tickers AAPL,MSFT,NVDA  # specific tickers
python run_screener.py --tickers-file list.txt --notifier file --log-path alerts.jsonl
```

Or as a scheduled service:

```bash
uvicorn app:app --port 8005
curl http://localhost:8005/alerts?limit=20&severity=critical
curl -X POST http://localhost:8005/admin/scan
```

The app runs a daily scan at 6am server time via APScheduler. `/alerts` reads from the JSONL log — no model computation on the request path.

## THESIS integration (verified against your real code)

`src/thesis_router.py` mounts the screener as a router on your existing FastAPI app, sharing its `Limiter` instance and `BackgroundScheduler`. Tested with a `TestClient` against a harness built from your actual `config.py` — 34 real alerts across your 52-ticker universe, invalid-ticker validation matching your existing `400 {"detail": "Invalid ticker symbol."}` shape.

Two lines in `main.py`:

```python
from screener.thesis_router import build_router as build_screener_router
app.include_router(build_screener_router(limiter), prefix="/api/screener")
```

One import and one line in `scheduler.py` before `scheduler.start()`:

```python
from screener.thesis_router import register_screener_job
register_screener_job(scheduler)
```

Copy `src/` into your THESIS backend as `screener/`. Set `SCREENER_TICKERS` to your real universe, or edit `_get_tickers()` in `thesis_router.py` to import it from `config.THEMES` directly.

One gap: your `PriceFetcher` carries Close prices only, so `volume_spike` fetches its own OHLCV via yfinance rather than reusing your existing data pipeline. If you extend `PriceFetcher` to OHLCV, swap `screener/data.py`'s `load_ohlcv()` to read from it and the rule benefits immediately.

## Running the tests

```bash
pytest tests/ -v
```

Seven tests. Includes the `fifty_two_week_breakout` fires-once verification: construct a series with a new high on the last day, confirm it fires; append one more day still below the new high, confirm it doesn't.

## Structure

```
screener-alerts/
├── run_screener.py  # CLI
├── app.py           # FastAPI + scheduled scanning
├── src/
│   ├── rules.py     # the six rules
│   ├── screener.py  # scan orchestration
│   ├── notifier.py  # ConsoleNotifier, FileNotifier, WebhookNotifier, EmailNotifier, MultiNotifier
│   ├── indicators.py
│   ├── data.py
│   ├── thesis_router.py  # THESIS-mountable router
│   └── seed.py
└── tests/test_core.py
```
