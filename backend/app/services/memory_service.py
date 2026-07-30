"""长篇记忆：五层上下文、事实提取、变更审批与影响分析。"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from app.database import get_db
from app.models import SetupCreate
from app.services.context_manager import select_context_summaries

_ALLOWED_LAYERS = {"state", "asset"}
_ALLOWED_TYPES = {
    "character", "relationship", "location", "injury", "item",
    "timeline", "foreshadowing", "world",
}
_STATE_TYPES = {"character", "relationship", "location", "injury", "timeline"}
_ASSET_TYPES = {"item", "foreshadowing", "world"}


def _clip(text: str, limit: int = 12000) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n……（正文中段省略）……\n" + text[-half:]


def _fact_line(item: dict) -> str:
    chapter = f"（第{item['chapter_number']}章）" if item["chapter_number"] else ""
    return (
        f"- [{item['entity_type']}] {item['entity_key']} · "
        f"{item['attribute']} = {item['value']}{chapter}"
    )


def _fixed_facts(setup: SetupCreate) -> list[dict]:
    facts: list[dict] = []
    bible = setup.story_bible
    if not bible:
        if setup.world_setting:
            facts.append(_fixed("world", "世界", "设定", setup.world_setting))
        for name in setup.characters or []:
            facts.append(_fixed("character", name, "存在", "主要人物"))
        return facts

    for profile in bible.character_profiles:
        for attribute in (
            "role", "identity", "personality", "goal", "internal_need",
            "secret", "arc", "speech_style",
        ):
            value = getattr(profile, attribute)
            if value:
                facts.append(_fixed("character", profile.name, attribute, value))
    for index, value in enumerate(bible.character_relationships, 1):
        facts.append(_fixed("relationship", value, f"关系设定{index}", value))
    for index, value in enumerate(bible.world_rules, 1):
        facts.append(_fixed("world", "世界规则", f"规则{index}", value))
    for value in bible.key_items:
        facts.append(_fixed("item", value, "设定", "关键道具"))
    for value in bible.locations:
        facts.append(_fixed("location", value, "设定", "关键地点"))
    for value in bible.foreshadowing:
        facts.append(_fixed("foreshadowing", value, "设定", "长期伏笔"))
    for attribute in ("world_summary", "power_system", "main_plot"):
        value = getattr(bible, attribute)
        if value:
            facts.append(_fixed("world", "作品", attribute, value))
    return facts


def _fixed(entity_type: str, entity_key: str, attribute: str, value: str) -> dict:
    return {
        "layer": "fixed", "entity_type": entity_type,
        "entity_key": entity_key, "attribute": attribute, "value": value,
        "chapter_number": 0, "source_excerpt": "小说圣经", "importance": 5,
    }


async def ensure_fixed_memories(job_id: str, setup: SetupCreate) -> None:
    """幂等地把结构化小说圣经投影为不可静默覆盖的固定事实。"""
    facts = _fixed_facts(setup)
    if not facts:
        return
    async with get_db() as db:
        for fact in facts:
            await db.execute(
                """INSERT INTO story_memories
                   (job_id, layer, entity_type, entity_key, attribute, value,
                    chapter_number, source_excerpt, importance)
                   SELECT ?, ?, ?, ?, ?, ?, 0, ?, 5
                   WHERE NOT EXISTS (
                       SELECT 1 FROM story_memories
                       WHERE job_id = ? AND layer = 'fixed'
                         AND entity_type = ? AND entity_key = ?
                         AND attribute = ? AND value = ? AND status = 'active'
                   )""",
                (
                    job_id, fact["layer"], fact["entity_type"], fact["entity_key"],
                    fact["attribute"], fact["value"], fact["source_excerpt"],
                    job_id, fact["entity_type"], fact["entity_key"],
                    fact["attribute"], fact["value"],
                ),
            )


async def list_memories(
    job_id: str,
    entity: Optional[str] = None,
    layer: Optional[str] = None,
    status: str = "active",
    limit: int = 200,
) -> list[dict]:
    sql = "SELECT * FROM story_memories WHERE job_id = ? AND status = ?"
    params: list[Any] = [job_id, status]
    if entity:
        sql += " AND (entity_key LIKE ? OR value LIKE ?)"
        params.extend([f"%{entity}%", f"%{entity}%"])
    if layer:
        sql += " AND layer = ?"
        params.append(layer)
    sql += " ORDER BY chapter_number DESC, importance DESC, id DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    async with get_db() as db:
        cursor = await db.execute(sql, params)
        return [dict(row) for row in await cursor.fetchall()]


def _query_text(chapter: dict) -> str:
    parts: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(chapter)
    return "\n".join(parts).lower()


async def build_five_layer_context(
    job_id: str,
    setup: SetupCreate,
    chapter: dict,
    previous_summary_parts: list[str],
) -> dict:
    """构建固定设定、剧情状态、长期资产、相关记忆、近期上下文五层记忆。"""
    await ensure_fixed_memories(job_id, setup)
    chapter_number = int(chapter.get("chapter_number") or 0)
    memories = await list_memories(job_id, status="active", limit=500)
    available = [
        item for item in memories
        if item["chapter_number"] == 0 or item["chapter_number"] < chapter_number
    ]
    fixed = [item for item in available if item["layer"] == "fixed"][:80]
    state = [item for item in available if item["layer"] == "state"][:40]
    assets = [item for item in available if item["layer"] == "asset"][:40]

    query = _query_text(chapter)
    scored: list[tuple[int, dict]] = []
    for item in available:
        key = item["entity_key"].strip().lower()
        value = item["value"].strip().lower()
        score = item["importance"] * 3
        if key and key in query:
            score += 100
        if len(value) >= 2 and value in query:
            score += 30
        if item["entity_type"] in {"foreshadowing", "item"}:
            score += 4
        if item["chapter_number"]:
            score += max(0, 10 - (chapter_number - item["chapter_number"]))
        scored.append((score, item))
    relevant = [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:24]]
    recent = select_context_summaries(previous_summary_parts)

    layers = {
        "fixed": [_fact_line(item) for item in fixed],
        "state": [_fact_line(item) for item in state],
        "assets": [_fact_line(item) for item in assets],
        "relevant": [_fact_line(item) for item in relevant],
        "recent": recent,
    }
    sections = [
        ("第一层｜固定设定（不可擅自改写）", layers["fixed"]),
        ("第二层｜当前剧情状态", layers["state"]),
        ("第三层｜长期资产与伏笔", layers["assets"]),
        ("第四层｜本章相关历史（可来自早期章节）", layers["relevant"]),
        ("第五层｜近期上下文", layers["recent"]),
    ]
    layers["formatted"] = "\n\n".join(
        f"## {title}\n" + ("\n".join(items) if items else "（暂无）")
        for title, items in sections
    )
    return layers


def _normalize_fact(raw: dict, chapter_number: int) -> Optional[dict]:
    entity_key = str(raw.get("entity_key") or "").strip()[:120]
    attribute = str(raw.get("attribute") or "").strip()[:80]
    attribute = {
        "身份": "identity", "人物身份": "identity", "角色": "role",
        "性格": "personality", "目标": "goal", "内在需求": "internal_need",
        "秘密": "secret", "人物弧光": "arc", "说话风格": "speech_style",
        "当前位置": "location", "位置": "location", "伤势": "injury",
        "持有者": "holder", "伏笔状态": "status",
    }.get(attribute, attribute)
    value = str(raw.get("value") or "").strip()[:1000]
    if not entity_key or not attribute or not value:
        return None
    entity_type = str(raw.get("entity_type") or "character").strip().lower()
    if entity_type not in _ALLOWED_TYPES:
        entity_type = "character"
    layer = str(raw.get("layer") or "").strip().lower()
    if layer not in _ALLOWED_LAYERS:
        layer = "state" if entity_type in _STATE_TYPES else "asset"
    try:
        importance = max(1, min(5, int(raw.get("importance", 3))))
    except (TypeError, ValueError):
        importance = 3
    return {
        "layer": layer, "entity_type": entity_type,
        "entity_key": entity_key, "attribute": attribute, "value": value,
        "chapter_number": chapter_number,
        "source_excerpt": str(raw.get("source_excerpt") or "").strip()[:300],
        "importance": importance,
    }


async def extract_chapter_memories(
    llm,
    job_id: str,
    setup: SetupCreate,
    chapter_number: int,
    title: str,
    summary: str,
    content: str,
) -> dict:
    """用结构化模型提取本章事实，并将重要变更转为待确认请求。"""
    await ensure_fixed_memories(job_id, setup)
    prompt = f"""从下面小说章节提取已明确发生或成立的长期事实。只输出 JSON 对象：
{{"facts":[{{"layer":"state或asset","entity_type":"character|relationship|location|injury|item|timeline|foreshadowing|world","entity_key":"规范实体名","attribute":"稳定、可比较的属性名","value":"本章结束时的值或事件事实","importance":1到5,"source_excerpt":"不超过80字的正文依据"}}]}}

