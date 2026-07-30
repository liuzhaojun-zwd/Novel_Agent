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
2. 每章对象必须原样使用以下英文键，禁止翻译、改名或嵌套到其他对象中：chapter_number、title、summary、pov_character、location、chapter_goal、conflict、turning_point、ending_hook、characters、foreshadowing_add、foreshadowing_resolve、scenes
3. chapter_number 必须是整数；title 和 summary 必须是非空字符串
4. characters、foreshadowing_add、foreshadowing_resolve 必须是数组
5. scenes 必须是数组，每项只使用 goal、conflict、result 三个英文键
6. 严格遵守小说圣经，只输出一个 JSON 对象，不要 Markdown 代码块或解释：{{"chapters": [...]}}
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
    """生成单批大纲，并对结构化响应做严格校验和 JSON 兜底。"""
    expected = end - start + 1
    if total_batches == 1:
        prompt = build_outline_prompt(setup)
    else:
        prompt = build_batch_prompt(
            setup, start, end, batch_no, total_batches, previous_summary,
        )

    batch_cache_key = f"{prompt}::batch"
    cached = get_cached(
        batch_cache_key, cfg["quality_model"], category="outline", prompt_version="2.0.0",
    )
    if cached:
        try:
            cached_chapters = json.loads(cached)
            chapters = _normalize_batch_chapters(cached_chapters, start, end)
            if chapters:
                logger.info(f"第{batch_no}批缓存命中: {len(chapters)}章")
                return chapters
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("第%s批缓存无效，将重新生成 error=%s", batch_no, type(exc).__name__)

    accumulated = ""
    messages = [
        {"role": "system", "content": "你是一位创意写作助手，擅长为小说设计结构完整的大纲。请始终输出 JSON。"},
        {"role": "user", "content": prompt},
    ]

    try:
        async for chunk in llm_stream_with_fallback(messages, max_tokens=8192):
            accumulated += chunk
            await publish_func("outline_token", text=chunk, accumulated=accumulated)
    except Exception as exc:
        logger.warning("第%s批流式生成异常 error=%s accumulated_chars=%s", batch_no, type(exc).__name__, len(accumulated))
        if not accumulated:
            raise
        logger.warning("第%s批已有部分流式内容，将继续尝试 JSON mode 兜底", batch_no)

    chapters = _normalize_batch_chapters(
        _parse_outline_json(accumulated, expected), start, end,
    )
    if not chapters:
        logger.warning(
            "第%s批流式结果不可用，改用非流式 JSON mode 兜底 batch=%s-%s chars=%s expected=%s",
            batch_no, start, end, len(accumulated), expected,
        )
        try:
            fallback_llm = LLMAdapter(
                purpose="outline.generate", prompt_id="outline.generate", job_id=None,
            )
            fallback_result = await fallback_llm.chat_json(
                messages, max_tokens=8192,
                purpose="outline.generate", prompt_id="outline.generate",
            )
            fallback_raw = json.dumps(fallback_result, ensure_ascii=False)
            chapters = _normalize_batch_chapters(
                _parse_outline_json(fallback_raw, expected), start, end,
            )
        except Exception as exc:
            logger.error(
                "第%s批 JSON mode 兜底请求失败 error=%s", batch_no, type(exc).__name__,
            )
            raise RuntimeError(
                f"第 {batch_no}/{total_batches} 批大纲 JSON 兜底请求失败"
            ) from exc

    if not chapters:
        raise RuntimeError(
            f"第 {batch_no}/{total_batches} 批大纲响应无效：需要 {expected} 个连续章节"
        )

    set_cache(
        batch_cache_key, cfg["quality_model"], json.dumps(chapters, ensure_ascii=False),
        category="outline", prompt_version="2.0.0",
    )
    return chapters


