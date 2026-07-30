"""Deterministic quality baselines and prompt/model comparison reports."""

from __future__ import annotations

from app.services.prompt_registry import get_prompt_version
from app.services.quality_scorer import SCORER_VERSION, score_chapter


def evaluate_sample(sample: dict, *, model: str, prompt_id: str) -> dict:
    score = score_chapter(
        sample["content"], sample["title"], sample["target_words"], sample["chapter_number"],
    )
    return {
        "sample_id": sample["id"],
        "model": model,
        "prompt_id": prompt_id,
        "prompt_version": get_prompt_version(prompt_id),
        "scorer_version": SCORER_VERSION,
        "overall": score["overall"],
        "dimensions": score["dimensions"],
        "issues": score["issues"],
    }


def compare_reports(baseline: dict, candidate: dict, tolerance: int = 3) -> dict:
    dimension_deltas = {
        key: candidate["dimensions"].get(key, 0) - baseline["dimensions"].get(key, 0)
        for key in sorted(set(baseline["dimensions"]) | set(candidate["dimensions"]))
    }
    overall_delta = candidate["overall"] - baseline["overall"]
    return {
        "sample_id": candidate["sample_id"],
        "baseline": {
            "model": baseline["model"], "prompt_version": baseline["prompt_version"],
        },
        "candidate": {
            "model": candidate["model"], "prompt_version": candidate["prompt_version"],
        },
        "overall_delta": overall_delta,
        "dimension_deltas": dimension_deltas,
        "regressed": overall_delta < -abs(tolerance),
    }
