"""Novel_Agent — 大纲相关路由（支持流式生成）"""

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from app.models import OutlineModifyRequest
from app.services import job_service as svc
from app.services.outline_generator import generate_outline_stream
from app.services.progress_tracker import publish
from app.models import SetupCreate

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["outline"])
logger = logging.getLogger("novel_agent.outline")


@router.post("/generate-outline")
async def trigger_generate_outline(job_id: str):
    """触发大纲生成（后台流式任务）"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许生成大纲")

    # 锁状态
    await svc.update_job_status(job_id, "generating_outline")

    # 后台异步生成大纲
    asyncio.create_task(_run_outline_generation(job_id, job))

    return {"message": "大纲生成已启动", "job_id": job_id}


async def _run_outline_generation(job_id: str, job):
    """后台运行大纲生成并推 SSE"""
    logger.info(f"大纲生成后台任务启动: job={job_id[:8]}")

    # 推初始进度
    await publish(job_id, "outline_progress",
                  message="正在调用 AI 生成大纲...",
                  status="generating_outline")

    try:
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

        # 流式生成（publish_func 直接复用 SSE）
        async def sse_publish(event_type, **data):
            await publish(job_id, event_type, **data)

        outline = await generate_outline_stream(setup, job_id, sse_publish)

        if not outline:
            raise RuntimeError("生成的大纲为空")

        # 保存
        await svc.save_outline(job_id, outline)
        logger.info(f"大纲生成完成: job={job_id[:8]} {len(outline)}章")

    except RuntimeError as e:
        logger.error(f"大纲生成业务错误: job={job_id[:8]} error={e}")
        await svc.update_job_status(job_id, "pending")
        await publish(job_id, "outline_error",
                      error=str(e),
                      message=f"大纲生成失败: {e}")
    except Exception as e:
        logger.error(f"大纲生成系统异常: job={job_id[:8]} error={e}", exc_info=True)
        await svc.update_job_status(job_id, "pending")
        await publish(job_id, "outline_error",
                      error=str(e),
                      message=f"大纲生成失败（系统异常）")


@router.get("/outline")
async def get_outline(job_id: str):
    """获取大纲"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.outline:
        raise HTTPException(status_code=404, detail="大纲尚未生成")
    return {"outline": job.outline}


@router.put("/outline")
async def modify_outline(job_id: str, req: OutlineModifyRequest):
    """修改大纲（自然语言指令）"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.outline:
        raise HTTPException(status_code=400, detail="大纲尚未生成")

    outline = job.outline
    instruction = req.instruction.strip()

    import re
    modified = False

    # 匹配 "第N章标题改为xxx"
    m = re.search(r"第(\d+)章标题改为[：:：]?\s*(.+)", instruction)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(outline):
            outline[idx]["title"] = m.group(2).strip()
            modified = True

    # 匹配 "第N章摘要改为xxx"
    m = re.search(r"第(\d+)章(?:摘要|情节|情节摘要|内容)改为[：:：]?\s*(.+)", instruction)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(outline):
            outline[idx]["summary"] = m.group(2).strip()
            modified = True

    if not modified:
        raise HTTPException(status_code=400, detail="无法解析修改指令，请使用如'第3章标题改为xxx'的格式")

    await svc.update_job_status(job_id, "pending", outline=json.dumps(outline, ensure_ascii=False))

    from app.database import get_db
    async with get_db() as db:
        for ch in outline:
            await db.execute(
                "UPDATE chapters SET title = ?, summary = ? WHERE job_id = ? AND chapter_number = ?",
                (ch["title"], ch["summary"], job_id, ch["chapter_number"]),
            )

    return {"outline": outline, "message": "大纲已更新"}


@router.post("/confirm-outline")
async def confirm_outline(job_id: str):
    """确认大纲，进入正文生成就绪"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.outline:
        raise HTTPException(status_code=400, detail="尚未生成大纲，请先生成大纲")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许确认大纲")

    return {"message": "大纲已确认，准备进入正文生成", "job_id": job_id, "ready": True}