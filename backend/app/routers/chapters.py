"""Novel_Agent — 章节路由

带并发锁（Issues 1 & 3）和日志（Issue 2）。
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query, Body
from app.services import job_service as svc
from app.services.chapter_generator import generate_chapters, regenerate_chapter
from app.services.job_locks import acquire_job_lock, release_job_lock, is_task_active, register_task, unregister_task
from app.models import ChapterResponse

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["chapters"])
logger = logging.getLogger("novel_agent.chapter")


@router.get("/chapters", response_model=list[ChapterResponse])
async def list_chapters(job_id: str):
    """获取任务的已生成章节列表"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    chapters = await svc.get_job_chapters(job_id)
    return [
        ChapterResponse(
            chapter_number=c["chapter_number"],
            title=c["title"],
            summary=c["summary"],
            content=c["content"],
            word_count=c["word_count"],
            status=c["status"],
        )
        for c in chapters
    ]


@router.get("/chapters/{chapter_number}", response_model=ChapterResponse)
async def get_chapter(job_id: str, chapter_number: int):
    """获取指定章节详情"""
    chapters = await svc.get_job_chapters(job_id)
    for c in chapters:
        if c["chapter_number"] == chapter_number:
            return ChapterResponse(
                chapter_number=c["chapter_number"],
                title=c["title"],
                summary=c["summary"],
                content=c["content"],
                word_count=c["word_count"],
                status=c["status"],
            )
    raise HTTPException(status_code=404, detail="章节不存在")


@router.put("/chapters/{chapter_number}")
async def update_chapter(
    job_id: str,
    chapter_number: int,
    content: str = Body(..., embed=True),
):
    """Issue 7: 手动编辑章节内容"""
    chapters = await svc.get_job_chapters(job_id)
    target = None
    for c in chapters:
        if c["chapter_number"] == chapter_number:
            target = c
            break
    if not target:
        raise HTTPException(status_code=404, detail="章节不存在")

    word_count = len(content.replace(" ", "").replace("\n", ""))
    await svc.save_chapter(job_id, chapter_number, content, word_count, target["title"])
    logger.info(f"章节编辑: job={job_id[:8]} chapter={chapter_number} {word_count}字")
    return {"message": "章节已更新", "word_count": word_count}


@router.post("/chapters/{chapter_number}/regenerate")
async def regenerate_chapter_endpoint(
    job_id: str,
    chapter_number: int,
    instruction: str = Body("", embed=True),
):
    """Issue 7: 重新生成指定章节（可附带修改指令）"""
    result = await regenerate_chapter(job_id, chapter_number, instruction)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "重新生成失败"))
    logger.info(f"章节重写: job={job_id[:8]} chapter={chapter_number} instr={instruction[:30]}")
    return result


async def _start_generation_internal(job_id: str, up_to: int | None, mode: str):
    """带锁的生成启动/续生（Issues 1 & 3）"""
    # 先获取锁（互斥 start/resume）
    locked = await acquire_job_lock(job_id)
    if not locked:
        raise HTTPException(status_code=429, detail="操作太频繁，请稍后再试")

    try:
        job = await svc.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")

        if mode == "start" and job.status not in ("pending",):
            raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许启动正文生成")
        if mode == "resume" and job.status != "paused":
            raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许续生")

        if not job.outline:
            raise HTTPException(status_code=400, detail="尚未生成并确认大纲")

        # 校验 up_to 范围
        if up_to is not None:
            if up_to < 1 or up_to > job.chapter_count:
                raise HTTPException(status_code=400, detail=f"up_to 须在 1-{job.chapter_count} 之间")
            if up_to <= job.current_chapter:
                raise HTTPException(status_code=400, detail=f"已生成到第 {job.current_chapter} 章")

        # 检查是否已有活跃任务
        if is_task_active(job_id):
            raise HTTPException(status_code=429, detail=f"该任务已有生成线程正在运行，请等待完成")

        # 锁状态
        await svc.update_job_status(job_id, "generating_chapters")

        # 在锁保护内启动后台任务 + 注册（修复竞态窗口）
        task = asyncio.create_task(_run_and_cleanup(job_id, up_to))
        register_task(job_id, task)

    finally:
        release_job_lock(job_id)

    desc = f"最多生成到第{up_to}章" if up_to else "生成剩余全部"
    return {"message": f"正文生成已启动（{desc}）", "job_id": job_id}


async def _run_and_cleanup(job_id: str, up_to: int | None):
    """运行生成任务并在完成后清理注册（Issue 1）"""
    logger.info(f"生成任务开始: job={job_id[:8]} up_to={up_to}")
    try:
        await generate_chapters(job_id, up_to=up_to)
    except Exception as e:
        logger.error(f"生成任务异常: job={job_id[:8]} error={e}", exc_info=True)
        # 尝试将状态置为 failed
        try:
            from app.services.progress_tracker import publish
            await svc.update_job_status(job_id, "failed")
            await publish(job_id, "error", job_id=job_id, status="failed",
                          error=f"后台任务异常: {str(e)}")
        except Exception:
            pass
    finally:
        unregister_task(job_id)
        logger.info(f"生成任务结束: job={job_id[:8]}")


@router.post("/start")
async def start_generation(
    job_id: str,
    up_to: int = Query(None, description="最多生成到第几章，不传则生成全部"),
):
    """启动正文生成（带并发锁）"""
    return await _start_generation_internal(job_id, up_to, mode="start")


@router.post("/resume")
async def resume_generation(
    job_id: str,
    up_to: int = Query(None, description="最多生成到第几章，不传则生成剩余全部"),
):
    """断点续生（带并发锁）"""
    result = await _start_generation_internal(job_id, up_to, mode="resume")
    # 获取 current_chapter 以显示从第几章续生
    job = await svc.get_job(job_id)
    result["from_chapter"] = (job.current_chapter + 1) if job else 1
    return result