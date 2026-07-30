"""Novel_Agent — 大纲生成器（分批生成 + 流式输出 + 缓存 + JSON mode）"""
import json
import logging
import re
from app.services.llm_adapter import LLMAdapter
from app.services.llm_cache import get_cached, set_cache
from app.config import get_llm_config
from app.models import SetupCreate
from app.services.story_bible import format_setup_context

logger = logging.getLogger("novel_agent.outline")

# 结构化章节卡字段较多，缩小批次避免长大纲输出被截断。
_BATCH_SIZE = 10


OUTLINE_PROMPT_TEMPLATE = """你是一位专业小说大纲策划师。请根据以下创作设定，为小说生成一份可直接指导正文写作的结构化大纲。

## 创作设定
- 题材：{theme}
- 主题/故事核心：{topic}
- 目标章节数：{chapter_count}
{optional_fields}

## 要求
1. 生成共 {chapter_count} 个章节，形成清晰的起承转合和人物成长弧
2. 每章必须给出标题、摘要、POV人物、地点、章节目标、核心冲突、转折和结尾钩子
3. 标明出场人物、本章埋下/回收的伏笔，并拆成 1-4 个场景
4. 所有内容严格遵守小说圣经，情节必须推进，避免重复事件
5. 只输出 JSON

## 输出格式
{{
  "chapters": [
    {{
      "chapter_number": 1,
      "title": "章节标题",
      "summary": "50-150字情节摘要",
      "pov_character": "视角人物",
      "location": "主要地点",
      "chapter_goal": "本章叙事目标",
      "conflict": "核心冲突",
      "turning_point": "关键转折",
      "ending_hook": "结尾悬念或情绪落点",
      "characters": ["人物名"],
      "foreshadowing_add": ["本章新伏笔"],
      "foreshadowing_resolve": ["本章回收伏笔"],
      "scenes": [{{"goal": "场景目标", "conflict": "场景阻碍", "result": "场景结果"}}]
    }}
  ]
}}
"""

