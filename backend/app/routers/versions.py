"""Version history API for the creative workbench."""

from fastapi import APIRouter, HTTPException, Query

from app.services import job_service as jobs
from app.services import version_service as versions

router = APIRouter(prefix="/api/jobs/{job_id}", tags=["versions"])


@router.get("/versions")
async def list_resource_versions(
    job_id: str,
    resource_type: str = Query(..., pattern="^(outline|settings|chapter)$"),
    resource_key: str = "",
    limit: int = Query(30, ge=1, le=100),
):
    if not await jobs.get_job(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        items = await versions.list_versions(job_id, resource_type, resource_key, limit)
        current = await versions.get_current_content(job_id, resource_type, resource_key)
        return {"versions": items, "current": current}
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/versions/{version_id}")
async def get_resource_version(job_id: str, version_id: int):
    item = await versions.get_version(job_id, version_id)
    if not item:
        raise HTTPException(status_code=404, detail="版本不存在")
    return item


@router.post("/versions/{version_id}/restore")
async def restore_resource_version(job_id: str, version_id: int):
    try:
        return await versions.restore_version(job_id, version_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc