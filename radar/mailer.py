"""Envío del digest por SMTP (stdlib). Con Gmail: contraseña de aplicación, smtp.gmail.com:465."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def smtp_configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "DIGEST_TO"))


def send(subject: str, body_markdown: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "465"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("DIGEST_FROM", user)
    msg["To"] = os.environ["DIGEST_TO"]
    msg.set_content(body_markdown)

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=60) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=60) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)
