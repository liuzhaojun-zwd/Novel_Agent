"""Novel_Agent — FastAPI 应用入口"""

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.database import init_db, close_db
from app.log_config import setup_logging, get_logger
from app.config import settings
from app.routers import auth, jobs, outline, chapters, export, stream, versions, settings as settings_router
from app.services.auth_service import authorize_request

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    db = await init_db()
    from app.config import get_llm_config
    from app.services.llm_adapter import close_http_client, init_http_client
    from app.services.task_worker import TaskWorker

    await init_http_client()
    cfg = get_llm_config()
    logger.info(
        "service_started model=%s fast_model=%s quality_model=%s base_url=%s database=%s",
        cfg["model"], cfg["fast_model"], cfg["quality_model"], cfg["base_url"], settings.database_path,
    )
    worker = TaskWorker() if settings.task_worker_enabled else None
    try:
        async with asyncio.TaskGroup() as group:
            if worker:
                group.create_task(worker.run())
            try:
                yield
            finally:
                if worker:
                    worker.stop()
    finally:
        await close_http_client()
        await close_db(db)
        logger.info("service_stopped")


app = FastAPI(
    title="Novel_Agent — 小说创作智能体",
    description="AI 自动写小说系统 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — 允许前端跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:5174",
        "http://127.0.0.1:5173", "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

# Auth endpoints are public; all job resources require a user and project membership.
from app.routers import memory

app.include_router(auth.router)
job_dependencies = [Depends(authorize_request)]
app.include_router(jobs.router, dependencies=job_dependencies)
app.include_router(outline.router, dependencies=job_dependencies)
app.include_router(chapters.router, dependencies=job_dependencies)
app.include_router(versions.router, dependencies=job_dependencies)
app.include_router(memory.router, dependencies=job_dependencies)
app.include_router(export.router, dependencies=job_dependencies)
app.include_router(stream.router, dependencies=job_dependencies)
app.include_router(settings_router.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Novel_Agent"}


# 生产模式：serve 前端构建产物
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    # 必须先挂载 /assets，否则 SPA fallback 会拦截
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")
    
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """SPA fallback — 所有非 API / assets 路径返回 index.html"""
        if full_path.startswith(("api/", "assets/")):
            from fastapi.responses import Response
            return Response(status_code=404)
        from fastapi.responses import FileResponse
        return FileResponse(str(frontend_dist / "index.html"))