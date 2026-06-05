"""Novel_Agent — FastAPI 应用入口"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.database import init_db
from app.log_config import setup_logging, get_logger
from app.routers import jobs, outline, chapters, export, stream, settings

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化
    setup_logging()
    await init_db()
    logger.info("Novel_Agent 启动完成")

    from app.config import get_llm_config
    cfg = get_llm_config()
    logger.info(f"LLM 配置: model={cfg['model']}, base_url={cfg['base_url']}")
    logger.info(f"API Key 已配置: {bool(cfg['api_key'])}")

    yield
    logger.info("Novel_Agent 关闭")


app = FastAPI(
    title="Novel_Agent — 小说创作智能体",
    description="AI 自动写小说系统 API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — 允许前端跨域访问（开发模式用 Vite proxy）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(jobs.router)
app.include_router(outline.router)
app.include_router(chapters.router)
app.include_router(export.router)
app.include_router(stream.router)
app.include_router(settings.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Novel_Agent"}


# 生产模式：serve 前端构建产物
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="assets")
    
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """SPA fallback — 所有非 API 路径返回 index.html"""
        if full_path.startswith("api/"):
            return None  # 让 API 路由处理
        from fastapi.responses import FileResponse
        return FileResponse(str(frontend_dist / "index.html"))