"""场景级正文生成流水线：规划、逐场景 checkpoint、合并润色。"""

from __future__ import annotations

import json
import math
from typing import Optional

from app.models import SetupCreate
from app.services import job_service as svc
from app.services.context_manager import select_context_summaries
from app.services.progress_tracker import publish
from app.services.story_bible import format_setup_context


class GenerationInterrupted(Exception):
    """用户请求暂停或取消；checkpoint 已在抛出前持久化。"""

    def __init__(self, state: str):
        super().__init__(state)
        self.state = state


def _count_chars(text: str) -> int:
    return len(text.replace(" ", "").replace("\n", ""))


def _truncate(text: str, limit: int = 2400) -> str:
    if len(text) <= limit:
        return text
    return text[: limit // 2] + "\n……（中间省略）……\n" + text[-limit // 2 :]


def _append_without_overlap(existing: str, addition: str) -> str:
    """去掉模型在断点续写时重复输出的精确前缀。"""
    if not existing:
        return addition
    clean = addition.lstrip()
    max_overlap = min(len(existing), len(clean), 800)
    for size in range(max_overlap, 19, -1):
        if existing[-size:] == clean[:size]:
            clean = clean[size:].lstrip()
            break
    return existing + clean

def _dedupe_paragraphs(text: str) -> str:
    """删除明显的整段重复，保留首次出现顺序。"""
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    seen: set[str] = set()
    result: list[str] = []
    for paragraph in paragraphs:
        normalized = "".join(paragraph.split())
        if len(normalized) >= 40 and normalized in seen:
            continue
        seen.add(normalized)
        result.append(paragraph)
    return "\n\n".join(result)


async def check_generation_control(run_id: str):
    """在每个 checkpoint 同时检查领域控制状态和 durable queue 取消状态。"""
    from app.services import task_queue
    from app.services.task_context import current_task_id

    task_id = current_task_id.get()
    if task_id and await task_queue.cancellation_requested(task_id):
        raise GenerationInterrupted("cancelled")
    run = await svc.get_generation_run(run_id)
    if not run:
        raise GenerationInterrupted("cancelled")
    if run["state"] == "pause_requested":
        raise GenerationInterrupted("paused")
    if run["state"] == "cancel_requested":
        raise GenerationInterrupted("cancelled")


def _parse_json_array(raw: str) -> list[dict]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("场景规划未返回 JSON 数组")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, list) or not value:
        raise ValueError("场景规划为空")
    return [item for item in value if isinstance(item, dict)]


def _normalize_plan(items: list[dict], chapter: dict, target_count: int) -> list[dict]:
    plan: list[dict] = []
    for index, item in enumerate(items[:8], start=1):
        conflict = item.get("obstacle") or item.get("conflict") or chapter.get("conflict", "")
        plan.append({
            "goal": str(item.get("goal") or chapter.get("chapter_goal") or f"推进本章第{index}阶段"),
            "obstacle": str(conflict or "局势与人物选择形成阻碍"),
            "action": str(item.get("action") or "人物采取具体行动应对阻碍"),
            "result": str(item.get("result") or chapter.get("turning_point") or "行动改变局势"),
            "next_entry": str(item.get("next_entry") or chapter.get("ending_hook") or "新的变化引向下一场"),
        })
    while len(plan) < target_count:
        index = len(plan) + 1
        plan.append({
            "goal": chapter.get("chapter_goal") or f"推进《{chapter['title']}》第{index}阶段",
            "obstacle": chapter.get("conflict") or "人物面临逐步升级的阻碍",
            "action": "人物基于动机做出具体选择并付诸行动",
            "result": chapter.get("turning_point") or "行动产生新的局势与代价",
            "next_entry": chapter.get("ending_hook") or "结果自然引出后续场景",
        })
    return plan[:8]


async def _collect_stream(
    llm, messages: list[dict], run_id: str, purpose: str, prompt_id: str,
) -> str:
    chunks: list[str] = []
    async for chunk in llm.chat_stream(messages, purpose=purpose, prompt_id=prompt_id):
        await check_generation_control(run_id)
        chunks.append(chunk)
    return "".join(chunks)

