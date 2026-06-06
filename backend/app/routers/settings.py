"""Novel_Agent — 设置路由（前端可配置 LLM API）"""

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional
from app.config import set_llm_config, is_llm_configured, get_llm_config, mask_api_key, settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ── 鉴权检查 ──
def _check_token(request: Request):
    """手动检查 admin token（PUT 操作需要鉴权）"""
    token = request.headers.get("X-Admin-Token") or request.query_params.get("token")
    if not token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="未授权")


class LLMConfigRequest(BaseModel):
    base_url: Optional[str] = None
    api_key: str
    model: Optional[str] = None
    temperature: Optional[float] = None


@router.get("/llm")
async def get_llm_settings():
    """获取当前 LLM 配置（不返回 api_key 完整值）"""
    cfg = get_llm_config()
    return {
        "base_url": cfg["base_url"],
        "api_key_masked": mask_api_key(cfg["api_key"]),
        "api_key_configured": bool(cfg["api_key"]),
        "model": cfg["model"],
        "temperature": cfg["temperature"],
    }


@router.put("/llm")
async def update_llm_settings(request: Request, req: LLMConfigRequest):
    """更新 LLM 配置（需要鉴权）"""
    _check_token(request)
    kwargs = {"api_key": req.api_key}
    if req.base_url:
        kwargs["base_url"] = req.base_url
    if req.model:
        kwargs["model"] = req.model
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature

    set_llm_config(**kwargs)

    # 测试连接
    from app.services.llm_adapter import LLMAdapter
    llm = LLMAdapter()
    try:
        await llm.chat([{"role": "user", "content": "回复一个词：好"}], max_tokens=5)
        configured = True
    except Exception:
        configured = False

    return {
        "message": "配置已保存" if configured else "配置已保存，但 API 连接测试失败，请检查密钥和地址",
        "connected": configured,
    }


@router.get("/status")
async def get_setup_status():
    """获取首次配置状态"""
    return {
        "llm_configured": is_llm_configured(),
        "api_key_set": bool(get_llm_config().get("api_key")),
    }