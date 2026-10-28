"""pytest 配置：确保无论从哪个目录运行，都能导入 orders 包。

背景：测试既支持在 demo_project 目录下运行

    cd minimax/demo_project && python -m pytest tests -q

也支持在仓库根目录运行

    python -m pytest minimax/demo_project/tests -q

后者的 sys.path 中不会自动包含 demo_project，因此这里显式补上，
使两种调用方式行为一致。
"""

import os
import sys

# tests/ 的上一级目录即 demo_project/
_DEMO_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if _DEMO_PROJECT_DIR not in sys.path:
    sys.path.insert(0, _DEMO_PROJECT_DIR)