规则：
1. 提取人物状态、关系、当前位置、伤势、道具持有/状态、时间线变化和伏笔状态。
2. 同一实体的可变状态使用稳定属性名（如 location、injury、与某人的关系、holder、status），以便与历史比较。
3. 人物固定属性必须使用 role/identity/personality/goal/internal_need/secret/arc/speech_style；timeline 的独立事件用“时间点:事件名”作为 attribute。
4. importance=4/5 仅用于死亡、身份、重大关系、严重伤势、关键道具、核心时间线和伏笔等重要事实。
5. 不推测、不提取文风或临时动作；没有事实则返回空数组。

第{chapter_number}章《{title}》
摘要：{summary}
正文：
{_clip(content)}"""
    result = await llm.chat_json([
        {"role": "system", "content": "你是小说连续性编辑，只输出可验证的结构化事实。"},
        {"role": "user", "content": prompt},
    ], max_tokens=4096)
    raw_facts = result.get("facts", []) if isinstance(result, dict) else []
    facts = [
        fact for fact in (
            _normalize_fact(item, chapter_number)
            for item in raw_facts if isinstance(item, dict)
        ) if fact
    ]
    return await persist_extracted_memories(job_id, facts)


async def persist_extracted_memories(job_id: str, facts: list[dict]) -> dict:
    activated = 0
    pending = 0
    unchanged = 0
    async with get_db() as db:
        for fact in facts:
            cursor = await db.execute(
                """SELECT * FROM story_memories
                   WHERE job_id = ? AND entity_type = ? AND entity_key = ?
                     AND attribute = ? AND status = 'active'
                   ORDER BY CASE layer WHEN 'fixed' THEN 1 ELSE 0 END,
                            chapter_number DESC, id DESC LIMIT 1""",
                (job_id, fact["entity_type"], fact["entity_key"], fact["attribute"]),
            )
            existing_row = await cursor.fetchone()
            existing = dict(existing_row) if existing_row else None
            if existing and existing["value"].strip().casefold() == fact["value"].strip().casefold():
                unchanged += 1
                continue
            if existing and max(existing["importance"], fact["importance"]) >= 4:
                payload = json.dumps(fact, ensure_ascii=False)
                cursor = await db.execute(
                    """SELECT id FROM fact_change_requests
                       WHERE job_id = ? AND existing_memory_id = ?
                         AND proposed_memory = ? AND status = 'pending'""",
                    (job_id, existing["id"], payload),
                )
                if not await cursor.fetchone():
                    await db.execute(
                        """INSERT INTO fact_change_requests
                           (job_id, existing_memory_id, proposed_memory, reason)
                           VALUES (?, ?, ?, ?)""",
                        (
                            job_id, existing["id"], payload,
                            f"重要事实“{fact['entity_key']}·{fact['attribute']}”从“{existing['value']}”变为“{fact['value']}”",
                        ),
                    )
                    pending += 1
                else:
                    unchanged += 1
                continue
            if existing:
                await db.execute(
                    "UPDATE story_memories SET status = 'superseded' WHERE id = ?",
                    (existing["id"],),
                )
            await _insert_memory(db, job_id, fact)
            activated += 1
    return {"extracted": len(facts), "activated": activated, "pending": pending, "unchanged": unchanged}


async def _insert_memory(db, job_id: str, fact: dict) -> None:
    await db.execute(
        """INSERT INTO story_memories
           (job_id, layer, entity_type, entity_key, attribute, value,
            chapter_number, source_excerpt, importance)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            job_id, fact["layer"], fact["entity_type"], fact["entity_key"],
            fact["attribute"], fact["value"], fact["chapter_number"],
            fact["source_excerpt"], fact["importance"],
        ),
    )


