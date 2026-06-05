"""Novel_Agent — LLM 响应缓存（Issue 10）

基于 prompt + model 的简单内存缓存，避免重复调用 LLM 浪费 token。
"""

import hashlib
import json
import time
from typing import Optional

# 缓存存储：key -> (timestamp, content)
_cache: dict[str, tuple[float, str]] = {}

# 默认 TTL：5 分钟
_DEFAULT_TTL = 300

# 缓存最大条目数
_MAX_ENTRIES = 50


def _make_key(prompt: str, model: str) -> str:
    """生成缓存 key"""
    raw = f"{prompt}:::{model}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def get_cached(prompt: str, model: str) -> Optional[str]:
    """获取缓存的 LLM 响应"""
    key = _make_key(prompt, model)
    if key not in _cache:
        return None
    ts, content = _cache[key]
    if time.time() - ts > _DEFAULT_TTL:
        del _cache[key]
        return None
    return content


def set_cache(prompt: str, model: str, content: str):
    """缓存 LLM 响应"""
    key = _make_key(prompt, model)
    # LRU 清理：超出最大条目时删除最旧的
    if len(_cache) >= _MAX_ENTRIES:
        oldest_key = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest_key]
    _cache[key] = (time.time(), content)


def clear_cache():
    """清空所有缓存"""
    _cache.clear()


def cache_stats() -> dict:
    """缓存统计"""
    return {
        "entries": len(_cache),
        "max_entries": _MAX_ENTRIES,
        "ttl_seconds": _DEFAULT_TTL,
    }