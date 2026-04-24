"""Audit logging helpers for admin actions and sensitive operations."""
from typing import Optional
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.audit_log import AuditLog


async def log_audit(
    db: AsyncSession,
    vendor_id: Optional[int],
    action: str,
    entity_type: str,
    entity_id: Optional[str] = None,
    details: Optional[str] = None,
    request: Optional[Request] = None,
) -> None:
    """Write an audit log entry. Swallows exceptions so logging never blocks operations."""
    try:
        ip = None
        ua = None
        if request is not None:
            ip = _get_client_ip(request)
            ua = request.headers.get("user-agent")

        entry = AuditLog(
            vendor_id=vendor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
            ip_address=ip,
            user_agent=ua,
        )
        db.add(entry)
        await db.commit()
    except Exception:
        # Audit logging should never break the main operation
        await db.rollback()


def _get_client_ip(request: Request) -> str:
    """Extract real client IP from forwarded headers or direct connection."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return "unknown"
