# Novel_Agent — 小说创作智能体 · 需求文档

> 版本：v1.0
> 日期：2026-06-04
> 状态：已定稿

---

## 1. Introduction

本功能旨在构建一个"自动写小说的智能体"（Novel_Agent）。用户提供创作设定后，系统自动生成小说大纲，并按章节逐步生成正文内容。系统在生成过程中实时展示进度，并在生成中途发生失败时支持重试与断点续生，确保已生成内容不丢失。最终用户可以查看、保存并导出完整作品。

本文档仅覆盖需求阶段，不包含具体实现方案与代码。

---

## 2. Glossary

| 术语 | 说明 |
|------|------|
| **Novel_Agent** | 小说创作智能体，整个系统的统称，负责协调大纲生成、章节生成、进度跟踪、存储与导出 |
| **Setup（创作设定）** | 用户在创作开始前提供的输入集合，包括题材、主题、目标章节数、每章目标字数，以及可选的写作风格、主要人物、世界观设定、叙事视角 |
| **Outline（大纲）** | 由系统生成的结构化作品规划，包含章节列表，每个章节含标题与情节摘要 |
| **Chapter（章节）** | 小说的一个组成单元，包含章节序号、标题与正文内容 |
| **Outline_Generator（大纲生成器）** | 根据 Setup 生成 Outline 的子系统 |
| **Chapter_Generator（章节生成器）** | 根据 Outline 与已生成内容逐章生成 Chapter 正文的子系统 |
| **Progress_Tracker（进度跟踪器）** | 负责记录并对外展示生成进度的子系统 |
| **Storage_Manager（存储管理器）** | 负责持久化保存 Setup、Outline 与各 Chapter 内容的子系统 |
| **Consistency_Checker（一致性检查器）** | 负责校验人物设定与已生成内容一致性的子系统 |
| **Exporter（导出器）** | 负责将完整作品导出为指定文件格式的子系统 |
| **Generation_Job（生成任务）** | 一次从开始到完成的完整小说生成过程，具有唯一标识与可恢复状态 |
| **Checkpoint（检查点）** | Generation_Job 在生成过程中保存的可恢复状态，记录已完成章节与当前进度 |
| **Resume（断点续生）** | 从最近一个 Checkpoint 继续生成，不重新生成已完成 Chapter 的操作 |
| **Consistency Alert（一致性告警）** | Consistency_Checker 检测到人物冲突时生成的告警记录，供用户查阅 |

---

## 3. 创作设定字段定义（Setup）

### 必填字段

| 字段 | 类型 | 说明 | 约束 |
|------|------|------|------|
| `theme` | string | 题材（如玄幻、科幻、言情、悬疑） | 不可为空 |
| `topic` | string | 主题/故事核心（如"一位失忆剑客的复仇之旅"） | 不可为空 |
| `chapter_count` | int | 目标章节数 | 1–1000 |
| `words_per_chapter` | int | 每章目标字数 | 2,000–20,000 |

### 可选字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `writing_style` | string | 写作风格（如幽默、冷峻、诗意、现实主义） |
| `characters` | string[] | 主要人物列表（如 ["林夜", "苏晚晴", "白眉老人"]） |
| `world_setting` | string | 世界观设定（如"修仙世界中，灵气复苏，上古遗迹重现"） |
| `narrative_perspective` | enum | 叙事视角：first_person / third_person / multi_pov |

---

## 4. Requirements

### Requirement 1: 创建小说创作任务（提供创作设定）

**User Story:** 作为用户，我想要提供小说的创作设定，以便系统按照我的意图生成作品。

#### Acceptance Criteria

1. WHEN 用户提交包含所有必填字段的 Setup，THE Novel_Agent SHALL 创建一个 Generation_Job 并返回该任务的唯一标识。
2. IF 用户提交的 Setup 缺少任一必填字段，THEN THE Novel_Agent SHALL 拒绝创建任务并返回指明缺失字段的错误信息。
3. IF 用户提交的 `chapter_count` 小于 1 或大于 500，THEN THE Novel_Agent SHALL 拒绝创建任务并返回说明允许范围为 1 至 500 的错误信息。
4. IF 用户提交的 `words_per_chapter` 小于 2000 或大于 20000，THEN THE Novel_Agent SHALL 拒绝创建任务并返回说明允许范围为 2000 至 20000 的错误信息。
5. WHERE 用户在 Setup 中提供了可选字段（`writing_style`、`characters`、`world_setting`、`narrative_perspective`），THE Novel_Agent SHALL 在后续大纲生成与章节生成中使用该信息。
6. WHEN 一个 Generation_Job 被成功创建，THE Storage_Manager SHALL 持久化保存对应的 Setup。

---

### Requirement 2: 生成大纲

