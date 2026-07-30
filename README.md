# Novel_Agent — 小说创作智能体

> AI 驱动的长篇小说创作工作台：先建立结构化小说圣经和大纲，再按场景生成正文，支持实时进度、长期记忆、语义审稿、局部修复、版本管理和断点续生。

## 核心能力

- 三步创作设定向导：作品定位、人物与世界、剧情资产。
- 结构化大纲和章节卡：目标、冲突、转折、结尾钩子、POV 与场景链。
- 场景级正文生成：规划 → 场景生成 → 合并润色，支持暂停、取消、恢复和幂等请求。
- 长篇记忆与一致性检查：人物状态、关系、地点、道具、伏笔和时间线变化。
- 语义审稿与局部修复：审稿建议、选区润色/扩写/缩写/改风格，并以补丁方式应用。
- 版本管理：大纲、设定和章节可保存、对比、恢复，恢复前自动备份。
- 生产化基础：持久化 SQLite 任务队列、任务租约/心跳/重试、LLM 连接池、模型分级、分类缓存、Token/费用台账。
- 用户与项目权限：HttpOnly Cookie 会话，项目角色支持 `owner`、`editor`、`viewer`。

## 项目结构

```
Novel_Agent/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI 应用入口和生命周期
│   │   ├── worker.py               # 独立任务 Worker 入口
│   │   ├── config.py               # .env 与运行时配置
│   │   ├── database.py             # SQLite/WAL 表结构与迁移
│   │   ├── models.py               # Pydantic 请求/响应模型
│   │   ├── routers/
│   │   │   ├── auth.py             # 登录、初始化、用户和项目成员
│   │   │   ├── jobs.py             # 创作任务 CRUD
│   │   │   ├── outline.py          # 大纲生成/编辑
│   │   │   ├── chapters.py         # 正文生成、控制和章节编辑
│   │   │   ├── memory.py           # 长篇记忆和事实审批
│   │   │   ├── versions.py         # 内容版本管理
│   │   │   ├── export.py           # 作品导出
│   │   │   └── stream.py           # SSE 实时进度
│   │   └── services/
│   │       ├── task_queue.py       # 持久队列、claim、租约、重试和取消
│   │       ├── task_worker.py      # 队列 Worker 与任务分发
│   │       ├── llm_adapter.py      # HTTP 连接池、重试和流式调用
│   │       ├── llm_metrics.py      # Token、费用和调用台账
│   │       ├── model_router.py     # 按用途选择模型等级
│   │       ├── prompt_registry.py  # Prompt 版本和模板哈希
│   │       ├── chapter_generator.py / scene_generator.py
│   │       ├── memory_service.py / consistency_checker.py
│   │       ├── editorial_service.py / quality_scorer.py
│   │       └── version_service.py / exporter.py
│   ├── data/                       # SQLite 数据库和缓存
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/                       # React + Vite + Tailwind 前端
│   └── src/
│       ├── App.jsx
│       ├── api.js
│       ├── hooks/useSSE.js
│       └── components/
├── OPTIMIZATION_TASKLIST.md        # 优化批次和验收记录
└── README.md
```

## 快速启动

### 1. 配置 LLM API

复制配置模板并编辑 `backend/.env`：

```cmd
cd backend
copy .env.example .env
```

至少配置以下内容：

```env
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=your-api-key-here
LLM_MODEL=deepseek-chat
LLM_TEMPERATURE=0.8
```

支持兼容 OpenAI Chat Completions 格式的服务，例如 DeepSeek、智谱 GLM、通义千问等。不要将真实 API Key 提交到 Git。

### 2. 安装依赖并构建前端

```cmd
cd backend
python -m pip install -r requirements.txt

cd ..\frontend
npm install
npm run build
```

### 3. 启动单进程开发模式

这是本地最简单的方式。API 服务会同时启动内置 Worker：

```cmd
cd backend
set TASK_WORKER_ENABLED=true
python -m uvicorn app.main:app --reload --port 8000
```

打开 <http://localhost:8000>。首次访问时，先创建管理员账号；之后使用该账号登录。

### 4. API 与 Worker 分离模式

生产环境或需要独立管理 Worker 时，将 `backend/.env` 设置为：

```env
TASK_WORKER_ENABLED=false
```

然后分别启动两个终端：

```cmd
:: 终端 1：API 服务
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

:: 终端 2：持久化任务 Worker
cd backend
python -m app.worker
```

此时 API 负责接收请求并写入 SQLite 队列，Worker 负责领取和执行大纲/正文生成任务。**只设置 `TASK_WORKER_ENABLED=false` 而不启动 `python -m app.worker`，任务会进入队列但不会执行。**

### 5. 前后端分离开发模式

```cmd
:: 终端 1：后端 API
cd backend
python -m uvicorn app.main:app --reload --port 8000

:: 终端 2：前端开发服务器
cd frontend
npm run dev
```

前端地址为 <http://localhost:5173>。如果 API 服务也需要处理生成任务，请确保内置 Worker 开启，或另开终端运行 `python -m app.worker`。

## 认证与项目权限

系统不再使用共享的默认管理员 Token，也不接受 query 参数中的 Token。首次启动时：

