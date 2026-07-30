"""Novel_Agent — SSE 进度推送路由（Issue 4：重连时推送初始状态）"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from app.services import job_service as svc
from app.services.progress_tracker import subscribe, unsubscribe

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["stream"])
logger = logging.getLogger("novel_agent.main")


@router.get("/stream")
async def stream_progress(job_id: str):
    """SSE 实时进度推送（连接时先推送初始状态快照）"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    queue = subscribe(job_id)

    async def event_generator():
        try:
            # Issue 4: 连接建立时推送当前状态快照（前端重连后补课）
            chapters = await svc.get_job_chapters(job_id)
            completed = [c for c in chapters if c["status"] == "completed"]
            yield {
                "event": "initial_state",
                "data": {
                    "event": "initial_state",
                    "status": job.status,
                    "current_chapter": job.current_chapter,
                    "chapter_count": job.chapter_count,
                    "outline_ready": bool(job.outline),
                    "completed_count": len(completed),
                    "chapters": [
                        {"chapter_number": c["chapter_number"],
                         "title": c["title"],
                         "word_count": c["word_count"],
                         "status": c["status"]}
                        for c in chapters
                    ],
                    "alerts": [a.model_dump() if hasattr(a, 'model_dump') else a
                              for a in (job.consistency_alerts or [])],
                },
            }

            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {
                        "event": data["event"],
                        "data": data,
                    }
                    if data.get("event") in ("job_complete", "error"):
                        break
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": {"ts": asyncio.get_event_loop().time()}}
        finally:
            unsubscribe(job_id, queue)

    return EventSourceResponse(event_generator())