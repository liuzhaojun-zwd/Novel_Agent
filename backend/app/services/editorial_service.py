"""语义审稿与安全局部修复服务。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.quality_scorer import score_chapter

SEMANTIC_DIMENSIONS = ("plot", "character", "continuity", "pacing")
SEVERITIES = {"critical", "high", "medium", "low"}


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _clamp_score(value: Any, default: int = 60) -> int:
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError):
        return default


def _location(content: str, issue: dict) -> dict:
    excerpt = str(issue.get("excerpt") or "").strip()
    try:
        start, end = int(issue.get("start", -1)), int(issue.get("end", -1))
    except (TypeError, ValueError):
        start = end = -1
    if excerpt and (start < 0 or end <= start or content[start:end] != excerpt):
        start = content.find(excerpt)
        end = start + len(excerpt) if start >= 0 else -1
    if start < 0 or end <= start or end > len(content):
        start, end = 0, min(len(content), 80)
        excerpt = content[start:end]
    return {"start": start, "end": end, "excerpt": content[start:end]}


def _normalize_issue(content: str, issue: Any) -> dict | None:
    if not isinstance(issue, dict):
        return None
    dimension = str(issue.get("dimension") or "plot").lower()
    if dimension not in {*SEMANTIC_DIMENSIONS, "style", "rule"}:
        dimension = "plot"
    severity = str(issue.get("severity") or "medium").lower()
    if severity not in SEVERITIES:
        severity = "medium"
    reason = str(issue.get("reason") or "").strip()
    suggestion = str(issue.get("suggestion") or "").strip()
    if not reason:
        return None
    return {
        "dimension": dimension,
        "severity": severity,
        "location": _location(content, issue),
        "reason": reason,
        "suggestion": suggestion or "请结合上下文进行针对性修改。",
        "source": "semantic",
    }


def _rule_issues(content: str, messages: list[str]) -> list[dict]:
    issues = []
    for message in messages:
        at_end = "结尾" in message
        start = max(0, len(content) - 120) if at_end else 0
        end = len(content) if at_end else min(len(content), 120)
        severity = "high" if "为空" in message or "不足" in message else "low"
        issues.append({
            "dimension": "rule",
            "severity": severity,
            "location": {"start": start, "end": end, "excerpt": content[start:end]},
            "reason": message,
            "suggestion": "按提示调整对应段落，并保持前后情节衔接。",
            "source": "rule",
        })
    return issues


def _job_context(job: Any, chapter: dict, chapters: list[dict]) -> str:
    bible = getattr(job, "story_bible", None) or {}
    outline = getattr(job, "outline", None) or []
    card = next(
        (item for item in outline if item.get("chapter_number") == chapter["chapter_number"]),
        {},
    )
    nearby = [
        {"chapter_number": item["chapter_number"], "title": item["title"], "summary": item["summary"]}
        for item in chapters
        if abs(item["chapter_number"] - chapter["chapter_number"]) <= 3
    ]
    return json.dumps({
        "theme": job.theme,
        "topic": job.topic,
        "writing_style": job.writing_style,
        "characters": job.characters,
        "world_setting": job.world_setting,
        "story_bible": bible,
        "chapter_card": card,
        "nearby_chapters": nearby,
    }, ensure_ascii=False, default=str)


async def review_chapter(llm, job: Any, chapter: dict, chapters: list[dict]) -> dict:
    """合并低成本规则评分与模型语义评分。"""
    content = chapter.get("content") or ""
    rule = score_chapter(
        content, chapter["title"], job.words_per_chapter, chapter["chapter_number"],
    )
    prompt = f"""你是严谨的中文长篇小说审稿人。请依据作品设定、章节卡和邻近章节，对本章进行语义审稿。
必须分别给 plot（剧情因果）、character（人物动机与言行）、continuity（设定和前后连续性）、pacing（节奏）0-100 分。
只指出有文本证据的问题，不得虚构设定。每个问题必须给 severity（critical/high/medium/low）、dimension、原文精确 excerpt、start/end 字符偏移、reason 和可执行 suggestion。
只返回 JSON 对象：{{"scores":{{"plot":0,"character":0,"continuity":0,"pacing":0}},"issues":[],"summary":""}}。

