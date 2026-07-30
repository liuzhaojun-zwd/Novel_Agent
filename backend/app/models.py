"""Novel_Agent — Pydantic 数据模型（请求/响应定义）"""

from __future__ import annotations
from pydantic import BaseModel, Field, model_validator
from typing import Optional
from uuid import uuid4
from datetime import datetime


# ── 请求模型 ──

class CharacterProfile(BaseModel):
    """小说圣经中的结构化人物卡。"""
    name: str = Field(..., min_length=1)
    role: str = ""
    identity: str = ""
    personality: str = ""
    goal: str = ""
    internal_need: str = ""
    secret: str = ""
    arc: str = ""
    speech_style: str = ""


class StoryBible(BaseModel):
    """贯穿大纲和正文生成的结构化小说圣经。"""
    target_audience: str = ""
    tone: str = ""
    core_conflict: str = ""
    theme_expression: str = ""
    selling_points: list[str] = Field(default_factory=list)
    prohibited_content: list[str] = Field(default_factory=list)
    character_profiles: list[CharacterProfile] = Field(default_factory=list)
    character_relationships: list[str] = Field(default_factory=list)
    world_summary: str = ""
    world_rules: list[str] = Field(default_factory=list)
    factions: list[str] = Field(default_factory=list)
    power_system: str = ""
    main_plot: str = ""
    subplots: list[str] = Field(default_factory=list)
    foreshadowing: list[str] = Field(default_factory=list)
    key_items: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)


class SetupCreate(BaseModel):
    """创作设定（兼容旧字段，并支持结构化小说圣经）。"""
    theme: str = Field(..., min_length=1, description="题材")
    topic: str = Field(..., min_length=1, description="主题/故事核心")
    chapter_count: int = Field(..., ge=1, le=1000, description="目标章数（1-1000）")
    words_per_chapter: int = Field(..., ge=2000, le=20000, description="每章字数（2000-20000）")
    writing_style: Optional[str] = Field(None, description="写作风格")
    characters: Optional[list[str]] = Field(None, description="主要人物（旧版兼容）")
    world_setting: Optional[str] = Field(None, description="世界观设定（旧版兼容）")
    narrative_perspective: Optional[str] = Field(None, description="叙事视角")
    story_bible: Optional[StoryBible] = None

    @model_validator(mode="after")
    def fill_legacy_fields(self):
        """让新小说圣经继续兼容依赖人物名和世界观文本的旧逻辑。"""
        if self.story_bible:
            if not self.characters:
                self.characters = [p.name for p in self.story_bible.character_profiles]
            if not self.world_setting and self.story_bible.world_summary:
                self.world_setting = self.story_bible.world_summary
        return self


class OutlineModifyRequest(BaseModel):
    """大纲修改请求"""
    instruction: str = Field(..., min_length=1, description="自然语言修改指令，如'把第3章标题改为xxx'")


class SceneCard(BaseModel):
    """章节内的场景规划，兼容旧 conflict 字段。"""
    goal: str = ""
    conflict: str = ""
    obstacle: str = ""
    action: str = ""
    result: str = ""
    next_entry: str = ""


class GenerationStartRequest(BaseModel):
    """场景级正文生成参数。"""
    up_to: Optional[int] = Field(None, ge=1)
    chapter: Optional[int] = Field(None, ge=1)
    generation_mode: str = Field("auto", pattern="^(auto|collaborative)$")
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_target(self):
        if self.up_to is not None and self.chapter is not None:
            raise ValueError("up_to 与 chapter 不能同时指定")
        return self


class OutlineChapterInput(BaseModel):
    """结构化章节卡；旧大纲只需提供编号、标题和摘要。"""
    chapter_number: int = Field(..., ge=1)
    title: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    pov_character: str = ""
    location: str = ""
    chapter_goal: str = ""
    conflict: str = ""
    turning_point: str = ""
    ending_hook: str = ""
    characters: list[str] = Field(default_factory=list)
    foreshadowing_add: list[str] = Field(default_factory=list)
    foreshadowing_resolve: list[str] = Field(default_factory=list)
    scenes: list[SceneCard] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class OutlineSaveRequest(BaseModel):
    """完整大纲保存请求"""
    chapters: list[OutlineChapterInput] = Field(..., min_length=1)


class LocalRewriteRequest(BaseModel):
    """针对已保存正文选区生成局部修复补丁。"""
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=1)
    operation: str = Field(
        ..., pattern="^(refine|expand|shorten|style|dialogue|description)$",
    )
    instruction: str = Field("", max_length=500)
    style: str = Field("", max_length=100)
    selected_text: str = Field("", max_length=12000)

    @model_validator(mode="after")
    def validate_selection(self):
        if self.end <= self.start:
            raise ValueError("end 必须大于 start")
        return self


class ApplyChapterPatchRequest(BaseModel):
    """应用经过预览的局部补丁。"""
    patch_id: str = Field(..., min_length=24, max_length=24)
    start: int = Field(..., ge=0)
    end: int = Field(..., ge=1)
    original: str = Field(..., min_length=1, max_length=12000)
    replacement: str = Field(..., min_length=1, max_length=40000)
    base_hash: str = Field(..., min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_range(self):
        if self.end <= self.start:
            raise ValueError("end 必须大于 start")
        return self


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
    project_id: Optional[str] = None
    status: str
    theme: str
    topic: str
    chapter_count: int
    words_per_chapter: int
    writing_style: Optional[str] = None
    characters: Optional[list[str]] = None
    world_setting: Optional[str] = None
    narrative_perspective: Optional[str] = None
    story_bible: Optional[StoryBible] = None
    outline: Optional[list[dict]] = None
    current_chapter: int = 0
    fail_count: int = 0
    consistency_alerts: list[ConsistencyAlert] = []
    feedback: list[dict] = []
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


class FactChangeDecision(BaseModel):
    """重要事实变更审批。"""
    approve: bool