def _normalize_batch_chapters(chapters: list[dict], start: int, end: int) -> list[dict]:
    """规范化并校验单批章节数量与连续编号，必要时修正从 1 开始的编号。"""
    expected = end - start + 1
    normalized = _normalize_outline_chapters(chapters, expected)
    if len(normalized) != expected:
        logger.warning(
            "大纲批次章节数量不匹配 start=%s end=%s raw=%s normalized=%s",
            start, end, len(chapters) if isinstance(chapters, list) else 0, len(normalized),
        )
        return []

    numbers = [chapter["chapter_number"] for chapter in normalized]
    if not all(isinstance(number, int) for number in numbers):
        return []
    if numbers != list(range(numbers[0], numbers[0] + expected)):
        logger.warning("大纲批次章节编号不连续 start=%s end=%s numbers=%s", start, end, numbers)
        return []

    offset = start - numbers[0]
    if offset:
        for chapter in normalized:
            chapter["chapter_number"] += offset
    return normalized if [c["chapter_number"] for c in normalized] == list(range(start, end + 1)) else []


async def llm_stream_with_fallback(messages, max_tokens=8192):
    """带降级的流式 LLM 调用。

    优先使用普通流式；只有完全没有流式内容时才降级到非流式 JSON mode。
    有部分内容但流中断时保留异常，由批次层执行结构化兜底，避免静默解析残文。
    """
    llm = LLMAdapter(purpose="outline.generate", prompt_id="outline.generate", job_id=None)
    chunks = []
    try:
        async for chunk in llm.chat_stream(messages, max_tokens=max_tokens):
            chunks.append(chunk)
            yield chunk
    except Exception as exc:
        logger.warning("普通流式失败 error=%s chunks=%s", type(exc).__name__, len(chunks))
        if chunks:
            raise

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


