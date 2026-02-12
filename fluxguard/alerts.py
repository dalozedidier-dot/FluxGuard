from __future__ import annotations

import json
import smtplib
import ssl
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Dict, Optional


def _http_post_json(url: str, payload: Dict[str, Any], *, timeout_s: int = 10) -> None:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        _ = resp.read()


def send_slack_webhook(webhook_url: str, text: str) -> None:
    _http_post_json(webhook_url, {"text": text})


def send_generic_webhook(webhook_url: str, payload: Dict[str, Any]) -> None:
    _http_post_json(webhook_url, payload)


def send_email_smtp(
    *,
    host: str,
    port: int,
    username: Optional[str],
    password: Optional[str],
    use_tls: bool,
    sender: str,
    to: str,
    subject: str,
    body: str,
) -> None:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if use_tls:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as s:
            if username and password:
                s.login(username, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as s:
            s.ehlo()
            try:
                s.starttls(context=ssl.create_default_context())
            except Exception:
                # Si STARTTLS indisponible, on reste en clair.
                pass
            if username and password:
                s.login(username, password)
            s.send_message(msg)


@dataclass
class AlertConfig:
    slack_webhook: Optional[str] = None
    generic_webhook: Optional[str] = None

    smtp_host: Optional[str] = None
    smtp_port: int = 465
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    email_from: Optional[str] = None
    email_to: Optional[str] = None


def notify(cfg: AlertConfig, *, title: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
    text = f"{title}\n{message}"

    if cfg.slack_webhook:
        try:
            send_slack_webhook(cfg.slack_webhook, text)
        except Exception:
            pass

    if cfg.generic_webhook:
        try:
            send_generic_webhook(cfg.generic_webhook, payload or {"title": title, "message": message})
        except Exception:
            pass

    if cfg.smtp_host and cfg.email_from and cfg.email_to:
        try:
            send_email_smtp(
                host=cfg.smtp_host,
                port=int(cfg.smtp_port),
                username=cfg.smtp_username,
                password=cfg.smtp_password,
                use_tls=bool(cfg.smtp_use_tls),
                sender=cfg.email_from,
                to=cfg.email_to,
                subject=title,
                body=text,
            )
        except Exception:
            pass
