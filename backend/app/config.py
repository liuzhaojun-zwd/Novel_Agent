"""Novel_Agent — 小说创作智能体 配置管理

支持环境变量（.env）+ 运行时动态配置。
运行时配置优先于环境变量，重启后失效（需重新配置）。
"""

import os
from pydantic_settings import BaseSettings
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    # LLM API
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_fast_model: str = ""
    llm_quality_model: str = ""
    llm_temperature: float = 0.8
    llm_context_window: int = 1000000
    llm_input_cost_per_million: float = 0.5
    llm_output_cost_per_million: float = 2.0

    # Durable worker. Disable in API replicas when running `python -m app.worker`.
    task_worker_enabled: bool = True

    # Database（支持通过环境变量覆盖，测试用）
    database_path: str = os.environ.get(
        "NOVEL_AGENT_DB_PATH", "data/novel_agent.db"
    )

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

# 运行时动态配置（前端可覆盖，重启后丢失）
_runtime_llm = {
    "base_url": None,   # str | None
    "api_key": None,
    "model": None,
    "temperature": None,
}


def get_llm_config() -> dict:
    """获取最终生效的 LLM 配置（运行时配置 > 环境变量）"""
    cfg = {
        "base_url": _runtime_llm["base_url"] or settings.llm_base_url,
        "api_key": _runtime_llm["api_key"] or settings.llm_api_key,
        "model": _runtime_llm["model"] or settings.llm_model,
        "fast_model": settings.llm_fast_model or _runtime_llm["model"] or settings.llm_model,
        "quality_model": settings.llm_quality_model or _runtime_llm["model"] or settings.llm_model,
        "input_cost_per_million": settings.llm_input_cost_per_million,
        "output_cost_per_million": settings.llm_output_cost_per_million,
        # 修复 temperature=0 被吞值：用 is not None 判断而非 or
        "temperature": (_runtime_llm["temperature"] if _runtime_llm["temperature"] is not None
                        else settings.llm_temperature),
    }
    return cfg


def set_llm_config(**kwargs):
    """更新运行时 LLM 配置"""
    for k in ("base_url", "api_key", "model", "temperature"):
        if k in kwargs and kwargs[k] is not None:
            _runtime_llm[k] = kwargs[k]


def mask_api_key(key: str) -> str:
    """掩码显示 API key，只露首尾"""
    if not key:
        return ""
    if len(key) <= 8:
        return key[:3] + "..." + key[-2:]
    return key[:5] + "..." + key[-3:]


def is_llm_configured() -> bool:
    """检查 API key 是否已配置"""
    cfg = get_llm_config()
    return bool(cfg["api_key"])


DATA_DIR = None


def get_data_dir() -> Path:
    """获取数据目录（懒初始化，确保测试时使用正确路径）"""
    global DATA_DIR
    if DATA_DIR is None or str(DATA_DIR) != str(Path(settings.database_path).parent):
        d = Path(settings.database_path).parent
        d.mkdir(parents=True, exist_ok=True)
        DATA_DIR = d
    return DATA_DIR