"""Novel_Agent — LLM Adapter：统一 OpenAI API 格式调用

增强：指数退避重试 + 429 处理 + 简易熔断
"""
import httpx
import json
import logging
import time
import asyncio
from typing import Optional, AsyncGenerator
from app.config import get_llm_config

logger = logging.getLogger("novel_agent.llm")

# ── 重试 & 熔断 ──
_MAX_RETRIES = 3
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRY_BASE_DELAY = 2.0  # 秒

# 熔断：连续失败计数
_consecutive_failures = 0
_CIRCUIT_BREAK_THRESHOLD = 5
_CIRCUIT_BREAK_COOLDOWN = 60.0  # 秒
_circuit_break_until = 0.0


def _is_circuit_open() -> bool:
    """熔断器是否打开"""
    if _consecutive_failures < _CIRCUIT_BREAK_THRESHOLD:
        return False
    if time.time() < _circuit_break_until:
        return True
    # 冷却期结束，半开
    return False


def _record_success():
    """记录成功调用，重置熔断计数"""
    global _consecutive_failures
    _consecutive_failures = 0


def _record_failure():
    """记录失败调用，触发熔断"""
    global _consecutive_failures, _circuit_break_until
    _consecutive_failures += 1
    if _consecutive_failures >= _CIRCUIT_BREAK_THRESHOLD:
        _circuit_break_until = time.time() + _CIRCUIT_BREAK_COOLDOWN
        logger.warning(f"熔断触发：连续失败{_consecutive_failures}次，暂停{_CIRCUIT_BREAK_COOLDOWN}s")


