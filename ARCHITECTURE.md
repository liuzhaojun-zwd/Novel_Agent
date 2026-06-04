# Novel_Agent — 架构设计文档

> 版本：v1.0 | 日期：2026-06-04

## 0. 技术选型

| 层 | 技术 | 理由 |
|----|------|------|
| 后端框架 | FastAPI | Python 生态、异步原生、内置 OpenAPI 文档 |
| 前端 | React + Tailwind CSS | 响应式 UI、组件化、SSE 实时推送 |
| 数据库 | SQLite (本地) | 单用户场景，零运维，文件级备份 |
| LLM 接入 | OpenAI API 格式 | 可切换任何兼容模型（DeepSeek / GLM / 通义等） |
| 实时推送 | SSE (Server-Sent Events) | 单向进度推送，比 WebSocket 轻量，够用 |
| 异步任务 | asyncio + 后台 Task | FastAPI 原生支持，无需 Celery 等重型方案 |
| 包管理 | pip + venv | 标准 Python 流程 |

---

## 1. 整体架构

```
┌─────────────────────────────────────────────────────┐
│                   Frontend (React)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────┐ ┌────────┐     │
│  │ 创作设定页 │ │ 大纲页   │ │进度页│ │ 查看/  │     │
│  │ (SetupForm)│ │(Outline) │ │Progress│ │导出页 │     │
│  └─────┬─────┘ └────┬─────┘ └──┬───┘ └───┬────┘     │
│        └──────────────┴──────────┴──────────┘        │
│                     HTTP / SSE                        │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                  API Layer (FastAPI)                  │
│  ┌──────────┐ ┌──────────┐ ┌──────┐ ┌────────────┐ │
│  │ Job CRUD │ │ Outline  │ │Export│ │ SSE 推送    │ │
│  │ /api/jobs│ │ /api/out-│ │/api/ │ │ /api/jobs/  │ │
│  │          │ │ line     │ │export│ │ {id}/stream │ │
│  └──────────┘ └──────────┘ └──────┘ └────────────┘ │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                 Core Engine Layer                     │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │Outline_Gen   │  │Chapter_Gen   │                  │
│  │  (LLM调用)    │  │ (LLM调用)     │                  │
│  └──────────────┘  └──────────────┘                  │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │Consistency   │  │Progress      │                  │
│  │Checker       │  │Tracker       │                  │
│  └──────────────┘  └──────────────┘                  │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │Exporter      │  │LLM Adapter   │                  │
│  │(TXT/MD)      │  │(OpenAI API)  │                  │
│  └──────────────┘  └──────────────┘                  │
└────────────────────────┬────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────┐
│                Storage Layer (SQLite)                 │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ jobs table   │  │ chapters    │                  │
│  │              │  │ table       │                  │
│  └──────────────┘  └──────────────┘                  │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ consistency  │  │ outputs/    │                  │
│  │ alerts table │  │ (导出文件)    │                  │
│  └──────────────┘  └──────────────┘                  │
└─────────────────────────────────────────────────────┘
```

---

## 2. 数据模型

### 2.1 Generation_Job

```
jobs
├── id              TEXT (UUID4, PK)
├── status          TEXT (pending|generating_outline|generating_chapters|paused|completed|failed)
├── theme           TEXT (题材)
├── topic           TEXT (主题)
├── chapter_count   INTEGER (目标章节数)
├── words_per_chapter INTEGER (每章字数)
├── writing_style   TEXT NULL (写作风格)
├── characters      TEXT NULL (JSON Array，人物列表)
├── world_setting   TEXT NULL (世界观设定)
├── narrative_perspective TEXT NULL (叙事视角)
├── outline         TEXT NULL (JSON，完整大纲)
├── current_chapter INTEGER DEFAULT 0 (当前完成到第几章)
├── fail_count      INTEGER DEFAULT 0 (当前章节连续失败次数)
├── consistency_alerts TEXT NULL (JSON Array，一致性告警列表)
├── created_at      TIMESTAMP
├── updated_at      TIMESTAMP
└── completed_at    TIMESTAMP NULL
```

### 2.2 Chapter

```
chapters
├── id              INTEGER (自增 PK)
├── job_id          TEXT (FK -> jobs.id)
├── chapter_number  INTEGER
├── title           TEXT (章节标题)
├── summary         TEXT (情节摘要，来自大纲)
├── content         TEXT (正文)
├── word_count      INTEGER
├── status          TEXT (generating|completed|failed)
├── retry_count     INTEGER DEFAULT 0
└── created_at      TIMESTAMP
```

---

## 3. API 接口设计

### 3.1 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/jobs` | 创建 Generation_Job |
| GET | `/api/jobs` | 获取任务列表 |
| GET | `/api/jobs/{id}` | 获取任务详情（含大纲、进度、已生成章节） |
| DELETE | `/api/jobs/{id}` | 删除任务及所有章节 |

### 3.2 大纲

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/jobs/{id}/generate-outline` | 触发大纲生成 |
| PUT | `/api/jobs/{id}/outline` | 修改大纲（用户修改指令） |
| POST | `/api/jobs/{id}/confirm-outline` | 确认大纲，进入正文生成 |

### 3.3 正文生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/jobs/{id}/start` | 启动逐章生成 |
| POST | `/api/jobs/{id}/resume` | 断点续生 |

