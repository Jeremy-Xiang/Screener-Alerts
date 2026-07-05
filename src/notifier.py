"""
notifier.py — Pluggable alert delivery. Every notifier implements
`send(alerts: list[Alert]) -> None`. Swap which one the screener uses
without touching screener.py or rules.py at all — same "swap the
implementation, not the caller" pattern as `set_headline_source()` in the
multi-agent-analyst project.

ConsoleNotifier and FileNotifier work with zero configuration (useful for
testing and for a local cron job). WebhookNotifier and EmailNotifier need
real credentials/URLs and aren't exercised by the test suite for that
reason — they're real, working code, just not something this sandbox can
verify end-to-end without an actual Slack webhook or SMTP server.
"""

from __future__ import annotations

import json
import os
import smtplib
from abc import ABC, abstractmethod
from dataclasses import asdict
from datetime import datetime, timezone
from email.mime.text import MIMEText

from .rules import Alert


class Notifier(ABC):
    @abstractmethod
    def send(self, alerts: list[Alert]) -> None:
        ...


class ConsoleNotifier(Notifier):
    def send(self, alerts: list[Alert]) -> None:
        for a in alerts:
            print(f"[{a.severity.upper()}] {a.ticker} — {a.rule}: {a.message}")


class FileNotifier(Notifier):
    """Appends one JSON line per alert. Good for a persistent local log a
    dashboard can tail, or for testing without sending anything anywhere."""

    def __init__(self, path: str = "alerts_log.jsonl"):
        self.path = path

    def send(self, alerts: list[Alert]) -> None:
        with open(self.path, "a") as f:
            for a in alerts:
                record = asdict(a)
                record["timestamp"] = datetime.now(timezone.utc).isoformat()
                f.write(json.dumps(record) + "\n")


class WebhookNotifier(Notifier):
    """
    POSTs a Slack-compatible {"text": ...} payload. Works as-is for Slack
    incoming webhooks; Discord webhooks accept the same {"text": ...} shape
    under a different field name ("content") — pass `payload_key="content"`
    for Discord.
    """

    def __init__(self, webhook_url: str, payload_key: str = "text"):
        self.webhook_url = webhook_url
        self.payload_key = payload_key

    def send(self, alerts: list[Alert]) -> None:
        import urllib.request

        if not alerts:
            return
        lines = [f"*[{a.severity.upper()}]* {a.ticker} — {a.rule}: {a.message}" for a in alerts]
        payload = json.dumps({self.payload_key: "\n".join(lines)}).encode()
        req = urllib.request.Request(self.webhook_url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)


class EmailNotifier(Notifier):
    """
    Sends one email summarizing all alerts via SMTP. Reads connection
    details from environment variables so no credentials end up in code:
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_EMAIL_TO,
    ALERT_EMAIL_FROM.
    """

    def send(self, alerts: list[Alert]) -> None:
        if not alerts:
            return

        host = os.environ["SMTP_HOST"]
        port = int(os.environ.get("SMTP_PORT", "587"))
        user = os.environ["SMTP_USER"]
        password = os.environ["SMTP_PASSWORD"]
        to_addr = os.environ["ALERT_EMAIL_TO"]
        from_addr = os.environ.get("ALERT_EMAIL_FROM", user)

        body = "\n".join(f"[{a.severity.upper()}] {a.ticker} — {a.rule}: {a.message}" for a in alerts)
        msg = MIMEText(body)
        msg["Subject"] = f"Screener alerts ({len(alerts)})"
        msg["From"] = from_addr
        msg["To"] = to_addr

        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)


class MultiNotifier(Notifier):
    """Fan out to several notifiers at once — e.g. log to file AND post to Slack."""

    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def send(self, alerts: list[Alert]) -> None:
        for n in self.notifiers:
            n.send(alerts)
