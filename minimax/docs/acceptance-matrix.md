# 六项必做项验收对照表（600077）

题面规则：六项全部通过得 20 分，任一项不通过得 0 分。下表逐项给出「通过条件 → 本作品如何满足 → 可核对证据」。

| # | 验收项 | 题面通过条件 | 本作品的实现 | 证据文件 |
| --- | --- | --- | --- | --- |
| 1 | 能够运行 | 按运行说明可初始化数据、启动模块并执行验证样例，不依赖未交付的本地文件或状态 | `README.md` 给出依赖、配置、初始化、调用入口；`scripts/verify_all.sh` 先 `rm -rf runtime` 从空状态开始，runner 内不含任何本地私货 | `evidence/doctor.json`、`evidence/verification-summary.json`、`verify_all.sh` 末行 `ALL CHECKS PASSED` |
| 2 | MiniMax 实际参与 | 开发记录包含本次任务、提供的上下文和代码修改过程，并与提交的代码差异对应 | `dev-run` 记录任务、上下文摘要（规格/代码/测试/状态）、完整响应、token 用量、补丁与测试结果；`check_dev_record.py` 用 `baseline → current` 重算 diff 并与记录逐行比对 | `dev-records/*-minimax-dev-run.json`、`evidence/dev-record-check.json` |
| 3 | 上下文正确 | 输出包含样例规定的必要规格、代码和测试来源；规格更新并重新导入后使用新内容 | `expectations.json` 固定必需来源，`verify-context` 逐条断言；`demo_spec_update.sh` 追加条款→重导入→断言新内容→回滚→断言旧内容 | `evidence/context-empty-state.check.json`、`evidence/context-after-spec-update.check.json`、`evidence/context-restored.check.json` |
| 4 | 数据库实际参与 | seekdb/OceanBase 中保存工程资料或索引，实际查询结果用于上下文 | 导入 3 规格 / 13 代码单元 / 30 测试到 seekdb，建 `min_token_size=2` 的 FULLTEXT 索引；上下文由 `MATCH ... AGAINST` 与按 id/符号查询产生，所有 SQL 留痕 | `evidence/import.json`（`fulltext: true`）、`evidence/db-import.log`、`evidence/db-queries.log` |
| 5 | 状态能够复用 | 从空状态开始保存任务记录，重启模块后能够读取，并用于后续上下文或任务处理 | 进程 1 `state-save`（空状态→PowerContext Memory）；进程 2 `state-show` 读回；进程 3 `context --with-state` 把状态注入上下文（`state_loaded: true`） | `evidence/powercontext-save.json`、`evidence/powercontext-reload.json`、`evidence/context-with-state.json` |
| 6 | 代码修改有效 | 同一组目标测试改前因功能未实现而失败，改后全部通过；回归测试也全部通过 | `baseline/pricing.py` 跑目标测试 = 15 failed 且全为 `AssertionError`；改后 `tests` 全量 = 30 passed。测试文件改前改后完全一致，未删断言/未跳过 | `evidence/test-before.log`、`evidence/test-after.log` |

## 补充说明

- 测试集在改前/改后使用**同一份文件**（`git` 中仅 `src/ordercore/pricing.py` 变更），未修改断言或期望值。
- 「改前失败」的判定显式排除了环境错误：`verify_all.sh` 会检查日志中没有 `ERROR collecting` / `ImportError` / `ModuleNotFoundError`。
- 规格更新演示只改规格 Markdown，不改代码与测试；回滚后 `import` 使上下文恢复，证明模块不是返回固定答案。
- 所有判断以评审实际执行 `verify_all.sh` 的结果为准；本表仅索引证据位置。