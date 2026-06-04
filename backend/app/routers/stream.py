"""Novel_Agent — SSE 进度推送路由"""

import asyncio
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from app.services import job_service as svc
from app.services.progress_tracker import subscribe, unsubscribe

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["stream"])


@router.get("/stream")
async def stream_progress(job_id: str):
    """SSE 实时进度推送"""
    job = await svc.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    queue = subscribe(job_id)

    async def event_generator():
        try:
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
                    # 发送心跳保持连接
                    yield {"event": "heartbeat", "data": {"ts": asyncio.get_event_loop().time()}}
        finally:
            unsubscribe(job_id, queue)

    return EventSourceResponse(event_generator())