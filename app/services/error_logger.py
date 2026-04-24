"""Centralized error logging service.

Captures exceptions with full context, sanitizes sensitive data, and stores
in the error_logs table. Designed to never raise — if DB logging fails,
it prints to stderr and moves on.
"""
import sys
import traceback
import json
from typing import Optional
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.error_log import ErrorLog


# Sensitive keys to strip from request bodies before logging
_SENSITIVE_KEYS = {
    "password", "password_hash", "token", "access_token", "refresh_token",
    "card_transaction_id", "square_payment_id", "poynt_transaction_id",
    "gift_card_barcode", "authorization", "api_key", "secret", "private_key",
    "cvv", "card_number", "account_number",
}

_MAX_STACK_TRACE = 20000  # characters
_MAX_REQUEST_BODY = 10000  # characters


def _sanitize_request_body(body: str) -> str:
    """Strip sensitive fields from a JSON request body string."""
    if not body or not body.strip():
        return ""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # Not JSON — return truncated raw string
        return body[:_MAX_REQUEST_BODY]

    def _redact(obj):
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                if k.lower() in _SENSITIVE_KEYS:
                    result[k] = "***REDACTED***"
                elif isinstance(v, (dict, list)):
                    result[k] = _redact(v)
                else:
                    result[k] = v
            return result
        elif isinstance(obj, list):
            return [_redact(i) for i in obj]
        return obj

    redacted = _redact(data)
    result = json.dumps(redacted, default=str)
    return result[:_MAX_REQUEST_BODY]


def _format_stack_trace(exc: Exception) -> str:
    """Format exception stack trace, capped at max size."""
    try:
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        full = "".join(tb)
        if len(full) > _MAX_STACK_TRACE:
            full = full[:_MAX_STACK_TRACE] + "\n... [truncated]"
        return full
    except Exception:
        return str(exc)


def _get_client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


async def log_error(
    db: AsyncSession,
    exc: Exception,
    source: str = "api",
    request: Optional[Request] = None,
    user: Optional = None,
    level: str = "error",
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
) -> Optional[int]:
    """Log an error to the database. Never raises. Returns error_log id or None.

    Args:
        db: Async database session
        exc: The exception that occurred
        source: 'api', 'frontend', 'startup', 'background'
        request: FastAPI request object (optional)
        user: Vendor/user object (optional)
        level: 'error', 'warning', 'critical'
        endpoint: Override endpoint path (if request not available)
        method: Override HTTP method (if request not available)
    """
    try:
        error_type = type(exc).__name__
        message = str(exc)[:2000]
        stack_trace = _format_stack_trace(exc)

        # Extract request context
        req_body = ""
        req_endpoint = endpoint
        req_method = method
        user_id = None
        user_email = None
        ip = None
        ua = None

        if request is not None:
            req_endpoint = endpoint or request.url.path
            req_method = method or request.method
            ip = _get_client_ip(request)
            ua = request.headers.get("user-agent")
            # Try to read body (only if not already consumed)
            try:
                body_bytes = await request.body()
                if body_bytes:
                    req_body = _sanitize_request_body(body_bytes.decode("utf-8", errors="replace"))
            except Exception:
                pass

        if user is not None:
            user_id = getattr(user, "id", None)
            user_email = getattr(user, "email", None)

        entry = ErrorLog(
            level=level,
            source=source,
            endpoint=req_endpoint,
            method=req_method,
            error_type=error_type,
            message=message,
            stack_trace=stack_trace,
            request_body=req_body or None,
            user_id=user_id,
            user_email=user_email,
            ip_address=ip,
            user_agent=ua,
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry.id
    except Exception as e:
        # Absolute last resort — never let error logging break the app
        print(
            f"BMM-POS FATAL: error logging itself failed: {type(e).__name__}: {e}",
            file=sys.stderr,
            flush=True,
        )
        return None


async def log_warning(
    db: AsyncSession,
    message: str,
    source: str = "api",
    request: Optional[Request] = None,
    user: Optional = None,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
) -> Optional[int]:
    """Log a warning-level entry (no stack trace)."""
    try:
        req_endpoint = endpoint or (request.url.path if request else None)
        req_method = method or (request.method if request else None)
        ip = _get_client_ip(request)
        ua = request.headers.get("user-agent") if request else None
        user_id = getattr(user, "id", None) if user else None
        user_email = getattr(user, "email", None) if user else None

        entry = ErrorLog(
            level="warning",
            source=source,
            endpoint=req_endpoint,
            method=req_method,
            error_type="Warning",
            message=message[:2000],
            user_id=user_id,
            user_email=user_email,
            ip_address=ip,
            user_agent=ua,
            occurred_at=datetime.now(timezone.utc),
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        return entry.id
    except Exception as e:
        print(f"BMM-POS FATAL: warning logging failed: {e}", file=sys.stderr, flush=True)
        return None
