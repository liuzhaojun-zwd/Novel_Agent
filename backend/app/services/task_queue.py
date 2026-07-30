"""SQLite-backed durable queue with leases, retries, deadlines and cancellation."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from app.database import get_db

logger = logging.getLogger("novel_agent.queue")
ACTIVE_STATES = ("queued", "running", "retry", "cancel_requested")


def _timestamp(offset_seconds: float = 0) -> str:
    return (datetime.utcnow() + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%d %H:%M:%S")


async def enqueue(
    task_type: str,
    job_id: str,
    payload: dict,
    *,
    project_id: str | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 3,
    timeout_seconds: int = 3600,
) -> tuple[dict, bool]:
    task_id = uuid4().hex
    dedupe_key = dedupe_key or f"{task_type}:{job_id}:{uuid4().hex}"
    async with get_db() as db:
        try:
            await db.execute(
                """INSERT INTO task_queue
                   (id, task_type, job_id, project_id, payload_json, state, dedupe_key,
                    max_attempts, timeout_seconds, scheduled_at)
                   VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?)""",
                (task_id, task_type, job_id, project_id, json.dumps(payload), dedupe_key,
                 max_attempts, timeout_seconds, _timestamp()),
            )
            created = True
        except Exception as exc:
            if "UNIQUE" not in str(exc).upper():
                raise
            created = False
        cursor = await db.execute(
            """SELECT * FROM task_queue WHERE id = ? OR
               (task_type = ? AND dedupe_key = ? AND state IN ('queued','running','retry','cancel_requested'))
               ORDER BY created_at DESC LIMIT 1""",
            (task_id, task_type, dedupe_key),
        )
        row = await cursor.fetchone()
    return _decode(row), created
def _decode(row) -> dict | None:
    if not row:
        return None
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json") or "{}")
    return item


async def get_active(job_id: str, task_type: str | None = None) -> dict | None:
    async with get_db() as db:
        sql = "SELECT * FROM task_queue WHERE job_id = ? AND state IN ('queued','running','retry','cancel_requested')"
        params: list = [job_id]
        if task_type:
            sql += " AND task_type = ?"
            params.append(task_type)
        sql += " ORDER BY created_at DESC LIMIT 1"
        cursor = await db.execute(sql, params)
        return _decode(await cursor.fetchone())


async def claim(worker_id: str, lease_seconds: int = 90) -> dict | None:
    """Atomically claim one due task, including a task whose worker lease expired."""
    now = _timestamp()
    lease = _timestamp(lease_seconds)
    async with get_db() as db:
        cursor = await db.execute(
            """UPDATE task_queue SET state = 'running', claimed_by = ?, attempt = attempt + 1,
                   started_at = COALESCE(started_at, ?), heartbeat_at = ?, lease_expires_at = ?,
                   updated_at = ?
               WHERE id = (
                   SELECT id FROM task_queue
                   WHERE ((state IN ('queued','retry') AND scheduled_at <= ? AND cancel_requested_at IS NULL)
                          OR (state IN ('running','cancel_requested') AND lease_expires_at < ?))
                   ORDER BY priority DESC, scheduled_at, created_at LIMIT 1
               )
               RETURNING *""",
            (worker_id, now, now, lease, now, now, now),
        )
        return _decode(await cursor.fetchone())


async def heartbeat(task_id: str, worker_id: str, lease_seconds: int = 90) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            """UPDATE task_queue SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
               WHERE id = ? AND claimed_by = ? AND state IN ('running','cancel_requested')""",
            (_timestamp(), _timestamp(lease_seconds), _timestamp(), task_id, worker_id),
        )
        return cursor.rowcount > 0


async def complete(task_id: str, worker_id: str) -> None:
    async with get_db() as db:
        await db.execute(
            """UPDATE task_queue SET state = 'completed', finished_at = ?, lease_expires_at = NULL,
               updated_at = ? WHERE id = ? AND claimed_by = ?""",
            (_timestamp(), _timestamp(), task_id, worker_id),
        )
async def fail(task: dict, worker_id: str, error: str) -> str:
    retry = task["attempt"] < task["max_attempts"]
    state = "retry" if retry else "failed"
    delay = min(300, 2 ** max(1, task["attempt"])) if retry else 0
    async with get_db() as db:
        await db.execute(
            """UPDATE task_queue SET state = ?, last_error = ?, scheduled_at = ?,
               claimed_by = NULL, lease_expires_at = NULL, finished_at = CASE WHEN ? = 'failed' THEN ? ELSE NULL END,
               updated_at = ? WHERE id = ? AND claimed_by = ?""",
            (state, error[:4000], _timestamp(delay), state, _timestamp(), _timestamp(), task["id"], worker_id),
        )
    logger.warning(
        "task_failed task_id=%s type=%s attempt=%s state=%s error=%s",
        task["id"], task["task_type"], task["attempt"], state, error,
    )
    return state


async def request_cancel(job_id: str) -> bool:
    now = _timestamp()
    async with get_db() as db:
        cursor = await db.execute(
            """UPDATE task_queue SET
                   state = CASE WHEN state IN ('queued','retry') THEN 'cancelled' ELSE 'cancel_requested' END,
                   cancel_requested_at = ?,
                   finished_at = CASE WHEN state IN ('queued','retry') THEN ? ELSE finished_at END,
                   updated_at = ?
               WHERE job_id = ? AND state IN ('queued','running','retry','cancel_requested')""",
            (now, now, now, job_id),
        )
        return cursor.rowcount > 0


async def cancellation_requested(task_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT cancel_requested_at FROM task_queue WHERE id = ?", (task_id,),
        )
        row = await cursor.fetchone()
        return bool(row and row["cancel_requested_at"])


async def mark_cancelled(task_id: str, worker_id: str) -> None:
    async with get_db() as db:
        await db.execute(
            """UPDATE task_queue SET state = 'cancelled', finished_at = ?, lease_expires_at = NULL,
               updated_at = ? WHERE id = ? AND claimed_by = ?""",
            (_timestamp(), _timestamp(), task_id, worker_id),
        )


async def metrics(job_id: str) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT state, COUNT(*) AS count, SUM(attempt) AS attempts,
               MAX(heartbeat_at) AS last_heartbeat FROM task_queue WHERE job_id = ? GROUP BY state""",
            (job_id,),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
    return {"by_state": rows, "total_attempts": sum(row["attempts"] or 0 for row in rows)}
