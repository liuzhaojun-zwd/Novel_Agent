"""Novel_Agent — 章节生成器"""
from app.services.llm_adapter import LLMAdapter
from app.services import job_service as svc
from app.services.progress_tracker import publish
from app.services.consistency_checker import check_consistency
from app.services.context_manager import select_context_summaries, estimate_tokens
from app.models import SetupCreate

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

## 要求
1. 创作正文内容，达到目标字数
2. 保持与人物设定一致
3. 情节扣题，细节丰富
4. 语言风格保持一致
5. 直接输出正文内容，不要输出章节标题
"""


def build_chapter_prompt(
    setup: SetupCreate,
    chapter_number: int,
    title: str,
    summary: str,
    previous_chapters_summary: str,
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

    return CHAPTER_PROMPT_TEMPLATE.format(
        theme=setup.theme,
        topic=setup.topic,
        optional_fields=optional_str,
        chapter_number=chapter_number,
        title=title,
        summary=summary,
        target_words=setup.words_per_chapter,
        previous_summary=previous_summary,
    )


async def generate_chapters(job_id: str, up_to: int | None = None):
    """
    逐章生成正文（后台任务），支持流式输出。

    Args:
        job_id: 任务 ID
        up_to: 可选，最多生成到第几章。不传则为 None 则生成全部章节。
    """
    job = await svc.get_job(job_id)
    if not job:
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
    fail_count = 0

    for ch in chapters:
        if ch["status"] == "completed":
            previous_summary_parts.append(
                f"第{ch['chapter_number']}章（{ch['title']}）：{ch['summary']}"
            )
            continue

        chapter_num = ch["chapter_number"]

        # 检查是否达到用户指定的上限
        if up_to is not None and chapter_num > up_to:
            remain = setup.chapter_count - (chapter_num - 1)
            await svc.update_job_status(job_id, "paused")
            await publish(job_id, "batch_complete",
                          chapter=chapter_num - 1,
                          total=setup.chapter_count,
                          status="paused",
                          message=f"已按您的要求写到第{chapter_num - 1}章，剩余{remain}章待续")
            return

        # 推送进度
        await publish(job_id, "progress",
                      chapter=chapter_num, total=job.chapter_count,
                      status="generating_chapters",
                      message=f"正在写第 {chapter_num}/{job.chapter_count} 章")

        # --- 上下文窗口动态管理 ---
        # 自动选择合适的摘要数量，避免超出上下文预算
        selected_summaries = select_context_summaries(previous_summary_parts)
        context_summary = "\n".join(selected_summaries)

        prompt = build_chapter_prompt(
            setup, chapter_num, ch["title"], ch["summary"], context_summary,
        )

        retry_count = 0
        success = False
        content = ""

        while retry_count < 3 and not success:
            try:
                messages = [
                    {"role": "system", "content": "你是一位专业小说作家，擅长创作引人入胜的故事。"},
                    {"role": "user", "content": prompt},
                ]

                # 流式输出：一边接收 LLM 返回的 token，一边推送 SSE
                # 同时累积完整内容
                content_chunks = []
                accumulated = ""
                async for chunk in llm.chat_stream(messages):
                    content_chunks.append(chunk)
                    accumulated += chunk
                    # 每收到一段 token 就推送 SSE，前端实时显示
                    await publish(job_id, "token",
                                  chapter=chapter_num,
                                  text=chunk,
                                  accumulated=accumulated)

                content = "".join(content_chunks)

                # 字数校验
                word_count = len(content.replace(" ", "").replace("\n", ""))
                if word_count < setup.words_per_chapter * 0.5:
                    retry_count += 1
                    if retry_count < 3:
                        await publish(job_id, "progress",
                                      chapter=chapter_num,
                                      total=job.chapter_count,
                                      status="generating_chapters",
                                      message=f"第 {chapter_num} 章字数不足（{word_count}/{setup.words_per_chapter}），正在重新生成...")
                        continue

                success = True

            except Exception as e:
                retry_count += 1
                await publish(job_id, "error",
                              chapter=chapter_num,
                              error=str(e),
                              retry_count=retry_count)
                if retry_count >= 3:
                    await svc.update_job_status(job_id, "failed")
                    await publish(job_id, "error",
                                  chapter=chapter_num,
                                  error=f"章节连续生成失败3次，任务已终止",
                                  retry_count=3)
                    return

        if not success:
            await svc.update_job_status(job_id, "failed")
            await publish(job_id, "error",
                          chapter=chapter_num,
                          error="章节生成失败")
            return

        word_count = len(content.replace(" ", "").replace("\n", ""))
        await svc.save_chapter(job_id, chapter_num, content, word_count, ch["title"])

        # 一致性检查
        if setup.characters:
            alerts = await check_consistency(content, setup.characters, chapter_num)
            for alert in alerts:
                await svc.add_consistency_alert(job_id, alert["chapter_number"], alert["conflict_name"])

        previous_summary_parts.append(f"第{chapter_num}章（{ch['title']}）：{ch['summary']}")

        await publish(job_id, "chapter_complete",
                      chapter=chapter_num,
                      title=ch["title"],
                      word_count=word_count)

    # 全部完成
    await svc.update_job_status(job_id, "completed")
    await publish(job_id, "job_complete",
                  job_id=job_id,
                  status="completed")