"""Offline fixed-sample regression; never calls a paid model."""

import json
from pathlib import Path

from app.services.quality_regression import compare_reports, evaluate_sample


FIXTURE = Path(__file__).parent / "fixtures" / "quality_regression" / "urban_mystery.json"


def test_fixed_sample_quality_floor_and_version_provenance():
    sample = json.loads(FIXTURE.read_text(encoding="utf-8"))
    report = evaluate_sample(sample, model="baseline-model", prompt_id="chapter.draft")
    assert report["overall"] >= 60
    assert report["dimensions"]["repetition"] >= 70
    assert report["prompt_version"]
    assert report["scorer_version"]


def test_prompt_model_comparison_flags_regression():
    baseline = {
        "sample_id": "case", "model": "model-a", "prompt_version": "1.0.0",
        "overall": 80, "dimensions": {"repetition": 90, "dialogue": 80},
    }
    candidate = {
        "sample_id": "case", "model": "model-b", "prompt_version": "2.0.0",
        "overall": 70, "dimensions": {"repetition": 60, "dialogue": 85},
    }
    comparison = compare_reports(baseline, candidate, tolerance=3)
    assert comparison["regressed"] is True
    assert comparison["dimension_deltas"]["repetition"] == -30
    assert comparison["candidate"]["model"] == "model-b"
