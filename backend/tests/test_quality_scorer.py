"""测试：写作质量评估器 (quality_scorer.py)"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.quality_scorer import score_chapter, score_summary


class TestScoreSummary:
    """score_summary 的输出格式"""

    def test_excellent(self):
        s = score_summary({"overall": 95})
        assert "优秀" in s and "95" in s

    def test_good(self):
        s = score_summary({"overall": 80})
        assert "良好" in s and "80" in s

    def test_passable(self):
        s = score_summary({"overall": 65})
        assert "及格" in s and "65" in s

    def test_needs_improvement(self):
        s = score_summary({"overall": 50})
        assert "待改进" in s and "50" in s

    def test_rewrite(self):
        s = score_summary({"overall": 30})
        assert "重写" in s and "30" in s


class TestScoreChapter:
    """score_chapter 评分逻辑"""

    def test_empty_content(self):
        result = score_chapter("", "第一章", 2000, 1)
        assert result["overall"] == 0
        assert "章节内容为空" in result["issues"]

    def test_word_count_exact(self):
        """刚好达标"""
        content = "测试正文。" * 500  # 2000字
        result = score_chapter(content, "第一章", 2000, 1)
        # 字数维度高分，但其他维度（如段落、对话、重复）可能拉低总分
        assert result["dimensions"]["word_count"] >= 90
        assert result["overall"] >= 30  # 其他维度影响，不设过高期望

    def test_word_count_short(self):
        """字数不足一半"""
        content = "测试。" * 50  # ~150字
        result = score_chapter(content, "第一章", 2000, 1)
        assert result["dimensions"]["word_count"] < 50
        assert any("字数不足" in i for i in result["issues"])

    def test_dialogue_none(self):
        """无对话"""
        content = "今天天气很好。小明走在路上。他看到了很多花。" * 200
        result = score_chapter(content, "第一章", 2000, 1)
        assert result["dimensions"]["dialogue"] <= 30
        assert any("无对话" in i for i in result["issues"])

    def test_dialogue_good_ratio(self):
        """中等对话比例——使用中文引号包裹的对话"""
        content = ("「这本书真好看。」小明说。「是啊。」小红回答。他们继续走着。" * 100)
        result = score_chapter(content, "第一章", 2000, 1)
        # 对话比例应该在合理范围内
        assert result["dimensions"]["dialogue"] >= 40

    def test_paragraph_diversity_many(self):
        """段落数多"""
        content = "\n\n".join([f"这是第{i}段的内容。" * 3 for i in range(15)])
        result = score_chapter(content, "第一章", 2000, 1)
        assert result["dimensions"]["paragraph_diversity"] >= 70

    def test_paragraph_diversity_few(self):
        """段落太少"""
        content = "只有一段。但是很长。" * 400
        result = score_chapter(content, "第一章", 2000, 1)
        assert result["dimensions"]["paragraph_diversity"] <= 30

    def test_repetition_many(self):
        """大量重复短语"""
        content = ("突然之间。" * 100) + ("就在这时。" * 100)
        result = score_chapter(content, "第一章", 2000, 1)
        assert result["dimensions"]["repetition"] < 60
        assert any("重复短语" in i for i in result["issues"])

    def test_repetition_none(self):
        """无重复——每次内容略有不同"""
        # 每个段落不同，减少重复
        content = "小明走进了森林。树木高大茂密。阳光透过树叶洒下来。" * 30
        content += "小红站在河边。河水清澈见底。鱼群在水中游动。" * 30
        content += "老人在树下休息。微风拂过他的脸。远处传来鸟鸣声。" * 30
        result = score_chapter(content, "第一章", 2000, 1)
        # 即使这些不同，ngram检测仍可能命中少量重复
        assert result["dimensions"]["repetition"] >= 30

    def test_opening_dialogue(self):
        """以对话开头"""
        content = "小明说道：我们走吧。"
        content += "这是后续内容。" * 300
        result = score_chapter(content, "第一章", 2000, 1)
        assert result["dimensions"]["opening"] <= 60
        assert any("对话开头" in i for i in result["issues"])

    def test_sentence_variety_good(self):
        """句式多样——长短句和不同标点"""
        content = "小明走在大街上。突然，他看到了一个熟悉的身影！那会是谁呢？他快步追了上去。就在这时，天空下起了雨。他停下脚步，抬头望去。雨水打湿了他的脸。远处传来呼唤声。会是她吗？"
        content = content * 30
        result = score_chapter(content, "第一章", 2000, 1)
        # 有长短句和不同标点，句式分应该不错
        assert result["dimensions"]["sentence_variety"] >= 40

    def test_overall_scale(self):
        """综合分范围 0-100"""
        content = "优秀的内容。" * 500
        result = score_chapter(content, "第一章", 2000, 1)
        assert 0 <= result["overall"] <= 100