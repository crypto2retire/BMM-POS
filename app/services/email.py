import base64
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_cached_token: Optional[dict] = None


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


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    plain_body: Optional[str] = None,
) -> dict:
    try:
        access_token = await _get_gmail_access_token()
        sender_email = await _get_sender_email(access_token)

        msg = MIMEMultipart("alternative")
        msg["To"] = to_email
        if sender_email and sender_email != "me":
            msg["From"] = f"Bowenstreet Market <{sender_email}>"
        msg["Subject"] = subject

        if plain_body:
            msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

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
            logger.info(f"Email sent to {to_email}: messageId={result.get('id')}")
            return {"success": True, "message_id": result.get("id")}

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
