"""Novel_Agent — 数据库初始化与管理（连接池化）"""

import asyncio
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path
from app.config import settings

# 模块级持久连接；锁保证请求与后台 worker 的事务不交错。
_db_conn: aiosqlite.Connection | None = None
_db_lock = asyncio.Lock()


async def init_db() -> aiosqlite.Connection:
    """初始化数据库表结构并返回持久连接（lifespan 中调用）"""
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    global _db_conn
    if _db_conn is not None:
        await _db_conn.close()
    _db_conn = await aiosqlite.connect(str(db_path))
    _db_conn.row_factory = aiosqlite.Row
    await _db_conn.execute("PRAGMA journal_mode=WAL")
    await _db_conn.execute("PRAGMA foreign_keys=ON")

    # 创建表
    await _db_conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                project_id TEXT,
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
                story_bible TEXT,
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

            CREATE TABLE IF NOT EXISTS generation_runs (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                generation_mode TEXT NOT NULL DEFAULT 'auto'
                    CHECK(generation_mode IN ('auto','collaborative')),
                start_chapter INTEGER NOT NULL,
                target_chapter INTEGER,
                single_chapter INTEGER,
                state TEXT NOT NULL DEFAULT 'running'
                    CHECK(state IN ('running','pause_requested','paused','cancel_requested','cancelled','completed','failed')),
                stage TEXT NOT NULL DEFAULT 'planning',
                current_chapter INTEGER NOT NULL DEFAULT 0,
                current_scene INTEGER NOT NULL DEFAULT 0,
                checkpoint_content TEXT NOT NULL DEFAULT '',
                error TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                UNIQUE(job_id, idempotency_key)
            );

            CREATE TABLE IF NOT EXISTS chapter_scenes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                chapter_number INTEGER NOT NULL,
                scene_index INTEGER NOT NULL,
                goal TEXT NOT NULL DEFAULT '',
                obstacle TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                next_entry TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'planned'
                    CHECK(status IN ('planned','generating','completed','failed')),
                retry_count INTEGER NOT NULL DEFAULT 0,
                plan_version INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                UNIQUE(job_id, chapter_number, scene_index)
            );

            CREATE TABLE IF NOT EXISTS story_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                layer TEXT NOT NULL
                    CHECK(layer IN ('fixed','state','asset')),
                entity_type TEXT NOT NULL,
                entity_key TEXT NOT NULL COLLATE NOCASE,
                attribute TEXT NOT NULL,
                value TEXT NOT NULL,
                chapter_number INTEGER NOT NULL DEFAULT 0,
                source_excerpt TEXT NOT NULL DEFAULT '',
                importance INTEGER NOT NULL DEFAULT 3
                    CHECK(importance BETWEEN 1 AND 5),
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active','superseded')),
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS fact_change_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                existing_memory_id INTEGER NOT NULL,
                proposed_memory TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                resolved_at TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                FOREIGN KEY (existing_memory_id) REFERENCES story_memories(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS content_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                resource_type TEXT NOT NULL
                    CHECK(resource_type IN ('outline','settings','chapter')),
                resource_key TEXT NOT NULL DEFAULT '',
                version_number INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'auto',
                word_count INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE,
                UNIQUE(job_id, resource_type, resource_key, version_number)
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('admin','user')),
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS project_members (
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (project_id, user_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS task_queue (
                id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                job_id TEXT NOT NULL,
                project_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                state TEXT NOT NULL DEFAULT 'queued'
                    CHECK(state IN ('queued','running','retry','cancel_requested','completed','failed','cancelled')),
                priority INTEGER NOT NULL DEFAULT 0,
                dedupe_key TEXT NOT NULL,
                attempt INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                scheduled_at TIMESTAMP NOT NULL,
                claimed_by TEXT,
                lease_expires_at TIMESTAMP,
                heartbeat_at TIMESTAMP,
                timeout_seconds INTEGER NOT NULL DEFAULT 3600,
                cancel_requested_at TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP,
                last_error TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                job_id TEXT,
                project_id TEXT,
                purpose TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                model_tier TEXT NOT NULL,
                prompt_id TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                template_hash TEXT NOT NULL,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                usage_estimated INTEGER NOT NULL DEFAULT 0,
                cache_hit INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                provider_request_id TEXT,
                error_code TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_generation_runs_job
                ON generation_runs(job_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_chapter_scenes_chapter
                ON chapter_scenes(job_id, chapter_number, scene_index);
            CREATE INDEX IF NOT EXISTS idx_story_memories_entity
                ON story_memories(job_id, entity_type, entity_key, status, chapter_number);
            CREATE INDEX IF NOT EXISTS idx_story_memories_layer
                ON story_memories(job_id, layer, status, chapter_number);
            CREATE INDEX IF NOT EXISTS idx_fact_changes_job
                ON fact_change_requests(job_id, status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_content_versions_resource
                ON content_versions(job_id, resource_type, resource_key, version_number DESC);
            CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON user_sessions(expires_at);
            CREATE INDEX IF NOT EXISTS idx_task_due ON task_queue(state, scheduled_at, priority DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_task_active_dedupe
                ON task_queue(task_type, dedupe_key)
                WHERE state IN ('queued','running','retry','cancel_requested');
            CREATE INDEX IF NOT EXISTS idx_llm_calls_job ON llm_calls(job_id, created_at DESC);
        """)
    # 迁移：幂等添加新列
    for col_sql in [
        "ALTER TABLE jobs ADD COLUMN feedback TEXT DEFAULT '[]'",
        "ALTER TABLE jobs ADD COLUMN story_bible TEXT",
        "ALTER TABLE jobs ADD COLUMN project_id TEXT",
    ]:
        try:
            await _db_conn.execute(col_sql)
        except Exception:
            pass

    await _db_conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id, created_at DESC)"
    )
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
    async with _db_lock:
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