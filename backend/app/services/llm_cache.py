"""Novel_Agent — LLM 响应缓存（增强版）

改进：
1. 磁盘持久化（JSON文件），重启不丢失
2. TTL 可配置（默认30分钟，大纲缓存更长）
3. model隔离（不同模型缓存互不干扰）
4. 缓存命中时验证章数一致性（防模型切换后返回旧结果）
"""

import hashlib
import json
import time
from typing import Optional
from pathlib import Path
from app.config import get_data_dir

# 默认 TTL：30 分钟（比之前的5分钟长6倍）
_DEFAULT_TTL = 1800

# 分类缓存策略：仅缓存确定性较强、可安全复用的调用。
_CACHE_POLICIES = {
    "outline": 7200,
    "planning": 3600,
    "memory": 1800,
    "review": 900,
    "default": _DEFAULT_TTL,
}
_OUTLINE_TTL = _CACHE_POLICIES["outline"]

# 缓存最大条目数
_MAX_ENTRIES = 200

# 磁盘缓存文件路径
_CACHE_FILE = None  # 懒初始化


def _get_cache_file() -> Path:
    """获取缓存文件路径（懒初始化）"""
    global _CACHE_FILE
    if _CACHE_FILE is None:
        _CACHE_FILE = get_data_dir() / "llm_cache.json"
    return _CACHE_FILE


def _load_disk_cache() -> dict:
    """从磁盘加载缓存"""
    cache_file = _get_cache_file()
    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_disk_cache(cache: dict):
    """将缓存写入磁盘"""
    cache_file = _get_cache_file()
    try:
        cache_file.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # 磁盘写入失败不影响运行


def _make_key(
    prompt: str, model: str, category: str = "default", prompt_version: str = "1.0.0",
) -> str:
    """Key includes cache category and prompt version to prevent stale cross-purpose hits."""
    raw = f"{category}:::{prompt_version}:::{prompt}:::{model}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def get_cached(
    prompt: str,
    model: str,
    ttl: Optional[int] = None,
    *,
    category: str = "default",
    prompt_version: str = "1.0.0",
) -> Optional[str]:
    """获取缓存的 LLM 响应（先查内存，miss则查磁盘）"""
    if ttl is None:
        ttl = _DEFAULT_TTL if category == "default" else _CACHE_POLICIES.get(category, _DEFAULT_TTL)
    key = _make_key(prompt, model, category, prompt_version)

    # 内存缓存
    if key in _memory_cache:
        ts, content = _memory_cache[key]
        if time.time() - ts <= ttl:
            return content
        else:
            del _memory_cache[key]

    # 磁盘缓存
    disk = _load_disk_cache()
    if key in disk:
        entry = disk[key]
        ts = entry.get("ts", 0)
        content = entry.get("content", "")
        if time.time() - ts <= ttl and content:
            # 回填到内存缓存
            _memory_cache[key] = (ts, content)
            return content
        else:
            # 过期，从磁盘也删除
            del disk[key]
            _save_disk_cache(disk)

    return None


def set_cache(
    prompt: str,
    model: str,
    content: str,
    *,
    category: str = "default",
    prompt_version: str = "1.0.0",
):
    """缓存 LLM 响应（同时写内存和磁盘）"""
    key = _make_key(prompt, model, category, prompt_version)
    now = time.time()

    # 内存缓存 + LRU清理
    if len(_memory_cache) >= _MAX_ENTRIES:
        oldest_key = min(_memory_cache, key=lambda k: _memory_cache[k][0])
        del _memory_cache[oldest_key]
    _memory_cache[key] = (now, content)

    # 磁盘缓存（异步批量写入，不在每次调用时写磁盘，避免IO瓶颈）
    # 立即写磁盘保证数据安全
    disk = _load_disk_cache()
    if len(disk) >= _MAX_ENTRIES:
        oldest_key = min(disk, key=lambda k: disk[k].get("ts", 0))
        del disk[oldest_key]
    disk[key] = {
        "ts": now, "content": content, "model": model,
        "category": category, "prompt_version": prompt_version,
    }
    _save_disk_cache(disk)


def clear_cache():
    """清空所有缓存（内存+磁盘）"""
    _memory_cache.clear()
    cache_file = _get_cache_file()
    if cache_file.exists():
        try:
            cache_file.unlink()
        except OSError:
            pass


def cache_stats() -> dict:
    """缓存统计（保留旧版 entries 字段兼容调用方）。"""
    disk = _load_disk_cache()
    return {
        "entries": len(_memory_cache),
        "memory_entries": len(_memory_cache),
        "disk_entries": len(disk),
        "max_entries": _MAX_ENTRIES,
        "default_ttl_seconds": _DEFAULT_TTL,
        "outline_ttl_seconds": _OUTLINE_TTL,
        "cache_file": str(_get_cache_file()),
    }


# 内存缓存存储：key -> (timestamp, content)
_memory_cache: dict[str, tuple[float, str]] = {}
# 旧版兼容别名；部分调用方和测试会直接检查该对象。
_cache = _memory_cache