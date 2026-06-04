"""Novel_Agent — 任务 CRUD 路由"""

from fastapi import APIRouter, HTTPException
from app.models import SetupCreate, JobResponse, JobListItem, ErrorResponse
from app.services import job_service as svc

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=dict, status_code=201)
async def create_job(setup: SetupCreate):
    """创建小说创作任务"""
    job_id = await svc.create_job(
        theme=setup.theme,
        topic=setup.topic,
        chapter_count=setup.chapter_count,
        words_per_chapter=setup.words_per_chapter,
        writing_style=setup.writing_style,
        characters=setup.characters,
        world_setting=setup.world_setting,
        narrative_perspective=setup.narrative_perspective,
    )
    return {"job_id": job_id, "status": "pending"}


@router.get("", response_model=list[JobListItem])
async def list_jobs():
    """获取任务列表"""
    return await svc.list_jobs()


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    """获取任务详情"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 组装章节列表
    chapters = await svc.get_job_chapters(job_id)
    return job


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str):
    """删除任务"""
    deleted = await svc.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="任务不存在")