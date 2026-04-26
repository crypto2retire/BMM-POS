import os
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from app.config import settings
from app.services.circuit_breaker import circuit_breaker

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def ai_runtime_mode() -> str:
    return "local" if settings.offline_mode else "cloud"


def local_vision_enabled() -> bool:
    return bool((settings.local_llm_vision_model or "").strip())


def _openrouter_api_key() -> str:
    return (settings.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY", "")).strip()


def _local_chat_completions_url() -> str:
    base_url = (settings.local_llm_base_url or "").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="Local AI is not configured")
    if base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _local_model_name(*, prefer_vision: bool, require_vision: bool) -> str:
    vision_model = (settings.local_llm_vision_model or "").strip()
    if prefer_vision and vision_model:
        return vision_model
    if prefer_vision and require_vision:
        raise HTTPException(
            status_code=503,
            detail="Offline vision AI is not configured. Set LOCAL_LLM_VISION_MODEL first.",
        )
    model = (settings.local_llm_chat_model or "").strip()
    if not model:
        raise HTTPException(status_code=503, detail="Local AI is not configured")
    return model


async def _post_json(url: str, *, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="AI request timed out")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"AI network error: {exc}") from exc

    if response.status_code == 429:
        print(f"[LLM_GATEWAY] OpenRouter 429 - rate limited", flush=True)
        raise HTTPException(status_code=429, detail="AI rate limit exceeded. Please try again shortly.")
    if response.status_code == 401:
        print(f"[LLM_GATEWAY] OpenRouter 401 - invalid API key", flush=True)
        raise HTTPException(status_code=503, detail="AI credentials are invalid or missing")
    if response.status_code == 404:
        print(f"[LLM_GATEWAY] OpenRouter 404 - endpoint not found: {url}", flush=True)
        raise HTTPException(status_code=503, detail=f"AI endpoint not found at {url}")
    if not response.is_success:
        body_preview = response.text[:200] if hasattr(response, 'text') else 'N/A'
        print(f"[LLM_GATEWAY] OpenRouter error status={response.status_code} body={body_preview}", flush=True)
        raise HTTPException(status_code=502, detail="AI service unavailable")

    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="AI service returned invalid JSON") from exc


@circuit_breaker("openrouter")
async def _call_openrouter(
    *,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]],
    max_tokens: int,
    referer: str,
    title: str,
) -> dict[str, Any]:
    api_key = _openrouter_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Assistant not configured. Please add your OpenRouter API key.",
        )

    payload: dict[str, Any] = {
        "model": "google/gemini-2.0-flash-001",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    return await _post_json(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": referer,
            "X-Title": title,
            "Content-Type": "application/json",
        },
        payload=payload,
        timeout=60.0,
    )


async def _call_local_llm(
    *,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]],
    max_tokens: int,
    prefer_vision: bool,
    require_vision: bool,
) -> dict[str, Any]:
    model = _local_model_name(prefer_vision=prefer_vision, require_vision=require_vision)
    headers = {"Content-Type": "application/json"}
    api_key = (settings.local_llm_api_key or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    return await _post_json(
        _local_chat_completions_url(),
        headers=headers,
        payload=payload,
        timeout=float(settings.local_llm_timeout_seconds or 60.0),
    )


async def chat_completion(
    *,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    max_tokens: int = 500,
    referer: str = "https://bowenstreetmarket.com",
    title: str = "Bowenstreet Market POS",
    prefer_vision: bool = False,
    require_local_vision: bool = False,
) -> dict[str, Any]:
    if settings.offline_mode:
        return await _call_local_llm(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            prefer_vision=prefer_vision,
            require_vision=require_local_vision,
        )

    if _openrouter_api_key():
        return await _call_openrouter(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            referer=referer,
            title=title,
        )

    if settings.local_ai_enabled:
        return await _call_local_llm(
            messages=messages,
            tools=tools,
            max_tokens=max_tokens,
            prefer_vision=prefer_vision,
            require_vision=require_local_vision,
        )

    raise HTTPException(status_code=503, detail="AI assistant is not configured")
