"""Novel_Agent — 进度跟踪器"""
from __future__ import annotations
import asyncio
from typing import Optional

# 存储活跃的 SSE 队列：job_id -> list[asyncio.Queue]
_active_streams: dict[str, list[asyncio.Queue]] = {}


def subscribe(job_id: str) -> asyncio.Queue:
    """订阅一个 job 的进度推送，返回一个 Queue"""
    queue: asyncio.Queue = asyncio.Queue()
    if job_id not in _active_streams:
        _active_streams[job_id] = []
    _active_streams[job_id].append(queue)
    return queue


def unsubscribe(job_id: str, queue: asyncio.Queue):
    """取消订阅"""
    if job_id in _active_streams:
        _active_streams[job_id] = [q for q in _active_streams[job_id] if q is not queue]
        if not _active_streams[job_id]:
            del _active_streams[job_id]


async def publish(job_id: str, event_type: str, **data):
    """向所有订阅者推送事件"""
    if job_id not in _active_streams:
        return
    payload = {"event": event_type, **data}
    for queue in _active_streams[job_id]:
        await queue.put(payload)