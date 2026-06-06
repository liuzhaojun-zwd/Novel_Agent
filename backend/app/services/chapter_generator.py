"""Novel_Agent — 章节生成器

增强版：
- Issue 6: 分段生成 + 章节内 checkpoint（每段立即持久化）
- Issue 5: 增强版一致性检查器（跨章节追踪）
- Issue 7: 支持指定章节重新生成
- Issue 8: 写作质量评估
"""
from typing import Optional
import logging
import time

from app.services.llm_adapter import LLMAdapter
from app.services import job_service as svc
from app.services.progress_tracker import publish
from app.services.consistency_checker import check_consistency
from app.services.quality_scorer import score_chapter, score_summary
from app.services.context_manager import select_context_summaries
from app.services.llm_cache import get_cached, set_cache, clear_cache
from app.models import SetupCreate

logger = logging.getLogger("novel_agent.chapter")

# 分段生成：每段目标字数动态计算，最小800最大2000
def _get_segment_target(target_words: int) -> int:
    return max(800, min(2000, target_words // 4))

# 最大分段数动态计算，确保有足够分段空间
def _get_max_segments(target_words: int) -> int:
    seg_target = _get_segment_target(target_words)
    return max(8, target_words // seg_target + 2)

# 字数达标阈值（80%视为达标）
_WORD_THRESHOLD = 0.8

CHAPTER_PROMPT_TEMPLATE = """你是一位专业小说作家，请根据以下设定和章节大纲，创作一篇小说的章节正文。

## 作品设定
- 题材：{theme}
- 故事核心：{topic}
{optional_fields}

## 章节信息
- 章节序号：第 {chapter_number} 章
- 章节标题：{title}
- 本章情节摘要：{summary}
- 目标字数：约 {target_words} 字

## 前文回顾
{previous_summary}
{user_feedback}

## 要求
1. 创作正文内容，达到目标字数
2. 保持与人物设定一致
3. 情节扣题，细节丰富
4. 语言风格保持一致
5. 按照自然段落换行，段落之间用空行分隔
6. 直接输出正文内容，不要输出章节标题
"""

SEGMENT_PROMPT_SUFFIX = """

---

⚠️ 注意：以上为本章节的一部分内容。请继续创作下一段正文，保持与上文的连贯性。当前已写约 {written_chars} 字，目标约 {target_words} 字。请继续，不要重复已写的内容。

以下是本章已写的内容摘要（供你参考，不要重复）：
{written_content_summary}"""


def _truncate_for_context(text: str, max_chars: int = 1500) -> str:
    """截取已写内容的摘要放进续段prompt（避免全文过长撑爆上下文）"""
    if len(text) <= max_chars:
        return text
    # 保留开头和结尾
    head = text[:max_chars // 2]
    tail = text[-(max_chars // 3):]
    return head + "\n\n……（中间省略）……\n\n" + tail


def build_chapter_prompt(
    setup: SetupCreate,
    chapter_number: int,
    title: str,
    summary: str,
    previous_chapters_summary: str,
    user_feedback: Optional[str] = None,
) -> str:
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

    if not previous_chapters_summary:
        previous_summary = "这是小说的开篇章节，没有前文。"
    else:
        previous_summary = previous_chapters_summary

    # Issue 12: 用户反馈
    if user_feedback:
        feedback_section = (
            f"\n## 用户反馈\n请参考以下用户的写作反馈进行调整：\n{user_feedback}\n"
        )
    else:
        feedback_section = ""

    return CHAPTER_PROMPT_TEMPLATE.format(
        theme=setup.theme,
        topic=setup.topic,
        optional_fields=optional_str,
        chapter_number=chapter_number,
        title=title,
        summary=summary,
        target_words=setup.words_per_chapter,
        previous_summary=previous_summary,
        user_feedback=feedback_section,
    )


async def _generate_single_chapter(
    llm: LLMAdapter,
    job_id: str,
    setup: SetupCreate,
    ch: dict,
    previous_summary_parts: list,
    user_feedback: Optional[str] = None,
) -> tuple[bool, str, int]:
    """生成单个章节（支持分段 checkpoint）。
    
    返回 (success, content, word_count)
    """
    chapter_num = ch["chapter_number"]

    # 上下文窗口动态管理
    selected_summaries = select_context_summaries(previous_summary_parts)
    context_summary = "\n".join(selected_summaries)

    main_prompt = build_chapter_prompt(
        setup, chapter_num, ch["title"], ch["summary"], context_summary,
        user_feedback=user_feedback,
    )

    full_content = ""
    segment = 0
    target_char_count = setup.words_per_chapter
    segment_target = _get_segment_target(target_char_count)
    max_segments = _get_max_segments(target_char_count)

    while True:
        # 构造当前段的 prompt
        if segment == 0:
            prompt = main_prompt
        else:
            # 把已写内容的摘要放进续段prompt（LLM能看到上文）
            written_summary = _truncate_for_context(full_content, 1500)
            prompt = main_prompt + SEGMENT_PROMPT_SUFFIX.format(
                written_chars=len(full_content.replace(" ", "").replace("\n", "")),
                target_words=target_char_count,
                written_content_summary=written_summary,
            )

        messages = [
            {"role": "system", "content": "你是一位专业小说作家，擅长创作引人入胜的故事。"},
            {"role": "user", "content": prompt},
        ]

        try:
            content_chunks = []
            accumulated = ""
            async for chunk in llm.chat_stream(messages):
                content_chunks.append(chunk)
                accumulated += chunk
                await publish(job_id, "token",
                              chapter=chapter_num,
                              text=chunk,
                              accumulated=full_content + accumulated)

            segment_content = "".join(content_chunks)
        except Exception as e:
            # 超时/错误，但已有部分内容——先保存 checkpoint
            if full_content:
                await _save_segment_checkpoint(job_id, chapter_num, full_content, "partial")
            return False, full_content, len(full_content.replace(" ", "").replace("\n", ""))

        # 追加到全文
        if full_content:
            full_content += "\n\n"
        full_content += segment_content
        segment += 1

        # 保存段 checkpoint（覆盖写，每段持久化）
        await _save_segment_checkpoint(job_id, chapter_num, full_content, "generating")

        # 检查字数是否达标
        char_count = len(full_content.replace(" ", "").replace("\n", ""))
        if char_count >= target_char_count:
            break

        # 防止死循环（动态最大分段数）
        if segment >= max_segments:
            break

    char_count = len(full_content.replace(" ", "").replace("\n", ""))
    return True, full_content, char_count


async def _save_segment_checkpoint(job_id: str, chapter_number: int, content: str, status: str):
    """保存章节的段级 checkpoint（覆盖写，始终保留最新内容）"""
    from app.database import get_db
    async with get_db() as db:
        await db.execute(
            "UPDATE chapters SET content = ?, status = ? WHERE job_id = ? AND chapter_number = ?",
            (content, status, job_id, chapter_number),
        )


async def _get_segment_checkpoint(job_id: str, chapter_number: int) -> tuple[str, str]:
    """读取已保存的段级 checkpoint"""
    from app.database import get_db
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT content, status FROM chapters WHERE job_id = ? AND chapter_number = ?",
            (job_id, chapter_number),
        )
        row = await cursor.fetchone()
        if row:
            return row["content"], row["status"]
        return "", "generating"


async def generate_chapters(job_id: str, up_to: int | None = None):
    """
    逐章生成正文（后台任务），支持分段 checkpoint 和质量评估。

    Args:
        job_id: 任务 ID
        up_to: 可选，最多生成到第几章
    """
    t_start = time.time()
    logger.info(f"开始逐章生成: job={job_id[:8]} up_to={up_to}")

    job = await svc.get_job(job_id)
    if not job:
        logger.warning(f"job 不存在: {job_id[:8]}")
        return

    setup = SetupCreate(
        theme=job.theme,
        topic=job.topic,
        chapter_count=job.chapter_count,
        words_per_chapter=job.words_per_chapter,
        writing_style=job.writing_style,
        characters=job.characters,
        world_setting=job.world_setting,
        narrative_perspective=job.narrative_perspective,
    )

    await svc.update_job_status(job_id, "generating_chapters")
    await publish(job_id, "progress",
                  chapter=0, total=setup.chapter_count,
                  status="generating_chapters",
                  message=f"准备开始写作（共{setup.chapter_count}章）")

    chapters = await svc.get_job_chapters(job_id)
    llm = LLMAdapter()

    previous_summary_parts = []
    # 跨章节人物跟踪
    characters_seen_overall = {}
    chapter_scores = []
    # Issue 12: 加载用户反馈
    user_feedback_str = None
    try:
        fb = job.feedback or []
        if fb:
            fb_texts = []
            for f in fb:
                if isinstance(f, dict) and f.get("text"):
                    fb_texts.append(f["text"])
            if fb_texts:
                user_feedback_str = "\n".join(f"- {t}" for t in fb_texts[-3:])  # 最近3条
    except Exception:
        pass

    for ch in chapters:
        if ch["status"] == "completed":
            previous_summary_parts.append(
                f"第{ch['chapter_number']}章（{ch['title']}）：{ch['summary']}"
            )
            continue

        chapter_num = ch["chapter_number"]

        # 检查是否达到上限
        if up_to is not None and chapter_num > up_to:
            remain = setup.chapter_count - (chapter_num - 1)
            await svc.update_job_status(job_id, "paused")
            await publish(job_id, "batch_complete",
                          chapter=chapter_num - 1, total=setup.chapter_count,
                          status="paused",
                          message=f"已写到第{chapter_num - 1}章，剩余{remain}章待续")
            return

        await publish(job_id, "progress",
                      chapter=chapter_num, total=job.chapter_count,
                      status="generating_chapters",
                      message=f"正在写第 {chapter_num}/{job.chapter_count} 章")

        # ── 尝试恢复段级 checkpoint ──
        saved_content, saved_status = await _get_segment_checkpoint(job_id, chapter_num)
        if saved_content and saved_status == "generating":
            # 有段级 checkpoint，从已有内容继续
            full_content = saved_content
            current_chars = len(full_content.replace(" ", "").replace("\n", ""))
            if current_chars >= setup.words_per_chapter * _WORD_THRESHOLD:
                # 已足够，直接完成
                pass
            else:
                # 使用 checkpoint 内容继续生成（给 LLM 上下文）
                checkpoint_prompt = (
                    f"以下是第 {chapter_num} 章（{ch['title']}）已生成的部分内容，"
                    f"请继续创作后续内容，不要重复。\n\n{full_content}"
                )
                messages = [
                    {"role": "system", "content": "你是一位专业小说作家，擅长创作引人入胜的故事。"},
                    {"role": "user", "content": checkpoint_prompt},
                ]
                content_chunks = []
                accumulated = ""
                try:
                    async for chunk in llm.chat_stream(messages):
                        content_chunks.append(chunk)
                        accumulated += chunk
                        await publish(job_id, "token",
                                      chapter=chapter_num, text=chunk,
                                      accumulated=full_content + accumulated)
                    full_content += "\n\n" + "".join(content_chunks)
                except Exception:
                    pass  # 保留已有内容即可

            await _save_segment_checkpoint(job_id, chapter_num, full_content, "generating")
        else:
            # 正常分段生成
            success, full_content, char_count = await _generate_single_chapter(
                llm, job_id, setup, ch, previous_summary_parts,
                user_feedback=user_feedback_str,
            )

        char_count = len(full_content.replace(" ", "").replace("\n", ""))

        # ── 字数校验 & 重试 ──
        retries = 0
        while retries < 3 and char_count < setup.words_per_chapter * _WORD_THRESHOLD:
            await publish(job_id, "progress",
                          chapter=chapter_num, total=job.chapter_count,
                          status="generating_chapters",
                          message=f"第 {chapter_num} 章字数不足（{char_count}/{setup.words_per_chapter}），重试中...")
            retries += 1
            # 重新全文生成（覆盖已有内容）
            success, full_content, char_count = await _generate_single_chapter(
                llm, job_id, setup, ch, previous_summary_parts,
                user_feedback=user_feedback_str,
            )
            char_count = len(full_content.replace(" ", "").replace("\n", ""))

        if char_count < setup.words_per_chapter * _WORD_THRESHOLD:
            await svc.update_job_status(job_id, "failed")
            await publish(job_id, "error",
                          chapter=chapter_num,
                          error=f"第 {chapter_num} 章连续生成失败3次，字数不足，任务已终止")
            return

        # ── 完成保存 ──
        await svc.save_chapter(job_id, chapter_num, full_content, char_count, ch["title"])

        # ── Issue 5: 增强版一致性检查 ──
        consistency_alerts = []
        if setup.characters:
            alerts, chars_seen, characters_seen_overall = await check_consistency(
                full_content, setup.characters, chapter_num, characters_seen_overall,
            )
            for alert in alerts:
                await svc.add_consistency_alert(job_id, alert["chapter_number"], alert["conflict_name"])
            consistency_alerts = alerts

        # ── Issue 8: 写作质量评估 ──
        quality = score_chapter(full_content, ch["title"], setup.words_per_chapter, chapter_num)
        chapter_scores.append({"chapter": chapter_num, "score": quality["overall"]})
        
        await publish(job_id, "chapter_complete",
                      chapter=chapter_num,
                      title=ch["title"],
                      word_count=char_count,
                      quality_score=quality["overall"],
                      quality_summary=score_summary(quality))

        # 如果有质量问题，推送给用户
        if quality["issues"]:
            await publish(job_id, "quality_issue",
                          chapter=chapter_num,
                          issues=quality["issues"],
                          score=quality["overall"])

        previous_summary_parts.append(f"第{chapter_num}章（{ch['title']}）：{ch['summary']}")

    # 全部完成
    elapsed = time.time() - t_start
    logger.info(f"全部章节生成完成: job={job_id[:8]} 耗时={elapsed:.0f}s 章节={setup.chapter_count}")
    await svc.update_job_status(job_id, "completed")
    await publish(job_id, "job_complete",
                  job_id=job_id,
                  status="completed",
                  scores=chapter_scores)


async def regenerate_chapter(
    job_id: str,
    chapter_number: int,
    instruction: str = "",
) -> dict:
    """重新生成指定章节（Issue 7：生成后改稿）。

    Args:
        job_id: 任务 ID
        chapter_number: 章节序号
        instruction: 用户修改指令（可选）
    """
    job = await svc.get_job(job_id)
    if not job:
        return {"success": False, "error": "任务不存在"}

    setup = SetupCreate(
        theme=job.theme,
        topic=job.topic,
        chapter_count=job.chapter_count,
        words_per_chapter=job.words_per_chapter,
        writing_style=job.writing_style,
        characters=job.characters,
        world_setting=job.world_setting,
        narrative_perspective=job.narrative_perspective,
    )

    chapters = await svc.get_job_chapters(job_id)
    target_ch = None
    for ch in chapters:
        if ch["chapter_number"] == chapter_number:
            target_ch = ch
            break

    if not target_ch:
        return {"success": False, "error": f"章节 {chapter_number} 不存在"}

    # 构建前文摘要
    previous_summary_parts = []
    for ch in chapters:
        if ch["chapter_number"] >= chapter_number:
            break
        if ch.get("summary"):
            previous_summary_parts.append(f"第{ch['chapter_number']}章（{ch['title']}）：{ch['summary']}")

    selected_summaries = select_context_summaries(previous_summary_parts)
    context_summary = "\n".join(selected_summaries)

    llm = LLMAdapter()

    # 构建 prompt（含修改指令）
    prompt = build_chapter_prompt(
        setup, chapter_number, target_ch["title"], target_ch["summary"], context_summary,
    )
    if instruction:
        prompt += f"\n\n## 用户修改要求\n{instruction}\n请根据以上修改要求重新创作本章正文。"

    messages = [
        {"role": "system", "content": "你是一位专业小说作家，擅长创作引人入胜的故事。"},
        {"role": "user", "content": prompt},
    ]

    content_chunks = []
    try:
        previous_content = ""
        async for chunk in llm.chat_stream(messages):
            content_chunks.append(chunk)
            previous_content += chunk
            await publish(job_id, "token",
                          chapter=chapter_number,
                          text=chunk,
                          accumulated=previous_content)
    except Exception as e:
        return {"success": False, "error": f"重新生成失败: {str(e)}"}

    content = "".join(content_chunks)
    word_count = len(content.replace(" ", "").replace("\n", ""))

    # 保存新内容
    await svc.save_chapter(job_id, chapter_number, content, word_count, target_ch["title"])

    # 质量评估
    quality = score_chapter(content, target_ch["title"], setup.words_per_chapter, chapter_number)

    return {
        "success": True,
        "content": content,
        "word_count": word_count,
        "quality": quality,
    }