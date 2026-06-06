"""Novel_Agent — 进度跟踪器（带超时清理）"""
from __future__ import annotations
import asyncio
import time
from typing import Optional

# 存储活跃的 SSE 队列：job_id -> list[(queue, timestamp)]
_active_streams: dict[str, list[tuple[asyncio.Queue, float]]] = {}

# 队列最大存活时间（秒），防止客户端断连后永久挂留
_QUEUE_MAX_LIVE_SECONDS = 3600  # 1小时


def subscribe(job_id: str) -> asyncio.Queue:
    """订阅一个 job 的进度推送，返回一个 Queue"""
    queue: asyncio.Queue = asyncio.Queue()
    now = time.time()
    if job_id not in _active_streams:
        _active_streams[job_id] = []
    _active_streams[job_id].append((queue, now))
    # 清理过期的队列
    _cleanup_stale_queues(job_id)
    return queue


def unsubscribe(job_id: str, queue: asyncio.Queue):
    """取消订阅"""
    if job_id in _active_streams:
        _active_streams[job_id] = [(q, ts) for q, ts in _active_streams[job_id] if q is not queue]
        if not _active_streams[job_id]:
            del _active_streams[job_id]


def _cleanup_stale_queues(job_id: str):
    """清理超过最大存活时间的队列"""
    now = time.time()
    if job_id not in _active_streams:
        return
    alive = [(q, ts) for q, ts in _active_streams[job_id] if now - ts < _QUEUE_MAX_LIVE_SECONDS]
    stale_count = len(_active_streams[job_id]) - len(alive)
    if stale_count:
        _active_streams[job_id] = alive
    if not _active_streams[job_id]:
        del _active_streams[job_id]


async def publish(job_id: str, event_type: str, **data):
    """向所有订阅者推送事件"""
    if job_id not in _active_streams:
        return
    payload = {"event": event_type, **data}
    now = time.time()
    alive = []
    for queue, ts in _active_streams[job_id]:
        # 检查队列是否过期
        if now - ts > _QUEUE_MAX_LIVE_SECONDS:
            continue
        try:
            await queue.put(payload)
            alive.append((queue, ts))
        except Exception:
            # 队列已关闭，跳过
            continue
    _active_streams[job_id] = alive
    if not _active_streams[job_id]:
        del _active_streams[job_id]