### 3.4 进度与推送

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs/{id}/stream` | SSE 实时进度推送 |
| GET | `/api/jobs/{id}/chapters` | 获取已生成章节列表 |
| GET | `/api/jobs/{id}/chapters/{n}` | 获取指定章节正文 |

### 3.5 导出

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/jobs/{id}/export?format=txt\|md` | 导出作品文件 |

---

## 4. 核心流程

### 4.1 完整生成流程

```
用户提交 Setup
    │
    ▼
创建 Job (status = pending)
    │
    ▼
触发大纲生成 ──→ LLM 调用生成大纲 ──→ 保存 Outline
    │                                        │
    │                                        ▼
    │                              展示给用户查看/修改
    │                                        │
    │                                        ▼
    │                              用户确认大纲
    │                                        │
    ▼                                        ▼
启动逐章生成 ──→ 循环：for chapter in 1..N:
    │                 │
    │                 ├── SSE 推送进度状态
    │                 ├── LLM 调用生成正文
    │                 ├── Consistency_Checker 校验
    │                 ├── 保存 Chapter + 更新 Checkpoint
    │                 └── 更新 fail_count / retry
    │
    ▼
完成 → 标记 completed
```

### 4.2 断点续生流程

```
用户对 paused 状态的 Job 发起 Resume
    │
    ▼
读取 Checkpoint (current_chapter)
    │
    ▼
从 current_chapter + 1 开始继续循环生成
    │
    ▼
后续同正常流程
```

### 4.3 失败重试流程

```
Chapter 生成失败
    │
    ▼
fail_count + 1
    │
    ├── fail_count < 3 → 自动重试该 Chapter
    │
    └── fail_count >= 3 → 标记 Job 为 failed，保留已完成内容
```

---

## 5. LLM Adapter 设计

统一的 OpenAI API 格式适配器，支持切换模型：

```
LLMAdapter
├── base_url: str        (API 端点，如 https://api.deepseek.com/v1)
├── api_key: str
├── model: str           (模型名，如 deepseek-chat / glm-4-plus)
├── temperature: float
└── max_tokens: int

使用方法：
generate_outline(setup) → 返回结构化 JSON Outline
generate_chapter(setup, outline, previous_chapters) → 返回正文
```

Prompt 设计和结构化输出（通过 JSON mode 或 function calling）在实现阶段详细定义。

---

## 6. SSE 进度推送协议

客户端连接 `GET /api/jobs/{id}/stream` 后，服务端推送如下事件：

```
event: progress
data: {"chapter": 3, "total": 10, "status": "generating_chapters", "message": "正在写第 3/10 章"}

event: chapter_complete
data: {"chapter": 3, "title": "密林追踪", "word_count": 2530}

event: job_complete
data: {"job_id": "xxx", "status": "completed"}

event: error
data: {"chapter": 5, "error": "LLM API timeout", "retry_count": 1}
```

---

## 7. 项目目录结构

```
novel-agent/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI 入口
│   │   ├── config.py            # 配置（API key、模型等）
│   │   ├── database.py          # SQLite 初始化 + 连接
│   │   ├── models.py            # 数据模型（Pydantic）
│   │   ├── db_models.py         # 数据库 ORM / 表定义
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── jobs.py          # 任务 CRUD 路由
│   │   │   ├── outline.py       # 大纲路由
│   │   │   ├── chapters.py      # 章节路由
│   │   │   ├── export.py        # 导出路由
│   │   │   └── stream.py        # SSE 推送路由
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── job_service.py    # 任务管理逻辑
│   │   │   ├── outline_generator.py
│   │   │   ├── chapter_generator.py
│   │   │   ├── consistency_checker.py
│   │   │   ├── progress_tracker.py
│   │   │   ├── exporter.py
│   │   │   └── llm_adapter.py   # OpenAI API 适配器
│   │   └── templates/           # (可选) Jinja2 模板
│   ├── requirements.txt
│   ├── data/                    # SQLite 数据库文件 + 导出文件
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── components/
│   │   │   ├── SetupForm.jsx        # 创作设定填写
│   │   │   ├── OutlineView.jsx      # 大纲展示/修改
│   │   │   ├── ProgressPanel.jsx    # 实时进度面板
│   │   │   ├── ChapterList.jsx      # 已生成章节列表
│   │   │   ├── ChapterViewer.jsx    # 章节正文阅读
│   │   │   └── Exporter.jsx         # 导出组件
│   │   ├── hooks/
│   │   │   └── useSSE.js            # SSE 连接 hook
│   │   └── api.js                   # 后端 API 调用
│   ├── package.json
│   └── vite.config.js
└── README.md
```

---

## 8. 设计要点总结

1. **SSE 而非 WebSocket** — 进度推送是单向的，SSE 更轻量，FastAPI 原生支持
2. **SQLite 本地存储** — 单用户工具场景，零运维，文件级备份/迁移
3. **LLM Adapter 抽象** — 统一 OpenAI API 接口，配置即切换模型
4. **章节级 Checkpoint** — 每完成一章立即持久化，保证断点续生不丢失
5. **上下文传递** — 生成新章节时传入已生成章节的摘要，保持连贯性
6. **异步任务** — 正文生成在后台 Task 中运行，不阻塞 API 响应