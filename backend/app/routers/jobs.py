"""Novel_Agent — 任务 CRUD 路由（含 Issue 11：设定导入/导出）"""

from fastapi import APIRouter, HTTPException, Request
from app.models import SetupCreate, StoryBible, JobResponse, JobListItem, ErrorResponse
from app.services import job_service as svc
from app.services import version_service as version_svc
from app.services.auth_service import default_project_id

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.post("", response_model=dict, status_code=201)
async def create_job(setup: SetupCreate, request: Request):
    """在当前用户的默认项目中创建小说创作任务。"""
    user = request.state.current_user
    project_id = await default_project_id(user["id"])
    job_id = await svc.create_job(
        theme=setup.theme,
        topic=setup.topic,
        chapter_count=setup.chapter_count,
        words_per_chapter=setup.words_per_chapter,
        writing_style=setup.writing_style,
        characters=setup.characters,
        world_setting=setup.world_setting,
        narrative_perspective=setup.narrative_perspective,
        story_bible=setup.story_bible.model_dump() if setup.story_bible else None,
        project_id=project_id,
    )
    return {"job_id": job_id, "status": "pending"}


@router.get("", response_model=list[JobListItem])
async def list_jobs(request: Request):
    """获取当前用户可访问的任务列表。"""
    user = request.state.current_user
    return await svc.list_jobs(user["id"], user["role"] == "admin")


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
        "story_bible": job.story_bible.model_dump() if job.story_bible else None,
    }
    return {"setup": setup}


@router.put("/{job_id}/setup")
async def update_setup(job_id: str, setup: SetupCreate):
    """保存创作设定并创建不可变版本快照。"""
    try:
        version = await version_svc.save_settings(
            job_id, setup.model_dump(), label="创作设定保存",
        )
        return {"message": "创作设定已保存", "version": version}
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/import-setup")
async def import_setup(setup: SetupCreate, request: Request):
    """导入创作设定并创建任务"""
    return await create_job(setup, request)


@router.post("/assist-setup")
async def assist_setup(setup: SetupCreate):
    """根据基础创意生成或补全结构化小说圣经，不创建任务。"""
    import json
    from app.services.llm_adapter import LLMAdapter

    current = setup.story_bible.model_dump() if setup.story_bible else {}
    prompt = f"""你是一位资深小说策划编辑。请根据用户提供的创意补全小说圣经。

题材：{setup.theme}
故事核心：{setup.topic}
写作风格：{setup.writing_style or '未指定'}
叙事视角：{setup.narrative_perspective or '未指定'}
现有世界观：{setup.world_setting or '未指定'}
现有小说圣经：{json.dumps(current, ensure_ascii=False)}

返回 JSON 对象，顶层键必须为 story_bible。story_bible 必须包含：target_audience、tone、core_conflict、theme_expression、selling_points、prohibited_content、character_profiles、character_relationships、world_summary、world_rules、factions、power_system、main_plot、subplots、foreshadowing、key_items、locations。
character_profiles 每项包含 name、role、identity、personality、goal、internal_need、secret、arc、speech_style。数组内容应具体、简洁、可直接指导后续写作；保留用户已有设定，不要输出解释。"""
    try:
        result = await LLMAdapter(
            purpose="story_bible.assist", prompt_id="story_bible.assist",
        ).chat_json([
            {"role": "system", "content": "你是小说策划编辑，只输出符合要求的 JSON。"},
            {"role": "user", "content": prompt},
        ], max_tokens=8192, cache_category="planning")
        bible_data = result.get("story_bible", result)
        bible = StoryBible.model_validate(bible_data)
        return {"story_bible": bible.model_dump()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"AI 完善设定失败：{exc}") from exc


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


