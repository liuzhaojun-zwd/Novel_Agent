"""测试：上下文窗口管理器 (context_manager.py)"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.context_manager import estimate_tokens, select_context_summaries, _compress_summary


class TestEstimateTokens:
    """token 估算"""

    def test_empty(self):
        assert estimate_tokens("") == 0

    def test_chinese_chars(self):
        """中文字符 ~1.5 token/字"""
        tokens = estimate_tokens("你好世界")
        assert 5 <= tokens <= 7  # 4字 * 1.5 = 6

    def test_english_words(self):
        """英文单词 ~1.3 token/词"""
        tokens = estimate_tokens("hello world test")
        assert 3 <= tokens <= 6  # 3词 * 1.3 = 3.9

    def test_mixed(self):
        tokens = estimate_tokens("你好 world")
        assert tokens > 0

    def test_punctuation(self):
        """标点算 0.5 token"""
        tokens = estimate_tokens("你好，世界！")
        assert 6 <= tokens <= 10  # 4字*1.5 + 2标点*0.5 = 7


class TestSelectContextSummaries:
    """摘要动态选择"""

    def test_empty_summaries(self):
        result = select_context_summaries([])
        assert result == []

    def test_single_summary_within_budget(self):
        summaries = ["第1章（标题）：内容摘要"]
        result = select_context_summaries(summaries, budget=10000)
        assert len(result) == 1
        assert result[0] == summaries[0]

    def test_all_within_budget(self):
        summaries = [
            f"第{i}章（标题）：{'内容' * 10}" for i in range(1, 6)
        ]
        result = select_context_summaries(summaries, budget=50000)
        assert len(result) == 5
        assert result[0] == summaries[0]

    def test_truncated_when_over_budget(self):
        """超出预算时自动截断，优先保留最近的"""
        summaries = [
            f"第{i}章（标题）：{'很长的摘要内容' * 50}" for i in range(1, 11)
        ]
        budget = 500  # 很小
        result = select_context_summaries(summaries, budget=budget)
        assert 1 <= len(result) <= 10
        # 最近的摘要应该保留（即使被压缩）
        assert result[-1].startswith("第10章")

    def test_returns_newest_first_logic(self):
        """优先保留最新的摘要"""
        summaries = [
            f"第{i}章（标题）：{'内容' * 5}" for i in range(1, 6)
        ]
        result = select_context_summaries(summaries, budget=200)
        if len(result) < len(summaries):
            # 被截断时，最新的保留
            assert result[-1] == summaries[-1]


class TestCompressSummary:
    """摘要压缩"""

    def test_short_uncompressed(self):
        s = "第1章（标题）：短内容"
        compressed = _compress_summary(s)
        assert compressed == s

    def test_long_compressed(self):
        s = "第1章（标题）：" + "很长" * 100
        compressed = _compress_summary(s, max_chars=50)
        assert len(compressed) <= 53  # 50 + 3 off-by-one
        assert "..." in compressed

    def test_no_prefix(self):
        """没有章节标记时也能截断"""
        s = "这是一段没有章节标记的非常长的内容。" * 30
        compressed = _compress_summary(s, max_chars=30)
        assert len(compressed) <= 33