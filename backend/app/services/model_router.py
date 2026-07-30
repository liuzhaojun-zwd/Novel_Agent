"""Purpose-aware model routing with explicit cost tiers."""

from __future__ import annotations

from app.config import get_llm_config

_FAST_PURPOSES = {"outline.edit", "chapter.plan", "memory.extract", "story_bible.assist"}
_QUALITY_PURPOSES = {"outline.generate", "chapter.draft", "chapter.polish", "chapter.review"}


def select_model(purpose: str = "default", requested_model: str | None = None) -> dict:
    cfg = get_llm_config()
    if requested_model:
        model, tier = requested_model, "explicit"
    elif purpose in _FAST_PURPOSES:
        model, tier = cfg["fast_model"], "fast"
    elif purpose in _QUALITY_PURPOSES:
        model, tier = cfg["quality_model"], "quality"
    else:
        model, tier = cfg["model"], "standard"
    return {
        "model": model,
        "tier": tier,
        "input_cost_per_million": cfg["input_cost_per_million"],
        "output_cost_per_million": cfg["output_cost_per_million"],
    }
