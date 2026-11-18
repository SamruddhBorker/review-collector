"""Delivery channels: console (dry), WhatsApp Cloud API, email (SMTP). Standard library only."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from pathlib import Path

from engine import normalize_phone, valid_email

API_VERSION = "v20.0"


def load_env(path: str | Path = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _whatsapp(c, text: str, cfg: dict) -> tuple[bool, str]:
    token, phone_id = os.environ.get("WHATSAPP_TOKEN"), os.environ.get("WHATSAPP_PHONE_ID")
    to = normalize_phone(c["phone"], cfg.get("default_country_code", "91"))
    if not to:
        return False, "no valid phone number"
    if not token or not phone_id:
        return False, "WHATSAPP_TOKEN / WHATSAPP_PHONE_ID not set"
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4000]}}
    req = urllib.request.Request(
        f"https://graph.facebook.com/{API_VERSION}/{phone_id}/messages", data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True, "sent via WhatsApp"
    except urllib.error.HTTPError as e:
        return False, f"WhatsApp HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError) as e:
        return False, f"WhatsApp error: {e}"


def _email(c, text: str, cfg: dict) -> tuple[bool, str]:
    if not valid_email(c["email"]):
        return False, "no valid email"
    host, user, pwd = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD")
    if not (host and user and pwd):
        return False, "SMTP_HOST / SMTP_USER / SMTP_PASSWORD not set"
    msg = EmailMessage()
    msg["Subject"] = f"How was your visit to {cfg['business_name']}?"
    msg["From"] = os.environ.get("SMTP_FROM", user)
    msg["To"] = c["email"]
    msg.set_content(text)
    port = int(os.environ.get("SMTP_PORT", "587"))
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pwd)
                s.send_message(msg)
        return True, "sent via email"
    except (smtplib.SMTPException, OSError) as e:
        return False, f"email error: {type(e).__name__}"


def send(channel: str, c, text: str, cfg: dict) -> tuple[bool, str]:
    if channel == "console":
        print(f"[console -> {c['name']}] {text}")
        return True, "printed"
    if channel == "whatsapp":
        return _whatsapp(c, text, cfg)
    if channel == "email":
        return _email(c, text, cfg)
    return False, f"unknown channel {channel!r}"
