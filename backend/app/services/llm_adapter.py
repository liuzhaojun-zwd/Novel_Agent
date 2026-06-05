"""Novel_Agent — LLM Adapter：统一 OpenAI API 格式调用"""
import httpx
import json
import logging
import time
from typing import Optional, AsyncGenerator
from app.config import get_llm_config

logger = logging.getLogger("novel_agent.llm")


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
        self.temperature = temperature or cfg["temperature"]

    async def chat(
        self,
        messages: list[dict],
        response_format: Optional[dict] = None,
        max_tokens: int = 8192,
    ) -> str:
        """调用 LLM chat completion（非流式）"""
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
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                elapsed = time.time() - t0
                logger.info(f"LLM chat OK: model={self.model} tok={max_tokens} "
                           f"elapsed={elapsed:.1f}s len={len(content)} "
                           f"prompt={prompt_preview}...")
                return content
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"LLM chat FAIL: model={self.model} elapsed={elapsed:.1f}s "
                         f"error={e} prompt={prompt_preview}...")
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
    ) -> AsyncGenerator[str, None]:
        """调用 LLM 并流式返回 token 片段。
        
        每次 yield 一段文本，前端可以实时展示。
        """
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

        prompt_preview = messages[-1]["content"][:80] if messages else ""

        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=body,
                ) as resp:
                    resp.raise_for_status()
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
                       f"prompt={prompt_preview}...")
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"LLM stream FAIL: model={self.model} elapsed={elapsed:.1f}s "
                        f"error={e} prompt={prompt_preview}... chars_before_error={total_chars}")
            raise