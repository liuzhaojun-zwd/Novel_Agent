"""Novel_Agent — 任务级并发锁管理（Issue 1 & 3）

提供：
1. asyncio.Lock 按 job_id 互斥，防止 start/resume 竞态
2. 活跃任务追踪，防止同一 job 多次启动后台生成
3. 自动清理已完成/失败的任务记录
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("novel_agent.locks")

# 按 job_id 的 asyncio.Lock
_locks: dict[str, asyncio.Lock] = {}

# 活跃的后台生成任务
_active_tasks: dict[str, asyncio.Task] = {}


def _get_lock(job_id: str) -> asyncio.Lock:
    """获取或创建 job 级别的锁"""
    if job_id not in _locks:
        _locks[job_id] = asyncio.Lock()
    return _locks[job_id]


async def acquire_job_lock(job_id: str) -> bool:
    """尝试获取 job 锁（非阻塞 + 超时）。
    
    返回是否成功获取锁。
    """
    lock = _get_lock(job_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=5.0)
        return True
    except asyncio.TimeoutError:
        logger.warning(f"获取 job {job_id} 锁超时（另一个操作正在进行中）")
        return False


def release_job_lock(job_id: str):
    """释放 job 锁"""
    lock = _locks.get(job_id)
    if lock and lock.locked():
        lock.release()


def is_task_active(job_id: str) -> bool:
    """检查是否有活跃的生成任务正在运行"""
    task = _active_tasks.get(job_id)
    if task is None:
        return False
    if task.done():
        # 已完成的 task，清理掉
        del _active_tasks[job_id]
        return False
    return True


def register_task(job_id: str, task: asyncio.Task):
    """注册活跃生成任务"""
    existing = _active_tasks.get(job_id)
    if existing and not existing.done():
        logger.warning(f"job {job_id} 已有活跃任务，正在覆盖")
        existing.cancel()
    _active_tasks[job_id] = task
    logger.info(f"已注册 job {job_id} 的生成任务")


def unregister_task(job_id: str):
    """取消注册活跃任务"""
    if job_id in _active_tasks:
        del _active_tasks[job_id]
        logger.info(f"已清除 job {job_id} 的生成任务记录")


async def run_with_lock(job_id: str, fn, *args, **kwargs):
    """在锁保护下执行异步函数。
    
    用法：
        result = await run_with_lock(job_id, my_async_func, arg1, arg2)
    """
    lock = _get_lock(job_id)
    async with lock:
        return await fn(*args, **kwargs)