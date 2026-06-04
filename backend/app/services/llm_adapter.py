"""Novel_Agent — LLM Adapter：统一 OpenAI API 格式调用"""
import httpx
import json
from typing import Optional
from app.config import get_llm_config


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
        max_tokens: int = 4096,
    ) -> str:
        """调用 LLM chat completion"""
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

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def chat_json(self, messages: list[dict], max_tokens: int = 4096) -> dict:
        """调用 LLM 并返回 JSON 格式结果"""
        content = await self.chat(
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
        )
        return json.loads(content)