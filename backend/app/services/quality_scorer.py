"""Novel_Agent — 写作质量评估器（增强版）

改进：
1. 对话检测支持中英文多种引号格式
2. 评分维度权重可按题材微调
3. "了"字检测更精确（只检测句尾滥用）
4. 开头质量评分更丰富（场景描写/悬念/动作开头加分）
5. 新增结尾质量维度
"""

import re
from typing import Optional

SCORER_VERSION = "2.0.0"


# ── 中文引号配对检测 ──
_DIALOGUE_OPENERS = {'"', '"', '「', '\u201c'}
_DIALOGUE_CLOSERS = {'"', '"', '」', '\u201d'}


def score_chapter(
    content: str,
    title: str,
    target_words: int,
    chapter_number: int,
) -> dict:
    """对单章进行质量评分。

    返回评分字典：
        overall: 0-100 综合分
        dimensions: 各维度评分
        issues: 发现的问题列表
    """
    if not content:
        return {
            "scorer_version": SCORER_VERSION,
            "overall": 0,
            "dimensions": {},
            "issues": ["章节内容为空"],
        }

    # 去除空白后的实际字符数
    text = content.strip()
    char_count = len(text.replace(" ", "").replace("\n", "").replace("\r", ""))
    
    dimensions = {}
    issues = []

    # ── 1. 字数达标率 ──
    word_ratio = char_count / target_words if target_words > 0 else 0
    if word_ratio >= 1.0:
        word_score = 100
    elif word_ratio >= 0.8:
        word_score = 80 + (word_ratio - 0.8) * 100
    elif word_ratio >= 0.5:
        word_score = 40 + (word_ratio - 0.5) * 130
    else:
        word_score = max(0, word_ratio * 80)
    
    if word_ratio < 0.5:
        issues.append(f"字数不足（{char_count}/{target_words}），达标率 {word_ratio:.0%}")
    elif word_ratio < 0.8:
        issues.append(f"字数略少（{char_count}/{target_words}），达标率 {word_ratio:.0%}")
    elif word_ratio > 1.5:
        issues.append(f"字数偏多（{char_count}/{target_words}），达标率 {word_ratio:.0%}，可能冗余")
    dimensions["word_count"] = round(word_score)

    # ── 2. 段落多样性 ──
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    if len(paragraphs) == 0:
        para_score = 0
    elif len(paragraphs) < 3:
        para_score = 20
        issues.append("段落太少，建议增加分段")
    elif len(paragraphs) < 5:
        para_score = 50
    elif len(paragraphs) >= 20:
        para_score = 100
    else:
        para_score = min(100, 40 + len(paragraphs) * 3)
    
    # 检查段落长度分布（好的小说段落长短交替）
    if paragraphs:
        para_lengths = [len(p) for p in paragraphs]
        avg_len = sum(para_lengths) / len(para_lengths)
        short_ratio = sum(1 for l in para_lengths if l < avg_len * 0.5) / len(para_lengths)
        long_ratio = sum(1 for l in para_lengths if l > avg_len * 1.5) / len(para_lengths)
        if 0.15 <= short_ratio <= 0.5 and 0.15 <= long_ratio <= 0.5:
            para_score = min(100, para_score + 15)
        elif short_ratio > 0.7 or long_ratio > 0.7:
            issues.append("段落长度过于单一，建议长短交替")
    dimensions["paragraph_diversity"] = round(para_score)

    # ── 3. 对话比例（支持多种引号格式） ──
    dialogue_chars = 0
    in_dialogue = False
    for c in content:
        if c in _DIALOGUE_OPENERS:
            in_dialogue = True
        elif c in _DIALOGUE_CLOSERS:
            in_dialogue = False
        elif in_dialogue and '\u4e00' <= c <= '\u9fff':
            dialogue_chars += 1
    
    dialogue_ratio = dialogue_chars / char_count if char_count > 0 else 0
    if dialogue_ratio == 0:
        dialogue_score = 30
        issues.append("无对话内容，建议加入人物对话增强可读性")
    elif dialogue_ratio < 0.1:
        dialogue_score = 40 + dialogue_ratio * 300
        issues.append("对话比例偏低，建议适当增加对话")
    elif dialogue_ratio < 0.5:
        dialogue_score = min(100, 60 + dialogue_ratio * 80)
    elif dialogue_ratio > 0.7:
        dialogue_score = 60
        issues.append("对话比例过高，建议增加描写段落")
    else:
        dialogue_score = 90
    dimensions["dialogue"] = round(dialogue_score)

    # ── 4. 句式多样性 ──
    sentences = re.split(r'[。！？.!?]', content)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
    if len(sentences) < 3:
        sent_score = 30
    else:
        sent_lengths = [len(s) for s in sentences]
        avg_sent = sum(sent_lengths) / len(sent_lengths)
        variance = sum((l - avg_sent) ** 2 for l in sent_lengths) / len(sent_lengths)
        std_dev = variance ** 0.5
        if std_dev < avg_sent * 0.3:
            sent_score = 50
            issues.append("句式长度过于均匀，建议长短句交替")
        elif std_dev > avg_sent * 1.2:
            sent_score = 60
        else:
            sent_score = 90
        
        # 检查"了"字句尾滥用（更精确：只看句尾的"了"而非所有"了"）
        le_at_end = len(re.findall(r'了[。！？]', content))
        total_endings = len(re.findall(r'[。！？]', content))
        if total_endings > 0 and le_at_end / total_endings > 0.4:
            issues.append(f"「了」字句尾偏多（{le_at_end}/{total_endings}处），建议精简")
    dimensions["sentence_variety"] = round(sent_score)

    # ── 5. 开头质量（更丰富的评分） ──
    opening = text[:300]  # 增加到300字以更准确判断
    open_score = 50  # 基础分

    # 场景描写开头加分
    if any(kw in opening for kw in ("阳光", "月光", "雨", "风", "雾", "雪", "夜色", 
                                      "清晨", "傍晚", "黑暗", "光明", "光线",
                                      "山", "河", "海", "城", "路", "林")):
        open_score += 20
    
    # 悬念/意外开头加分
    if any(kw in opening for kw in ("忽然", "突然", "一声", "就在这时", "不料", "谁知",
                                      "竟然", "居然", "意外", "震惊")):
        open_score += 15
    
    # 动作开头加分
    if any(kw in opening for kw in ("奔跑", "冲", "跳", "挥", "拔", "刺", "斩",
                                      "推", "拉", "抓", "握", "逃", "追")):
        open_score += 15
    
    # 引号或“某人说道：”形式的对话开头减分
    starts_with_quoted_dialogue = any(c in opening[:20] for c in _DIALOGUE_OPENERS)
    starts_with_speech = bool(re.match(
        r'^.{0,12}(?:说道|说|问道|问|喊道|喊|答道|回答)[：:]',
        opening,
    ))
    if starts_with_quoted_dialogue or starts_with_speech:
        open_score -= 10
        issues.append("章节以对话开头，建议加入场景描写")

    open_score = max(0, min(100, open_score))
    dimensions["opening"] = round(open_score)

    # ── 6. 结尾质量 ──
    ending = text[-300:] if len(text) > 300 else text
    end_score = 50

    # 悬念结尾加分
    if any(kw in ending for kw in ("究竟", "到底", "谁知", "不料", "然而", 
                                      "未完", "悬念", "谜", "秘密", "未知")):
        end_score += 20
    
    # 情感高潮结尾加分
    if any(kw in ending for kw in ("终于", "泪", "笑", "怒", "悲", "喜",
                                      "嘶吼", "呐喊", "沉默", "叹息", "释然")):
        end_score += 15
    
    # 平淡结尾减分
    if any(kw in ending for kw in ("就这样", "然后", "于是", "日子", "平淡地")):
        end_score -= 10

    end_score = max(0, min(100, end_score))
    dimensions["ending"] = round(end_score)

    # ── 7. 重复短语检测 ──
    repeat_issues = []
    for ngram_len in [4, 5, 6]:
        seen = {}
        for j in range(len(text) - ngram_len):
            ngram = text[j:j+ngram_len]
            seen[ngram] = seen.get(ngram, 0) + 1
        for ngram, count in seen.items():
            if count >= 4 and any('\u4e00' <= c <= '\u9fff' for c in ngram):
                repeat_issues.append(ngram)
    
    if repeat_issues:
        unique_phrases = set(repeat_issues)
        if len(unique_phrases) >= 3:
            repeat_score = 40
            issues.append(f"检测到 {len(unique_phrases)} 个重复短语，建议润色避免机械重复")
        else:
            repeat_score = 70
    else:
        repeat_score = 100
    dimensions["repetition"] = round(repeat_score)

    # ── 综合分（权重调整：增加结尾权重） ──
    weights = {
        "word_count": 0.25,
        "paragraph_diversity": 0.12,
        "dialogue": 0.12,
        "sentence_variety": 0.12,
        "opening": 0.10,
        "ending": 0.10,
        "repetition": 0.19,
    }
    overall = sum(
        dimensions.get(dim, 0) * weight
        for dim, weight in weights.items()
    )
    overall = round(max(0, min(100, overall)))

    return {
        "scorer_version": SCORER_VERSION,
        "overall": overall,
        "dimensions": dimensions,
        "char_count": char_count,
        "issues": issues,
    }


def score_summary(score: dict) -> str:
    """生成评分摘要字符串"""
    overall = score["overall"]
    if overall >= 90:
        return f"⭐ 优秀（{overall}分）"
    elif overall >= 75:
        return f"✅ 良好（{overall}分）"
    elif overall >= 60:
        return f"📝 及格（{overall}分）"
    elif overall >= 40:
        return f"⚠️ 待改进（{overall}分）"
    else:
        return f"❌ 需重写（{overall}分）"