async def plan_chapter_scenes(
    llm,
    job_id: str,
    run_id: str,
    setup: SetupCreate,
    chapter: dict,
    previous_summary: str,
) -> list[dict]:
    """调用模型创建结构化场景卡；已有规划直接复用以保证幂等。"""
    chapter_number = chapter["chapter_number"]
    existing = await svc.get_chapter_scenes(job_id, chapter_number)
    if existing:
        return existing

    await check_generation_control(run_id)
    await svc.update_generation_run(
        run_id, stage="planning", current_chapter=chapter_number, current_scene=0,
        checkpoint_content="",
    )
    await publish(
        job_id, "scene_progress", chapter=chapter_number, scene=0,
        phase="planning", message=f"正在规划第 {chapter_number} 章场景",
    )

    requested_count = max(3, min(8, math.ceil(setup.words_per_chapter / 1000)))
    outline_scenes = chapter.get("scenes") or []
    prompt = f"""你是小说章节策划师。请把下面章节拆成 {requested_count} 个连续、不可互换的场景。
每个场景必须包含 goal、obstacle、action、result、next_entry 五个字符串字段。
后一场必须承接前一场 result/next_entry，事件逐级升级，禁止用同一冲突反复拖延。
只输出 JSON 数组，不要 Markdown 或解释。

作品设定：
{format_setup_context(setup)}

章节：第{chapter_number}章《{chapter['title']}》
摘要：{chapter['summary']}
章节目标：{chapter.get('chapter_goal', '')}
核心冲突：{chapter.get('conflict', '')}
转折：{chapter.get('turning_point', '')}
结尾钩子：{chapter.get('ending_hook', '')}
已有场景提示：{json.dumps(outline_scenes, ensure_ascii=False)}
前文回顾：{previous_summary or '这是开篇章节。'}
"""
    messages = [
        {"role": "system", "content": "你擅长把章节设计成因果紧密的场景链。"},
        {"role": "user", "content": prompt},
    ]

    raw = ""
    try:
        raw = await _collect_stream(llm, messages, run_id, "chapter.plan", "chapter.plan")
        parsed = _parse_json_array(raw)
    except GenerationInterrupted:
        raise
    except Exception:
        parsed = outline_scenes if isinstance(outline_scenes, list) else []

    plan = _normalize_plan(parsed, chapter, requested_count)
    await svc.save_scene_plan(job_id, chapter_number, plan)
    saved = await svc.get_chapter_scenes(job_id, chapter_number)
    await publish(
        job_id, "scene_plan", chapter=chapter_number,
        scene_count=len(saved), scenes=saved,
    )
    return saved

async def _generate_scene_once(
    llm,
    job_id: str,
    run_id: str,
    setup: SetupCreate,
    chapter: dict,
    scene: dict,
    all_scenes: list[dict],
    previous_summary: str,
    user_feedback: Optional[str],
) -> str:
    chapter_number = chapter["chapter_number"]
    scene_index = scene["scene_index"]
    prior_contents = [item["content"] for item in all_scenes if item["scene_index"] < scene_index and item["status"] == "completed"]
    prior_text = "\n\n".join(prior_contents)
    partial = scene.get("content") or ""
    target_words = max(500, math.ceil(setup.words_per_chapter / max(1, len(all_scenes))))
    partial_instruction = (
        f"\n本场景已有以下 checkpoint，请只从末尾继续，不要重写或复述：\n{_truncate(partial, 2600)}"
        if partial else ""
    )
    feedback = f"\n用户近期反馈：{user_feedback}" if user_feedback else ""
    prompt = f"""你是专业小说作家。请只创作指定场景的正文，不输出标题、提纲或说明。

作品设定：
{format_setup_context(setup)}

章节：第{chapter_number}章《{chapter['title']}》
章节摘要：{chapter['summary']}
本场景：{scene_index}/{len(all_scenes)}
- 目标：{scene['goal']}
- 阻碍：{scene['obstacle']}
- 行动：{scene['action']}
- 结果：{scene['result']}
- 下一场入口：{scene['next_entry']}
- 本场景目标字数：约 {target_words} 字

前文回顾：{previous_summary or '这是开篇章节。'}
本章前序场景末段：{_truncate(prior_text, 2200) if prior_text else '这是本章首场。'}
{feedback}{partial_instruction}

要求：让行动导致结果，以具体事件、感官和对白推进；不得总结后续场景，不得重复前序内容，不得提前完成下一场目标。
"""
    messages = [
        {"role": "system", "content": "你擅长写因果清楚、细节具体且不重复的小说场景。"},
        {"role": "user", "content": prompt},
    ]

    await svc.update_generation_run(
        run_id, stage="scene", current_chapter=chapter_number, current_scene=scene_index,
    )
    await svc.save_scene_checkpoint(job_id, chapter_number, scene_index, partial, "generating")
    await publish(
        job_id, "scene_progress", chapter=chapter_number, scene=scene_index,
        scene_count=len(all_scenes), phase="generating",
        message=f"正在生成第 {chapter_number} 章场景 {scene_index}/{len(all_scenes)}",
    )

    content = partial
    try:
        async for chunk in llm.chat_stream(
            messages, purpose="chapter.draft", prompt_id="chapter.draft",
        ):
            await check_generation_control(run_id)
            content = _append_without_overlap(content, chunk)
            await svc.save_scene_checkpoint(job_id, chapter_number, scene_index, content, "generating")
            preview = "\n\n".join(prior_contents + [content])
            await svc.save_chapter_checkpoint(job_id, chapter_number, preview)
            await publish(
                job_id, "token", chapter=chapter_number, text=chunk,
                accumulated=preview,
            )
    except GenerationInterrupted:
        await svc.save_scene_checkpoint(job_id, chapter_number, scene_index, content, "generating")
        raise
    except Exception:
        await svc.save_scene_checkpoint(
            job_id, chapter_number, scene_index, content, "failed", increment_retry=True,
        )
        raise

    if not content.strip():
        await svc.save_scene_checkpoint(
            job_id, chapter_number, scene_index, content, "failed", increment_retry=True,
        )
        raise RuntimeError(f"场景 {scene_index} 未生成有效正文")
    await svc.save_scene_checkpoint(job_id, chapter_number, scene_index, content, "completed")
    await publish(
        job_id, "scene_complete", chapter=chapter_number, scene=scene_index,
        scene_count=len(all_scenes), word_count=_count_chars(content),
    )
    return content

