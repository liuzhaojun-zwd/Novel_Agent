"""章节 API：场景级生成、控制、读取与重写。"""

import logging
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Query

from app.models import ApplyChapterPatchRequest, ChapterResponse, LocalRewriteRequest
from app.services import job_service as svc
from app.services import llm_metrics, task_queue
from app.services.chapter_generator import regenerate_chapter
from app.services.editorial_service import apply_patch, propose_patch, review_chapter
from app.services.llm_adapter import LLMAdapter
from app.services.job_locks import acquire_job_lock, release_job_lock
from app.services.progress_tracker import publish

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["chapters"])
logger = logging.getLogger("novel_agent.chapter")


async def _chapter_or_404(job_id: str, chapter_number: int) -> tuple[object, dict, list[dict]]:
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    chapters = await svc.get_job_chapters(job_id)
    chapter = next((item for item in chapters if item["chapter_number"] == chapter_number), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return job, chapter, chapters


async def _refresh_chapter_memory(job, target: dict, content: str) -> str:
    """正文保存后刷新长期记忆；模型失败不回滚用户正文。"""
    try:
        from app.models import SetupCreate
        from app.services.memory_service import extract_chapter_memories

        setup = SetupCreate(
            theme=job.theme, topic=job.topic, chapter_count=job.chapter_count,
            words_per_chapter=job.words_per_chapter, writing_style=job.writing_style,
            characters=job.characters, world_setting=job.world_setting,
            narrative_perspective=job.narrative_perspective, story_bible=job.story_bible,
        )
        await extract_chapter_memories(
            LLMAdapter(), job.id, setup, target["chapter_number"],
            target["title"], target["summary"], content,
        )
        return "updated"
    except Exception as exc:
        logger.warning(
            "正文保存后的记忆提取失败: job=%s chapter=%s error=%s",
            job.id[:8], target["chapter_number"], exc,
        )
        return "retry_required"


@router.get("/chapters", response_model=list[ChapterResponse])
async def list_chapters(job_id: str):
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return [ChapterResponse(**chapter) for chapter in await svc.get_job_chapters(job_id)]


@router.get("/chapters/{chapter_number}", response_model=ChapterResponse)
async def get_chapter(job_id: str, chapter_number: int):
    chapters = await svc.get_job_chapters(job_id)
    chapter = next((item for item in chapters if item["chapter_number"] == chapter_number), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return ChapterResponse(**chapter)


@router.get("/chapters/{chapter_number}/scenes")
async def get_chapter_scenes(job_id: str, chapter_number: int):
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"chapter": chapter_number, "scenes": await svc.get_chapter_scenes(job_id, chapter_number)}

@router.put("/chapters/{chapter_number}")
async def update_chapter(
    job_id: str,
    chapter_number: int,
    content: str = Body(..., embed=True),
):
    job, target, _ = await _chapter_or_404(job_id, chapter_number)
    word_count = len(content.replace(" ", "").replace("\n", ""))
    await svc.save_chapter(job_id, chapter_number, content, word_count, target["title"])
    memory_status = await _refresh_chapter_memory(job, target, content)
    return {"message": "章节已更新", "word_count": word_count, "memory_status": memory_status}


@router.post("/chapters/{chapter_number}/review")
async def semantic_review(job_id: str, chapter_number: int):
    job, chapter, chapters = await _chapter_or_404(job_id, chapter_number)
    if not chapter.get("content"):
        raise HTTPException(status_code=400, detail="章节正文为空，无法审稿")
    try:
        return await review_chapter(
            LLMAdapter(purpose="chapter.review", prompt_id="chapter.review", job_id=job_id),
            job, chapter, chapters,
        )
    except Exception as exc:
        logger.error("语义审稿失败: job=%s chapter=%s error=%s", job_id[:8], chapter_number, exc)
        raise HTTPException(status_code=502, detail=f"语义审稿失败: {exc}") from exc


@router.post("/chapters/{chapter_number}/patches")
async def create_local_patch(
    job_id: str,
    chapter_number: int,
    request: LocalRewriteRequest,
):
    job, chapter, _ = await _chapter_or_404(job_id, chapter_number)
    try:
        return await propose_patch(
            LLMAdapter(), job, chapter, request.start, request.end,
            request.operation, request.instruction, request.style, request.selected_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("局部补丁生成失败: job=%s chapter=%s error=%s", job_id[:8], chapter_number, exc)
        raise HTTPException(status_code=502, detail=f"局部补丁生成失败: {exc}") from exc


@router.post("/chapters/{chapter_number}/patches/apply")
async def accept_local_patch(
    job_id: str,
    chapter_number: int,
    request: ApplyChapterPatchRequest,
):
    job, chapter, _ = await _chapter_or_404(job_id, chapter_number)
    try:
        updated = apply_patch(chapter.get("content") or "", request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    word_count = len(updated.replace(" ", "").replace("\n", ""))
    await svc.save_chapter(job_id, chapter_number, updated, word_count, chapter["title"])
    memory_status = await _refresh_chapter_memory(job, chapter, updated)
    return {
        "message": "局部补丁已应用", "content": updated,
        "word_count": word_count, "memory_status": memory_status,
    }


@router.post("/chapters/{chapter_number}/regenerate")
async def regenerate_chapter_endpoint(
    job_id: str,
    chapter_number: int,
    instruction: str = Body("", embed=True),
):
    result = await regenerate_chapter(job_id, chapter_number, instruction)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "重新生成失败"))
    return result


def _validate_generation_mode(value: str | None, fallback: str = "auto") -> str:
    mode = value or fallback
    if mode not in {"auto", "collaborative"}:
        raise HTTPException(status_code=400, detail="generation_mode 仅支持 auto 或 collaborative")
    return mode


async def _start_generation_internal(
    job_id: str,
    up_to: int | None,
    request_mode: str,
    generation_mode: str | None = None,
    chapter: int | None = None,
    idempotency_key: str | None = None,
):
    """在任务锁内创建/恢复持久运行，并保证同一幂等键只启动一次。"""
    locked = await acquire_job_lock(job_id)
    if not locked:
        raise HTTPException(status_code=429, detail="操作太频繁，请稍后再试")

    try:
        job = await svc.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if up_to is not None and chapter is not None:
            raise HTTPException(status_code=400, detail="up_to 与 chapter 不能同时指定")
        if up_to is not None and not 1 <= up_to <= job.chapter_count:
            raise HTTPException(status_code=400, detail=f"up_to 须在 1-{job.chapter_count} 之间")
        if chapter is not None and not 1 <= chapter <= job.chapter_count:
            raise HTTPException(status_code=400, detail=f"chapter 须在 1-{job.chapter_count} 之间")

        existing = None
        if idempotency_key:
            existing = await svc.get_generation_run_by_key(job_id, idempotency_key)
            if existing and existing["state"] in {
                "running", "pause_requested", "cancel_requested", "completed", "failed"
            }:
                return {
                    "message": "相同幂等请求已处理",
                    "job_id": job_id,
                    "run_id": existing["id"],
                    "state": existing["state"],
                    "idempotent": True,
                }
            if existing and request_mode == "start":
                return {
                    "message": "相同幂等请求已暂停，可使用恢复操作继续",
                    "job_id": job_id,
                    "run_id": existing["id"],
                    "state": existing["state"],
                    "idempotent": True,
                }

        if request_mode == "start" and job.status != "pending":
            raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许启动正文生成")
        if request_mode == "resume" and job.status not in {"paused", "failed", "generating_chapters"}:
            raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许续生")
        if not job.outline:
            raise HTTPException(status_code=400, detail="尚未生成并确认大纲")
        active_task = await task_queue.get_active(job_id, "chapter.generate")
        if active_task:
            return {
                "message": "该任务已有持久化生成任务在执行",
                "job_id": job_id,
                "task_id": active_task["id"],
                "state": active_task["state"],
                "idempotent": True,
            }

        chapters = await svc.get_job_chapters(job_id)
        if chapter is not None:
            target = next((item for item in chapters if item["chapter_number"] == chapter), None)
            if not target:
                raise HTTPException(status_code=404, detail="章节不存在")
            if target["status"] == "completed":
                raise HTTPException(status_code=400, detail=f"第 {chapter} 章已完成")
            start_chapter = chapter
        else:
            pending = [
                item["chapter_number"] for item in chapters
                if item["status"] != "completed" and (up_to is None or item["chapter_number"] <= up_to)
            ]
            if not pending:
                raise HTTPException(status_code=400, detail="指定范围内没有待生成章节")
            start_chapter = min(pending)

        resumable = existing
        if request_mode == "resume" and resumable is None:
            resumable = await svc.get_latest_generation_run(job_id, ("paused", "cancelled"))

        if resumable:
            effective_mode = _validate_generation_mode(generation_mode, resumable["generation_mode"])
            effective_up_to = up_to if up_to is not None else resumable["target_chapter"]
            effective_chapter = chapter if chapter is not None else resumable["single_chapter"]
            await svc.resume_generation_run(
                resumable["id"], effective_mode, effective_up_to, effective_chapter,
            )
            run = await svc.get_generation_run(resumable["id"])
        else:
            effective_mode = _validate_generation_mode(generation_mode)
            effective_up_to = up_to
            effective_chapter = chapter
            key = idempotency_key or uuid4().hex
            run, _ = await svc.create_generation_run(
                job_id, key, effective_mode, start_chapter,
                effective_up_to, effective_chapter,
            )

        task, _ = await task_queue.enqueue(
            "chapter.generate",
            job_id,
            {
                "up_to": effective_up_to,
                "run_id": run["id"],
                "generation_mode": effective_mode,
                "single_chapter": effective_chapter,
            },
            project_id=job.project_id,
            dedupe_key=f"chapter:{job_id}",
            max_attempts=3,
            timeout_seconds=7200,
        )
        await svc.update_job_status(job_id, "generating_chapters")
    finally:
        release_job_lock(job_id)

    target_desc = f"单章第{effective_chapter}章" if effective_chapter else (
        f"生成到第{effective_up_to}章" if effective_up_to else "生成剩余全部"
    )
    return {
        "message": f"场景级正文生成已启动（{target_desc}）",
        "job_id": job_id,
        "run_id": run["id"],
        "task_id": task["id"],
        "state": task["state"],
        "generation_mode": effective_mode,
    }

@router.post("/start")
async def start_generation(
    job_id: str,
    up_to: int = Query(None, description="最多生成到第几章，不传则生成全部"),
    chapter: int = Query(None, description="只生成指定单章"),
    generation_mode: str = Query(None, description="auto 或 collaborative"),
    idempotency_key: str = Query(None, max_length=128),
):
    return await _start_generation_internal(
        job_id, up_to, "start", generation_mode, chapter, idempotency_key,
    )


@router.post("/resume")
async def resume_generation(
    job_id: str,
    up_to: int = Query(None, description="最多续生到第几章"),
    chapter: int = Query(None, description="只恢复指定单章"),
    generation_mode: str = Query(None, description="auto 或 collaborative"),
    idempotency_key: str = Query(None, max_length=128),
):
    result = await _start_generation_internal(
        job_id, up_to, "resume", generation_mode, chapter, idempotency_key,
    )
    job = await svc.get_job(job_id)
    result["from_chapter"] = (job.current_chapter + 1) if job else 1
    return result


@router.post("/chapters/{chapter_number}/generate")
async def generate_single_chapter(
    job_id: str,
    chapter_number: int,
    generation_mode: str = Query("auto"),
    idempotency_key: str = Query(None, max_length=128),
):
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    request_mode = "start" if job.status == "pending" else "resume"
    return await _start_generation_internal(
        job_id, None, request_mode, generation_mode, chapter_number, idempotency_key,
    )


async def _request_control(job_id: str, action: str):
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    run = await svc.get_latest_generation_run(
        job_id, ("running", "pause_requested", "cancel_requested"),
    )
    if not run:
        raise HTTPException(status_code=400, detail="当前没有可控制的生成任务")

    requested = "pause_requested" if action == "pause" else "cancel_requested"
    final = "paused" if action == "pause" else "cancelled"
    await svc.update_generation_run(run["id"], state=requested)
    active_task = await task_queue.get_active(job_id, "chapter.generate")
    if action == "cancel" and active_task:
        await task_queue.request_cancel(job_id)
    if not active_task:
        await svc.update_generation_run(run["id"], state=final)
        await svc.update_job_status(job_id, "paused")
    message = "暂停请求已提交，将在当前输出 checkpoint 后暂停" if action == "pause" else "取消请求已提交，将保留场景 checkpoint"
    await publish(job_id, "control_state", state=requested, chapter=run["current_chapter"], message=message)
    return {"message": message, "run_id": run["id"], "state": requested}


@router.post("/pause")
async def pause_generation(job_id: str):
    return await _request_control(job_id, "pause")


@router.post("/cancel")
async def cancel_generation(job_id: str):
    return await _request_control(job_id, "cancel")


@router.get("/generation-state")
async def generation_state(job_id: str):
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    run = await svc.get_latest_generation_run(job_id)
    chapters = await svc.get_job_chapters(job_id)
    output_chars = sum(len(item.get("content") or "") for item in chapters)
    # Providers do not consistently return usage for streaming calls. Keep these
    # values explicitly estimated instead of presenting them as billing facts.
    estimated_output_tokens = max(0, round(output_chars * 1.5))
    estimated_input_tokens = round(estimated_output_tokens * 0.35)
    estimated_cost_usd = round(
        (estimated_input_tokens * 0.5 + estimated_output_tokens * 2.0) / 1_000_000, 4,
    )
    base_metrics = {
        "estimated": True,
        "input_tokens": estimated_input_tokens,
        "output_tokens": estimated_output_tokens,
        "total_tokens": estimated_input_tokens + estimated_output_tokens,
        "cost_usd": estimated_cost_usd,
        "pricing_note": "未取得模型 usage 时按配置价格估算",
        "elapsed_seconds": 0,
        "eta_seconds": None,
        "progress_percent": 0,
    }
    actual = await llm_metrics.job_totals(job_id)
    if actual["calls"]:
        base_metrics.update(actual)
        base_metrics["pricing_note"] = "优先采用模型 usage；不支持 usage 的流式调用标记为估算"
    base_metrics["queue"] = await task_queue.metrics(job_id)
    if not run:
        return {"state": job.status, "run": None, "scenes": [], "metrics": base_metrics}

    chapter = run["current_chapter"] or run["start_chapter"]
    scenes = await svc.get_chapter_scenes(job_id, chapter)
    target = run.get("single_chapter") or run.get("target_chapter") or job.chapter_count
    start = run["start_chapter"]
    total_units = max(1, target - start + 1)
    completed_units = sum(
        1 for item in chapters
        if start <= item["chapter_number"] <= target and item["status"] == "completed"
    )
    scene_fraction = 0.0
    if scenes and completed_units < total_units:
        scene_fraction = sum(item["status"] == "completed" for item in scenes) / len(scenes)
        if run.get("stage") == "polishing":
            scene_fraction = max(scene_fraction, 0.9)
    progress = min(1.0, (completed_units + scene_fraction) / total_units)
    try:
        created = datetime.strptime(run["created_at"], "%Y-%m-%d %H:%M:%S")
        elapsed = max(0, int((datetime.now() - created).total_seconds()))
    except (TypeError, ValueError):
        elapsed = 0
    eta = round(elapsed * (1 - progress) / progress) if progress > 0 and run["state"] == "running" else None
    base_metrics.update({
        "elapsed_seconds": elapsed,
        "eta_seconds": eta,
        "progress_percent": round(progress * 100),
    })
    return {"state": run["state"], "run": run, "scenes": scenes, "metrics": base_metrics}
