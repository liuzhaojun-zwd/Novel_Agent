"""Novel_Agent — 日志配置（Issue 2）

结构化日志，支持按模块过滤。
"""

import logging
import sys
from datetime import datetime
from pathlib import Path


def setup_logging():
    """配置全局日志"""
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 Handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    # 根 Logger
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(console)

    # 文件 Handler（如果 logs/ 目录存在）
    log_dir = Path(__file__).parent.parent / "logs"
    if log_dir.exists():
        file_handler = logging.FileHandler(
            str(log_dir / f"novel_agent_{datetime.now().strftime('%Y%m%d')}.log")
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # 模块级 Logger
    for name in ("novel_agent", "novel_agent.chapter", "novel_agent.llm", "novel_agent.locks"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sse_starlette").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """获取模块级 Logger"""
    return logging.getLogger(f"novel_agent.{name}")