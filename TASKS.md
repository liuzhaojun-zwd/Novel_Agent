# Novel_Agent — 开发任务清单

> 预估：5 Phase，15 个 Task，约 12.5 人·天
> 实际：5 Phase，16 个 Task，已完成全部
> 日期：2026-06-04 | 状态：✅ 全部完成

---

## Phase 0：项目初始化（0.5 人·天）

### Task 0.1：项目脚手架搭建 ✅

- [x] 创建后端项目结构（FastAPI）
- [x] 初始化 `requirements.txt`（fastapi, uvicorn, pydantic, httpx, aiosqlite）
- [x] 初始化前端项目（Vite + React + Tailwind CSS）
- [x] 配置 `vite.config.js` 代理后端 API
- [x] 编写 `README.md` 启动说明

---

## Phase 1：核心数据层 + API（3 人·天）

### Task 1.1：SQLite 数据库层 ✅

- [x] 定义 `jobs` 表结构和 `chapters` 表结构
- [x] 实现数据库初始化和连接管理
- [x] 实现 CRUD：创建 job、查询 job（含大纲/章节）、更新 job 状态、删除 job
- [x] 实现章节存储：按 job 存储/查询/删除 chapter

### Task 1.2：Pydantic 数据模型 ✅

- [x] 定义 SetupCreate 模型（含必填/可选字段校验）
- [x] 定义 JobResponse 模型（含状态、大纲、进度信息）
- [x] 定义 ChapterResponse 模型
- [x] 定义 ProgressEvent 模型（SSE 消息体）
- [x] 定义错误响应模型

### Task 1.3：Job CRUD API ✅

- [x] POST `/api/jobs` — 创建任务（含 Setup 校验）
- [x] GET `/api/jobs` — 任务列表
- [x] GET `/api/jobs/{id}` — 任务详情（含已完成章节数）
- [x] DELETE `/api/jobs/{id}` — 删除任务（级联删除章节）

---

## Phase 2：核心生成引擎（4 人·天）

### Task 2.1：LLM Adapter ✅

- [x] 实现 OpenAI API 格式的 LLM 调用封装
- [x] 支持配置 `base_url`、`api_key`、`model`、`temperature`
- [x] 支持 JSON mode / structured output
- [x] 错误处理（超时、速率限制等）
- [x] `.env` 文件配置

### Task 2.2：大纲生成器（Outline_Generator） ✅

- [x] 构建大纲生成 Prompt（含题材、主题、风格、世界观、叙事视角）
- [x] 调用 LLM 生成结构化 JSON 大纲（章节序号 + 标题 + 情节摘要）
- [x] 解析 LLM 返回结果并校验格式
- [x] 保存大纲到 job 记录
- [x] 失败处理：部分生成时保留已有内容，返回失败原因

### Task 2.3：用户大纲修改 ✅

- [x] 用户提交自然语言修改指令（如"把第3章标题改为…"）
- [x] 解析指令，定位目标章节和修改内容
- [x] 支持操作：修改标题、修改情节摘要
- [x] 更新保存修改后的大纲

### Task 2.4：章节生成器（Chapter_Generator） ✅

- [x] 构建章节生成 Prompt（含人物设定、世界观、前文摘要）
- [x] 调用 LLM 逐章生成正文
- [x] 生成完成后执行字数校验（低于 50% 时自动重生成一次）
- [x] 生成完成后调用 Consistency_Checker 校验人物
- [x] 生成完成后调用 Progress_Tracker 更新进度
- [x] 保存 chapter 到数据库 + 更新 job Checkpoint
- [x] 失败重试逻辑：单章最多重试 3 次，超限则标记 job 为 failed

### Task 2.5：一致性检查器（Consistency_Checker） ✅

- [x] 读取 Setup 中定义的 `characters` 集合
- [x] 基于中文姓氏+上下文的名称检测
- [x] 检测到未定义人物时，生成一致性告警（含章节序号 + 冲突人物名）
- [x] 告警存入 job 的 `consistency_alerts` 字段

---

## Phase 3：进度推送 + 业务编排（2.5 人·天）

### Task 3.1：进度跟踪与 SSE 推送 ✅

- [x] 实现 SSE 端点 `GET /api/jobs/{id}/stream`
- [x] 生成过程中推送进度事件（当前章节 / 总章节 / 状态）
- [x] 章节完成事件（含字数统计）
- [x] 错误事件（含重试次数）
- [x] Job 完成事件
- [x] 前端 `useSSE` hook 连接并解析 SSE 事件（含自动重连）

### Task 3.2：业务编排（生成流程控制器） ✅

