#!/usr/bin/env python3
"""初始化 seekdb 索引数据（等价于 ``python -m speckit.cli init``）。

用法::

    cd minimax
    python scripts/init_data.py

本脚本做两件事：

1. 调用 :meth:`speckit.store.SeekDBStore.init_schema` 建库建表
   （spec_items / code_items / test_items）；
2. 调用 :meth:`speckit.store.SeekDBStore.import_from_json` 把 ``data/`` 下的
   ``specs.json`` / ``code_index.json`` / ``tests_index.json`` 三份索引幂等导入，
   并打印每类条目数与当前表计数。

失败处理：
    * seekdb 连接 / SQL 失败时打印**中文错误**与排查方向，并以**非零退出码**返回，
      便于在 ``scripts/run_all.sh``、CI 等场景中阻断后续步骤；
    * 索引文件缺失或格式异常只作为 ``[提示]`` 打印，不视为致命错误
      （由 ``import_from_json`` 汇总到 ``warnings``）。

凭据只来自环境变量或 ``minimax/.env``（参考 ``minimax/.env.example``），
脚本内不写死任何真实凭据。
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ 的上一级即 minimax/；把它加入 sys.path，
# 使本脚本无论从哪个工作目录调用都能 import speckit。
_MINIMAX_ROOT = Path(__file__).resolve().parent.parent
if str(_MINIMAX_ROOT) not in sys.path:
    sys.path.insert(0, str(_MINIMAX_ROOT))

from speckit.config import Config  # noqa: E402
from speckit.store import SeekDBStore, StoreError  # noqa: E402

EXIT_STORE_ERROR = 2
EXIT_UNEXPECTED = 3


def main() -> int:
    cfg = Config.from_env()
    store = SeekDBStore(cfg)

    print(
        f"目标 seekdb：{cfg.seekdb_host}:{cfg.seekdb_port}/{cfg.seekdb_database}"
        f"（user={cfg.seekdb_user}）"
    )

    try:
        print("1/2 建库建表：init_schema() ...")
        store.init_schema()

        print("2/2 导入 data/ 三份索引：import_from_json() ...")
        counts = store.import_from_json()
    except StoreError as exc:
        # 可预期的 seekdb 错误：给出中文说明 + 排查方向 + 非零退出
        print(f"[错误] 初始化 seekdb 失败：{exc}", file=sys.stderr)
        print(
            "[排查] 请确认：1) seekdb 实例已启动并监听端口；"
            "2) SEEKDB_HOST / SEEKDB_PORT / SEEKDB_USER / SEEKDB_PASSWORD "
            "已按 minimax/.env.example 正确配置；3) 网络与防火墙放行。",
            file=sys.stderr,
        )
        return EXIT_STORE_ERROR
    except Exception as exc:  # 兜底：不隐藏未预期错误
        print(
            f"[未预期错误] {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_UNEXPECTED

    # 打印各类条目数
    print(
        f"导入条目数：specs={counts['specs']} "
        f"code={counts['code']} tests={counts['tests']}"
    )
    for warning in counts.get("warnings", []):
        print(f"[提示] {warning}")

    stats = store.stats()
    print(
        "当前表计数："
        f"spec_items={stats.get('spec_items', 0)} "
        f"code_items={stats.get('code_items', 0)} "
        f"test_items={stats.get('test_items', 0)}"
    )
    print("初始化完成：索引数据已就绪，可执行 build 检索。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())