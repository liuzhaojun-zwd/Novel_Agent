"""pytest 共享配置：使用测试专用数据库"""

import os
import sys

# 确保能 import 到 app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 使用测试专用的数据库路径
os.environ["NOVEL_AGENT_DB_PATH"] = "data/test_novel_agent.db"