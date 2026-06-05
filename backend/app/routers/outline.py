"""Novel_Agent — 大纲相关路由"""

from fastapi import APIRouter, HTTPException
from app.models import OutlineModifyRequest
from app.services import job_service as svc
from app.services.outline_generator import generate_outline
from app.models import SetupCreate

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["outline"])


@router.post("/generate-outline")
async def trigger_generate_outline(job_id: str):
    """触发大纲生成"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许生成大纲")

    await svc.update_job_status(job_id, "generating_outline")

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
        outline = await generate_outline(setup)
        await svc.save_outline(job_id, outline)
        return {"outline": outline, "message": "大纲生成成功"}
    except Exception as e:
        await svc.update_job_status(job_id, "pending")
        raise HTTPException(status_code=500, detail=f"大纲生成失败: {str(e)}")


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

    # 简单的自然语言指令解析
    import re
    modified = False

    # 匹配 "第N章标题改为xxx"
    m = re.search(r"第(\d+)章标题改为[：:：]?\s*(.+)", instruction)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(outline):
            outline[idx]["title"] = m.group(2).strip()
            modified = True

    # 匹配 "第N章摘要改为xxx" 或 "第N章情节改为xxx"
    m = re.search(r"第(\d+)章(?:摘要|情节|情节摘要|内容)改为[：:：]?\s*(.+)", instruction)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(outline):
            outline[idx]["summary"] = m.group(2).strip()
            modified = True

    # 匹配 "第N章替换为" 或 "重写第N章"
    m = re.search(r"重写第(\d+)章[：:：]?\s*标题[：:：]?\s*(.+?)[，,。]?\s*摘要[：:：]?\s*(.+)", instruction)
    if not m:
        m = re.search(r"把第(\d+)章(.+?)改为(.+)", instruction)
    if m:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(outline):
            if "标题" in instruction:
                outline[idx]["title"] = instruction.split("标题")[-1].strip()
            if "摘要" in instruction or "情节" in instruction:
                outline[idx]["summary"] = instruction.split("摘要")[-1].strip() if "摘要" in instruction else instruction.split("情节")[-1].strip()
            modified = True

    if not modified:
        raise HTTPException(status_code=400, detail="无法解析修改指令，请使用如'第3章标题改为xxx'的格式")

    import json
    await svc.update_job_status(job_id, "pending", outline=json.dumps(outline, ensure_ascii=False))

    # 同时更新 chapters 表中的标题和摘要
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