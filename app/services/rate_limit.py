"""Centralized rate limiting service with memory-safe cleanup.

Uses an in-memory sliding window with automatic cleanup of stale entries.
Suitable for single-instance deployments (Railway, Replit).
For multi-instance, migrate to Redis-backed rate limiting.
"""
import time
import logging
from collections import defaultdict
from typing import Optional

from fastapi import Request, HTTPException

logger = logging.getLogger("bmm-rate-limit")

# Global rate limit state
_rate_limit_windows: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
_last_cleanup = 0.0
_CLEANUP_INTERVAL = 300  # cleanup every 5 minutes
_MAX_TRACKED_IPS = 10000  # hard cap to prevent memory exhaustion


def _cleanup_stale_entries(window_seconds: int):
    """Remove stale entries from all rate limit windows."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < _CLEANUP_INTERVAL:
        return

    cutoff = now - window_seconds
    total_removed = 0
    for window_name, ip_dict in list(_rate_limit_windows.items()):
        for ip, timestamps in list(ip_dict.items()):
            fresh = [t for t in timestamps if t > cutoff]
            if fresh:
                ip_dict[ip] = fresh
            else:
                del ip_dict[ip]
                total_removed += 1
        if not ip_dict:
            del _rate_limit_windows[window_name]

    _last_cleanup = now
    if total_removed > 0:
        logger.debug(f"Rate limit cleanup removed {total_removed} stale IP entries")


def _enforce_ip_cap(window_name: str):
    """Enforce hard cap on tracked IPs per window by removing oldest entries."""
    ip_dict = _rate_limit_windows[window_name]
    if len(ip_dict) <= _MAX_TRACKED_IPS:
        return

    # Sort by most recent activity and trim
    sorted_ips = sorted(
        ip_dict.items(),
        key=lambda x: max(x[1]) if x[1] else 0,
        reverse=True
    )
    to_remove = len(sorted_ips) - _MAX_TRACKED_IPS
    for ip, _ in sorted_ips[-to_remove:]:
        del ip_dict[ip]
    logger.warning(f"Rate limit IP cap enforced for {window_name}: removed {to_remove} oldest IPs")


def check_rate_limit(
    request: Request,
    window_name: str,
    max_requests: int,
    window_seconds: int,
    error_message: str = "Rate limit exceeded. Please try again later.",
) -> None:
    """Check if the request exceeds the rate limit.

    Args:
        request: FastAPI request object
        window_name: Unique name for this rate limit window (e.g., 'login', 'gc_lookup')
        max_requests: Maximum allowed requests in the window
        window_seconds: Time window in seconds
        error_message: Custom error message when limit exceeded

    Raises:
        HTTPException: 429 if rate limit exceeded
    """
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Periodic cleanup
    _cleanup_stale_entries(window_seconds)

    # Get or create window
    ip_dict = _rate_limit_windows[window_name]
    cutoff = now - window_seconds

    # Filter stale timestamps for this IP
    timestamps = [t for t in ip_dict.get(client_ip, []) if t > cutoff]

    if len(timestamps) >= max_requests:
        logger.warning(f"Rate limit exceeded for {window_name} from IP {client_ip}")
        raise HTTPException(status_code=429, detail=error_message)

    # Record this request
    timestamps.append(now)
    ip_dict[client_ip] = timestamps

    # Enforce global IP cap
    _enforce_ip_cap(window_name)


def get_rate_limit_status(window_name: str) -> dict:
    """Get current rate limit status for monitoring."""
    ip_dict = _rate_limit_windows.get(window_name, {})
    now = time.time()
    active_ips = sum(1 for ts in ip_dict.values() if any(t > now - 3600 for t in ts))
    return {
        "window_name": window_name,
        "tracked_ips": len(ip_dict),
        "active_ips_last_hour": active_ips,
    }
