# 证据索引

所有文件均为 `scripts/verify_all.sh` 在**空状态**下真实执行产生的输出（`ALL CHECKS PASSED`）。
机器可汇总见 `verification-summary.json`。

| 必做项 | 证据文件 | 说明 |
| --- | --- | --- |
| ① 能够运行 | `doctor.json`、`import.json`、`verification-summary.json` | 环境自检、空状态初始化、一键复核汇总 |
| ② MiniMax 实际参与 | `../dev-records/*-minimax-dev-run.json`、`../dev-records/*-prompt.md`、`dev-record-check.json` | 请求原文、原始响应、用量、补丁，与提交 diff 逐行比对（`diff_matches_recomputed: true`） |
| ③ 上下文正确 | `context-empty-state.json/.md`、`context-empty-state.check.json`、`context-after-spec-update.*`、`context-restored.*` | 规格/代码/测试来源齐全；规格更新后刷新、回滚后恢复 |
| ④ 数据库实际参与 | `import.json`（`fulltext: true`）、`db-import.log`、`db-queries.log` | seekdb 建表/建 FULLTEXT 索引/`MATCH … AGAINST` 查询的完整留痕 |
| ⑤ 状态能够复用 | `powercontext-save.json`、`powercontext-reload.json`、`context-with-state.json/.md` | 进程 1 从空状态写入 scope+Memory；进程 2 读回；进程 3 注入上下文 |
| ⑥ 代码修改有效 | `test-before.log`、`test-after.log`、`code-diff.patch` | 改前 15 failed（AssertionError）→ 改后 30 passed；`baseline/` 与当前文件的差异 |

补充：

- `context-before-dev.json/.md` 是交给 MiniMax 的那份上下文（与开发记录中的 `context_digest` 对应）。
- `context-with-state.md` 中可直接看到 PowerContext 状态块被注入上下文。
- `db-import.log` 逐条记录导入时的 DML/DDL；`db-queries.log` 逐条记录上下文构建时的 SELECT 与命中行数。