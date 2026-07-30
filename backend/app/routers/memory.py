"""长篇记忆、重要事实变更审批与影响分析 API。"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models import FactChangeDecision, SetupCreate
from app.services import job_service as jobs
from app.services import memory_service as memory
from app.services.llm_adapter import LLMAdapter

router = APIRouter(prefix="/api/jobs/{job_id}/memory", tags=["memory"])


def _setup(job) -> SetupCreate:
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


async def _job_or_404(job_id: str):
    job = await jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("")
async def get_memories(
    job_id: str,
    entity: Optional[str] = None,
    layer: Optional[str] = Query(None, pattern="^(fixed|state|asset)$"),
    status: str = Query("active", pattern="^(active|superseded)$"),
    limit: int = Query(200, ge=1, le=500),
):
    job = await _job_or_404(job_id)
    await memory.ensure_fixed_memories(job_id, _setup(job))
    return {"memories": await memory.list_memories(job_id, entity, layer, status, limit)}


@router.get("/context/{chapter_number}")
async def get_memory_context(job_id: str, chapter_number: int):
    job = await _job_or_404(job_id)
    chapters = await jobs.get_job_chapters(job_id)
    chapter = next((item for item in chapters if item["chapter_number"] == chapter_number), None)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    outline = next(
        (item for item in (job.outline or []) if item.get("chapter_number") == chapter_number),
        {},
    )
    summaries = [
        f"第{item['chapter_number']}章（{item['title']}）：{item['summary']}"
        for item in chapters
        if item["chapter_number"] < chapter_number and item["status"] == "completed"
    ]
    return await memory.build_five_layer_context(
        job_id, _setup(job), {**chapter, **outline}, summaries,
    )


@router.post("/extract/{chapter_number}")
async def extract_memory(job_id: str, chapter_number: int):
    job = await _job_or_404(job_id)
    chapters = await jobs.get_job_chapters(job_id)
    chapter = next((item for item in chapters if item["chapter_number"] == chapter_number), None)
    if not chapter or not chapter["content"].strip():
        raise HTTPException(status_code=400, detail="章节不存在或尚无正文")
    try:
        return await memory.extract_chapter_memories(
            LLMAdapter(), job_id, _setup(job), chapter_number,
            chapter["title"], chapter["summary"], chapter["content"],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"记忆提取失败：{exc}") from exc


@router.get("/changes")
async def get_fact_changes(
    job_id: str,
    status: Optional[str] = Query(None, pattern="^(pending|approved|rejected)$"),
):
    await _job_or_404(job_id)
    return {"changes": await memory.list_fact_changes(job_id, status)}


@router.get("/changes/{change_id}/impact")
async def get_change_impact(job_id: str, change_id: int):
    await _job_or_404(job_id)
    result = await memory.analyze_change_impact(job_id, change_id)
    if not result:
        raise HTTPException(status_code=404, detail="事实变更不存在")
    return result


@router.post("/changes/{change_id}/resolve")
async def resolve_change(job_id: str, change_id: int, decision: FactChangeDecision):
    await _job_or_404(job_id)
    result = await memory.resolve_fact_change(job_id, change_id, decision.approve)
    if not result:
        raise HTTPException(status_code=404, detail="事实变更不存在")
    return result
