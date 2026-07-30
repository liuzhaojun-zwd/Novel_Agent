"""章节生成器：场景规划 → 场景生成 → 合并润色。"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional
from uuid import uuid4

from app.models import SetupCreate
from app.services import job_service as svc
from app.services.consistency_checker import check_consistency
from app.services.context_manager import select_context_summaries
from app.services.llm_adapter import LLMAdapter
from app.services.progress_tracker import publish
from app.services.quality_scorer import score_chapter, score_summary
from app.services.scene_generator import (
    GenerationInterrupted,
    check_generation_control,
    generate_scene_chapter,
)
from app.services.story_bible import format_setup_context

logger = logging.getLogger("novel_agent.chapter")

CHAPTER_PROMPT_TEMPLATE = """你是一位专业小说作家，请根据小说圣经和结构化章节卡创作章节正文。

## 作品设定
- 题材：{theme}
- 故事核心：{topic}
{optional_fields}

## 章节信息
- 章节序号：第 {chapter_number} 章
- 章节标题：{title}
- 本章情节摘要：{summary}
- 目标字数：约 {target_words} 字

## 结构化章节卡
{chapter_card}

## 前文回顾
{previous_summary}
{user_feedback}
"""

def build_chapter_prompt(
    setup: SetupCreate,
    chapter_number: int,
    title: str,
    summary: str,
    previous_chapters_summary: str,
    user_feedback: Optional[str] = None,
    chapter_card: Optional[dict] = None,
) -> str:
    """保留给章节重写功能使用的整章 prompt。"""
    feedback_section = (
        f"\n## 用户反馈\n请参考以下用户的写作反馈进行调整：\n{user_feedback}\n"
        if user_feedback else ""
    )
    card = dict(chapter_card or {})
    for key in ("chapter_number", "title", "summary", "content", "status", "word_count"):
        card.pop(key, None)
    chapter_card_json = json.dumps(card, ensure_ascii=False, indent=2) if card else "按章节摘要自然规划场景。"
    return CHAPTER_PROMPT_TEMPLATE.format(
        theme=setup.theme,
        topic=setup.topic,
        optional_fields=format_setup_context(setup),
        chapter_number=chapter_number,
        title=title,
        summary=summary,
        target_words=setup.words_per_chapter,
        chapter_card=chapter_card_json,
        previous_summary=previous_chapters_summary or "这是小说的开篇章节，没有前文。",
        user_feedback=feedback_section,
    )


def _setup_from_job(job) -> SetupCreate:
    return SetupCreate(
        theme=job.theme,
        topic=job.topic,
        chapter_count=job.chapter_count,
        words_per_chapter=job.words_per_chapter,
        writing_style=job.writing_style,
        characters=job.characters,
        world_setting=job.world_setting,
        narrative_perspective=job.narrative_perspective,
        story_bible=job.story_bible,
    )


def _feedback_text(job) -> Optional[str]:
    texts = [
        item["text"] for item in (job.feedback or [])
        if isinstance(item, dict) and item.get("text")
    ]
    return "\n".join(f"- {text}" for text in texts[-3:]) or None


async def _finish_interrupted(job_id: str, run_id: str, state: str, chapter: int):
    final_state = "cancelled" if state == "cancelled" else "paused"
    await svc.update_generation_run(run_id, state=final_state)
    await svc.update_job_status(job_id, "paused")
    message = "生成已取消，场景 checkpoint 已保留，可随时恢复" if final_state == "cancelled" else "生成已暂停，场景 checkpoint 已保留"
    await publish(job_id, "control_state", state=final_state, chapter=chapter, message=message)
    await publish(job_id, "batch_complete", chapter=chapter, status="paused", message=message)

async def generate_chapters(
    job_id: str,
    up_to: int | None = None,
    run_id: str | None = None,
    generation_mode: str = "auto",
    single_chapter: int | None = None,
):
    """按场景 checkpoint 生成章节；旧的 job_id/up_to 调用方式保持兼容。"""
    started_at = time.time()
    job = await svc.get_job(job_id)
    if not job:
        logger.warning("job 不存在: %s", job_id[:8])
        return
    setup = _setup_from_job(job)
    chapters = await svc.get_job_chapters(job_id)
    outline_by_number = {
        item.get("chapter_number"): item
        for item in (job.outline or []) if isinstance(item, dict)
    }
    chapters = [
        {**chapter, **outline_by_number.get(chapter["chapter_number"], {})}
        for chapter in chapters
    ]

    if run_id is None:
        pending = [item["chapter_number"] for item in chapters if item["status"] != "completed"]
        if not pending:
            return
        run, _ = await svc.create_generation_run(
            job_id, f"direct-{uuid4().hex}", generation_mode,
            single_chapter or pending[0], up_to, single_chapter,
        )
        run_id = run["id"]

    await svc.update_job_status(job_id, "generating_chapters")
    await publish(
        job_id, "progress", chapter=0, total=setup.chapter_count,
        status="generating_chapters", message=f"准备场景级写作（共{setup.chapter_count}章）",
    )

    llm = LLMAdapter(purpose="chapter.draft", prompt_id="chapter.draft", job_id=job_id)
    previous_summary_parts: list[str] = []
    characters_seen_overall: dict = {}
    chapter_scores: list[dict] = []
    active_chapter = job.current_chapter

    try:
        for chapter in chapters:
            chapter_number = chapter["chapter_number"]
            if chapter["status"] == "completed":
                previous_summary_parts.append(
                    f"第{chapter_number}章（{chapter['title']}）：{chapter['summary']}"
                )
                continue
            if single_chapter is not None and chapter_number != single_chapter:
                continue
            if up_to is not None and chapter_number > up_to:
                break

            active_chapter = chapter_number
            await check_generation_control(run_id)
            await publish(
                job_id, "progress", chapter=chapter_number, total=job.chapter_count,
                status="generating_chapters",
                message=f"正在写第 {chapter_number}/{job.chapter_count} 章",
            )
            content, char_count = await generate_scene_chapter(
                llm, job_id, run_id, setup, chapter, previous_summary_parts,
                user_feedback=_feedback_text(job),
            )
            await svc.save_chapter(
                job_id, chapter_number, content, char_count, chapter["title"],
            )
            await svc.update_generation_run(
                run_id, current_chapter=chapter_number, current_scene=0,
                stage="chapter_complete", checkpoint_content="",
            )

            try:
                from app.services.memory_service import extract_chapter_memories

                memory_result = await extract_chapter_memories(
                    llm, job_id, setup, chapter_number, chapter["title"],
                    chapter["summary"], content,
                )
                await publish(
                    job_id, "memory_updated", chapter=chapter_number,
                    activated=memory_result["activated"],
                    pending=memory_result["pending"],
                    message=(
                        f"已更新长期记忆；{memory_result['pending']} 项重要事实变更待确认"
                        if memory_result["pending"]
                        else "已更新长期记忆"
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "章节记忆提取失败，不阻断正文生成: job=%s chapter=%s error=%s",
                    job_id[:8], chapter_number, exc,
                )
                await publish(
                    job_id, "memory_warning", chapter=chapter_number,
                    message="正文已保存，但长期记忆提取失败，可稍后手动重试",
                )

            if setup.characters:
                alerts, _, characters_seen_overall = await check_consistency(
                    content, setup.characters, chapter_number, characters_seen_overall,
                )
                for alert in alerts:
                    await svc.add_consistency_alert(
                        job_id, alert["chapter_number"], alert["conflict_name"],
                    )

            quality = score_chapter(
                content, chapter["title"], setup.words_per_chapter, chapter_number,
            )
            chapter_scores.append({"chapter": chapter_number, "score": quality["overall"]})
            await publish(
                job_id, "chapter_complete", chapter=chapter_number,
                title=chapter["title"], word_count=char_count,
                quality_score=quality["overall"], quality_summary=score_summary(quality),
            )
            if quality["issues"]:
                await publish(
                    job_id, "quality_issue", chapter=chapter_number,
                    issues=quality["issues"], score=quality["overall"],
                )
            previous_summary_parts.append(
                f"第{chapter_number}章（{chapter['title']}）：{chapter['summary']}"
            )

            remaining_in_run = [
                item for item in chapters
                if item["status"] != "completed"
                and item["chapter_number"] > chapter_number
                and (up_to is None or item["chapter_number"] <= up_to)
                and single_chapter is None
            ]
            if generation_mode == "collaborative" and remaining_in_run:
                await svc.update_generation_run(run_id, state="paused")
                await svc.update_job_status(job_id, "paused")
                message = f"协作模式已完成第 {chapter_number} 章，请检查后继续"
                await publish(job_id, "control_state", state="paused", chapter=chapter_number, message=message)
                await publish(
                    job_id, "batch_complete", chapter=chapter_number,
                    total=setup.chapter_count, status="paused", message=message,
                )
                return

        refreshed = await svc.get_job_chapters(job_id)
        all_completed = bool(refreshed) and all(item["status"] == "completed" for item in refreshed)
        await svc.update_generation_run(run_id, state="completed", stage="completed", checkpoint_content="")
        if all_completed:
            await svc.update_job_status(job_id, "completed")
            await publish(
                job_id, "job_complete",
                status="completed", scores=chapter_scores,
            )
        else:
            latest = await svc.get_job(job_id)
            completed_to = latest.current_chapter if latest else active_chapter
            await svc.update_job_status(job_id, "paused")
            message = f"本次生成已完成，当前连续完成到第 {completed_to} 章"
            await publish(
                job_id, "batch_complete", chapter=completed_to,
                total=setup.chapter_count, status="paused", message=message,
            )
        logger.info(
            "场景级生成结束: job=%s 耗时=%.0fs", job_id[:8], time.time() - started_at,
        )
    except GenerationInterrupted as exc:
        latest = await svc.get_job(job_id)
        checkpoint_chapter = latest.current_chapter if latest else max(0, active_chapter - 1)
        await _finish_interrupted(job_id, run_id, exc.state, checkpoint_chapter)
    except Exception as exc:
        logger.error("场景级生成失败: job=%s error=%s", job_id[:8], exc, exc_info=True)
        await svc.update_generation_run(run_id, state="paused", error=str(exc))
        await svc.update_job_status(job_id, "paused")
        await publish(
            job_id, "error", chapter=active_chapter, status="paused",
            error=f"{exc}；场景 checkpoint 已保留，可点击恢复",
        )
        await publish(
            job_id, "control_state", state="paused", chapter=active_chapter,
            message="生成遇到错误，checkpoint 已保留，持久队列将自动重试",
        )
        raise

async def regenerate_chapter(
    job_id: str,
    chapter_number: int,
    instruction: str = "",
) -> dict:
    """按用户指令重写已完成章节；与场景流水线保持独立。"""
    job = await svc.get_job(job_id)
    if not job:
        return {"success": False, "error": "任务不存在"}
    setup = _setup_from_job(job)
    chapters = await svc.get_job_chapters(job_id)
    target = next(
        (item for item in chapters if item["chapter_number"] == chapter_number), None,
    )
    if not target:
        return {"success": False, "error": f"章节 {chapter_number} 不存在"}
    chapter_card = next(
        (
            item for item in (job.outline or [])
            if isinstance(item, dict) and item.get("chapter_number") == chapter_number
        ),
        target,
    )
    prior = [
        f"第{item['chapter_number']}章（{item['title']}）：{item['summary']}"
        for item in chapters if item["chapter_number"] < chapter_number and item.get("summary")
    ]
    prompt = build_chapter_prompt(
        setup, chapter_number, target["title"], target["summary"],
        "\n".join(select_context_summaries(prior)), chapter_card=chapter_card,
    )
    if instruction:
        prompt += f"\n\n## 用户修改要求\n{instruction}\n请据此重写本章。"
    messages = [
        {"role": "system", "content": "你是一位专业小说作家，擅长创作引人入胜的故事。"},
        {"role": "user", "content": prompt},
    ]
    chunks: list[str] = []
    accumulated = ""
    try:
        async for chunk in LLMAdapter(
            purpose="chapter.draft", prompt_id="chapter.draft", job_id=job_id,
        ).chat_stream(messages):
            chunks.append(chunk)
            accumulated += chunk
            await publish(
                job_id, "token", chapter=chapter_number,
                text=chunk, accumulated=accumulated,
            )
    except Exception as exc:
        return {"success": False, "error": f"重新生成失败: {exc}"}

    content = "".join(chunks)
    word_count = len(content.replace(" ", "").replace("\n", ""))
    await svc.save_chapter(job_id, chapter_number, content, word_count, target["title"])
    quality = score_chapter(content, target["title"], setup.words_per_chapter, chapter_number)
    return {
        "success": True,
        "content": content,
        "word_count": word_count,
        "quality": quality,
    }
