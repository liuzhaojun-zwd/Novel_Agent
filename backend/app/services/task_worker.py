"""Durable task worker; can run in-process or as a separate worker process."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
from contextlib import suppress

from app.models import SetupCreate
from app.services import job_service as jobs
from app.services import task_queue
from app.services.progress_tracker import publish
from app.services.task_context import current_job_id, current_project_id, current_task_id

logger = logging.getLogger("novel_agent.worker")


class TaskWorker:
    def __init__(self, worker_id: str | None = None, poll_seconds: float = 0.5):
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.poll_seconds = poll_seconds
        self._stopping = asyncio.Event()

    def stop(self) -> None:
        self._stopping.set()

    async def run(self) -> None:
        logger.info("worker_started worker_id=%s", self.worker_id)
        while not self._stopping.is_set():
            task = await task_queue.claim(self.worker_id)
            if not task:
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=self.poll_seconds)
                continue
            await self._process(task)
        logger.info("worker_stopped worker_id=%s", self.worker_id)

    async def _process(self, task: dict) -> None:
        tokens = (
            current_task_id.set(task["id"]),
            current_job_id.set(task["job_id"]),
            current_project_id.set(task.get("project_id")),
        )
        error: BaseException | None = None
        done = asyncio.Event()

        async def heartbeat_loop():
            while not done.is_set():
                try:
                    await asyncio.wait_for(done.wait(), timeout=30)
                except asyncio.TimeoutError:
                    if not await task_queue.heartbeat(task["id"], self.worker_id):
                        raise RuntimeError("任务租约已丢失")

        async def execute():
            try:
                async with asyncio.timeout(task["timeout_seconds"]):
                    await self._dispatch(task)
            finally:
                done.set()

        try:
            try:
                async with asyncio.TaskGroup() as group:
                    group.create_task(heartbeat_loop())
                    group.create_task(execute())
            except* BaseException as group_error:
                error = group_error.exceptions[0]

            if error:
                raise error
            if await task_queue.cancellation_requested(task["id"]):
                await task_queue.mark_cancelled(task["id"], self.worker_id)
            else:
                await task_queue.complete(task["id"], self.worker_id)
            logger.info(
                "task_completed task_id=%s type=%s job_id=%s attempt=%s",
                task["id"], task["task_type"], task["job_id"], task["attempt"],
            )
        except BaseException as exc:
            if await task_queue.cancellation_requested(task["id"]):
                await task_queue.mark_cancelled(task["id"], self.worker_id)
            else:
                state = await task_queue.fail(task, self.worker_id, str(exc))
                if state == "failed":
                    await self._terminal_failure(task, exc)
        finally:
            current_task_id.reset(tokens[0])
            current_job_id.reset(tokens[1])
            current_project_id.reset(tokens[2])
    async def _dispatch(self, task: dict) -> None:
        if await task_queue.cancellation_requested(task["id"]):
            raise asyncio.CancelledError("任务已取消")
        if task["task_type"] == "outline.generate":
            await self._generate_outline(task)
        elif task["task_type"] == "chapter.generate":
            await self._generate_chapters(task)
        else:
            raise RuntimeError(f"未知任务类型: {task['task_type']}")

    async def _generate_outline(self, task: dict) -> None:
        from app.services.outline_generator import generate_outline_stream

        job = await jobs.get_job(task["job_id"])
        if not job:
            raise RuntimeError("任务不存在")
        await publish(
            job.id, "outline_progress", message="正在调用 AI 生成大纲...",
            status="generating_outline",
        )
        setup = SetupCreate(
            theme=job.theme, topic=job.topic, chapter_count=job.chapter_count,
            words_per_chapter=job.words_per_chapter, writing_style=job.writing_style,
            characters=job.characters, world_setting=job.world_setting,
            narrative_perspective=job.narrative_perspective, story_bible=job.story_bible,
        )

        async def tracked_publish(event_type: str, **data):
            if await task_queue.cancellation_requested(task["id"]):
                raise asyncio.CancelledError("任务已取消")
            await publish(job.id, event_type, **data)

        outline = await generate_outline_stream(setup, job.id, tracked_publish)
        if not outline:
            raise RuntimeError("生成的大纲为空")
        await jobs.save_outline(job.id, outline)
        await publish(
            job.id, "outline_done", outline=outline,
            message=f"大纲生成成功（共 {len(outline)} 章）",
        )

    async def _generate_chapters(self, task: dict) -> None:
        from app.services.chapter_generator import generate_chapters

        payload = task["payload"]
        await generate_chapters(
            task["job_id"], up_to=payload.get("up_to"), run_id=payload["run_id"],
            generation_mode=payload.get("generation_mode", "auto"),
            single_chapter=payload.get("single_chapter"),
        )

    async def _terminal_failure(self, task: dict, exc: BaseException) -> None:
        if task["task_type"] == "outline.generate":
            await jobs.update_job_status(task["job_id"], "pending")
            await publish(
                task["job_id"], "outline_error", error=str(exc),
                message="大纲生成失败，任务重试已耗尽",
            )
            return
        run_id = task["payload"].get("run_id")
        if run_id:
            await jobs.update_generation_run(run_id, state="failed", error=str(exc))
        await jobs.update_job_status(task["job_id"], "failed")
        await publish(task["job_id"], "error", status="failed", error=str(exc))