async def list_fact_changes(job_id: str, status: Optional[str] = None) -> list[dict]:
    sql = """SELECT change.*, memory.entity_type, memory.entity_key,
                    memory.attribute, memory.value AS old_value,
                    memory.chapter_number AS old_chapter_number
             FROM fact_change_requests change
             JOIN story_memories memory ON memory.id = change.existing_memory_id
             WHERE change.job_id = ?"""
    params: list[Any] = [job_id]
    if status:
        sql += " AND change.status = ?"
        params.append(status)
    sql += " ORDER BY change.created_at DESC, change.id DESC"
    async with get_db() as db:
        cursor = await db.execute(sql, params)
        rows = []
        for row in await cursor.fetchall():
            item = dict(row)
            item["proposed_memory"] = json.loads(item["proposed_memory"])
            rows.append(item)
        return rows


async def resolve_fact_change(job_id: str, change_id: int, approve: bool) -> Optional[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT change.*, memory.layer AS old_layer
               FROM fact_change_requests change
               JOIN story_memories memory ON memory.id = change.existing_memory_id
               WHERE change.id = ? AND change.job_id = ?""",
            (change_id, job_id),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        change = dict(row)
        if change["status"] != "pending":
            return change
        status = "approved" if approve else "rejected"
        if approve:
            fact = json.loads(change["proposed_memory"])
            if change["old_layer"] != "fixed":
                await db.execute(
                    "UPDATE story_memories SET status = 'superseded' WHERE id = ?",
                    (change["existing_memory_id"],),
                )
            await _insert_memory(db, job_id, fact)
        await db.execute(
            """UPDATE fact_change_requests SET status = ?,
               resolved_at = datetime('now','localtime') WHERE id = ?""",
            (status, change_id),
        )
        change["status"] = status
        change["proposed_memory"] = json.loads(change["proposed_memory"])
        return change


async def analyze_change_impact(job_id: str, change_id: int) -> Optional[dict]:
    changes = await list_fact_changes(job_id)
    change = next((item for item in changes if item["id"] == change_id), None)
    if not change:
        return None
    proposed = change["proposed_memory"]
    entity = change["entity_key"]
    source_chapter = int(proposed.get("chapter_number") or 0)
    direct: set[int] = set()
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT chapter_number FROM chapters
               WHERE job_id = ? AND (summary LIKE ? OR content LIKE ?)
               ORDER BY chapter_number""",
            (job_id, f"%{entity}%", f"%{entity}%"),
        )
        direct.update(row["chapter_number"] for row in await cursor.fetchall())
        cursor = await db.execute(
            """SELECT DISTINCT chapter_number FROM story_memories
               WHERE job_id = ? AND entity_key = ?""",
            (job_id, entity),
        )
        direct.update(row["chapter_number"] for row in await cursor.fetchall() if row["chapter_number"])
        cursor = await db.execute("SELECT outline FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
    planned: set[int] = set()
    if row and row["outline"]:
        try:
            for chapter in json.loads(row["outline"]):
                if entity in json.dumps(chapter, ensure_ascii=False):
                    planned.add(int(chapter.get("chapter_number", 0)))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    affected = sorted(number for number in direct | planned if number > 0)
    downstream = [number for number in affected if number >= source_chapter]
    return {
        "change_id": change_id,
        "entity_key": entity,
        "attribute": change["attribute"],
        "old_value": change["old_value"],
        "new_value": proposed.get("value", ""),
        "source_chapter": source_chapter,
        "affected_chapters": affected,
        "downstream_chapters": downstream,
        "summary": f"共发现 {len(affected)} 个直接提及或规划涉及该事实的章节。",
    }