- [x] 实现 `POST /api/jobs/{id}/generate-outline`
- [x] 实现 `POST /api/jobs/{id}/confirm-outline`
- [x] 实现 `POST /api/jobs/{id}/start`（支持 `?up_to=N` 分批生成）
- [x] 实现 `POST /api/jobs/{id}/resume`（支持 `?up_to=N` 分批续生）
- [x] 并发安全：立即锁状态，防止重复启动

---

## Phase 4：导出 + 前端页面（2.5 人·天）

### Task 4.1：导出器（Exporter） ✅

- [x] TXT 格式导出（章节按顺序拼接，包含标题和正文）
- [x] Markdown 格式导出（`# 第X章 标题` 格式）
- [x] 未完成的作品也能导出（文件开头附加提示信息）
- [x] GET `/api/jobs/{id}/export?format=txt|md` 端点

### Task 4.2：前端 — 创作设定页 ✅

- [x] 表单组件：题材、主题、章节数、字数（必填）
- [x] 可选字段：风格、人物、世界观、视角
- [x] 表单验证（即时提示必填项、范围校验）
- [x] 提交创建任务后跳转到任务详情页

### Task 4.3：前端 — 大纲页 ✅

- [x] 展示大纲章节列表（序号 + 标题 + 情节摘要）
- [x] 章节修改交互：点击章节后可编辑标题/摘要
- [x] "确认大纲，开始写正文"按钮
- [x] "重新生成大纲"按钮 + 自然语言修改指令

### Task 4.4：前端 — 进度面板 + 章节阅读 ✅

- [x] SSE 连接，实时展示进度条和"正在写第 X/Y 章"
- [x] 已生成章节列表（可点击查看正文）
- [x] 章节正文阅读器
- [x] 一致性告警展示
- [x] 导出按钮（TXT / Markdown）
- [x] 批次控制按钮（写5章 / 写10章 / 全部）
- [x] Resume 按钮（当 job 为 paused 状态时显示）

---

## Phase 4.5：分批生成控制（新增 — 0.5 人·天）

### Task 4.5：分批生成控制 ✅

> 用户需求：不要求一次性生成所有章节，可人为控制每次生成的数量。

**理由：** 用户可以先看几章的效果，不满意方向可及时调整，不必等全部生成完。

- [x] `start` 和 `resume` 路由支持 `?up_to=N` 查询参数
- [x] `chapter_generator` 接收 `up_to` 参数，到达上限后自动暂停
- [x] 新增 SSE 事件 `batch_complete`，前端监听并刷新状态
- [x] 前端进度面板：开始写作时可选"写5章/10章/全部"
- [x] 前端进度面板：暂停后续写可选"5章/10章/全部(剩余N章)"
- [x] `up_to` 参数边界校验（不超总数、不小于当前进度）

---

## Phase 5：打磨收尾（0.5 人·天）

### Task 5.1：错误处理打磨 ✅

- [x] 前端统一错误提示
- [x] 后端子任务异常时，API 返回标准错误格式
- [x] 前端 SSE 超时自动重连（3s 间隔）
- [x] 并发安全：start/resume 立即锁状态防止重复启动

### Task 5.2：README + 部署说明 ✅

- [x] 安装步骤（pip install / npm install）
- [x] 配置 LLM API（.env 文件说明）
- [x] 单命令生产部署（`uvicorn` 同时 serve API + 前端页面）
- [x] 开发模式说明（前后端热更新）

---

## 汇总

| Phase | 任务 | 预估 | 实际 |
|-------|------|------|------|
| Phase 0 | 项目脚手架搭建 | 0.5 天 | — |
| Phase 1 | 核心数据层 + API | 3.0 天 | ✅ |
| Phase 2 | 核心生成引擎 | 4.0 天 | ✅ |
| Phase 3 | 进度推送 + 编排 | 2.5 天 | ✅ |
| Phase 4 | 导出 + 前端页面 | 2.5 天 | ✅ |
| Phase 4.5 | 分批生成控制 | — | ✅ 新增 |
| Phase 5 | 打磨收尾 | 0.5 天 | ✅ |
| **合计** | **16 个 Task** | **12.5 天** | **✅ 已完成** |

---

## 启动方式

```bash
# 首次运行
cd frontend && npm install && npm run build
cd backend && pip install -r requirements.txt

# 配置 API Key（复制 .env.example 为 .env，填入密钥）
cp .env.example .env

# 单命令启动（API + 页面都在 http://localhost:8000）
cd backend && uvicorn app.main:app --port 8000
```

```bash
# 开发模式（前后端热更新）
cd backend && uvicorn app.main:app --reload --port 8000 &
cd frontend && npm run dev   # http://localhost:5173
```