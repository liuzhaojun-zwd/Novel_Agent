"""Novel_Agent — 任务 CRUD 路由（含 Issue 11：设定导入/导出）"""

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
    return job


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str):
    """删除任务"""
    deleted = await svc.delete_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="任务不存在")


# ── Issue 11: 创作设定导出/导入 ──

@router.get("/{job_id}/setup")
async def export_setup(job_id: str):
    """导出创作设定为 JSON"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    setup = {
        "theme": job.theme,
        "topic": job.topic,
        "chapter_count": job.chapter_count,
        "words_per_chapter": job.words_per_chapter,
        "writing_style": job.writing_style,
        "characters": job.characters,
        "world_setting": job.world_setting,
        "narrative_perspective": job.narrative_perspective,
    }
    return {"setup": setup}


@router.post("/import-setup")
async def import_setup(setup: SetupCreate):
    """导入创作设定并创建任务"""
    return await create_job(setup)


# ── Issue 12: 写作反馈 ──

@router.put("/{job_id}/feedback")
async def save_feedback(job_id: str, feedback: list[dict]):
    """保存写作反馈"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    import json
    await svc.update_job_status(
        job_id, job.status,
        feedback=json.dumps(feedback, ensure_ascii=False),
    )
    return {"message": "反馈已保存", "count": len(feedback)}


@router.get("/{job_id}/feedback")
async def get_feedback(job_id: str):
    """获取写作反馈"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"feedback": job.feedback or []}