**User Story:** 作为用户，我想要系统先生成大纲，以便在正式写作前确认作品结构。

#### Acceptance Criteria

1. WHEN 一个 Generation_Job 被成功创建，THE Outline_Generator SHALL 根据 Setup 生成一份 Outline。
2. THE Outline SHALL 包含数量等于 Setup 中 `chapter_count` 的章节条目。
3. THE Outline 中的每个章节条目 SHALL 包含章节序号、章节标题与情节摘要。
4. WHEN 一份 Outline 生成完成，THE Storage_Manager SHALL 持久化保存该 Outline。
5. WHEN 一份 Outline 生成完成，THE Novel_Agent SHALL 向用户展示该 Outline 供查看。
6. WHEN 用户查看 Outline 后，SHALL 允许用户通过自然语言指令修改 Outline（如"把第3章标题改一下""调整第5-7章的顺序""重写第2章的情节摘要"），THE Outline_Generator SHALL 根据修改指令更新对应章节条目。
7. WHEN 用户对 Outline 满意并确认进入正文生成，THE Outline_Generator SHALL 将最终版 Outline 提交给 Storage_Manager。
8. IF Outline 生成失败，THEN THE Novel_Agent SHALL 向用户展示已生成的部分 Outline 内容与失败原因，并允许用户重试大纲生成。

---

### Requirement 3: 逐章生成正文

**User Story:** 作为用户，我想要系统按大纲逐章生成正文，以便获得完整的小说内容。

#### Acceptance Criteria

1. WHEN 用户确认大纲后启动正文生成，THE Chapter_Generator SHALL 按章节序号从小到大依次生成各 Chapter 的正文内容。
2. WHEN 一个 Chapter 的正文生成完成，THE Storage_Manager SHALL 在生成下一个 Chapter 之前持久化保存该 Chapter 的正文内容。
3. WHILE 正文生成进行中，THE Chapter_Generator SHALL 使用 Outline 中对应章节的情节摘要作为该 Chapter 的生成依据。
4. WHEN 全部 Chapter 的正文生成完成，THE Novel_Agent SHALL 将该 Generation_Job 的状态标记为已完成。
5. IF 某个 Chapter 生成的正文字数低于 `words_per_chapter` 的 50%，THEN THE Chapter_Generator SHALL 对该 Chapter 重新生成一次。

---

### Requirement 4: 展示生成进度

**User Story:** 作为用户，我想要在生成过程中看到实时进度，以便了解当前进展。

#### Acceptance Criteria

1. WHILE 正文生成进行中，THE Progress_Tracker SHALL 展示当前正在生成的章节序号与总章节数（例如"正在写第 3/10 章"）。
2. WHEN 一个 Chapter 的正文生成完成，THE Progress_Tracker SHALL 更新已完成章节数。
3. THE Progress_Tracker SHALL 展示当前 Generation_Job 的状态，状态取值范围为：`pending`（待开始）、`generating_outline`（生成大纲中）、`generating_chapters`（生成正文中）、`paused`（已暂停）、`completed`（已完成）、`failed`（失败）。
4. WHEN Generation_Job 的状态发生变化，THE Progress_Tracker SHALL 在状态变化后更新对外展示的状态。

---

### Requirement 5: 失败重试与断点续生

**User Story:** 作为用户，我想要在生成中途失败时能够续生，以便不丢失已写好的内容。

#### Acceptance Criteria

1. WHEN 一个 Chapter 的正文生成成功并被保存，THE Storage_Manager SHALL 更新该 Generation_Job 的 Checkpoint，记录已完成的章节序号。
2. IF 某个 Chapter 在生成过程中发生失败，THEN THE Novel_Agent SHALL 将该 Generation_Job 的状态标记为 `paused` 并保留已完成的 Chapter 内容。
3. WHEN 用户对一个已 `paused` 的 Generation_Job 发起 Resume，THE Chapter_Generator SHALL 从 Checkpoint 记录的下一个未完成章节序号继续生成。
4. WHEN 一个 Generation_Job 被 Resume，THE Chapter_Generator SHALL 跳过 Checkpoint 中已标记为完成的 Chapter，且不修改这些 Chapter 的已保存内容。
5. IF 单个 Chapter 连续生成失败达到 3 次，THEN THE Novel_Agent SHALL 停止该 Generation_Job 并将状态标记为 `failed`，同时保留已完成的 Chapter 内容。
6. WHEN 用户查询一个 Generation_Job，THE Storage_Manager SHALL 返回该任务已完成的 Chapter 列表与当前 Checkpoint 信息。

> **设计决定：断点以"章节"为最小粒度。** 段落级 checkpoint 需更细粒度的 token 追踪与保存策略，复杂度高、收益有限（当前 LLM 上下文窗口足够容纳单章内容），留作 V2 考虑。