BATCH_PROMPT_TEMPLATE = """你是一位专业小说大纲策划师。请生成小说第 {start}-{end} 章的结构化章节卡。

## 创作设定
- 题材：{theme}
- 主题/故事核心：{topic}
{optional_fields}

## 前文大纲概要
{previous_batch_summary}

## 范围
- 第 {start} 章到第 {end} 章，共 {count} 章
- 当前为第 {batch_index}/{total_batches} 批

## 要求
1. 章节编号必须从 {start} 连续到 {end}
2. 每章必须包含 title、summary、pov_character、location、chapter_goal、conflict、turning_point、ending_hook
3. 每章必须包含 characters、foreshadowing_add、foreshadowing_resolve 数组和 scenes 场景数组
4. scenes 每项包含 goal、conflict、result；保持与前文连贯并推进长期主线
5. 严格遵守小说圣经，只输出 JSON 对象：{{"chapters": [...]}}
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
    return format_setup_context(setup)


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
    cached = get_cached(
        full_prompt, cfg["quality_model"], category="outline", prompt_version="2.0.0",
    )
    if cached:
        chapters = json.loads(cached)
        if len(chapters) == total:
            chapters = _normalize_outline_chapters(chapters, total)
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
        set_cache(
            full_prompt, cfg["quality_model"], json.dumps(all_chapters, ensure_ascii=False),
            category="outline", prompt_version="2.0.0",
        )

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
    cached = get_cached(
        batch_cache_key, cfg["quality_model"], category="outline", prompt_version="2.0.0",
    )
    if cached:
        chapters = json.loads(cached)
        expected = end - start + 1
        if len(chapters) == expected and chapters[0]["chapter_number"] == start:
            chapters = _normalize_outline_chapters(chapters, expected)
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
            set_cache(
                batch_cache_key, cfg["quality_model"], json.dumps(chapters, ensure_ascii=False),
                category="outline", prompt_version="2.0.0",
            )

    return chapters


async def llm_stream_with_fallback(messages, max_tokens=8192):
    """带降级的流式 LLM 调用
    
    优先级：
    1. 普通流式（某些 API 不支持 JSON mode 流式转空）
    2. 非流式 JSON mode
    """
    llm = LLMAdapter(purpose="outline.generate", prompt_id="outline.generate", job_id=None)
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
        result = await llm.chat_json(
            messages, max_tokens=max_tokens,
            purpose="outline.generate", prompt_id="outline.generate",
        )
        yield json.dumps(result, ensure_ascii=False)


async def generate_outline(setup: SetupCreate) -> list[dict]:
    """非流式生成大纲（兜底用）"""
    cfg = get_llm_config()
    full_prompt = build_outline_prompt(setup)
    cached = get_cached(
        full_prompt, cfg["quality_model"], category="outline", prompt_version="2.0.0",
    )
    if cached:
        chapters = json.loads(cached)
        if len(chapters) == setup.chapter_count:
            return _normalize_outline_chapters(chapters, setup.chapter_count)

    logger.info(f"非流式生成大纲: theme={setup.theme} chapters={setup.chapter_count}")
    messages = [
        {"role": "system", "content": "你是一位创意写作助手，擅长为小说设计结构完整的大纲。请始终输出 JSON。"},
        {"role": "user", "content": full_prompt},
    ]
    result = await LLMAdapter(
        purpose="outline.generate", prompt_id="outline.generate",
    ).chat_json(messages, max_tokens=8192)
    chapters = _parse_outline_json(json.dumps(result, ensure_ascii=False), setup.chapter_count)
    return chapters


def _normalize_outline_chapters(chapters: list, expected_count: int) -> list[dict]:
    """补齐结构化章节卡字段，使旧缓存和旧模型输出继续可用。"""
    string_fields = (
        "pov_character", "location", "chapter_goal", "conflict",
        "turning_point", "ending_hook",
    )
    list_fields = ("characters", "foreshadowing_add", "foreshadowing_resolve")
    normalized = []
    for chapter in chapters[:expected_count]:
        if not isinstance(chapter, dict) or not all(
            key in chapter for key in ("chapter_number", "title", "summary")
        ):
            continue
        item = dict(chapter)
        for field in string_fields:
            item[field] = item.get(field) or ""
        for field in list_fields:
            value = item.get(field, [])
            item[field] = value if isinstance(value, list) else [str(value)]
        scenes = item.get("scenes", [])
        item["scenes"] = [
            {
                "goal": scene.get("goal", ""),
                "conflict": scene.get("conflict", ""),
                "result": scene.get("result", ""),
            }
            for scene in scenes if isinstance(scene, dict)
        ] if isinstance(scenes, list) else []
        normalized.append(item)
    return normalized


def _parse_outline_json(raw: str, expected_count: int) -> list[dict]:
    """从原始 JSON 文本中解析并标准化大纲章节列表。"""
    if not raw or not raw.strip():
        logger.warning("大纲内容为空")
        return []

    try:
        data = json.loads(raw)
        chapters = data.get("chapters", [])
        if chapters:
            logger.info(f"直接解析成功: {len(chapters)} 章")
            return _normalize_outline_chapters(chapters, expected_count)
    except json.JSONDecodeError:
        pass

    patterns = [
        r'\{[\s\S]*?"chapters"[\s\S]*?\}',
        r'```json\s*([\s\S]*?)```',
        r'```\s*([\s\S]*?)```',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        candidate = match.group(1) if match.lastindex else match.group(0)
        try:
            chapters = json.loads(candidate).get("chapters", [])
            if chapters:
                logger.info(f"正则提取解析成功: {len(chapters)} 章")
                return _normalize_outline_chapters(chapters, expected_count)
        except json.JSONDecodeError:
            continue

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            chapters = json.loads(raw[start:end + 1]).get("chapters", [])
            if chapters:
                return _normalize_outline_chapters(chapters, expected_count)
        except json.JSONDecodeError:
            pass

    chapters = _extract_chapters_from_truncated(raw)
    if chapters:
        logger.info(f"截断恢复成功: 提取到 {len(chapters)} 章")
        return _normalize_outline_chapters(chapters, expected_count)
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