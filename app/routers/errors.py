"""Client-side error reporting endpoint."""
import sys
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.error_log import ErrorLog

router = APIRouter(prefix="/errors", tags=["errors"])

# Simple in-memory rate limit: IP -> (count, reset_time)
_rate_limit: dict[str, tuple[int, float]] = {}
_RATE_LIMIT = 10  # per minute
_RATE_WINDOW = 60


class FrontendErrorReport(BaseModel):
    message: str
    source: str = "frontend"
    error_type: str = "FrontendError"
    stack_trace: Optional[str] = None
    url: Optional[str] = None
    user_agent: Optional[str] = None


@router.post("/report")
async def report_frontend_error(payload: FrontendErrorReport, request: Request):
    """Receive a frontend error report. Rate-limited per IP."""
    ip = request.client.host if request.client else None
    if ip:
        now = datetime.now(timezone.utc).timestamp()
        count, reset = _rate_limit.get(ip, (0, now + _RATE_WINDOW))
        if now > reset:
            count = 0
            reset = now + _RATE_WINDOW
        if count >= _RATE_LIMIT:
            return {"status": "rate_limited"}
        _rate_limit[ip] = (count + 1, reset)

    try:
        async with AsyncSessionLocal() as session:
            entry = ErrorLog(
                level="error",
                source=payload.source,
                endpoint=payload.url,
                error_type=payload.error_type,
                message=payload.message[:2000],
                stack_trace=payload.stack_trace,
                user_agent=payload.user_agent or request.headers.get("user-agent"),
                ip_address=ip,
                occurred_at=datetime.now(timezone.utc),
            )
            session.add(entry)
            await session.commit()
    except Exception as e:
        print(f"BMM-POS: failed to log frontend error: {e}", file=sys.stderr, flush=True)

    return {"status": "ok"}
