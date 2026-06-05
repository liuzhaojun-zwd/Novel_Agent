"""Novel_Agent — 大纲生成器（分批生成 + 流式输出 + 缓存 + JSON mode）"""
import json
import logging
import re
from app.services.llm_adapter import LLMAdapter
from app.services.llm_cache import get_cached, set_cache
from app.config import get_llm_config
from app.models import SetupCreate

logger = logging.getLogger("novel_agent.outline")

# 每批最多生成多少章（避免单次输出被截断）
_BATCH_SIZE = 50


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
5. 输出必须是 JSON 格式

## 输出格式
{{
  "chapters": [
    {{"chapter_number": 1, "title": "第一章标题", "summary": "本章情节摘要"}},
    ...
  ]
}}
"""

BATCH_PROMPT_TEMPLATE = """你是一位专业小说大纲策划师。请为小说的第 {start}-{end} 章生成大纲。

## 创作设定
- 题材：{theme}
- 主题/故事核心：{topic}
{optional_fields}

## 前文大纲概要
{previous_batch_summary}

## 本章节范围
- 章节序号：第 {start} 章 到 第 {end} 章
- 这是整个大系列中的第 {batch_index}/{total_batches} 批

## 要求
1. 生成从第 {start} 章到第 {end} 章的大纲，共 {count} 章
2. 每个章节包含：章节序号 (1-based)、标题、情节摘要（50-150字）
3. 情节要有推进感，与前文连贯
4. 标题要有吸引力
5. 输出必须是 JSON 格式

