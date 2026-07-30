"""Persistent version snapshots for outlines, project settings, and chapters."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.database import get_db
from app.models import OutlineChapterInput, SetupCreate

RESOURCE_TYPES = {"outline", "settings", "chapter"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _word_count(value: Any) -> int:
    text = value.get("content", "") if isinstance(value, dict) else _canonical(value)
    return len(str(text).replace(" ", "").replace("\n", ""))


def _validate_resource(resource_type: str, resource_key: str = "") -> str:
    if resource_type not in RESOURCE_TYPES:
        raise ValueError("resource_type 仅支持 outline、settings 或 chapter")
    key = str(resource_key or "")
    if resource_type == "chapter" and (not key.isdigit() or int(key) < 1):
        raise ValueError("章节版本需要有效的 resource_key")
    return key


async def create_version(
    job_id: str,
    resource_type: str,
    content: Any,
    resource_key: str = "",
    label: str = "",
    source: str = "auto",
) -> dict:
    """Create a deduplicated immutable snapshot and return its metadata."""
    key = _validate_resource(resource_type, resource_key)
    digest = _hash(content)
    serialized = _canonical(content)
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT * FROM content_versions
               WHERE job_id = ? AND resource_type = ? AND resource_key = ?
               ORDER BY version_number DESC LIMIT 1""",
            (job_id, resource_type, key),
        )
        latest = await cursor.fetchone()
        if latest and latest["content_hash"] == digest:
            return _version_dict(latest)
        cursor = await db.execute(
            """SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
               FROM content_versions
               WHERE job_id = ? AND resource_type = ? AND resource_key = ?""",
            (job_id, resource_type, key),
        )
        version_number = (await cursor.fetchone())["next_version"]
        cursor = await db.execute(
            """INSERT INTO content_versions
               (job_id, resource_type, resource_key, version_number, content,
                content_hash, label, source, word_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (job_id, resource_type, key, version_number, serialized, digest,
             label, source, _word_count(content)),
        )
        version_id = cursor.lastrowid
        cursor = await db.execute("SELECT * FROM content_versions WHERE id = ?", (version_id,))
        return _version_dict(await cursor.fetchone())


def _version_dict(row, include_content: bool = False) -> dict:
    result = {
        "id": row["id"],
        "job_id": row["job_id"],
        "resource_type": row["resource_type"],
        "resource_key": row["resource_key"],
        "version_number": row["version_number"],
        "content_hash": row["content_hash"],
        "label": row["label"],
        "source": row["source"],
        "word_count": row["word_count"],
        "created_at": row["created_at"],
    }
    if include_content:
        result["content"] = json.loads(row["content"])
    return result


async def get_current_content(job_id: str, resource_type: str, resource_key: str = "") -> Any:
    key = _validate_resource(resource_type, resource_key)
    async with get_db() as db:
        if resource_type == "outline":
            cursor = await db.execute("SELECT outline FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            if not row:
                raise LookupError("任务不存在")
            return json.loads(row["outline"]) if row["outline"] else []
        if resource_type == "settings":
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            if not row:
                raise LookupError("任务不存在")
            return {
                "theme": row["theme"], "topic": row["topic"],
                "chapter_count": row["chapter_count"],
                "words_per_chapter": row["words_per_chapter"],
                "writing_style": row["writing_style"],
                "characters": json.loads(row["characters"]) if row["characters"] else None,
                "world_setting": row["world_setting"],
                "narrative_perspective": row["narrative_perspective"],
                "story_bible": json.loads(row["story_bible"]) if row["story_bible"] else None,
            }
        cursor = await db.execute(
            """SELECT chapter_number, title, summary, content, word_count, status
               FROM chapters WHERE job_id = ? AND chapter_number = ?""",
            (job_id, int(key)),
        )
        row = await cursor.fetchone()
        if not row:
            raise LookupError("章节不存在")
        return dict(row)


async def capture_current(
    job_id: str,
    resource_type: str,
    resource_key: str = "",
    label: str = "",
    source: str = "auto",
) -> dict | None:
    content = await get_current_content(job_id, resource_type, resource_key)
    if resource_type == "outline" and not content:
        return None
    return await create_version(job_id, resource_type, content, resource_key, label, source)


async def list_versions(
    job_id: str, resource_type: str, resource_key: str = "", limit: int = 30,
) -> list[dict]:
    key = _validate_resource(resource_type, resource_key)
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT * FROM content_versions
               WHERE job_id = ? AND resource_type = ? AND resource_key = ?
               ORDER BY version_number DESC LIMIT ?""",
            (job_id, resource_type, key, max(1, min(limit, 100))),
        )
        return [_version_dict(row) for row in await cursor.fetchall()]


