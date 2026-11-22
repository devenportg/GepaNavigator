"""Отправка уведомлений пациентам по e-mail через SMTP.

В демо-режиме (SMTP_ENABLED=false) письма не уходят: сообщение остаётся в журнале
со статусом QUEUED, чтобы показ не зависел от почтового сервера.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from .config import settings


def is_configured() -> bool:
    return bool(settings.smtp_enabled and settings.smtp_host)


def build_message(to_email: str, subject: str, text: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg.set_content(text)
    return msg


def send_email(to_email: str | None, subject: str, text: str) -> tuple[bool, str | None]:
    """Вернуть (отправлено, ошибка). Никогда не бросает исключение наружу."""
    if not to_email:
        return False, "у пациента не указан e-mail"
    if not settings.smtp_enabled:
        return False, "SMTP выключен (демо-режим)"
    try:
        msg = build_message(to_email, subject, text)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                          timeout=settings.smtp_timeout_seconds) as smtp:
            smtp.ehlo()
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password.get_secret_value()
                           if settings.smtp_password else "")
            smtp.send_message(msg)
        return True, None
    except Exception as exc:  # сеть, авторизация, TLS — фиксируем в журнале
        return False, str(exc)[:300]