def _coerce_chapter_number(value) -> int | None:
    """兼容整数、数字字符串和“第 N 章”格式。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def _first_present(data: dict, aliases: tuple[str, ...], default=None):
    for key in aliases:
        if key in data and data[key] is not None:
            return data[key]
    return default


def _as_string(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def _normalize_outline_chapters(chapters: list, expected_count: int) -> list[dict]:
    """补齐章节卡字段，并兼容模型偶尔返回的中文或替代字段名。"""
    aliases = {
        "chapter_number": ("chapter_number", "chapter_no", "chapter", "number", "index", "章节编号", "章节序号", "章号"),
        "title": ("title", "chapter_title", "name", "标题", "章节标题"),
        "summary": ("summary", "chapter_summary", "plot_summary", "synopsis", "outline", "plot", "content", "description", "摘要", "章节摘要", "情节摘要", "内容概要"),
        "pov_character": ("pov_character", "pov", "viewpoint_character", "视角人物", "POV人物"),
        "location": ("location", "place", "地点", "主要地点"),
        "chapter_goal": ("chapter_goal", "goal", "objective", "章节目标", "本章目标"),
        "conflict": ("conflict", "core_conflict", "核心冲突", "冲突"),
        "turning_point": ("turning_point", "turn", "关键转折", "转折"),
        "ending_hook": ("ending_hook", "hook", "结尾钩子", "结尾悬念"),
        "characters": ("characters", "cast", "人物", "出场人物"),
        "foreshadowing_add": ("foreshadowing_add", "foreshadowing", "伏笔", "新增伏笔", "埋下伏笔"),
        "foreshadowing_resolve": ("foreshadowing_resolve", "resolved_foreshadowing", "回收伏笔", "伏笔回收"),
        "scenes": ("scenes", "scene_list", "场景", "场景列表"),
    }
    scene_aliases = {
        "goal": ("goal", "objective", "目标", "场景目标"),
        "conflict": ("conflict", "obstacle", "阻碍", "冲突", "场景阻碍"),
        "result": ("result", "outcome", "结果", "场景结果"),
    }
    normalized = []
    rejected = 0
    first_rejected_keys: list[str] = []
    first_missing: list[str] = []

    if not isinstance(chapters, list):
        logger.warning("大纲 chapters 不是数组 type=%s", type(chapters).__name__)
        return []

    for chapter in chapters[:expected_count]:
        if not isinstance(chapter, dict):
            rejected += 1
            if not first_missing:
                first_missing = ["chapter_object"]
            continue

        source = chapter
        for wrapper in ("chapter_card", "card", "章节卡"):
            nested = chapter.get(wrapper)
            if isinstance(nested, dict):
                source = nested
                break
        if isinstance(chapter.get("chapter"), dict):
            source = chapter["chapter"]

        number = _coerce_chapter_number(_first_present(source, aliases["chapter_number"]))
        title = _as_string(_first_present(source, aliases["title"]))
        summary = _as_string(_first_present(source, aliases["summary"]))
        missing = [
            field for field, value in (
                ("chapter_number", number), ("title", title), ("summary", summary),
            ) if value is None or value == ""
        ]
        if missing:
            rejected += 1
            if not first_rejected_keys:
                first_rejected_keys = sorted(str(key) for key in source.keys())[:30]
                first_missing = missing
            continue

        item = dict(source)
        item.update({"chapter_number": number, "title": title, "summary": summary})
        for field in ("pov_character", "location", "chapter_goal", "conflict", "turning_point", "ending_hook"):
            item[field] = _as_string(_first_present(source, aliases[field]))
        for field in ("characters", "foreshadowing_add", "foreshadowing_resolve"):
            item[field] = _as_list(_first_present(source, aliases[field], []))

        scenes = _as_list(_first_present(source, aliases["scenes"], []))
        item["scenes"] = [
            {
                field: _as_string(_first_present(scene, scene_aliases[field]))
                for field in ("goal", "conflict", "result")
            }
            for scene in scenes if isinstance(scene, dict)
        ]
        normalized.append(item)

    if rejected:
        logger.warning(
            "大纲章节字段校验过滤 rejected=%s accepted=%s first_missing=%s first_keys=%s",
            rejected, len(normalized), first_missing, first_rejected_keys,
        )
    return normalized


def _chapters_from_data(data) -> list:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("chapters", "outline", "章节", "大纲"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


def _parsed_chapters(data, expected_count: int, source: str) -> list[dict]:
    chapters = _chapters_from_data(data)
    if not chapters:
        return []
    normalized = _normalize_outline_chapters(chapters, expected_count)
    logger.info("%s: raw=%s normalized=%s", source, len(chapters), len(normalized))
    return normalized


def _parse_outline_json(raw: str, expected_count: int) -> list[dict]:
    """从原始 JSON 文本中解析并标准化大纲章节列表。"""
    if not raw or not raw.strip():
        logger.warning("大纲内容为空")
        return []

    try:
        chapters = _parsed_chapters(json.loads(raw), expected_count, "直接解析")
        if chapters:
            return chapters
    except json.JSONDecodeError as exc:
        logger.info("直接解析失败 position=%s chars=%s", exc.pos, len(raw))

    patterns = [
        r'```json\s*([\s\S]*?)```',
        r'```\s*([\s\S]*?)```',
        r'\{[\s\S]*?"chapters"[\s\S]*?\}',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        candidate = match.group(1) if match.lastindex else match.group(0)
        try:
            chapters = _parsed_chapters(json.loads(candidate), expected_count, "提取解析")
            if chapters:
                return chapters
        except json.JSONDecodeError:
            continue

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        try:
            chapters = _parsed_chapters(
                json.loads(raw[start:end + 1]), expected_count, "边界解析",
            )
            if chapters:
                return chapters
        except json.JSONDecodeError:
            pass

    chapters = _extract_chapters_from_truncated(raw)
    if chapters:
        normalized = _normalize_outline_chapters(chapters, expected_count)
        logger.info("截断恢复: raw=%s normalized=%s", len(chapters), len(normalized))
        return normalized
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