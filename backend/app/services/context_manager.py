"""Novel_Agent — 上下文窗口管理器

负责：
1. Token 估算（中英文差异计数）
2. 动态选择前文摘要（基于 token budget）
3. 摘要压缩（超出窗口时自动截断）
"""

import re
from typing import Optional

# 中文 ≈ 每字 1.5 token，英文 ≈ 每词 1.3 token
_CHINESE_CHAR_WEIGHT = 1.5
_ENGLISH_WORD_WEIGHT = 1.3

# 系统提示词和用户消息的固定开销（token 数）
_SYSTEM_PROMPT_TOKENS = 200
_USER_PROMPT_OVERHEAD = 100
_RESPONSE_BUDGET = 4096  # 留给生成内容的 token

# 默认上下文预算（总上下文窗口 - 响应预算 - 固定开销）
_DEFAULT_TOTAL_WINDOW = 32000
_DEFAULT_CONTEXT_BUDGET = _DEFAULT_TOTAL_WINDOW - _SYSTEM_PROMPT_TOKENS - _USER_PROMPT_OVERHEAD - _RESPONSE_BUDGET


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数。
    
    中文按每个字 ~1.5 token，英文按每个单词 ~1.3 token。
    这是一个保守估算，不同的 LLM 可能有不同的精确 tokenizer。
    """
    if not text:
        return 0

    # 提取中文字符
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    
    # 提取英文单词和其他非中文字符
    non_chinese = re.sub(r'[\u4e00-\u9fff]', ' ', text)
    english_words = len(non_chinese.split())
    
    # 标点和数字按每个 0.5 token 估算
    punctuation = len(re.findall(r'[，。！？、；：""''（）【】《》\.,!?;:\'"\[\]\(\)\{\}]', text))
    
    tokens = (
        chinese_chars * _CHINESE_CHAR_WEIGHT
        + english_words * _ENGLISH_WORD_WEIGHT
        + punctuation * 0.5
    )
    
    return max(1, int(tokens))


def select_context_summaries(
    summaries: list[str],
    budget: Optional[int] = None,
) -> list[str]:
    """从前文摘要列表中选择合适的数量，确保总 token 不超过预算。
    
    Args:
        summaries: 已完成的章节摘要列表，每项格式如 "第N章（标题）：摘要"
        budget: token 预算，默认使用 _DEFAULT_CONTEXT_BUDGET
    
    Returns:
        选中的摘要列表（按时间顺序，最新的优先）
    """
    if budget is None:
        budget = _DEFAULT_CONTEXT_BUDGET
    
    if not summaries:
        return []
    
    # 从最新的开始往前选，优先保留最近的内容
    selected: list[str] = []
    total_tokens = 0
    
    for s in reversed(summaries):
        tokens = estimate_tokens(s)
        if total_tokens + tokens > budget:
            # 超出预算：尝试压缩这条摘要再判断
            compressed = _compress_summary(s)
            compressed_tokens = estimate_tokens(compressed)
            if total_tokens + compressed_tokens <= budget:
                selected.insert(0, compressed)
                total_tokens += compressed_tokens
            break  # 就算压缩了也放不下，后面的更早，直接停
        selected.insert(0, s)
        total_tokens += tokens
    
    return selected


def _compress_summary(summary: str, max_chars: int = 100) -> str:
    """压缩一条摘要到指定长度。
    
    策略：保留章节号、标题，缩减摘要本体。
    """
    # 尝试提取章节号和标题
    m = re.match(r'^(第\d+章（[^）]+）[：:])', summary)
    if m:
        prefix = m.group(1)
        body = summary[len(prefix):]
        # 如果正文太长，截取开头并加省略号
        remaining = max_chars - len(prefix) - 3  # -3 for "..."
        if len(body) > remaining:
            body = body[:remaining] + "..."
        return prefix + body
    else:
        # 没有清晰的章节标记，直接截断
        if len(summary) > max_chars:
            return summary[:max_chars] + "..."
        return summary


def get_context_budget(total_window: Optional[int] = None) -> int:
    """获取当前可用的上下文预算（token）"""
    if total_window is None:
        total_window = _DEFAULT_TOTAL_WINDOW
    return total_window - _SYSTEM_PROMPT_TOKENS - _USER_PROMPT_OVERHEAD - _RESPONSE_BUDGET