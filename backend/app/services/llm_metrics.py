"""Persistent LLM usage and cost ledger."""

from __future__ import annotations

from app.database import get_db
from app.services.task_context import current_job_id, current_project_id, current_task_id


async def record_call(**item) -> None:
    async with get_db() as db:
        await db.execute(
            """INSERT INTO llm_calls
               (task_id, job_id, project_id, purpose, provider, model, model_tier,
                prompt_id, prompt_version, template_hash, input_tokens, output_tokens,
                cost_usd, usage_estimated, cache_hit, attempt_count, latency_ms, status,
                provider_request_id, error_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item.get("task_id") or current_task_id.get(),
                item.get("job_id") or current_job_id.get(),
                item.get("project_id") or current_project_id.get(),
                item["purpose"], item["provider"], item["model"], item["model_tier"],
                item["prompt_id"], item["prompt_version"], item["template_hash"],
                item.get("input_tokens", 0), item.get("output_tokens", 0),
                item.get("cost_usd", 0), int(item.get("usage_estimated", False)),
                int(item.get("cache_hit", False)), item.get("attempt_count", 1),
                item.get("latency_ms", 0), item["status"],
                item.get("provider_request_id"), item.get("error_code"),
            ),
        )


async def job_totals(job_id: str) -> dict:
    async with get_db() as db:
        cursor = await db.execute(
            """SELECT COALESCE(SUM(input_tokens),0) input_tokens,
                      COALESCE(SUM(output_tokens),0) output_tokens,
                      COALESCE(SUM(cost_usd),0) cost_usd,
                      SUM(cache_hit) cache_hits, COUNT(*) calls,
                      MAX(usage_estimated) usage_estimated
               FROM llm_calls WHERE job_id = ? AND status = 'ok'""",
            (job_id,),
        )
        row = dict(await cursor.fetchone())
    row["total_tokens"] = row["input_tokens"] + row["output_tokens"]
    row["estimated"] = bool(row.pop("usage_estimated"))
    row["cost_usd"] = round(row["cost_usd"], 6)
    return row
