"""pytest 共享配置：使用测试专用数据库"""

import os
import sys

import pytest_asyncio

# 确保能 import 到 app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 使用测试专用的数据库路径
os.environ["NOVEL_AGENT_DB_PATH"] = "data/test_novel_agent.db"


@pytest_asyncio.fixture(scope="session", autouse=True)
async def close_test_database():
    """测试会话结束时关闭持久 SQLite 连接，避免后台线程阻止 pytest 退出。"""
    yield
    import app.database as database
    if database._db_conn is not None:
        await database.close_db(database._db_conn)