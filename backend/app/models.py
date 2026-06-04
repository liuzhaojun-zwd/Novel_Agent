"""Novel_Agent — Pydantic 数据模型（请求/响应定义）"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from uuid import uuid4
from datetime import datetime


# ── 请求模型 ──

class SetupCreate(BaseModel):
    """创作设定（创建任务时的输入）"""
    theme: str = Field(..., min_length=1, description="题材")
    topic: str = Field(..., min_length=1, description="主题/故事核心")
    chapter_count: int = Field(..., ge=1, le=1000, description="目标章数（1-1000）")
    words_per_chapter: int = Field(..., ge=2000, le=20000, description="每章字数（2000-20000）")
    writing_style: Optional[str] = Field(None, description="写作风格")
    characters: Optional[list[str]] = Field(None, description="主要人物")
    world_setting: Optional[str] = Field(None, description="世界观设定")
    narrative_perspective: Optional[str] = Field(None, description="叙事视角")


class OutlineModifyRequest(BaseModel):
    """大纲修改请求"""
    instruction: str = Field(..., description="自然语言修改指令，如'把第3章标题改为xxx'")


# ── 响应模型 ──

class ChapterResponse(BaseModel):
    """章节响应"""
    chapter_number: int
    title: str
    summary: str
    content: str
    word_count: int
    status: str

    model_config = {"from_attributes": True}


class ConsistencyAlert(BaseModel):
    """一致性告警"""
    chapter_number: int
    conflict_name: str


class JobResponse(BaseModel):
    """任务详情响应"""
    id: str
    status: str
    theme: str
    topic: str
    chapter_count: int
    words_per_chapter: int
    writing_style: Optional[str] = None
    characters: Optional[list[str]] = None
    world_setting: Optional[str] = None
    narrative_perspective: Optional[str] = None
    outline: Optional[list[dict]] = None
    current_chapter: int = 0
    fail_count: int = 0
    consistency_alerts: list[ConsistencyAlert] = []
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None

    model_config = {"from_attributes": True}


class JobListItem(BaseModel):
    """任务列表项"""
    id: str
    status: str
    theme: str
    topic: str
    chapter_count: int
    current_chapter: int
    created_at: str

    model_config = {"from_attributes": True}


class ProgressEvent(BaseModel):
    """SSE 进度事件"""
    event: str  # progress | chapter_complete | job_complete | error
    chapter: int = 0
    total: int = 0
    status: str = ""
    title: str = ""
    word_count: int = 0
    message: str = ""
    error: str = ""
    retry_count: int = 0


class ErrorResponse(BaseModel):
    """标准错误响应"""
    detail: str
    missing_fields: Optional[list[str]] = None