1. 打开前端页面。
2. 创建首位管理员账号，密码至少 10 位。
3. 系统自动创建默认项目并接管旧数据库中尚未归属项目的任务。
4. 后续通过 HttpOnly Cookie 会话登录。

角色权限：

| 角色 | 读取项目 | 编辑内容/生成 | 删除任务 | 管理成员 |
|------|----------|---------------|----------|----------|
| `owner` | 是 | 是 | 是 | 是 |
| `editor` | 是 | 是 | 否 | 否 |
| `viewer` | 是 | 否 | 否 | 否 |

管理员可以通过 `/api/auth/users` 创建用户，并通过项目成员接口分配角色。

## 使用流程

1. **登录或初始化账号** — 首次运行创建管理员，后续使用账号登录。
2. **填写创作设定** — 题材、故事核心、目标章数、每章字数为必填。
3. **AI 完善小说圣经** — 可补全人物卡、世界规则、主线、支线和伏笔。
4. **生成并编辑大纲** — 系统生成结构化章节卡和场景提示，可手动保存或让 AI 修改。
5. **确认大纲并生成正文** — 按章节规划场景，实时查看生成阶段和正文流。
6. **暂停、取消或恢复** — 场景和润色阶段都会保存 checkpoint，失败后可继续。
7. **审稿与局部修复** — 对章节进行语义审稿，预览并接受/拒绝局部补丁。
8. **版本管理与导出** — 对比/恢复版本，导出 Markdown 或 TXT 作品。

## API 概览

所有 `/api/jobs/{job_id}` 资源接口都需要登录，并会校验项目成员权限。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/api/auth/status` | 查询会话和系统初始化状态 |
| POST | `/api/auth/bootstrap` | 创建首位管理员 |
| POST | `/api/auth/login` | 登录并签发 HttpOnly Cookie |
| POST | `/api/auth/logout` | 注销会话 |
| GET/POST | `/api/auth/projects` | 查询/创建项目 |
| PUT | `/api/auth/projects/{id}/members` | 设置项目成员角色 |
| POST | `/api/jobs` | 创建创作任务 |
| GET | `/api/jobs` | 当前用户可访问的任务列表 |
| GET | `/api/jobs/{id}` | 任务详情 |
| POST | `/api/jobs/{id}/generate-outline` | 将大纲生成加入持久队列 |
| GET/PUT | `/api/jobs/{id}/outline` | 获取/修改大纲 |
| POST | `/api/jobs/{id}/confirm-outline` | 确认大纲 |
| POST | `/api/jobs/{id}/start` | 启动正文生成 |
| POST | `/api/jobs/{id}/resume` | 从 checkpoint 续生 |
| POST | `/api/jobs/{id}/pause` | 请求暂停 |
| POST | `/api/jobs/{id}/cancel` | 请求取消 |
| GET | `/api/jobs/{id}/generation-state` | 查询阶段、队列和 Token/费用指标 |
| GET | `/api/jobs/{id}/chapters` | 章节列表 |
| GET | `/api/jobs/{id}/export?format=txt\|md` | 导出作品 |
| GET | `/api/jobs/{id}/stream` | SSE 实时进度 |

完整接口可在服务启动后访问 <http://localhost:8000/docs>。

## 配置说明

| 配置项 | 默认值/示例 | 说明 |
|--------|-------------|------|
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容 API 地址 |
| `LLM_API_KEY` | 空 | LLM API 密钥 |
| `LLM_MODEL` | `deepseek-chat` | 默认模型 |
| `LLM_FAST_MODEL` | 空 | 规划、记忆等低成本用途模型；为空时使用默认模型 |
| `LLM_QUALITY_MODEL` | 空 | 大纲、正文、润色等高质量用途模型；为空时使用默认模型 |
| `LLM_INPUT_COST_PER_MILLION` | `0.5` | 输入 Token 估算价格（美元/百万） |
| `LLM_OUTPUT_COST_PER_MILLION` | `2.0` | 输出 Token 估算价格（美元/百万） |
| `TASK_WORKER_ENABLED` | `true` | 是否在 API 进程内启动 Worker；独立 Worker 部署时设为 `false` |
| `DATABASE_PATH` | `data/novel_agent.db` | SQLite 数据库路径 |

任务队列使用 SQLite WAL 模式，包含去重键、最大重试次数、租约过期恢复和心跳。LLM 调用会记录模型、Prompt 版本、Token、费用、缓存命中、延迟和重试信息。

## 测试与验证

后端：

```cmd
cd backend
python -m compileall app
python -m pytest -q
```

前端：

```cmd
cd frontend
npm run lint
npm run build
```

固定样本质量回归默认不调用真实模型，真实模型回归应显式单独运行，避免意外产生费用。

## 技术栈

- **后端：** Python 3.10+ / FastAPI / SQLite / aiosqlite / httpx
- **前端：** React 19 / Vite / Tailwind CSS v4
- **LLM：** OpenAI Chat Completions 兼容接口
- **认证：** PBKDF2 密码哈希 + HttpOnly Cookie 会话
- **队列：** SQLite 持久化队列 + Worker 租约/心跳
- **实时推送：** SSE（Server-Sent Events）
