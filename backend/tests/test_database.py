"""测试：数据库层 (database.py / job_service.py)"""

import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import get_db, init_db


def _unique_id(prefix="test"):
    import uuid
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

@pytest.mark.asyncio
class TestDatabaseInit:
    """数据库初始化"""

    async def test_init_db_creates_tables(self):
        await init_db()
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = [r["name"] for r in await cursor.fetchall()]
            assert "jobs" in tables
            assert "chapters" in tables

    async def test_insert_and_query_job(self):
        await init_db()
        async with get_db() as db:
            job_id = _unique_id()
            await db.execute(
                """INSERT INTO jobs (id, status, theme, topic, chapter_count, words_per_chapter)
                VALUES (?, 'pending', ?, ?, ?, ?)""",
                (job_id, "玄幻", "修仙之路", 10, 2000),
            )
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            assert row is not None
            assert row["theme"] == "玄幻"
            assert row["status"] == "pending"

    async def test_insert_chapter(self):
        await init_db()
        async with get_db() as db:
            job_id = _unique_id()
            await db.execute(
                "INSERT INTO jobs (id, status, theme, topic, chapter_count, words_per_chapter) VALUES (?, 'pending', ?, ?, ?, ?)",
                (job_id, "科幻", "火星殖民", 5, 3000),
            )
            await db.execute(
                """INSERT INTO chapters (job_id, chapter_number, title, summary, content, word_count, status)
                VALUES (?, ?, ?, ?, ?, ?, 'completed')""",
                (job_id, 1, "启程", "出发去火星", "正文内容...", 1500),
            )
            cursor = await db.execute(
                "SELECT * FROM chapters WHERE job_id = ? AND chapter_number = ?",
                (job_id, 1),
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row["title"] == "启程"
            assert row["word_count"] == 1500

    async def test_get_db_rollback_on_error(self):
        await init_db()
        job_id = _unique_id()
        try:
            async with get_db() as db:
                await db.execute(
                    "INSERT INTO jobs (id, status, theme, topic, chapter_count, words_per_chapter) VALUES (?, 'pending', ?, ?, ?, ?)",
                    (job_id, "测试", "回滚测试", 3, 2000),
                )
                raise ValueError("模拟异常")
        except ValueError:
            pass

        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
            row = await cursor.fetchone()
            assert row is None


@pytest.mark.asyncio
class TestJobService:
    """job_service 基础功能测试"""

    async def test_create_and_get_job(self):
        await init_db()
        from app.services import job_service as svc

        job_id = await svc.create_job(
            theme="仙侠",
            topic="剑道修行",
            chapter_count=20,
            words_per_chapter=2500,
            writing_style="诗意",
            characters=["林夜", "苏晚晴"],
            world_setting="灵气复苏",
            narrative_perspective="third_person",
        )
        assert job_id is not None
        assert len(job_id) == 12

        job = await svc.get_job(job_id)
        assert job is not None
        assert job.theme == "仙侠"
        assert job.status == "pending"
        assert len(job.characters) == 2
        assert "林夜" in job.characters

    async def test_list_jobs(self):
        await init_db()
        from app.services import job_service as svc

        jobs = await svc.list_jobs()
        assert isinstance(jobs, list)

    async def test_save_and_get_chapters(self):
        await init_db()
        from app.services import job_service as svc

        job_id = await svc.create_job("都市", "程序员修仙", 3, 2000)
        chapters_data = [
            {"chapter_number": 1, "title": "第一章", "summary": "开场"},
            {"chapter_number": 2, "title": "第二章", "summary": "发展"},
            {"chapter_number": 3, "title": "第三章", "summary": "高潮"},
        ]
        await svc.save_outline(job_id, chapters_data)

        chapters = await svc.get_job_chapters(job_id)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "第一章"

    async def test_save_chapter_updates_count(self):
        await init_db()
        from app.services import job_service as svc

        job_id = await svc.create_job("悬疑", "密室之谜", 5, 2000)
        await svc.save_outline(job_id, [
            {"chapter_number": 1, "title": "第一案", "summary": "发现尸体"},
        ])
        await svc.save_chapter(job_id, 1, "详细的正文内容...", 1200, "第一案")

        job = await svc.get_job(job_id)
        assert job.current_chapter == 1

    async def test_add_consistency_alert(self):
        await init_db()
        from app.services import job_service as svc

        job_id = await svc.create_job("玄幻", "测试", 3, 2000)
        await svc.add_consistency_alert(job_id, 1, "未知人物")

        job = await svc.get_job(job_id)
        assert len(job.consistency_alerts) == 1
        assert job.consistency_alerts[0].conflict_name == "未知人物"