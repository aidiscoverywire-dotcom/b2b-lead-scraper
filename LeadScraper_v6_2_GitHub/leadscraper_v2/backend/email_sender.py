"""Bulk outreach — sends one email (subject/body, optionally personalised)
to every lead in a job that has an email address, from inside the app.

Runs over the user's own SMTP account (Gmail, Outlook, Zoho, a transactional
provider's SMTP endpoint, etc.) — nothing is routed through us, same
philosophy as the Google/Apollo/OpenAI keys. Kept dependency-light: only the
Python standard library's smtplib/email modules.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

log = logging.getLogger(__name__)

# Small delay between sends so a single SMTP account doesn't trip provider
# rate limits / spam heuristics when blasting hundreds of leads at once.
SEND_DELAY_SECONDS = 1.2


@dataclass
class SmtpConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    from_name: str = ""
    use_tls: bool = True


def render_template(template: str, lead) -> str:
    """Very small {{placeholder}} substitution — no Jinja dependency needed."""
    company = (lead.name or "").strip()
    first_word = company.split(" ")[0] if company else "there"
    values = {
        "name": lead.decision_maker_name or first_word,
        "company": company,
        "title": lead.decision_maker_title or "",
        "address": lead.address or "",
        "website": lead.website or "",
    }
    out = template
    for key, val in values.items():
        out = out.replace("{{" + key + "}}", val).replace("{{ " + key + " }}", val)
    return out


def _build_message(cfg: SmtpConfig, to_email: str, subject: str, html_body: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.from_name or cfg.from_email, cfg.from_email))
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html"))
    return msg


def send_one_sync(cfg: SmtpConfig, to_email: str, subject: str, html_body: str) -> None:
    """Blocking single send — always called via asyncio.to_thread."""
    msg = _build_message(cfg, to_email, subject, html_body)
    context = ssl.create_default_context()
    with smtplib.SMTP(cfg.host, cfg.port, timeout=20) as server:
        server.ehlo()
        if cfg.use_tls:
            server.starttls(context=context)
            server.ehlo()
        if cfg.username:
            server.login(cfg.username, cfg.password)
        server.sendmail(cfg.from_email, [to_email], msg.as_string())


async def send_test_email(cfg: SmtpConfig, to_email: str) -> tuple[bool, str]:
    try:
        await asyncio.to_thread(
            send_one_sync,
            cfg,
            to_email,
            "LeadScraper Pro — test email",
            "<p>Your SMTP settings are working. Bulk outreach is ready to use.</p>",
        )
        return True, f"Test email sent to {to_email}."
    except smtplib.SMTPAuthenticationError:
        return False, "SMTP login rejected — check username/password (for Gmail/Outlook use an app password)."
    except Exception as exc:  # noqa: BLE001 — surfaced to the user as-is
        return False, f"Send failed: {exc}"


async def send_bulk(cfg: SmtpConfig, subject_template: str, body_template: str, leads: list, on_progress=None):
    """Sends to every lead sequentially with a small delay between sends.

    Returns (sent_count, failed_count). Mutates each lead's
    campaign_email_status / campaign_email_sent_at / campaign_email_error
    in place — caller is responsible for committing to the DB.
    """
    import datetime

    sent, failed = 0, 0
    for lead in leads:
        subject = render_template(subject_template, lead)
        body = render_template(body_template, lead)
        try:
            await asyncio.to_thread(send_one_sync, cfg, lead.decision_maker_email, subject, body)
            lead.campaign_email_status = "sent"
            lead.campaign_email_sent_at = datetime.datetime.utcnow()
            lead.campaign_email_error = ""
            sent += 1
        except Exception as exc:  # noqa: BLE001
            lead.campaign_email_status = "failed"
            lead.campaign_email_error = str(exc)[:500]
            failed += 1
            log.warning("bulk email failed for %s: %s", lead.decision_maker_email, exc)
        if on_progress:
            await on_progress(sent, failed)
        await asyncio.sleep(SEND_DELAY_SECONDS)
    return sent, failed
