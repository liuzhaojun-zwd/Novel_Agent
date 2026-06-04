# Novel_Agent — 小说创作智能体

> AI 驱动的自动小说写作系统。用户提供创作设定，系统自动生成大纲并按章节逐章创作正文，支持实时进度展示与断点续生。

---

## 项目结构

```
novel-agent/
├── backend/                  # Python FastAPI 后端
│   ├── app/
│   │   ├── main.py          # 应用入口
│   │   ├── config.py        # 配置管理（.env）
│   │   ├── database.py      # SQLite 数据库
│   │   ├── models.py        # Pydantic 数据模型
│   │   ├── routers/         # API 路由
│   │   │   ├── jobs.py      # 任务 CRUD
│   │   │   ├── outline.py   # 大纲生成/修改
│   │   │   ├── chapters.py  # 章节生成/续生
│   │   │   ├── export.py    # 作品导出
│   │   │   └── stream.py    # SSE 实时推送
│   │   └── services/        # 业务逻辑
│   │       ├── llm_adapter.py          # LLM 调用封装
│   │       ├── job_service.py          # 任务管理
│   │       ├── outline_generator.py    # 大纲生成
│   │       ├── chapter_generator.py    # 章节生成
│   │       ├── consistency_checker.py  # 一致性校验
│   │       ├── progress_tracker.py     # 进度推送
│   │       └── exporter.py             # 文件导出
│   ├── data/                # SQLite + 导出文件
│   └── requirements.txt
├── frontend/                # React + Vite + Tailwind 前端
│   ├── src/
│   │   ├── App.jsx
│   │   ├── api.js
│   │   ├── hooks/useSSE.js
│   │   └── components/
│   │       ├── SetupForm.jsx       # 创作设定表单
│   │       ├── OutlineView.jsx     # 大纲展示/修改
│   │       └── ProgressPanel.jsx   # 实时进度面板
│   └── package.json
├── REQUIREMENTS.md           # 需求文档
├── ARCHITECTURE.md           # 架构设计
└── TASKS.md                  # 开发任务清单
```

---

## 快速启动

### 1. 配置 LLM API

编辑 `backend/.env`（或复制 `.env.example`）：

```env
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_API_KEY=sk-your-api-key-here
LLM_MODEL=qwen-max
LLM_TEMPERATURE=0.8
```

支持任何兼容 OpenAI API 格式的服务（DeepSeek、智谱 GLM、通义千问等）。

### 2. 构建前端（首次运行需要）

```bash
cd frontend
npm install
npm run build
```

### 3. 启动后端（同时 serve API + 前端页面）

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开 http://localhost:8000 即可使用。

### 4. 开发模式（前后端热更新）

```bash
# 终端 1：后端
cd backend && uvicorn app.main:app --reload --port 8000

# 终端 2：前端（自动代理 API 到后端）
cd frontend && npm run dev
```

前端运行在 http://localhost:5173。

---

## 使用流程

1. **填写创作设定** — 题材、主题、目标章数、每章字数为必填，风格、人物、世界观、叙事视角可选
2. **查看大纲** — 系统生成完整大纲，可逐章修改标题和情节摘要
3. **确认大纲** — 满意后确认，进入正文生成
4. **实时写作** — 页面实时显示"正在写第 X/Y 章"的进度条
5. **阅读章节** — 左侧章节列表可点击查看已完成正文
6. **断点续生** — 生成失败后可一键续写，已写内容不丢失
7. **导出作品** — 支持 Markdown 和 TXT 格式下载

---

## API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/jobs` | 创建创作任务 |
| GET | `/api/jobs` | 任务列表 |
| GET | `/api/jobs/{id}` | 任务详情 |
| DELETE | `/api/jobs/{id}` | 删除任务 |
| POST | `/api/jobs/{id}/generate-outline` | 生成大纲 |
| GET | `/api/jobs/{id}/outline` | 获取大纲 |
| PUT | `/api/jobs/{id}/outline` | 修改大纲 |
| POST | `/api/jobs/{id}/confirm-outline` | 确认大纲 |
| GET | `/api/jobs/{id}/chapters` | 章节列表 |
| GET | `/api/jobs/{id}/chapters/{n}` | 章节详情 |
| POST | `/api/jobs/{id}/start` | 启动正文生成 |
| POST | `/api/jobs/{id}/resume` | 断点续生 |
| GET | `/api/jobs/{id}/export?format=txt\|md` | 导出作品 |
| GET | `/api/jobs/{id}/stream` | SSE 实时进度 |

---

## 技术栈

- **后端：** Python 3.10+ / FastAPI / SQLite / httpx
- **前端：** React 19 / Vite / Tailwind CSS v4
- **LLM：** OpenAI API 格式（可切换模型）
- **实时推送：** SSE (Server-Sent Events)