"""Novel_Agent — 大纲生成器（支持流式输出 + 缓存）"""
import json
import logging
from app.services.llm_adapter import LLMAdapter
from app.services.llm_cache import get_cached, set_cache
from app.config import get_llm_config
from app.models import SetupCreate

logger = logging.getLogger("novel_agent.outline")


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


async def generate_outline_stream(
    setup: SetupCreate,
    job_id: str,
    publish_func,
) -> list[dict]:
    """流式生成大纲，边生成边推 SSE 事件。
    
    Args:
        setup: 创作设定
        job_id: 任务 ID
        publish_func: SSE 推送函数，签名 publish(event_type, **data)
    
    Returns:
        章节列表
    """
    llm = LLMAdapter()
    prompt = build_outline_prompt(setup)
    full_prompt = prompt
    logger.info(f"流式生成大纲: theme={setup.theme} chapters={setup.chapter_count}")

    cfg = get_llm_config()

    # 尝试缓存
    cached = get_cached(full_prompt, cfg["model"])
    if cached:
        chapters = json.loads(cached)
        logger.info(f"大纲缓存命中: {len(chapters)} 章")
        if len(chapters) == setup.chapter_count:
            # 缓存命中，立即推送
            await publish_func("outline_token", text=json.dumps({"chapters": chapters}, ensure_ascii=False))
            await publish_func("outline_done", outline=chapters, message="大纲生成成功（缓存）")
            return chapters

    # 流式生成
    await publish_func("outline_progress", message="正在调用 AI 生成大纲...")
    accumulated = ""

    messages = [
        {"role": "system", "content": "你是一位创意写作助手，擅长为小说设计结构完整的大纲。"},
        {"role": "user", "content": prompt},
    ]

    try:
        async for chunk in llm.chat_stream(messages):
            accumulated += chunk
            # 每收到一段就推送到前端
            await publish_func("outline_token", text=chunk, accumulated=accumulated)
            await publish_func("outline_progress", message=f"已接收 {len(accumulated)} 字符...")
    except Exception as e:
        logger.error(f"大纲流式生成失败: {e}")
        # 尝试用非流式兜底
        try:
            logger.info("流式失败，切换到非流式模式重试")
            await publish_func("outline_progress", message="流式生成异常，正在重试...")
            result = await llm.chat_json(messages)
            accumulated = json.dumps(result, ensure_ascii=False)
        except Exception as e2:
            raise RuntimeError(f"大纲生成失败（流式+非流式均异常）: {e2}")

    # 解析 JSON
    chapters = _parse_outline_json(accumulated, setup.chapter_count)

    # 缓存
    if len(chapters) == setup.chapter_count:
        set_cache(full_prompt, cfg["model"], json.dumps(chapters, ensure_ascii=False))

    # 推送完成事件
    await publish_func("outline_done", outline=chapters, message="大纲生成成功")

    return chapters


async def generate_outline(setup: SetupCreate) -> list[dict]:
    """生成大纲，返回章节列表（非流式）"""
    llm = LLMAdapter()
    prompt = build_outline_prompt(setup)
    full_prompt = prompt
    logger.info(f"生成大纲: theme={setup.theme} chapters={setup.chapter_count}")

    cfg = get_llm_config()
    cached = get_cached(full_prompt, cfg["model"])
    if cached:
        chapters = json.loads(cached)
        logger.info(f"大纲缓存命中: {len(chapters)} 章")
        if len(chapters) == setup.chapter_count:
            return chapters

    messages = [
        {"role": "system", "content": "你是一位创意写作助手，擅长为小说设计结构完整的大纲。"},
        {"role": "user", "content": prompt},
    ]
    result = await llm.chat_json(messages)
    return _parse_outline_json(json.dumps(result, ensure_ascii=False), setup.chapter_count)


def _parse_outline_json(raw: str, expected_count: int) -> list[dict]:
    """从原始 JSON 文本中解析大纲章节列表"""
    # 尝试直接解析
    try:
        data = json.loads(raw)
        chapters = data.get("chapters", [])
    except json.JSONDecodeError:
        # 尝试从流式片段中提取 JSON（可能包含 markdown 包裹）
        import re
        m = re.search(r'\{[\s\S]*"chapters"[\s\S]*\}', raw)
        if m:
            try:
                data = json.loads(m.group(0))
                chapters = data.get("chapters", [])
            except json.JSONDecodeError:
                chapters = []
        else:
            chapters = []

    # 确保数量
    if len(chapters) != expected_count:
        logger.warning(f"大纲章节数不匹配: 期望 {expected_count}，实际 {len(chapters)}")
        chapters = chapters[:expected_count]

    logger.info(f"大纲解析完成: {len(chapters)} 章")
    return chapters