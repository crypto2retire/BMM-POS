"""Lightweight circuit breaker for external HTTP calls.

Tracks failures per service. Opens after 5 failures in 60 seconds.
Stays open for 60 seconds, then moves to half-open (allows 1 probe).
"""
import time
from enum import Enum
from functools import wraps
from typing import Optional, Callable, Any

from fastapi import HTTPException


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-service circuit breaker. Supports async functions."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
        expected_exception: tuple = (Exception,),
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.expected_exception = expected_exception

        self.state = State.CLOSED
        self.failures: list[float] = []
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0

    def _is_failure_threshold_reached(self) -> bool:
        now = time.time()
        window = 60.0
        self.failures = [t for t in self.failures if now - t < window]
        return len(self.failures) >= self.failure_threshold

    def _before_call(self):
        if self.state == State.OPEN:
            if self.last_failure_time and (time.time() - self.last_failure_time) >= self.recovery_timeout:
                print(f"[CIRCUIT_BREAKER] {self.name}: OPEN -> HALF_OPEN", flush=True)
                self.state = State.HALF_OPEN
                self.half_open_calls = 0
            else:
                print(f"[CIRCUIT_BREAKER] {self.name}: OPEN - rejecting call", flush=True)
                raise HTTPException(
                    status_code=503,
                    detail=f"Service '{self.name}' is temporarily unavailable. Please try again later.",
                )

        if self.state == State.HALF_OPEN and self.half_open_calls >= self.half_open_max_calls:
            print(f"[CIRCUIT_BREAKER] {self.name}: HALF_OPEN - max calls reached, rejecting", flush=True)
            raise HTTPException(
                status_code=503,
                detail=f"Service '{self.name}' is temporarily unavailable. Please try again later.",
            )

        if self.state == State.HALF_OPEN:
            self.half_open_calls += 1

    def _on_success(self):
        if self.state == State.HALF_OPEN:
            print(f"[CIRCUIT_BREAKER] {self.name}: HALF_OPEN -> CLOSED (recovered)", flush=True)
            self.state = State.CLOSED
            self.failures = []
            self.last_failure_time = None
            self.half_open_calls = 0

    def _on_failure(self):
        now = time.time()
        self.failures.append(now)
        self.last_failure_time = now

        if self.state == State.HALF_OPEN:
            print(f"[CIRCUIT_BREAKER] {self.name}: HALF_OPEN -> OPEN (probe failed)", flush=True)
            self.state = State.OPEN
        elif self.state == State.CLOSED and self._is_failure_threshold_reached():
            print(f"[CIRCUIT_BREAKER] {self.name}: CLOSED -> OPEN ({len(self.failures)} failures)", flush=True)
            self.state = State.OPEN

    async def call_async(self, coro: Callable[[], Any]) -> Any:
        self._before_call()
        try:
            result = await coro()
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e

    def call_sync(self, fn: Callable[[], Any]) -> Any:
        self._before_call()
        try:
            result = fn()
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e


# Global breakers per external service
_square_breaker = CircuitBreaker("square", failure_threshold=5, recovery_timeout=60.0)
_openrouter_breaker = CircuitBreaker("openrouter", failure_threshold=20, recovery_timeout=30.0)
_poynt_breaker = CircuitBreaker("poynt", failure_threshold=5, recovery_timeout=60.0)


def circuit_breaker(service: str):
    """Decorator that wraps an async function with a circuit breaker."""
    breakers = {
        "square": _square_breaker,
        "openrouter": _openrouter_breaker,
        "poynt": _poynt_breaker,
    }
    breaker = breakers.get(service)
    if not breaker:
        raise ValueError(f"Unknown service: {service}")

    def decorator(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            return await breaker.call_async(lambda: fn(*args, **kwargs))
        return wrapper
    return decorator


def get_breaker_status() -> dict:
    """Return current state of all breakers for health monitoring."""
    return {
        "square": {
            "state": _square_breaker.state.value,
            "failures_last_60s": len(_square_breaker.failures),
        },
        "openrouter": {
            "state": _openrouter_breaker.state.value,
            "failures_last_60s": len(_openrouter_breaker.failures),
        },
        "poynt": {
            "state": _poynt_breaker.state.value,
            "failures_last_60s": len(_poynt_breaker.failures),
        },
    }
