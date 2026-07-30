"""OpenAI-compatible LLM adapter with pooled HTTP, routing, retries and metrics."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse

import httpx

from app.config import get_llm_config
from app.services import llm_cache, llm_metrics
from app.services.model_router import select_model
from app.services.prompt_registry import get_prompt_version, template_hash

logger = logging.getLogger("novel_agent.llm")
_MAX_RETRIES = 3
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRY_BASE_DELAY = 2.0
_http_client: httpx.AsyncClient | None = None


async def init_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=20.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    return _http_client


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()
    _http_client = None


def _estimate_tokens(messages: list[dict], content: str) -> tuple[int, int]:
    input_chars = sum(len(str(message.get("content", ""))) for message in messages)
    return max(1, round(input_chars * 1.2)), max(1, round(len(content) * 1.5))
class LLMAdapter:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        *,
        purpose: str = "default",
        prompt_id: str | None = None,
        job_id: str | None = None,
    ):
        cfg = get_llm_config()
        self.base_url = base_url or cfg["base_url"]
        self.api_key = api_key or cfg["api_key"]
        self.requested_model = model
        self.temperature = temperature if temperature is not None else cfg["temperature"]
        self.purpose = purpose
        self.prompt_id = prompt_id or purpose
        self.job_id = job_id
        route = select_model(purpose, model)
        self.model = route["model"]

    def _metadata(self, messages: list[dict], purpose: str | None, prompt_id: str | None) -> dict:
        selected_purpose = purpose or self.purpose
        selected_prompt = prompt_id or self.prompt_id or selected_purpose
        route = select_model(selected_purpose, self.requested_model)
        cfg = get_llm_config()
        return {
            "purpose": selected_purpose,
            "prompt_id": selected_prompt,
            "prompt_version": get_prompt_version(selected_prompt),
            "template_hash": template_hash(messages),
            "model": route["model"],
            "model_tier": route["tier"],
            "input_rate": route["input_cost_per_million"],
            "output_rate": route["output_cost_per_million"],
            "provider": urlparse(cfg["base_url"]).netloc or "openai-compatible",
        }

    async def _record(self, meta: dict, **values) -> None:
        try:
            await llm_metrics.record_call(job_id=self.job_id, **meta, **values)
        except Exception as exc:
            logger.warning("llm_metric_write_failed error=%s", exc)

    async def chat(
        self,
        messages: list[dict],
        response_format: Optional[dict] = None,
        max_tokens: int = 8192,
        *,
        purpose: str | None = None,
        prompt_id: str | None = None,
        cache_category: str | None = None,
    ) -> str:
        meta = self._metadata(messages, purpose, prompt_id)
        cache_input = json.dumps(
            {"messages": messages, "temperature": self.temperature, "response_format": response_format},
            ensure_ascii=False, sort_keys=True,
        )
        if cache_category:
            cached = llm_cache.get_cached(
                cache_input, meta["model"], category=cache_category,
                prompt_version=meta["prompt_version"],
            )
            if cached is not None:
                input_tokens, output_tokens = _estimate_tokens(messages, cached)
                await self._record_usage(meta, input_tokens, output_tokens, 0, 0, True, True)
                return cached
        body = {
            "model": meta["model"], "messages": messages,
            "temperature": self.temperature, "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format
        started = time.perf_counter()
        client = await init_http_client()
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers=self._headers(), json=body,
                )
                if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                    await asyncio.sleep(self._retry_delay(response, attempt))
                    continue
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                estimated = not bool(usage)
                input_tokens, output_tokens = (
                    (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                    if usage else _estimate_tokens(messages, content)
                )
                latency_ms = round((time.perf_counter() - started) * 1000)
                await self._record_usage(
                    meta, input_tokens, output_tokens, latency_ms, attempt, estimated, False,
                    response.headers.get("x-request-id") or data.get("id"),
                )
                if cache_category:
                    llm_cache.set_cache(
                        cache_input, meta["model"], content, category=cache_category,
                        prompt_version=meta["prompt_version"],
                    )
                logger.info(
                    "llm_call status=ok purpose=%s model=%s tier=%s latency_ms=%s attempt=%s",
                    meta["purpose"], meta["model"], meta["model_tier"], latency_ms, attempt,
                )
                return content
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in _RETRYABLE_STATUS_CODES
                if retryable and attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
                    continue
                await self._record(
                    meta, status="error", attempt_count=attempt,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    error_code=type(exc).__name__,
                )
                raise
        raise RuntimeError("LLM 调用重试耗尽")

    async def chat_json(self, messages: list[dict], max_tokens: int = 8192, **kwargs) -> dict:
        content = await self.chat(
            messages, response_format={"type": "json_object"}, max_tokens=max_tokens, **kwargs,
        )
        return json.loads(content)
    async def chat_stream(
        self,
        messages: list[dict],
        max_tokens: int = 8192,
        response_format: Optional[dict] = None,
        *,
        purpose: str | None = None,
        prompt_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        meta = self._metadata(messages, purpose, prompt_id)
        body = {
            "model": meta["model"], "messages": messages, "temperature": self.temperature,
            "max_tokens": max_tokens, "stream": True,
        }
        if response_format:
            body["response_format"] = response_format
        started = time.perf_counter()
        content_parts: list[str] = []
        usage: dict = {}
        client = await init_http_client()
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with client.stream(
                    "POST", f"{self.base_url.rstrip('/')}/chat/completions",
                    headers=self._headers(), json=body,
                ) as response:
                    if response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                        await response.aread()
                        await asyncio.sleep(self._retry_delay(response, attempt))
                        continue
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                            if chunk.get("usage"):
                                usage = chunk["usage"]
                            text = chunk["choices"][0].get("delta", {}).get("content", "")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue
                        if text:
                            content_parts.append(text)
                            yield text
                content = "".join(content_parts)
                estimated = not bool(usage)
                input_tokens, output_tokens = (
                    (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
                    if usage else _estimate_tokens(messages, content)
                )
                latency_ms = round((time.perf_counter() - started) * 1000)
                await self._record_usage(
                    meta, input_tokens, output_tokens, latency_ms, attempt, estimated, False,
                    response.headers.get("x-request-id"),
                )
                logger.info(
                    "llm_stream status=ok purpose=%s model=%s latency_ms=%s attempt=%s chars=%s",
                    meta["purpose"], meta["model"], latency_ms, attempt, len(content),
                )
                return
            except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as exc:
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in _RETRYABLE_STATUS_CODES
                if retryable and attempt < _MAX_RETRIES and not content_parts:
                    await asyncio.sleep(_RETRY_BASE_DELAY * (2 ** (attempt - 1)))
                    continue
                await self._record(
                    meta, status="error", attempt_count=attempt,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                    error_code=type(exc).__name__,
                )
                raise
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        try:
            return min(60.0, float(response.headers.get("Retry-After", 0))) or _RETRY_BASE_DELAY * (2 ** (attempt - 1))
        except ValueError:
            return _RETRY_BASE_DELAY * (2 ** (attempt - 1))

    async def _record_usage(
        self,
        meta: dict,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        attempt: int,
        estimated: bool,
        cache_hit: bool,
        provider_request_id: str | None = None,
    ) -> None:
        cost = (
            input_tokens * meta["input_rate"] + output_tokens * meta["output_rate"]
        ) / 1_000_000
        ledger_meta = {key: value for key, value in meta.items() if key not in {"input_rate", "output_rate"}}
        await self._record(
            ledger_meta, status="ok", input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=cost, usage_estimated=estimated, cache_hit=cache_hit,
            attempt_count=max(1, attempt), latency_ms=latency_ms,
            provider_request_id=provider_request_id,
        )
