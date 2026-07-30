"""小说圣经与创作设定的 Prompt 格式化工具。"""

import json

from app.models import SetupCreate


def format_setup_context(setup: SetupCreate) -> str:
    """将新旧创作设定统一格式化，供大纲和正文生成复用。"""
    lines: list[str] = []
    if setup.writing_style:
        lines.append(f"- 写作风格：{setup.writing_style}")
    if setup.narrative_perspective:
        lines.append(f"- 叙事视角：{setup.narrative_perspective}")
    if setup.characters:
        lines.append(f"- 主要人物：{', '.join(setup.characters)}")
    if setup.world_setting:
        lines.append(f"- 世界观摘要：{setup.world_setting}")
    if setup.story_bible:
        bible_json = json.dumps(
            setup.story_bible.model_dump(exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
        lines.append(f"\n## 小说圣经（必须遵守）\n{bible_json}")
    return "\n".join(lines)