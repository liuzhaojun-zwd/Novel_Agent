"""Run a dedicated durable worker with: python -m app.worker"""

import asyncio

from app.database import close_db, init_db
from app.log_config import setup_logging
from app.services.llm_adapter import close_http_client, init_http_client
from app.services.task_worker import TaskWorker


async def main() -> None:
    setup_logging()
    db = await init_db()
    await init_http_client()
    try:
        await TaskWorker().run()
    finally:
        await close_http_client()
        await close_db(db)


if __name__ == "__main__":
    asyncio.run(main())
