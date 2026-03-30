import base64
import logging
import os
import smtplib
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_cached_token: Optional[dict] = None


def _has_replit_connector() -> bool:
    return bool(
        os.environ.get("REPLIT_CONNECTORS_HOSTNAME")
        and (os.environ.get("REPL_IDENTITY") or os.environ.get("WEB_REPL_RENEWAL"))
    )


def _has_smtp_credentials() -> bool:
    return bool(
        os.environ.get("GMAIL_ADDRESS") and os.environ.get("GMAIL_APP_PASSWORD")
    )


async def _get_gmail_access_token() -> str:
    global _cached_token
    from datetime import datetime

    if (
        _cached_token
        and _cached_token.get("expires_at")
        and datetime.fromisoformat(_cached_token["expires_at"].replace("Z", "+00:00")).timestamp() > datetime.now().timestamp()
    ):
        return _cached_token["access_token"]

    hostname = os.environ.get("REPLIT_CONNECTORS_HOSTNAME")
    repl_identity = os.environ.get("REPL_IDENTITY")
    web_repl_renewal = os.environ.get("WEB_REPL_RENEWAL")

    if repl_identity:
        x_replit_token = f"repl {repl_identity}"
    elif web_repl_renewal:
        x_replit_token = f"depl {web_repl_renewal}"
    else:
        raise RuntimeError("No Replit identity token found for Gmail connector")

    if not hostname:
        raise RuntimeError("REPLIT_CONNECTORS_HOSTNAME not set")

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://{hostname}/api/v2/connection",
            params={"include_secrets": "true", "connector_names": "google-mail"},
            headers={
                "Accept": "application/json",
                "X-Replit-Token": x_replit_token,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

    items = data.get("items", [])
    if not items:
        raise RuntimeError("Gmail connector not configured")

    connection = items[0]
    settings = connection.get("settings", {})
    access_token = settings.get("access_token") or (
        settings.get("oauth", {}).get("credentials", {}).get("access_token")
    )

    if not access_token:
        raise RuntimeError("Gmail access token not found")

    _cached_token = {
        "access_token": access_token,
        "expires_at": settings.get("expires_at", ""),
    }
    return access_token


async def _get_sender_email(access_token: str) -> str:
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("emailAddress", "me")
    except Exception:
        return "me"


def _build_message(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str],
    from_email: str,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["To"] = to_email
    msg["From"] = f"Bowenstreet Market <{from_email}>"
    msg["Subject"] = subject

    if plain_body:
        msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg


async def _send_via_replit_connector(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str],
) -> dict:
    access_token = await _get_gmail_access_token()
    sender_email = await _get_sender_email(access_token)

    msg = _build_message(to_email, subject, html_body, plain_body, sender_email)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"Email sent via Replit connector to {to_email}: messageId={result.get('id')}")
        return {"success": True, "message_id": result.get("id")}


async def _send_via_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str],
) -> dict:
    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = _build_message(to_email, subject, html_body, plain_body, gmail_address)

    def _smtp_send():
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as server:
            server.login(gmail_address, gmail_app_password)
            server.sendmail(gmail_address, to_email, msg.as_string())

    await asyncio.get_event_loop().run_in_executor(None, _smtp_send)
    logger.info(f"Email sent via SMTP to {to_email}")
    return {"success": True}


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str] = None,
) -> dict:
    try:
        if _has_replit_connector():
            return await _send_via_replit_connector(to_email, subject, html_body, plain_body)
        elif _has_smtp_credentials():
            return await _send_via_smtp(to_email, subject, html_body, plain_body)
        else:
            logger.error("No email provider configured. Set GMAIL_ADDRESS + GMAIL_APP_PASSWORD for SMTP, or use Replit Gmail connector.")
            return {"success": False, "error": "No email provider configured"}

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return {"success": False, "error": str(e)}


async def send_email_safe(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str] = None,
) -> dict:
    try:
        return await send_email(to_email, subject, html_body, plain_body)
    except Exception as e:
        logger.error(f"send_email_safe failed for {to_email}: {e}")
        return {"success": False, "error": str(e)}
