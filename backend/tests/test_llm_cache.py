"""测试：LLM 响应缓存 (llm_cache.py)"""

import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.llm_cache import get_cached, set_cache, clear_cache, cache_stats


class TestLLMCache:
    """缓存基础功能"""

    def setup_method(self):
        clear_cache()

    def test_miss_on_empty(self):
        """没有缓存时返回 None"""
        result = get_cached("some prompt", "model-a")
        assert result is None

    def test_set_and_get(self):
        """设置后可以获取"""
        set_cache("hello", "model1", "world")
        result = get_cached("hello", "model1")
        assert result == "world"

    def test_different_model_different_cache(self):
        """不同模型的缓存隔离"""
        set_cache("hello", "model1", "world")
        result = get_cached("hello", "model2")
        assert result is None

    def test_different_prompt_different_cache(self):
        """不同 prompt 的缓存隔离"""
        set_cache("prompt-a", "model1", "result-a")
        result = get_cached("prompt-b", "model1")
        assert result is None

    def test_clear_cache(self):
        """清空缓存"""
        set_cache("hello", "model1", "world")
        clear_cache()
        result = get_cached("hello", "model1")
        assert result is None

    def test_cache_stats(self):
        """缓存统计"""
        clear_cache()
        stats = cache_stats()
        assert stats["entries"] == 0
        assert stats["max_entries"] > 0

        set_cache("a", "m1", "1")
        set_cache("b", "m1", "2")
        stats = cache_stats()
        assert stats["entries"] == 2

    def test_ttl_expiry(self):
        """TTL 过期后不可用（超短 TTL 验证）"""
        # 用一个很短的 TTL 来测试
        from app.services.llm_cache import _cache, _DEFAULT_TTL
        original_ttl = _DEFAULT_TTL
        # 修改模块内部的 TTL
        import app.services.llm_cache as cache_mod
        cache_mod._DEFAULT_TTL = 0  # 立即过期

        try:
            set_cache("expire-test", "m1", "data")
            # 小睡确保过期
            result = get_cached("expire-test", "m1")
            assert result is None
        finally:
            cache_mod._DEFAULT_TTL = original_ttl

    def test_lru_eviction(self):
        """超出最大条目时淘汰最旧的"""
        from app.services.llm_cache import _MAX_ENTRIES

        original_max = _MAX_ENTRIES
        import app.services.llm_cache as cache_mod
        cache_mod._MAX_ENTRIES = 3

        try:
            set_cache("key1", "m1", "val1")
            set_cache("key2", "m1", "val2")
            set_cache("key3", "m1", "val3")
            set_cache("key4", "m1", "val4")  # 触发 eviction
            
            assert get_cached("key1", "m1") is None  # 淘汰了
            assert get_cached("key4", "m1") == "val4"  # 最新的在
        finally:
            cache_mod._MAX_ENTRIES = original_max
            clear_cache()