## 输出格式
{{
  "chapters": [
    {{"chapter_number": {start}, "title": "第{start}章标题", "summary": "本章情节摘要"}},
    ...
  ]
}}
"""


def build_outline_prompt(setup: SetupCreate) -> str:
    optional_lines = _build_optional_lines(setup)
    return OUTLINE_PROMPT_TEMPLATE.format(
        theme=setup.theme,
        topic=setup.topic,
        chapter_count=setup.chapter_count,
        optional_fields=optional_lines,
    )


def build_batch_prompt(
    setup: SetupCreate,
    start: int,
    end: int,
    batch_index: int,
    total_batches: int,
    previous_batch_summary: str = "",
) -> str:
    """构建分批生成的大纲 prompt"""
    optional_lines = _build_optional_lines(setup)
    return BATCH_PROMPT_TEMPLATE.format(
        theme=setup.theme,
        topic=setup.topic,
        optional_fields=optional_lines,
        start=start,
        end=end,
        count=end - start + 1,
        batch_index=batch_index,
        total_batches=total_batches,
        previous_batch_summary=previous_batch_summary or "（这是第一批，无前文）",
    )


def _build_optional_lines(setup: SetupCreate) -> str:
    lines = []
    if setup.writing_style:
        lines.append(f"- 写作风格：{setup.writing_style}")
    if setup.characters:
        lines.append(f"- 主要人物：{', '.join(setup.characters)}")
    if setup.world_setting:
        lines.append(f"- 世界观设定：{setup.world_setting}")
    if setup.narrative_perspective:
        lines.append(f"- 叙事视角：{setup.narrative_perspective}")
    return "\n".join(lines) if lines else ""


async def generate_outline_stream(
    setup: SetupCreate,
    job_id: str,
    publish_func,
) -> list[dict]:
    """分批流式生成大纲。

    对于大量章节（> _BATCH_SIZE），自动拆成多批生成，
    每批完成后保存并继续下一批，最后合并。

    Args:
        setup: 创作设定
        job_id: 任务 ID
        publish_func: SSE 推送函数

    Returns:
        完整章节列表
    """
    cfg = get_llm_config()
    all_chapters = []
    total = setup.chapter_count
    batch_size = _BATCH_SIZE
    total_batches = (total + batch_size - 1) // batch_size

    logger.info(f"分批生成大纲: theme={setup.theme} total={total} batches={total_batches} batch_size={batch_size}")

    # 尝试全量缓存
    full_prompt = build_outline_prompt(setup)
    cached = get_cached(full_prompt, cfg["model"])
    if cached:
        chapters = json.loads(cached)
        if len(chapters) == total:
            logger.info(f"全量缓存命中: {len(chapters)} 章")
            await publish_func("outline_done", outline=chapters, message="大纲生成成功（缓存）")
            return chapters

    previous_batch_summary = ""

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size + 1
        end = min(start + batch_size - 1, total)
        batch_no = batch_idx + 1

        await publish_func("outline_progress",
                           message=f"正在生成第 {batch_no}/{total_batches} 批（{start}-{end}章）...",
                           batch=batch_no,
                           total_batches=total_batches,
                           batch_start=start,
                           batch_end=end)

        chapters = await _generate_single_batch(
            setup, start, end, batch_no, total_batches,
            previous_batch_summary, cfg, publish_func,
        )

        if not chapters:
            logger.error(f"第{batch_no}批大纲生成失败，终止")
            raise RuntimeError(f"第 {batch_no}/{total_batches} 批大纲生成失败")

        all_chapters.extend(chapters)

        # 为下一批生成前文概要（从刚生成的这批取每章摘要）
        summaries = [f"第{c['chapter_number']}章（{c['title']}）：{c['summary'][:60]}"
                     for c in chapters[:5]]  # 只取前5章摘要就够了
        previous_batch_summary = "\n".join(summaries)

        logger.info(f"第{batch_no}批完成: {len(chapters)}章，累计{len(all_chapters)}章")

    # 全部完成，缓存全量
    if len(all_chapters) == total:
        set_cache(full_prompt, cfg["model"], json.dumps(all_chapters, ensure_ascii=False))

    await publish_func("outline_done", outline=all_chapters,
                       message=f"大纲生成成功（共{batch_no}批，{len(all_chapters)}章）")
    return all_chapters


async def _generate_single_batch(
    setup: SetupCreate,
    start: int,
    end: int,
    batch_no: int,
    total_batches: int,
    previous_summary: str,
    cfg: dict,
    publish_func,
) -> list[dict]:
    """生成单批大纲"""
    # 尝试该批的缓存
    if total_batches == 1:
        prompt = build_outline_prompt(setup)
    else:
        prompt = build_batch_prompt(
            setup, start, end, batch_no, total_batches, previous_summary,
        )

    # 尝试批缓存
    batch_cache_key = f"{prompt}::batch"
    cached = get_cached(batch_cache_key, cfg["model"])
    if cached:
        chapters = json.loads(cached)
        expected = end - start + 1
        if len(chapters) == expected and chapters[0]["chapter_number"] == start:
            logger.info(f"第{batch_no}批缓存命中: {len(chapters)}章")
            return chapters

    # 流式生成
    accumulated = ""
    messages = [
        {"role": "system", "content": "你是一位创意写作助手，擅长为小说设计结构完整的大纲。请始终输出 JSON。"},
        {"role": "user", "content": prompt},
    ]

    try:
        async for chunk in llm_stream_with_fallback(messages, max_tokens=8192):
            accumulated += chunk
            await publish_func("outline_token", text=chunk, accumulated=accumulated)
    except Exception as e:
        logger.error(f"第{batch_no}批流式生成失败: {e}")
        raise

    # 解析
    chapters = _parse_outline_json(accumulated, end - start + 1)

    if chapters:
        # 修正章节号偏移（如果是分批，LLM 可能从 1 开始计数而非 start）
        offset = start - chapters[0]["chapter_number"]
        if offset != 0:
            for ch in chapters:
                ch["chapter_number"] += offset

        # 缓存该批
        expected = end - start + 1
        if len(chapters) == expected:
            set_cache(batch_cache_key, cfg["model"], json.dumps(chapters, ensure_ascii=False))

    return chapters


async def llm_stream_with_fallback(messages, max_tokens=8192):
    """带降级的流式 LLM 调用
    
    优先级：
    1. 普通流式（某些 API 不支持 JSON mode 流式转空）
    2. 非流式 JSON mode
    """
    llm = LLMAdapter()
    chunks = []
    # 先试普通流式
    try:
        async for chunk in llm.chat_stream(messages, max_tokens=max_tokens):
            chunks.append(chunk)
            yield chunk
    except Exception as e:
        logger.warning(f"普通流式失败: {e}")

    # 普通流式空内容 → JSON mode 非流式
    if not chunks:
        logger.warning("流式为空，降级到非流式 JSON mode")
        result = await LLMAdapter().chat_json(messages, max_tokens=max_tokens)
        yield json.dumps(result, ensure_ascii=False)


async def generate_outline(setup: SetupCreate) -> list[dict]:
    """非流式生成大纲（兜底用）"""
    cfg = get_llm_config()
    full_prompt = build_outline_prompt(setup)
    cached = get_cached(full_prompt, cfg["model"])
    if cached:
        chapters = json.loads(cached)
        if len(chapters) == setup.chapter_count:
            return chapters

    logger.info(f"非流式生成大纲: theme={setup.theme} chapters={setup.chapter_count}")
    messages = [
        {"role": "system", "content": "你是一位创意写作助手，擅长为小说设计结构完整的大纲。请始终输出 JSON。"},
        {"role": "user", "content": full_prompt},
    ]
    result = await LLMAdapter().chat_json(messages, max_tokens=8192)
    chapters = _parse_outline_json(json.dumps(result, ensure_ascii=False), setup.chapter_count)
    return chapters


def _parse_outline_json(raw: str, expected_count: int) -> list[dict]:
    """从原始 JSON 文本中解析大纲章节列表"""
    if not raw or not raw.strip():
        logger.warning("大纲内容为空")
        return []

    # 尝试直接解析
    try:
        data = json.loads(raw)
        chapters = data.get("chapters", [])
        if chapters:
            logger.info(f"直接解析成功: {len(chapters)} 章")
            return chapters[:expected_count]
    except json.JSONDecodeError:
        pass

    # 尝试从流式片段中提取 JSON
    patterns = [
        r'\{[\s\S]*?"chapters"[\s\S]*?\}',
        r'```json\s*([\s\S]*?)```',
        r'```\s*([\s\S]*?)```',
    ]
    for pattern in patterns:
        m = re.search(pattern, raw)
        if m:
            candidate = m.group(1) if m.lastindex else m.group(0)
            try:
                data = json.loads(candidate)
                chapters = data.get("chapters", [])
                if chapters:
                    logger.info(f"正则提取解析成功: {len(chapters)} 章")
                    return chapters[:expected_count]
            except json.JSONDecodeError:
                continue

    # Fallback: 截取最外层 {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = raw[start:end + 1]
        try:
            data = json.loads(candidate)
            chapters = data.get("chapters", [])
            if chapters:
                return chapters[:expected_count]
        except json.JSONDecodeError:
            pass

    # Fallback: 逐条提取完整的 chapter 对象（截断恢复）
    chapters = _extract_chapters_from_truncated(raw)
    if chapters:
        logger.info(f"截断恢复成功: 提取到 {len(chapters)} 章")
        return chapters[:expected_count]

    return []


def _extract_chapters_from_truncated(text: str) -> list[dict]:
    """从截断的 JSON 中逐个提取完整的 chapter 对象"""
    pattern = (
        r'\{\s*"chapter_number"\s*:\s*\d+\s*,'
        r'\s*"title"\s*:\s*"[^"]*"\s*,'
        r'\s*"summary"\s*:\s*"[^"]*"\s*\}'
    )
    matches = re.findall(pattern, text)
    chapters = []
    for m in matches:
        try:
            ch = json.loads(m)
            if all(k in ch for k in ("chapter_number", "title", "summary")):
                chapters.append(ch)
        except json.JSONDecodeError:
            continue
    return chapters