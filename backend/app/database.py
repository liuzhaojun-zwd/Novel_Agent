"""Novel_Agent — 数据库初始化与管理（连接池化）"""

import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from app.config import settings

# 模块级持久连接
_db_conn: aiosqlite.Connection | None = None


async def init_db() -> aiosqlite.Connection:
    """初始化数据库表结构并返回持久连接（lifespan 中调用）"""
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    global _db_conn
    _db_conn = await aiosqlite.connect(str(db_path))
    _db_conn.row_factory = aiosqlite.Row
    await _db_conn.execute("PRAGMA journal_mode=WAL")
    await _db_conn.execute("PRAGMA foreign_keys=ON")

    # 创建表
    await _db_conn.executescript("""
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
                feedback TEXT DEFAULT '[]',
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
    # 迁移：幂等添加新列
    for col_sql in [
        "ALTER TABLE jobs ADD COLUMN feedback TEXT DEFAULT '[]'",
    ]:
        try:
            await _db_conn.execute(col_sql)
        except Exception:
            pass

    await _db_conn.commit()
    return _db_conn


async def close_db(conn: aiosqlite.Connection):
    """关闭持久连接（lifespan 退出时调用）"""
    global _db_conn
    if conn:
        await conn.close()
    _db_conn = None


@asynccontextmanager
async def get_db():
    """获取持久连接的上下文管理器（commit/rollback，不再每次 open/close）。"""
    if _db_conn is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    try:
        yield _db_conn
        await _db_conn.commit()
    except Exception:
        await _db_conn.rollback()
        raise


# 兼容旧版
async def get_db_conn() -> aiosqlite.Connection:
    """（已弃用）返回持久连接，请使用 async with get_db() as db: 替代"""
    if _db_conn is None:
        raise RuntimeError("数据库未初始化，请先调用 init_db()")
    return _db_conn