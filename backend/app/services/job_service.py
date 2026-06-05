"""Novel_Agent — 任务管理服务（Job CRUD + 状态管理）"""

import json
from uuid import uuid4
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models import JobResponse, JobListItem, ConsistencyAlert


async def create_job(
    theme: str,
    topic: str,
    chapter_count: int,
    words_per_chapter: int,
    writing_style: Optional[str] = None,
    characters: Optional[list[str]] = None,
    world_setting: Optional[str] = None,
    narrative_perspective: Optional[str] = None,
) -> str:
    """创建新任务，返回 job_id"""
    job_id = uuid4().hex[:12]
    characters_json = json.dumps(characters) if characters else None
    async with get_db() as db:
        await db.execute(
            """INSERT INTO jobs 
            (id, status, theme, topic, chapter_count, words_per_chapter,
             writing_style, characters, world_setting, narrative_perspective)
            VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, theme, topic, chapter_count, words_per_chapter,
             writing_style, characters_json, world_setting, narrative_perspective),
        )
    return job_id


async def get_job(job_id: str) -> Optional[JobResponse]:
    """获取任务详情"""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_job_response(row)


async def list_jobs() -> list[JobListItem]:
    """获取任务列表"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, status, theme, topic, chapter_count, current_chapter, created_at FROM jobs ORDER BY created_at DESC"
        )
        rows = await cursor.fetchall()
        return [
            JobListItem(
                id=r["id"], status=r["status"], theme=r["theme"],
                topic=r["topic"], chapter_count=r["chapter_count"],
                current_chapter=r["current_chapter"], created_at=r["created_at"],
            )
            for r in rows
        ]


async def delete_job(job_id: str) -> bool:
    """删除任务"""
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cursor.rowcount > 0


async def update_job_status(job_id: str, status: str, **extra):
    """更新任务状态"""
    async with get_db() as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sets = ["status = ?", "updated_at = ?"]
        params = [status, now]
        if status == "completed":
            sets.append("completed_at = ?")
            params.append(now)
        for k, v in extra.items():
            sets.append(f"{k} = ?")
            params.append(v if not isinstance(v, (dict, list)) else json.dumps(v))
        params.append(job_id)
        await db.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", params)


async def save_outline(job_id: str, outline: list[dict]):
    """保存大纲"""
    await update_job_status(job_id, status="pending", outline=json.dumps(outline, ensure_ascii=False))
    async with get_db() as db:
        for ch in outline:
            await db.execute(
                """INSERT OR REPLACE INTO chapters 
                (job_id, chapter_number, title, summary, status)
                VALUES (?, ?, ?, ?, 'generating')""",
                (job_id, ch["chapter_number"], ch["title"], ch["summary"]),
            )


async def save_chapter(job_id: str, chapter_number: int, content: str, word_count: int, title: str):
    """保存已完成的章节"""
    async with get_db() as db:
        await db.execute(
            """UPDATE chapters SET content = ?, word_count = ?, status = 'completed'
            WHERE job_id = ? AND chapter_number = ?""",
            (content, word_count, job_id, chapter_number),
        )
        await db.execute(
            "UPDATE jobs SET current_chapter = ?, fail_count = 0, updated_at = datetime('now','localtime') WHERE id = ?",
            (chapter_number, job_id),
        )


async def get_job_chapters(job_id: str) -> list[dict]:
    """获取任务的章节列表"""
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT chapter_number, title, summary, content, word_count, status FROM chapters WHERE job_id = ? ORDER BY chapter_number",
            (job_id,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def add_consistency_alert(job_id: str, chapter_number: int, conflict_name: str):
    """添加一致性告警"""
    async with get_db() as db:
        cursor = await db.execute("SELECT consistency_alerts FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        alerts = json.loads(row["consistency_alerts"]) if row else []
        alerts.append({"chapter_number": chapter_number, "conflict_name": conflict_name})
        await db.execute(
            "UPDATE jobs SET consistency_alerts = ? WHERE id = ?",
            (json.dumps(alerts, ensure_ascii=False), job_id),
        )


def _row_to_job_response(row) -> JobResponse:
    characters_raw = row["characters"]
    characters = json.loads(characters_raw) if characters_raw else None
    outline_raw = row["outline"]
    outline = json.loads(outline_raw) if outline_raw else None
    alerts_raw = row["consistency_alerts"]
    alerts = json.loads(alerts_raw) if alerts_raw else []
    feedback_raw = row["feedback"]
    try:
        feedback = json.loads(feedback_raw) if feedback_raw else []
    except (json.JSONDecodeError, TypeError):
        feedback = []

    return JobResponse(
        id=row["id"],
        status=row["status"],
        theme=row["theme"],
        topic=row["topic"],
        chapter_count=row["chapter_count"],
        words_per_chapter=row["words_per_chapter"],
        writing_style=row["writing_style"],
        characters=characters,
        world_setting=row["world_setting"],
        narrative_perspective=row["narrative_perspective"],
        outline=outline,
        current_chapter=row["current_chapter"],
        fail_count=row["fail_count"],
        consistency_alerts=[ConsistencyAlert(**a) for a in alerts],
        feedback=feedback,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )