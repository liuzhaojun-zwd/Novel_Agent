"""Novel_Agent — 导出器（带过期文件清理）"""
import os
import time
from app.database import get_db
from pathlib import Path
from app.config import get_data_dir

# 导出文件最大存活时间（秒）
_EXPORT_FILE_MAX_AGE = 3600  # 1小时后清理


async def _cleanup_old_exports():
    """清理超过存活时间的导出文件"""
    import asyncio
    data_dir = get_data_dir()
    now = time.time()
    for f in data_dir.iterdir():
        if f.is_file() and f.suffix in ('.txt', '.md'):
            if now - f.stat().st_mtime > _EXPORT_FILE_MAX_AGE:
                try:
                    os.remove(str(f))
                except OSError:
                    pass


async def export_job(job_id: str, fmt: str) -> tuple[str, str, str]:
    """
    导出任务作品。
    返回 (文件路径, 文件名, mime_type)
    """
    # 先清理旧导出文件
    await _cleanup_old_exports()
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        job = await cursor.fetchone()
        if not job:
            return "", "", ""

        chapters = await _get_completed_chapters(db, job_id)
        status = job["status"]

        if fmt == "txt":
            content = _build_txt(job, chapters, status)
            ext = "txt"
            mime = "text/plain; charset=utf-8"
        else:
            content = _build_md(job, chapters, status)
            ext = "md"
            mime = "text/markdown; charset=utf-8"

        filename = f"{job['theme']}_{job_id[:8]}.{ext}"
        filepath = str(get_data_dir() / filename)
        Path(filepath).write_text(content, encoding="utf-8")
        return filepath, filename, mime


async def _get_completed_chapters(db, job_id):
    cursor = await db.execute(
        "SELECT chapter_number, title, content FROM chapters "
        "WHERE job_id = ? AND status = 'completed' ORDER BY chapter_number",
        (job_id,),
    )
    return await cursor.fetchall()


def _build_txt(job, chapters, status) -> str:
    lines = _build_header(job, status, len(chapters))
    lines.append("=" * 40)
    lines.append("")
    for ch in chapters:
        lines.append(f"第{ch['chapter_number']}章 {ch['title']}")
        lines.append("")
        lines.append(ch["content"])
        lines.append("")
        lines.append("-" * 30)
        lines.append("")
    return "\n".join(lines)


def _build_md(job, chapters, status) -> str:
    lines = _build_header(job, status, len(chapters))
    lines.append("---")
    lines.append("")
    for ch in chapters:
        lines.append(f"## 第{ch['chapter_number']}章 {ch['title']}")
        lines.append("")
        lines.append(ch["content"])
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


def _build_header(job, status, chapter_count) -> list[str]:
    lines = [
        f"# 《{job['theme']}》",
        "",
        f"**主题：** {job['topic']}",
        f"**总章节：** {job['chapter_count']}",
        f"**已生成：** {chapter_count} 章",
    ]
    if status != "completed":
        lines += [
            "",
            f"> ⚠️ 该作品尚未完成（状态：{status}），仅导出当前已生成的内容。"
            f"如需完整作品请等待生成完成。",
        ]
    lines.append("")
    return lines