---

### Requirement 6: 保持内容一致性

**User Story:** 作为用户，我想要各章节在人物与情节上保持一致，以便作品连贯可读。

#### Acceptance Criteria

1. WHILE 生成第二章及之后的 Chapter，THE Chapter_Generator SHALL 将先前已生成 Chapter 的摘要作为上下文输入。
2. WHERE Setup 中定义了 `characters`，THE Chapter_Generator SHALL 在生成正文时使用这些主要人物名称。
3. WHERE Setup 中未定义 `characters`，THE Chapter_Generator SHALL 正常生成 Chapter 正文，且不执行主要人物名称校验。
4. WHERE Setup 中定义了 `characters`，WHEN 一个 Chapter 生成完成，THE Consistency_Checker SHALL 校验该 Chapter 中出现的主要人物名称是否在 Setup 定义的 `characters` 集合内。
5. IF Consistency_Checker 检测到 Chapter 中出现 Setup 未定义的主要人物名称，THEN THE Consistency_Checker SHALL 记录一条一致性告警，包含章节序号与冲突的人物名称。
6. 一致性告警仅用于记录和展示给用户，**不执行自动修正**。自动替换可能造成张冠李戴影响剧情连贯性，留待用户审阅后决定是否处理。

---

### Requirement 7: 查看与导出作品

**User Story:** 作为用户，我想要查看并导出完整作品，以便保存与分享。

#### Acceptance Criteria

1. WHEN 用户请求查看一个 Generation_Job 的作品，THE Novel_Agent SHALL 按章节序号从小到大返回已生成的全部 Chapter 内容。
2. WHEN 用户请求导出一个 Generation_Job 的作品，THE Exporter SHALL 生成一个包含全部 Chapter 内容的文档文件。
3. THE Exporter SHALL 支持导出为 TXT 与 Markdown 两种格式。
4. THE Exporter 生成的导出文件 SHALL 按章节序号顺序排列各 Chapter，且每个 Chapter 包含其标题与正文。
5. IF 用户请求导出一个状态不为 `completed` 的 Generation_Job，THE Exporter SHALL 返回说明任务尚未完成的提示，并按当前已完成的 Chapter 内容生成导出文件。

> **格式说明：** 一期仅支持 TXT 和 Markdown。EPUB 格式（带目录、封面、分章导航）对长篇小说体验更好，留作 V2 考虑。

---

## 5. 状态机定义

```
                  ┌──────────┐
                  │  pending  │
                  └────┬─────┘
                       │ 用户提交 Setup
                       ▼
             ┌─────────────────┐
             │ generating_     │
             │ outline         │
             └────┬────────┬───┘
                  │        │ 失败
                  │        ▼
                  │    ┌───────┐
                  │    │ failed │
                  │    └───────┘
                  │ 用户确认大纲
                  ▼
          ┌──────────────────┐
          │ generating_      │
          │ chapters         │
          └──┬────┬──────┬───┘
             │    │      │
      成功    │    │失败  │ 连续失败3次
      (全部)  │    │      │
             ▼    ▼      ▼
       ┌────────┐ ┌──────┐ ┌───────┐
       │completed│ │paused│ │ failed│
       └────────┘ └──┬───┘ └───────┘
                     │ 用户发起 Resume
                     │ (从 Checkpoint 续生)
                     ▼
              ┌──────────────────┐
              │ generating_      │
              │ chapters (续生)  │
              └──────────────────┘
```

---

## 6. 设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 叙事视角与世界观设定 | 加入可选字段 | 对玄幻/科幻类作品影响大，放可选让用户自由决定 |
| 时间线/故事跨度 | 暂不加 | 可按需在`world_setting`中描述，独立字段价值不高 |
| 大纲修改方式 | 自然语言指令 | 避免复杂交互 UI，用户说"改第X章"系统直接理解执行 |
| 一致性冲突处理 | 告警记录，不自动修正 | 自动替换/重生成可能破坏剧情，留用户审阅更安全 |
| 断点粒度 | 章节级（非段落级） | 当前 LLM 上下文窗口够大，段落级复杂度高收益低 |
| 导出格式 | TXT + Markdown（一期） | EPUB 体验更好但实现复杂度高，放入 V2 |

---

## 7. 开放问题（V2 候选）

- **段落级 checkpoint**：当单章字数很大（如 > 10000 字）时，支持章节内分段生成与续生
- **EPUB 导出**：支持封面、目录、分章导航
- **自动修正一致性**：基于告警数据训练或规则驱动的自动修正策略
- **多轮修改**：支持在正文生成完成后，对特定章节进行修改后重新生成后续章节
- **批量创作**：一次提供多个 Setup，批量生成多部作品