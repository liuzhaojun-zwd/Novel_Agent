"""Novel_Agent — 章节路由"""

from fastapi import APIRouter, HTTPException, Query
from app.services import job_service as svc
from app.services.chapter_generator import generate_chapters
from app.models import ChapterResponse

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["chapters"])


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


@router.post("/start")
async def start_generation(
    job_id: str,
    up_to: int = Query(None, description="最多生成到第几章，不传则生成全部"),
):
    """启动正文生成（可指定批次章节数）"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许启动正文生成")
    if not job.outline:
        raise HTTPException(status_code=400, detail="尚未生成并确认大纲")

    # 校验 up_to 范围
    if up_to is not None:
        if up_to < 1 or up_to > job.chapter_count:
            raise HTTPException(status_code=400, detail=f"up_to 须在 1-{job.chapter_count} 之间")
        if up_to <= job.current_chapter:
            raise HTTPException(status_code=400, detail=f"已生成到第 {job.current_chapter} 章，up_to 须大于当前进度")

    # 立即锁状态
    await svc.update_job_status(job_id, "generating_chapters")

    import asyncio
    asyncio.create_task(generate_chapters(job_id, up_to=up_to))

    desc = f"最多生成到第{up_to}章" if up_to else "生成全部章节"
    return {"message": f"正文生成已启动（{desc}）", "job_id": job_id}


@router.post("/resume")
async def resume_generation(
    job_id: str,
    up_to: int = Query(None, description="最多生成到第几章，不传则生成剩余全部"),
):
    """断点续生（可指定批次章节数）"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "paused":
        raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许续生，只有 paused 状态可续生")

    # 校验 up_to 范围
    if up_to is not None:
        if up_to <= job.current_chapter or up_to > job.chapter_count:
            raise HTTPException(
                status_code=400,
                detail=f"已生成到第 {job.current_chapter} 章，up_to 须在 {job.current_chapter + 1}-{job.chapter_count} 之间",
            )

    # 立即锁状态
    await svc.update_job_status(job_id, "generating_chapters")

    import asyncio
    asyncio.create_task(generate_chapters(job_id, up_to=up_to))

    desc = f"最多生成到第{up_to}章" if up_to else "生成剩余全部"
    return {"message": f"断点续生已启动（{desc}）", "job_id": job_id, "from_chapter": job.current_chapter + 1}