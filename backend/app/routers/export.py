"""Novel_Agent — 导出路由"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.services.exporter import export_job

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["export"])


@router.get("/export")
async def export_job_endpoint(job_id: str, format: str = "md"):
    """导出作品文件"""
    if format not in ("txt", "md"):
        raise HTTPException(status_code=400, detail="不支持的格式，支持 txt 和 md")

    filepath, filename, mime = await export_job(job_id, format)
    if not filepath:
        raise HTTPException(status_code=404, detail="任务不存在")

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type=mime,
    )