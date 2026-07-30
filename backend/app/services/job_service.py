"""Novel_Agent — 任务管理服务（Job CRUD + 状态管理）"""

import json
from uuid import uuid4
from typing import Optional
from datetime import datetime

from app.database import get_db
from app.models import JobResponse, JobListItem, ConsistencyAlert


async def _capture_version(
    job_id: str, resource_type: str, resource_key: str = "", label: str = "",
):
    """Keep persistence paths versioned without coupling callers to version APIs."""
    from app.services.version_service import capture_current

    await capture_current(job_id, resource_type, resource_key, label=label)


async def create_job(
    theme: str,
    topic: str,
    chapter_count: int,
    words_per_chapter: int,
    writing_style: Optional[str] = None,
    characters: Optional[list[str]] = None,
    world_setting: Optional[str] = None,
    narrative_perspective: Optional[str] = None,
    story_bible: Optional[dict] = None,
    project_id: Optional[str] = None,
) -> str:
    """创建新任务，返回 job_id。"""
    job_id = uuid4().hex[:12]
    characters_json = json.dumps(characters, ensure_ascii=False) if characters else None
    story_bible_json = json.dumps(story_bible, ensure_ascii=False) if story_bible else None
    async with get_db() as db:
        await db.execute(
            """INSERT INTO jobs
            (id, project_id, status, theme, topic, chapter_count, words_per_chapter,
             writing_style, characters, world_setting, narrative_perspective, story_bible)
            VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, project_id, theme, topic, chapter_count, words_per_chapter,
             writing_style, characters_json, world_setting, narrative_perspective,
             story_bible_json),
        )
    await _capture_version(job_id, "settings", label="初始创作设定")
    return job_id


async def get_job(job_id: str) -> Optional[JobResponse]:
    """获取任务详情"""
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        return _row_to_job_response(row)


async def list_jobs(user_id: str | None = None, is_admin: bool = False) -> list[JobListItem]:
    """获取当前用户可访问的任务列表。"""
    async with get_db() as db:
        if user_id and not is_admin:
            cursor = await db.execute(
                """SELECT j.id, j.status, j.theme, j.topic, j.chapter_count,
                          j.current_chapter, j.created_at FROM jobs j
                   JOIN project_members pm ON pm.project_id = j.project_id
                   WHERE pm.user_id = ? ORDER BY j.created_at DESC""",
                (user_id,),
            )
        else:
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
    """保存新生成的大纲并初始化章节。"""
    await update_job_status(job_id, status="pending", outline=json.dumps(outline, ensure_ascii=False))
    async with get_db() as db:
        for ch in outline:
            await db.execute(
                """INSERT OR REPLACE INTO chapters
                (job_id, chapter_number, title, summary, status)
                VALUES (?, ?, ?, ?, 'generating')""",
                (job_id, ch["chapter_number"], ch["title"], ch["summary"]),
            )
    await _capture_version(job_id, "outline", label="AI 生成大纲")


async def update_outline(job_id: str, outline: list[dict]):
    """持久化用户编辑的大纲，同时保留已有章节正文和生成状态。"""
    await update_job_status(
        job_id,
        status="pending",
        outline=json.dumps(outline, ensure_ascii=False),
    )
    async with get_db() as db:
        for ch in outline:
            await db.execute(
                """INSERT INTO chapters
                (job_id, chapter_number, title, summary, status)
                VALUES (?, ?, ?, ?, 'generating')
                ON CONFLICT(job_id, chapter_number) DO UPDATE SET
                    title = excluded.title,
                    summary = excluded.summary""",
                (job_id, ch["chapter_number"], ch["title"], ch["summary"]),
            )
    await _capture_version(job_id, "outline", label="大纲保存")


async def save_chapter(job_id: str, chapter_number: int, content: str, word_count: int, title: str):
    """保存已完成章节，并将 current_chapter 更新为连续完成的最后一章。"""
    async with get_db() as db:
        await db.execute(
            """UPDATE chapters SET content = ?, word_count = ?, status = 'completed'
            WHERE job_id = ? AND chapter_number = ?""",
            (content, word_count, job_id, chapter_number),
        )
        cursor = await db.execute(
            "SELECT chapter_number, status FROM chapters WHERE job_id = ? ORDER BY chapter_number",
            (job_id,),
        )
        contiguous = 0
        for row in await cursor.fetchall():
            if row["chapter_number"] != contiguous + 1 or row["status"] != "completed":
                break
            contiguous = row["chapter_number"]
        await db.execute(
            "UPDATE jobs SET current_chapter = ?, fail_count = 0, updated_at = datetime('now','localtime') WHERE id = ?",
            (contiguous, job_id),
        )
    await _capture_version(
        job_id, "chapter", str(chapter_number), label=f"第{chapter_number}章保存",
    )


async def save_chapter_checkpoint(job_id: str, chapter_number: int, content: str):
    """保存尚未合并完成的章节预览，不改变完成状态。"""
    word_count = len(content.replace(" ", "").replace("\n", ""))
    async with get_db() as db:
        await db.execute(
            """UPDATE chapters SET content = ?, word_count = ?, status = 'generating'
            WHERE job_id = ? AND chapter_number = ? AND status != 'completed'""",
            (content, word_count, job_id, chapter_number),
        )


async def get_chapter_scenes(job_id: str, chapter_number: int) -> list[dict]:
    """按顺序读取章节场景 checkpoint。"""
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT scene_index, goal, obstacle, action, result, next_entry,
                      content, status, retry_count, plan_version
               FROM chapter_scenes
               WHERE job_id = ? AND chapter_number = ? ORDER BY scene_index""",
            (job_id, chapter_number),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def save_scene_plan(job_id: str, chapter_number: int, scenes: list[dict]):
    """幂等保存场景规划；已有内容和完成状态不会被覆盖。"""
    async with get_db() as db:
        for index, scene in enumerate(scenes, start=1):
            await db.execute(
                """INSERT INTO chapter_scenes
                   (job_id, chapter_number, scene_index, goal, obstacle, action, result, next_entry)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(job_id, chapter_number, scene_index) DO UPDATE SET
                       goal = excluded.goal,
                       obstacle = excluded.obstacle,
                       action = excluded.action,
                       result = excluded.result,
                       next_entry = excluded.next_entry,
                       updated_at = datetime('now','localtime')""",
                (
                    job_id, chapter_number, index,
                    scene.get("goal", ""), scene.get("obstacle", ""),
                    scene.get("action", ""), scene.get("result", ""),
                    scene.get("next_entry", ""),
                ),
            )


async def save_scene_checkpoint(
    job_id: str,
    chapter_number: int,
    scene_index: int,
    content: str,
    status: str = "generating",
    increment_retry: bool = False,
):
    """覆盖保存一个场景；恢复时继续该场景而不会重写已完成场景。"""
    retry_sql = ", retry_count = retry_count + 1" if increment_retry else ""
    async with get_db() as db:
        await db.execute(
            f"""UPDATE chapter_scenes
                SET content = ?, status = ?, updated_at = datetime('now','localtime'){retry_sql}
                WHERE job_id = ? AND chapter_number = ? AND scene_index = ?""",
            (content, status, job_id, chapter_number, scene_index),
        )


async def create_generation_run(
    job_id: str,
    idempotency_key: str,
    generation_mode: str,
    start_chapter: int,
    target_chapter: Optional[int] = None,
    single_chapter: Optional[int] = None,
) -> tuple[dict, bool]:
    """创建幂等生成运行；返回 (run, 是否新建)。"""
    run_id = uuid4().hex[:16]
    async with get_db() as db:
        cursor = await db.execute(
            """INSERT OR IGNORE INTO generation_runs
               (id, job_id, idempotency_key, generation_mode, start_chapter,
                target_chapter, single_chapter, state, current_chapter)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?)""",
            (
                run_id, job_id, idempotency_key, generation_mode, start_chapter,
                target_chapter, single_chapter, max(0, start_chapter - 1),
            ),
        )
        created = cursor.rowcount > 0
        cursor = await db.execute(
            "SELECT * FROM generation_runs WHERE job_id = ? AND idempotency_key = ?",
            (job_id, idempotency_key),
        )
        row = await cursor.fetchone()
        return dict(row), created


async def get_generation_run(run_id: str) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM generation_runs WHERE id = ?", (run_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_generation_run_by_key(job_id: str, idempotency_key: str) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM generation_runs WHERE job_id = ? AND idempotency_key = ?",
            (job_id, idempotency_key),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_latest_generation_run(job_id: str, states: Optional[tuple[str, ...]] = None) -> Optional[dict]:
    async with get_db() as db:
        sql = "SELECT * FROM generation_runs WHERE job_id = ?"
        params: list = [job_id]
        if states:
            sql += f" AND state IN ({','.join('?' for _ in states)})"
            params.extend(states)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
        cursor = await db.execute(sql, params)
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_generation_run(run_id: str, **fields):
    """更新生成运行；字段白名单避免动态 SQL 注入。"""
    allowed = {
        "generation_mode", "target_chapter", "single_chapter", "state", "stage",
        "current_chapter", "current_scene", "checkpoint_content", "error",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    sets = [f"{key} = ?" for key in updates]
    params = list(updates.values())
    sets.append("updated_at = datetime('now','localtime')")
    params.append(run_id)
    async with get_db() as db:
        await db.execute(
            f"UPDATE generation_runs SET {', '.join(sets)} WHERE id = ?",
            params,
        )


async def resume_generation_run(
    run_id: str,
    generation_mode: str,
    target_chapter: Optional[int],
    single_chapter: Optional[int],
):
    await update_generation_run(
        run_id,
        generation_mode=generation_mode,
        target_chapter=target_chapter,
        single_chapter=single_chapter,
        state="running",
        error=None,
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
    story_bible_raw = row["story_bible"]
    try:
        story_bible = json.loads(story_bible_raw) if story_bible_raw else None
    except (json.JSONDecodeError, TypeError):
        story_bible = None
    alerts_raw = row["consistency_alerts"]
    alerts = json.loads(alerts_raw) if alerts_raw else []
    feedback_raw = row["feedback"]
    try:
        feedback = json.loads(feedback_raw) if feedback_raw else []
    except (json.JSONDecodeError, TypeError):
        feedback = []

    return JobResponse(
        id=row["id"],
        project_id=row["project_id"],
        status=row["status"],
        theme=row["theme"],
        topic=row["topic"],
        chapter_count=row["chapter_count"],
        words_per_chapter=row["words_per_chapter"],
        writing_style=row["writing_style"],
        characters=characters,
        world_setting=row["world_setting"],
        narrative_perspective=row["narrative_perspective"],
        story_bible=story_bible,
        outline=outline,
        current_chapter=row["current_chapter"],
        fail_count=row["fail_count"],
        consistency_alerts=[ConsistencyAlert(**a) for a in alerts],
        feedback=feedback,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )