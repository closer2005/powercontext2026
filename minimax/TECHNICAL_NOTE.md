# 一页技术说明 · 规有所依 SDD 上下文管理系统

> 题目：MiniMax × OceanBase（平台 600077）。基线：`oceanbase/powercontext` 的 `2026-competition-ecosystem` 分支。

## 1. 模块结构

```
minimax/
├── context_module/sdd_context/     # 上下文模块（CLI + 可 import 的包）
│   ├── materials.py                # 规格 front-matter / ast 代码单元 / 测试函数抽取 + 中英文分词
│   ├── store.py                    # 嵌入式 seekdb：建表、FULLTEXT 索引、SQL 检索、查询留痕
│   ├── importer.py                 # 全量导入（规格按 spec_id 版本化，代码/测试可替换）
│   ├── selector.py                 # 任务→上下文：规格、代码、目标/回归测试、来源校验、Markdown 渲染
│   ├── pc_state.py                 # PowerContext Builtin runtime：任务状态 Memory 写入/读取 + scope 映射
│   ├── minimax_client.py           # MiniMax OpenAI 兼容调用（订阅 Key，记录不含凭据/思维链）
│   ├── devrun.py                   # 提示词渲染、diff 解析与应用、整文件兜底、测试回灌、开发记录落盘
│   └── cli.py                      # doctor / import / context / state-* / dev-run / verify-context
├── sample_app/                     # 业务工程 ordercore：v1 基线 + v2 规格 + 目标/回归测试
├── scripts/                        # verify_all.sh（六项必做端到端）、demo_spec_update.sh、check_dev_record.py
├── evidence/                       # 数据库查询、测试日志、上下文、状态读写、验收汇总
└── dev-records/                    # MiniMax 开发记录（请求上下文摘要、响应、补丁、测试结果）
```

上下文模块的输入是「业务工程根目录 + task.yaml」；输出是 `context.json`（结构化、可机检）与
`context.md`（供人/模型阅读）。CLI 是主要入口，同一逻辑也可作为 Python 包直接 import。

## 2. 上下文选择方式（确定性、可核对）

1. **规格**：任务声明 `specs: [SPEC-ORD-001, SPEC-ORD-002]` 决定候选；按 `spec_id` 取
   `status='active'` 的**最高 revision**，再叠加关键词全文检索补充。v1 自动标为 `superseded`，
   因此「同一 spec 的旧版本不会混进上下文」。
2. **代码**：`task.yaml` 的 `hints.symbols` 精确命中函数（`final_price_cents` 等 4 个），
   `hints.paths` 命中 `pricing.py` 与 `models.py` 的全部单元，再用任务描述做关键词检索补足以至上限。
   每条代码都带 `path`、`line_start`、`line_end`、`anchor`（`path::symbol`）。
3. **测试**：`target_tests` / `regression_tests` 指定的文件内全部 `test_*` 函数（各 15 条），
   明确区分「改前应红、改后必须绿」与「前后都必须绿」。
4. **来源校验**：`verify-context` 按 `expectations.json` 逐条校验规格锚点、必需正文、代码锚点、
   目标/回归测试名单，并拒绝 superseded 规格；`selector.validate_context` 还会校验每条来源
   的文件真实存在、行号在范围内、内容与库中一致（规格文件被改而未 re-import 会报 stale）。

选择是**确定性**的：同样的库内容与任务必然得到同样的上下文摘要（`context_digest`），
评审可对照 `expectations.json` 复算，不依赖模型措辞或排序。

## 3. 三项技术的分工与关键实现

- **seekdb**：嵌入式 `pylibseekdb` 启动本地实例（也可 `SDD_SEEKDB_MODE=server` 连远程），
  表 `sdd_materials(mat_id, kind, path, anchor, symbol, spec_id, revision, status, content, tokenized, digest, …)`
  + `sdd_import_runs`。中文用「字符二元组 + 英文词」预切分写入 `tokenized`，全文索引必须用
  `WITH PARSER space PARSER_PROPERTIES=(min_token_size=2,...)`，否则 2 字中文词会被默认解析器丢弃
  （实测默认解析器对 `额外` 命中 0）。所有 SELECT/DML 都记录到 `evidence/db-queries.log`。
- **PowerContext**：用 Builtin runtime SDK（题面允许 SDK/HTTP/MCP/插件任选）在
  `runtime/powercontext` 建库；`scopes.create` 用幂等键 `sdd-task::<task_id>` 注册工作域，
  服务端返回的 `scp_…` 存进 `runtime/powercontext-scopes.json`，任务状态作为一条
  `kind=sdd-task-state` 的 Memory 写入。读取时新进程按映射找到同一 scope 取最新条目，
  因此「重启后读取并使用」不依赖进程内缓存。
- **MiniMax**：`dev-run` 把任务描述 + 生效规格全文 + 相关代码 + 30 条测试 + 任务状态渲染成
  系统/用户消息，调用 `POST {base}/v1/chat/completions`（`MiniMax-M3.1-Flash`，输出预算 32k）。
  模型返回 unified diff；模块用**自研 hunk 应用器**（精确上下文匹配、允许行号漂移）落地，
  失败则退回「整文件回填」，测试红则把失败输出回灌重试。最终补丁、`git diff`、测试结果、
  token 用量写入 `dev-records/*.json`（剔除模型私有思维链与凭据）。

## 4. 规格演进的验证

`scripts/demo_spec_update.sh` 向 `SPEC-ORD-001.v2.md` 追加带 `DEMO-SPEC-UPDATE-MARKER` 的演示条款，
重新 `import` 后上下文必须出现新内容；随后撤销并重新导入，上下文必须回到旧内容且 marker 消失。
这证明模块每次都从 seekdb 现查，而不是返回固定答案。

## 5. 验收结果（对应题面六项）

| 必做项 | 结果 | 证据 |
| --- | --- | --- |
| 能够运行 | `verify_all.sh` 从空状态一键跑通 | `evidence/verification-summary.json` |
| MiniMax 实际参与 | 一次调用即生成可用补丁，30 测试转绿 | `dev-records/*-minimax-dev-run.json`、`evidence/dev-record-check.json` |
| 上下文正确 | 规格/代码/测试来源齐全，规格更新后刷新 | `evidence/context-empty-state.check.json`、`context-after-spec-update.check.json` |
| 数据库实际参与 | seekdb 建索引并逐次查询，`MATCH … AGAINST` 留痕 | `evidence/import.json`、`evidence/db-queries.log` |
| 状态能够复用 | 空状态写入，重启进程读回并注入上下文 | `evidence/powercontext-save.json`、`evidence/powercontext-reload.json` |
| 代码修改有效 | 改前 15 failed（AssertionError），改后 30 passed | `evidence/test-before.log`、`evidence/test-after.log` |