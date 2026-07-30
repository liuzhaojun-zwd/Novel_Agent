"""Novel_Agent — 大纲相关路由（支持流式生成，带并发保护）"""

import json
import logging

from fastapi import APIRouter, HTTPException
from app.models import OutlineModifyRequest, OutlineSaveRequest
from app.services import job_service as svc

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["outline"])
logger = logging.getLogger("novel_agent.outline")


@router.post("/generate-outline")
async def trigger_generate_outline(job_id: str):
    """将大纲生成提交到带租约和重试的持久队列。"""
    from app.services import task_queue

    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    active = await task_queue.get_active(job_id)
    if active:
        return {
            "message": "生成任务已在队列中", "job_id": job_id,
            "task_id": active["id"], "state": active["state"], "idempotent": True,
        }
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许生成大纲")
    task, created = await task_queue.enqueue(
        "outline.generate", job_id, {}, project_id=job.project_id,
        dedupe_key=f"outline:{job_id}", max_attempts=3, timeout_seconds=900,
    )
    await svc.update_job_status(job_id, "generating_outline")
    return {
        "message": "大纲生成已进入持久队列", "job_id": job_id,
        "task_id": task["id"], "state": task["state"], "idempotent": not created,
    }


@router.get("/outline")
async def get_outline(job_id: str):
    """获取大纲"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.outline:
        raise HTTPException(status_code=404, detail="大纲尚未生成")
    return {"outline": job.outline}


@router.put("/outline/content")
async def save_outline_content(job_id: str, req: OutlineSaveRequest):
    """保存用户在大纲编辑器中直接修改的完整大纲。"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status != "pending":
        raise HTTPException(status_code=400, detail=f"当前状态 {job.status} 不允许编辑大纲")
    if len(req.chapters) != job.chapter_count:
        raise HTTPException(
            status_code=400,
            detail=f"大纲章数应为 {job.chapter_count}，当前为 {len(req.chapters)}",
        )

    outline = [chapter.model_dump() for chapter in req.chapters]
    expected_numbers = list(range(1, job.chapter_count + 1))
    actual_numbers = [chapter["chapter_number"] for chapter in outline]
    if actual_numbers != expected_numbers:
        raise HTTPException(status_code=400, detail="章节编号必须从 1 开始连续且不可重复")

    for chapter in outline:
        chapter["title"] = chapter["title"].strip()
        chapter["summary"] = chapter["summary"].strip()
        if not chapter["title"] or not chapter["summary"]:
            raise HTTPException(status_code=400, detail="章节标题和摘要不能为空")

    await svc.update_outline(job_id, outline)
    logger.info(f"用户大纲保存成功: job={job_id[:8]} {len(outline)}章")
    return {"outline": outline, "message": "大纲已保存"}


@router.put("/outline")
async def modify_outline(job_id: str, req: OutlineModifyRequest):
    """修改大纲（自然语言指令，LLM辅助理解复杂修改）"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.outline:
        raise HTTPException(status_code=400, detail="大纲尚未生成")

    outline = job.outline
    instruction = req.instruction.strip()

    import re
    modified = False

    # ── 层1：简单正则匹配（零成本，不需要LLM调用）──
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

    # ── 层2：LLM辅助修改（正则无法匹配的复杂指令）──
    if not modified:
        from app.services.llm_adapter import LLMAdapter
        llm = LLMAdapter(
            purpose="outline.edit", prompt_id="outline.edit", job_id=job_id,
        )
        outline_str = json.dumps(outline, ensure_ascii=False, indent=2)
        llm_prompt = f"""你是一位小说大纲编辑助手。用户希望修改大纲，请根据用户的指令返回修改后的完整大纲 JSON。

当前大纲：
{outline_str}

用户修改指令：{instruction}

要求：
1. 根据指令修改大纲中对应的章节
2. 保持所有未涉及章节和字段完全不变
3. 每章继续保留 chapter_number、title、summary、pov_character、location、chapter_goal、conflict、turning_point、ending_hook、characters、foreshadowing_add、foreshadowing_resolve、scenes
4. 返回完整修改后的 JSON，不要省略任何章节或结构化章节卡字段
5. 只输出 JSON，不要输出其他内容

输出格式：
{{"chapters": [完整的结构化章节对象, ...]}}"""

        messages = [
            {"role": "system", "content": "你是一位小说大纲编辑助手，擅长根据用户意图修改大纲。请始终输出 JSON。"},
            {"role": "user", "content": llm_prompt},
        ]

        try:
            result = await llm.chat_json(messages, max_tokens=8192)
            new_chapters = result.get("chapters", [])
            if new_chapters and len(new_chapters) == len(outline):
                # 验证每个章节都有必需字段
                for ch in new_chapters:
                    if not all(k in ch for k in ("chapter_number", "title", "summary")):
                        raise ValueError("LLM返回的大纲缺少必需字段")
                outline = new_chapters
                modified = True
                logger.info(f"LLM辅助大纲修改成功: job={job_id[:8]} instruction={instruction[:30]}")
            else:
                logger.warning(f"LLM返回大纲章数不匹配: expected={len(outline)} got={len(new_chapters)}")
        except Exception as e:
            logger.error(f"LLM辅助大纲修改失败: {e}")
            # LLM失败时回退到提示用户用简单格式
            raise HTTPException(
                status_code=400,
                detail=f"无法理解修改指令「{instruction}」，LLM辅助修改也失败了。请尝试更明确的格式，如「第3章标题改为xxx」"
            )

    await svc.update_outline(job_id, outline)

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