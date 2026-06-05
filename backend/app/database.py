"""Novel_Agent — 数据库初始化与管理"""

import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from app.config import settings


async def _get_conn() -> aiosqlite.Connection:
    """创建新数据库连接（低层函数）"""
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


@asynccontextmanager
async def get_db():
    """安全的数据库连接上下文管理器。
    
    用法：
        async with get_db() as db:
            cursor = await db.execute(...)
    """
    db = await _get_conn()
    try:
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


# 兼容旧版直接调用（内部仍走上下文管理器）
async def get_db_conn() -> aiosqlite.Connection:
    """（已弃用）临时连接，请使用 async with get_db() as db: 替代"""
    return await _get_conn()


async def init_db():
    """初始化数据库表结构"""
    async with get_db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','generating_outline','generating_chapters','paused','completed','failed')),
                theme TEXT NOT NULL,
                topic TEXT NOT NULL,
                chapter_count INTEGER NOT NULL CHECK(chapter_count >= 1 AND chapter_count <= 1000),
                words_per_chapter INTEGER NOT NULL CHECK(words_per_chapter >= 2000 AND words_per_chapter <= 20000),
                writing_style TEXT,
                characters TEXT,
                world_setting TEXT,
                narrative_perspective TEXT,
                outline TEXT,
                current_chapter INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                consistency_alerts TEXT DEFAULT '[]',
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                completed_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                chapter_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                word_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'generating'
                    CHECK(status IN ('generating','completed','failed')),
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                UNIQUE(job_id, chapter_number)
            );
        """)