上下文：{_job_context(job, chapter, chapters)}
规则评分：{json.dumps(rule, ensure_ascii=False)}
正文（偏移从 0 开始）：
{content}
"""
    raw = await llm.chat_json([
        {"role": "system", "content": "你输出可验证、可定位的结构化小说审稿结果。"},
        {"role": "user", "content": prompt},
    ], max_tokens=5000)
    scores_raw = raw.get("scores") if isinstance(raw, dict) else {}
    scores = {name: _clamp_score((scores_raw or {}).get(name)) for name in SEMANTIC_DIMENSIONS}
    semantic_issues = [
        normalized
        for item in (raw.get("issues", []) if isinstance(raw, dict) else [])
        if (normalized := _normalize_issue(content, item)) is not None
    ]
    semantic_average = round(sum(scores.values()) / len(scores))
    overall = round(rule["overall"] * 0.3 + semantic_average * 0.7)
    return {
        "chapter_number": chapter["chapter_number"],
        "overall": overall,
        "rule_score": rule["overall"],
        "semantic_score": semantic_average,
        "dimensions": {**scores, "technical": rule["overall"]},
        "issues": semantic_issues + _rule_issues(content, rule.get("issues", [])),
        "summary": str(raw.get("summary") or "").strip(),
        "reviewed_content_hash": content_hash(content),
    }


_OPERATION_INSTRUCTIONS = {
    "refine": "润色文字，提升准确性、流畅度和文学表现力，不改变事实与情节",
    "expand": "扩写选区，补足动作、感官和心理细节，保持原有事实",
    "shorten": "缩写选区，删除冗余但保留关键动作、信息和因果",
    "style": "按指定风格改写选区，不改变人物、事实、时空和情节结果",
    "dialogue": "增加自然且推动情节的人物对白，同时保留原事件结果",
    "description": "增加环境、动作或感官描写，但不引入新设定和新事件",
}


async def propose_patch(
    llm,
    job: Any,
    chapter: dict,
    start: int,
    end: int,
    operation: str,
    instruction: str = "",
    style: str = "",
    selected_text: str = "",
) -> dict:
    """只让模型返回选区替换文本，不允许生成整章。"""
    content = chapter.get("content") or ""
    if start < 0 or end <= start or end > len(content):
        raise ValueError("选区位置无效")
    original = content[start:end]
    if selected_text and selected_text != original:
        raise RuntimeError("正文已变化，请保存或刷新后重新选择")
    if len(original) > 12000:
        raise ValueError("单次选区不能超过 12000 字符")
    before = content[max(0, start - 1200):start]
    after = content[end:min(len(content), end + 1200)]
    action = _OPERATION_INSTRUCTIONS[operation]
    prompt = f"""你是中文小说局部编辑器。任务：{action}。
用户补充要求：{instruction or '无'}
目标风格：{style or job.writing_style or '延续原文'}
硬性约束：仅改写【选区】，不得复述前后文；不得改变选区外事实；替换文本必须能直接接回上下文；不要输出 Markdown。
返回 JSON 对象：{{"replacement":"可直接替换的文本","explanation":"一句话说明"}}。

前文：{before}
【选区】{original}【选区结束】
后文：{after}
"""
    raw = await llm.chat_json([
        {"role": "system", "content": "你只生成安全、边界明确的局部小说补丁。"},
        {"role": "user", "content": prompt},
    ], max_tokens=5000)
    replacement = str(raw.get("replacement") or "")
    if not replacement.strip():
        raise RuntimeError("模型未返回有效替换文本")
    base_hash = content_hash(content)
    patch_id = content_hash(f"{base_hash}:{start}:{end}:{original}:{replacement}")[:24]
    return {
        "patch_id": patch_id,
        "chapter_number": chapter["chapter_number"],
        "operation": operation,
        "start": start,
        "end": end,
        "original": original,
        "replacement": replacement,
        "explanation": str(raw.get("explanation") or "").strip(),
        "base_hash": base_hash,
    }


def apply_patch(content: str, patch: Any) -> str:
    """以哈希和原文双重校验后进行一次切片替换。"""
    if content_hash(content) != patch.base_hash:
        raise RuntimeError("正文已变化，补丁不能安全应用，请重新生成")
    if patch.start < 0 or patch.end <= patch.start or patch.end > len(content):
        raise ValueError("补丁位置无效")
    if content[patch.start:patch.end] != patch.original:
        raise RuntimeError("选区原文不匹配，补丁不能安全应用")
    expected_id = content_hash(
        f"{patch.base_hash}:{patch.start}:{patch.end}:{patch.original}:{patch.replacement}"
    )[:24]
    if patch.patch_id != expected_id:
        raise ValueError("补丁签名无效")
    return content[:patch.start] + patch.replacement + content[patch.end:]
