"""Novel_Agent — 大纲生成器（支持 LLM 缓存）"""
from app.services.llm_adapter import LLMAdapter
from app.services.llm_cache import get_cached, set_cache
from app.config import get_llm_config
from app.models import SetupCreate


OUTLINE_PROMPT_TEMPLATE = """你是一位专业小说大纲策划师。请根据以下创作设定，为小说生成一份完整的大纲。

## 创作设定
- 题材：{theme}
- 主题/故事核心：{topic}
- 目标章节数：{chapter_count}
{optional_fields}

## 要求
1. 生成共 {chapter_count} 个章节的大纲
2. 每个章节包含：章节序号 (1-based)、标题、情节摘要（50-150字）
3. 大纲应有起承转合的结构，情节有推进感
4. 标题要有吸引力

## 输出格式
请以 JSON 格式输出，格式如下：
{{
  "chapters": [
    {{"chapter_number": 1, "title": "第一章标题", "summary": "本章情节摘要"}},
    ...
  ]
}}
"""


def build_outline_prompt(setup: SetupCreate) -> str:
    optional_lines = []
    if setup.writing_style:
        optional_lines.append(f"- 写作风格：{setup.writing_style}")
    if setup.characters:
        optional_lines.append(f"- 主要人物：{', '.join(setup.characters)}")
    if setup.world_setting:
        optional_lines.append(f"- 世界观设定：{setup.world_setting}")
    if setup.narrative_perspective:
        optional_lines.append(f"- 叙事视角：{setup.narrative_perspective}")
    optional_str = "\n".join(optional_lines)
    if optional_str:
        optional_str = "\n" + optional_str

    return OUTLINE_PROMPT_TEMPLATE.format(
        theme=setup.theme,
        topic=setup.topic,
        chapter_count=setup.chapter_count,
        optional_fields=optional_str,
    )


async def generate_outline(setup: SetupCreate) -> list[dict]:
    """生成大纲，返回章节列表（使用 LLM 缓存）"""
    llm = LLMAdapter()
    prompt = build_outline_prompt(setup)
    full_prompt = prompt  # 系统+用户消息合并用于缓存key

    # Issue 10: 尝试从缓存读取
    cfg = get_llm_config()
    cached = get_cached(full_prompt, cfg["model"])
    if cached:
        import json
        chapters = json.loads(cached)
        if len(chapters) == setup.chapter_count:
            return chapters

    messages = [
        {"role": "system", "content": "你是一位创意写作助手，擅长为小说设计结构完整的大纲。"},
        {"role": "user", "content": prompt},
    ]
    result = await llm.chat_json(messages)
    chapters = result.get("chapters", [])
    # 确保数量正确
    if len(chapters) != setup.chapter_count:
        chapters = chapters[:setup.chapter_count]
    else:
        # 缓存完整结果
        import json
        set_cache(full_prompt, cfg["model"], json.dumps(chapters, ensure_ascii=False))
    return chapters