"""Google Search Console URL indexing ping.

Fire-and-forget best-effort. We call the internal Perplexity programmatic
tool-calling endpoint if available (set PPLX_PTC_URL + PPLX_PTC_TOKEN env
vars); otherwise we simply log and return. This lets the code ship safely
even when running locally or without credentials — we never block the
main request on the external call.

Environment variables (all optional):
  PPLX_PTC_URL    — programmatic tool-calling endpoint
  PPLX_PTC_TOKEN  — bearer token for the above
  GSC_PING_ENABLED — "true" to enable (default "false")
  PUBLIC_BASE_URL — defaults to https://www.bowenstreetmarket.com
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal, Optional

import httpx

logger = logging.getLogger(__name__)

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://www.bowenstreetmarket.com").rstrip("/")

NotificationType = Literal["URL_UPDATED", "URL_DELETED"]


def _enabled() -> bool:
    return os.environ.get("GSC_PING_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


async def _call_programmatic_tool(tool_name: str, source_id: str,
                                  arguments: dict) -> Optional[dict]:
    """Invoke a Perplexity connector via programmatic tool-calling.

    Returns parsed JSON on success, None on any failure.
    """
    url = os.environ.get("PPLX_PTC_URL", "").strip()
    token = os.environ.get("PPLX_PTC_TOKEN", "").strip()
    if not url or not token:
        logger.info("gsc_ping: PPLX_PTC_URL/TOKEN not set, skipping")
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "tool_name": tool_name,
                    "source_id": source_id,
                    "arguments": arguments,
                },
            )
            if r.status_code >= 400:
                logger.warning("gsc_ping: non-2xx %s: %s", r.status_code, r.text[:200])
                return None
            try:
                return r.json()
            except ValueError:
                return None
    except Exception as e:
        logger.warning("gsc_ping: request failed: %s", e)
        return None


async def submit_url_to_gsc(slug: str,
                            notification_type: NotificationType = "URL_UPDATED",
                            base_url: Optional[str] = None) -> None:
    """Fire-and-forget GSC submission for a vendor landing slug.

    Runs as a background task so it never blocks the API response.
    Silently no-ops if GSC_PING_ENABLED is not set.
    """
    if not _enabled():
        return
    if not slug or not slug.strip():
        return
    base = (base_url or PUBLIC_BASE_URL).rstrip("/")
    target = f"{base}/{slug.strip().lstrip('/')}"
    try:
        await _call_programmatic_tool(
            tool_name="google_search_console-submit-url-for-indexing",
            source_id="google_search_console__pipedream",
            arguments={"siteUrl": target, "notificationType": notification_type},
        )
        logger.info("gsc_ping: submitted %s (%s)", target, notification_type)
    except Exception as e:
        logger.info("gsc_ping: submission error (non-fatal): %s", e)


def schedule_gsc_ping(slug: Optional[str],
                      notification_type: NotificationType = "URL_UPDATED") -> None:
    """Schedule a background ping without awaiting. Safe to call from
    within request handlers — returns immediately.
    """
    if not slug:
        return
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(submit_url_to_gsc(slug, notification_type))
    except RuntimeError:
        # No running loop (unlikely inside FastAPI) — just skip.
        logger.info("gsc_ping: no running loop, skipping schedule for %s", slug)
