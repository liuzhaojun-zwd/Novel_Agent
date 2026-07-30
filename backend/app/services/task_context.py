"""Context propagated from durable workers into LLM calls and checkpoints."""

from contextvars import ContextVar

current_task_id: ContextVar[str | None] = ContextVar("task_id", default=None)
current_job_id: ContextVar[str | None] = ContextVar("job_id", default=None)
current_project_id: ContextVar[str | None] = ContextVar("project_id", default=None)
