"""Stable prompt/model provenance for generation and regression reports."""

from __future__ import annotations

import hashlib
import json

PROMPT_VERSIONS = {
    "outline.generate": "2.1.0",
    "outline.edit": "2.0.0",
    "story_bible.assist": "1.1.0",
    "chapter.plan": "1.0.0",
    "chapter.draft": "1.0.0",
    "chapter.polish": "1.0.0",
    "chapter.review": "1.0.0",
    "memory.extract": "1.0.0",
}


def get_prompt_version(prompt_id: str) -> str:
    return PROMPT_VERSIONS.get(prompt_id, "1.0.0")


def template_hash(messages: list[dict]) -> str:
    normalized = json.dumps(messages, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def registry_snapshot() -> dict[str, str]:
    return dict(sorted(PROMPT_VERSIONS.items()))
