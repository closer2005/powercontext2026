"""speckit —— 面向软件持续演进的 SDD 上下文管理模块。

对外主要入口：
    config.Config            配置（环境变量 / .env）
    store.SeekDBStore        seekdb 索引存取（PyMySQL）
    selector.build_context   上下文检索与组装（带 source）
    state.ProgressStore      PowerContext 任务状态保存 / 恢复（含本地降级）
    minimax.chat             MiniMax 调用（OpenAI 兼容 HTTP）
    patch.extract_patch/apply 补丁提取与应用
    cli.main                 命令行入口（python -m speckit.cli）
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]