async def _polish_chapter(
    llm,
    job_id: str,
    run_id: str,
    setup: SetupCreate,
    chapter: dict,
    scenes: list[dict],
) -> str:
    chapter_number = chapter["chapter_number"]
    raw_content = "\n\n".join(scene["content"] for scene in scenes if scene["content"].strip())
    run = await svc.get_generation_run(run_id)
    partial = ""
    if run and run["stage"] == "polishing" and run["current_chapter"] == chapter_number:
        partial = run.get("checkpoint_content") or ""

    continuation = (
        f"\n润色稿已有以下 checkpoint。请只从末尾继续，最终不要重复已有段落：\n{_truncate(partial, 3000)}"
        if partial else ""
    )
    prompt = f"""你是资深小说编辑。请把场景草稿合并润色为第{chapter_number}章《{chapter['title']}》完整正文。
目标约 {setup.words_per_chapter} 字。保留每个场景的关键行动和结果，补足必要过渡与细节，删除重复信息和机械总结。
直接输出正文，不输出标题、场景编号、点评或说明。不得改变人物动机、事实和结尾钩子。
{continuation}

场景草稿：
{raw_content}
"""
    messages = [
        {"role": "system", "content": "你擅长无痕合并场景、消除重复并保持叙事连贯。"},
        {"role": "user", "content": prompt},
    ]
    await svc.update_generation_run(
        run_id, stage="polishing", current_chapter=chapter_number,
        current_scene=len(scenes) + 1, checkpoint_content=partial,
    )
    await publish(
        job_id, "scene_progress", chapter=chapter_number, scene=len(scenes) + 1,
        scene_count=len(scenes), phase="polishing", message=f"正在合并润色第 {chapter_number} 章",
    )

    polished = partial
    async for chunk in llm.chat_stream(
        messages, purpose="chapter.polish", prompt_id="chapter.polish",
    ):
        await check_generation_control(run_id)
        polished = _append_without_overlap(polished, chunk)
        await svc.update_generation_run(run_id, checkpoint_content=polished)
        await svc.save_chapter_checkpoint(job_id, chapter_number, polished)
        await publish(
            job_id, "token", chapter=chapter_number, text=chunk,
            accumulated=polished,
        )

    polished = _dedupe_paragraphs(polished.strip())
    if _count_chars(polished) < setup.words_per_chapter * 0.6 and _count_chars(raw_content) > _count_chars(polished):
        polished = _dedupe_paragraphs(raw_content)
    if not polished:
        raise RuntimeError("章节合并润色未返回有效正文")
    await svc.update_generation_run(run_id, checkpoint_content="")
    return polished


async def generate_scene_chapter(
    llm,
    job_id: str,
    run_id: str,
    setup: SetupCreate,
    chapter: dict,
    previous_summary_parts: list[str],
    user_feedback: Optional[str] = None,
) -> tuple[str, int]:
    """完成单章的规划→场景生成→合并润色，可从任一场景恢复。"""
    from app.services.memory_service import build_five_layer_context

    selected = select_context_summaries(previous_summary_parts)
    memory_context = await build_five_layer_context(
        job_id, setup, chapter, previous_summary_parts,
    )
    previous_summary = memory_context["formatted"]
    if selected and not memory_context["recent"]:
        previous_summary += "\n\n## 近期章节摘要\n" + "\n".join(selected)
    scenes = await plan_chapter_scenes(
        llm, job_id, run_id, setup, chapter, previous_summary,
    )

    for scene in scenes:
        if scene["status"] == "completed":
            continue
        last_error: Optional[Exception] = None
        for _ in range(3):
            refreshed = await svc.get_chapter_scenes(job_id, chapter["chapter_number"])
            current = next(item for item in refreshed if item["scene_index"] == scene["scene_index"])
            try:
                await _generate_scene_once(
                    llm, job_id, run_id, setup, chapter, current, refreshed,
                    previous_summary, user_feedback,
                )
                last_error = None
                break
            except GenerationInterrupted:
                raise
            except Exception as exc:
                last_error = exc
        if last_error:
            raise RuntimeError(
                f"第 {chapter['chapter_number']} 章场景 {scene['scene_index']} 连续生成失败，checkpoint 已保留"
            ) from last_error

    completed = await svc.get_chapter_scenes(job_id, chapter["chapter_number"])
    await check_generation_control(run_id)
    content = await _polish_chapter(llm, job_id, run_id, setup, chapter, completed)
    return content, _count_chars(content)
