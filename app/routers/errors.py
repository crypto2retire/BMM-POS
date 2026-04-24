"""Client-side error reporting endpoint."""
import sys
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.error_log import ErrorLog
from app.services.rate_limit import check_rate_limit

router = APIRouter(prefix="/errors", tags=["errors"])


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
    try:
        check_rate_limit(
            request,
            window_name="frontend_error_report",
            max_requests=10,
            window_seconds=60,
            error_message="Rate limited",
        )
    except Exception:
        return {"status": "rate_limited"}

    ip = request.client.host if request.client else None

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