async def get_version(job_id: str, version_id: int) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM content_versions WHERE id = ? AND job_id = ?",
            (version_id, job_id),
        )
        row = await cursor.fetchone()
        return _version_dict(row, include_content=True) if row else None


async def save_settings(job_id: str, payload: dict, label: str = "设定保存") -> dict:
    setup = SetupCreate.model_validate(payload)
    data = setup.model_dump()
    async with get_db() as db:
        cursor = await db.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
        if not await cursor.fetchone():
            raise LookupError("任务不存在")
        await db.execute(
            """UPDATE jobs SET theme = ?, topic = ?, chapter_count = ?,
               words_per_chapter = ?, writing_style = ?, characters = ?,
               world_setting = ?, narrative_perspective = ?, story_bible = ?,
               updated_at = datetime('now','localtime') WHERE id = ?""",
            (
                setup.theme, setup.topic, setup.chapter_count, setup.words_per_chapter,
                setup.writing_style,
                json.dumps(setup.characters, ensure_ascii=False) if setup.characters else None,
                setup.world_setting, setup.narrative_perspective,
                json.dumps(data["story_bible"], ensure_ascii=False) if data["story_bible"] else None,
                job_id,
            ),
        )
    return await capture_current(job_id, "settings", label=label, source="user")


async def restore_version(job_id: str, version_id: int) -> dict:
    target = await get_version(job_id, version_id)
    if not target:
        raise LookupError("版本不存在")
    resource_type = target["resource_type"]
    resource_key = target["resource_key"]
    current = await get_current_content(job_id, resource_type, resource_key)
    if _hash(current) == target["content_hash"]:
        return {"restored": target, "changed": False}

    await create_version(
        job_id, resource_type, current, resource_key,
        label="恢复前自动备份", source="restore_backup",
    )
    content = target["content"]
    async with get_db() as db:
        if resource_type == "outline":
            chapters = [OutlineChapterInput.model_validate(item).model_dump() for item in content]
            cursor = await db.execute("SELECT chapter_count FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            if not row or len(chapters) != row["chapter_count"]:
                raise ValueError("该大纲版本与当前目标章数不一致")
            await db.execute(
                "UPDATE jobs SET outline = ?, updated_at = datetime('now','localtime') WHERE id = ?",
                (json.dumps(chapters, ensure_ascii=False), job_id),
            )
            for chapter in chapters:
                await db.execute(
                    """INSERT INTO chapters (job_id, chapter_number, title, summary, status)
                       VALUES (?, ?, ?, ?, 'generating')
                       ON CONFLICT(job_id, chapter_number) DO UPDATE SET
                       title = excluded.title, summary = excluded.summary""",
                    (job_id, chapter["chapter_number"], chapter["title"], chapter["summary"]),
                )
        elif resource_type == "chapter":
            text = str(content.get("content") or "")
            await db.execute(
                """UPDATE chapters SET content = ?, word_count = ?, status = ?
                   WHERE job_id = ? AND chapter_number = ?""",
                (text, _word_count({"content": text}), content.get("status", "completed"),
                 job_id, int(resource_key)),
            )
        else:
            setup = SetupCreate.model_validate(content)
            data = setup.model_dump()
            await db.execute(
                """UPDATE jobs SET theme = ?, topic = ?, chapter_count = ?, words_per_chapter = ?,
                   writing_style = ?, characters = ?, world_setting = ?, narrative_perspective = ?,
                   story_bible = ?, updated_at = datetime('now','localtime') WHERE id = ?""",
                (setup.theme, setup.topic, setup.chapter_count, setup.words_per_chapter,
                 setup.writing_style,
                 json.dumps(setup.characters, ensure_ascii=False) if setup.characters else None,
                 setup.world_setting, setup.narrative_perspective,
                 json.dumps(data["story_bible"], ensure_ascii=False) if data["story_bible"] else None,
                 job_id),
            )
    restored = await capture_current(
        job_id, resource_type, resource_key,
        label=f"恢复至 v{target['version_number']}", source="restore",
    )
    return {"restored": restored, "changed": True}