class LLMAdapter:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        cfg = get_llm_config()
        self.base_url = base_url or cfg["base_url"]
        self.api_key = api_key or cfg["api_key"]
        self.model = model or cfg["model"]
        # 修复 temperature=0 吞值
        self.temperature = (temperature if temperature is not None else cfg["temperature"])

    async def chat(
        self,
        messages: list[dict],
        response_format: Optional[dict] = None,
        max_tokens: int = 8192,
    ) -> str:
        """调用 LLM chat completion（非流式），带指数退避重试"""
        # 熔断检查
        if _is_circuit_open():
            raise RuntimeError(f"LLM 熔断中，请等待{_CIRCUIT_BREAK_COOLDOWN}s后重试")

        t0 = time.time()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format

        prompt_preview = messages[-1]["content"][:80] if messages else ""

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=180.0) as client:
                    resp = await client.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=body,
                    )

                if resp.status_code in _RETRYABLE_STATUS_CODES:
                    retry_after = float(resp.headers.get("Retry-After", _RETRY_BASE_DELAY * (2 ** (attempt - 1))))
                    logger.warning(f"LLM 可重试错误: status={resp.status_code} attempt={attempt}/{_MAX_RETRIES} retry_after={retry_after}s")
                    if attempt < _MAX_RETRIES:
                        await asyncio.sleep(retry_after)
                        continue
                    # 最后一次重试也失败
                    resp.raise_for_status()

                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                elapsed = time.time() - t0
                logger.info(f"LLM chat OK: model={self.model} tok={max_tokens} "
                           f"elapsed={elapsed:.1f}s len={len(content)} "
                           f"attempt={attempt} prompt={prompt_preview}...")
                _record_success()
                return content

            except httpx.HTTPStatusError as e:
                if e.response.status_code not in _RETRYABLE_STATUS_CODES:
                    # 非可重试错误（401/403等），直接失败
                    elapsed = time.time() - t0
                    logger.error(f"LLM chat FAIL (non-retryable): model={self.model} status={e.response.status_code} "
                                 f"elapsed={elapsed:.1f}s prompt={prompt_preview}...")
                    _record_failure()
                    raise
                # 可重试错误已在上面处理
                elapsed = time.time() - t0
                logger.error(f"LLM chat FAIL after {_MAX_RETRIES} retries: model={self.model} "
                             f"elapsed={elapsed:.1f}s prompt={prompt_preview}...")
                _record_failure()
                raise

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(f"LLM 网络/超时错误: {type(e).__name__} attempt={attempt}/{_MAX_RETRIES} delay={delay}s")
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    continue
                elapsed = time.time() - t0
                logger.error(f"LLM chat FAIL after {_MAX_RETRIES} retries (timeout/connect): "
                             f"elapsed={elapsed:.1f}s prompt={prompt_preview}...")
                _record_failure()
                raise

            except Exception as e:
                elapsed = time.time() - t0
                logger.error(f"LLM chat FAIL (unexpected): model={self.model} elapsed={elapsed:.1f}s "
                             f"error={e} prompt={prompt_preview}...")
                _record_failure()
                raise

    async def chat_json(self, messages: list[dict], max_tokens: int = 8192) -> dict:
        """调用 LLM 并返回 JSON 格式结果"""
        content = await self.chat(
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
        return json.loads(content)

    async def chat_stream(
        self,
        messages: list[dict],
        max_tokens: int = 8192,
        response_format: Optional[dict] = None,
    ) -> AsyncGenerator[str, None]:
        """调用 LLM 并流式返回 token 片段。带重试（连接阶段）。"""
        # 熔断检查
        if _is_circuit_open():
            raise RuntimeError(f"LLM 熔断中，请等待{_CIRCUIT_BREAK_COOLDOWN}s后重试")

        t0 = time.time()
        total_chars = 0
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if response_format:
            body["response_format"] = response_format

        prompt_preview = messages[-1]["content"][:80] if messages else ""

        # 连接阶段重试（stream 建立后不再重试）
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    async with client.stream(
                        "POST",
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=body,
                    ) as resp:
                        # 连接阶段的 HTTP 错误
                        if resp.status_code in _RETRYABLE_STATUS_CODES:
                            retry_after = float(resp.headers.get("Retry-After", _RETRY_BASE_DELAY * (2 ** (attempt - 1))))
                            logger.warning(f"LLM stream 可重试错误: status={resp.status_code} attempt={attempt} retry_after={retry_after}s")
                            if attempt < _MAX_RETRIES:
                                await asyncio.sleep(retry_after)
                                continue
                            resp.raise_for_status()

                        resp.raise_for_status()
                        # 连接成功，开始流式读取
                        async for line in resp.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:].strip()
                            if payload == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    total_chars += len(content)
                                    yield content
                            except (json.JSONDecodeError, KeyError, IndexError):
                                continue

                elapsed = time.time() - t0
                logger.info(f"LLM stream OK: model={self.model} tok={max_tokens} "
                           f"elapsed={elapsed:.1f}s chars={total_chars} "
                           f"attempt={attempt} prompt={prompt_preview}...")
                _record_success()
                return  # stream 正常结束

            except httpx.HTTPStatusError as e:
                if e.response.status_code not in _RETRYABLE_STATUS_CODES:
                    _record_failure()
                    raise
                # 可重试的已在上面处理了（attempt == _MAX_RETRIES 时 raise）
                elapsed = time.time() - t0
                logger.error(f"LLM stream FAIL after {_MAX_RETRIES} retries: status={e.response.status_code}")
                _record_failure()
                raise

            except (httpx.TimeoutException, httpx.ConnectError) as e:
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(f"LLM stream 网络/超时: {type(e).__name__} attempt={attempt} delay={delay}s")
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(delay)
                    continue
                elapsed = time.time() - t0
                logger.error(f"LLM stream FAIL after {_MAX_RETRIES} retries: {type(e).__name__}")
                _record_failure()
                raise

            except Exception as e:
                elapsed = time.time() - t0
                logger.error(f"LLM stream FAIL: model={self.model} elapsed={elapsed:.1f}s "
                            f"error={e} prompt={prompt_preview}... chars_before_error={total_chars}")
                _record_failure()
                raise