# MiniMax × OceanBase · 规有所依：SDD 上下文管理系统

本题（平台题号 **600077**，20 分）要求围绕规格驱动开发（Spec-Driven Development）实现一个工程上下文模块：根据开发任务找出当前有效的规格、相关代码和测试，交给使用 **MiniMax** 的开发助手完成一次真实代码修改，并用 **PowerContext** 保存/复用任务状态、用 **seekdb** 存储并检索工程资料。

本目录即提交物，基线仓库分支 `2026-competition-ecosystem`。

## 1. 一次真实开发任务的闭环

| 环节 | 本仓库中的实现 |
| --- | --- |
| 业务工程 | `sample_app/`（`ordercore` 计费服务，SPEC-ORD-001 从 v1 演进到 v2） |
| 工程资料导入 seekdb | `context_module/sdd_context` 的 `import`：规格 Markdown、`src/` 代码单元、`tests/` 测试函数入表，建 FULLTEXT 索引 |
| 任务上下文选择 | `context`：按任务声明的规格 id、提示符号/文件和关键词检索，输出规格条目、待改代码（含行号锚点）、目标/回归测试、任务状态 |
| MiniMax 实际改代码 | `dev-run`：把上下文渲染成提示词调用 MiniMax（OpenAI 兼容接口），解析 unified diff 并应用，落 `dev-records/` 开发记录 |
| 验证 | 改前目标测试 15 failed（AssertionError），改后 15+15 全通过 |
| 状态复用 | `state-save` / `state-show`：PowerContext 记忆写入与跨进程读取，读回的状态进入下一次上下文 |

## 2. 技术分工（三项均为真实参与）

| 技术 | 实际承担的作用 | 证据 |
| --- | --- | --- |
| **MiniMax**（`MiniMax-M3.1-Flash`，订阅 Key，OpenAI 兼容接口） | 读取上下文后生成 `pricing.py` 的修改补丁，一次成功应用 | `dev-records/*-minimax-dev-run.json`（请求上下文摘要、响应、token 用量、补丁、测试结果） |
| **seekdb**（嵌入式 `pylibseekdb`，备选 server 模式） | 存储 3 条规格、13 个代码单元、30 个测试函数，建 `min_token_size=2` 的 FULLTEXT 索引；上下文里的规格/代码/测试全部来自 SQL 查询 | `evidence/db-queries.log`、`evidence/import.json`（`fulltext: true`） |
| **PowerContext**（`powercontext==1.2.0` SDK，Builtin runtime） | 保存任务进展（status/done/todo/verifications）到 Memory，模块重启后按任务 id 读回并注入下一次上下文 | `evidence/powercontext-save.json`、`evidence/powercontext-reload.json` |

## 3. 依赖与安装

要求：**Linux x86_64**、Python ≥ 3.11（实测 3.12.3）、可联网安装 wheel。

```bash
cd minimax
pip install -r requirements.txt
```

关键依赖（`requirements.txt` 已锁定）：

- `powercontext[seekdb]==1.2.0`（含 Builtin runtime、`pylibseekdb`、PyMySQL）
- `PyMySQL==1.2.0`：`aiomysql 0.3.2` 需要 1.x 的转换器 API，新版 PyMySQL 会让所有查询报 `'str' object is not callable`
- `PyYAML>=6,<7`、`pytest==9.0.2`

## 4. 配置

```bash
cp .env.example .env
# 必填：MINIMAX_API_KEY=sk-cp-...（官方订阅 Key，仅复现 dev-run 时需要）
```

其余默认值即可：`SDD_SEEKDB_MODE=embedded`、`POWERCONTEXT_BACKEND=seekdb`。
若仓库放在 Windows 盘符下再用 WSL 运行，嵌入版 seekdb 需要原生文件系统，请设置
`export SDD_DATA_DIR=/var/tmp/minimax-runtime`。

## 5. 数据初始化与调用入口

模块入口是 CLI（也可作为 Python 包 import）：

```bash
cd minimax/context_module
export PYTHONPATH=$PWD

python3 -m sdd_context doctor          # 环境自检
python3 -m sdd_context import --reset  # 导入规格/代码/测试并建索引
python3 -m sdd_context context --with-state --out ../evidence/context.json --md ../evidence/context.md
python3 -m sdd_context verify-context --context ../evidence/context.json --expect ../expectations.json
python3 -m sdd_context state-save --task-id TASK-ORD-PRICING-V2 --state-file state.json
python3 -m sdd_context state-show --task-id TASK-ORD-PRICING-V2
python3 -m sdd_context dev-run --context ../evidence/context.json --repo <repo-root>
```

`context` 输出 JSON（机器核对）与 Markdown（人读）两份；JSON 中每条来源都带
`path` / `anchor` / `line_start` / `line_end`，可用 `verify-context` 按
`expectations.json` 校验是否包含规定的规格、代码和测试来源。

## 6. 验证

一键端到端（六项必做逐条检查，约 1–2 分钟）：

```bash
bash minimax/scripts/verify_all.sh
```

脚本会从**空状态**开始：重置 `runtime/`、建索引、生成上下文、跑改前/改后测试、
写读 PowerContext 状态、核对开发记录与代码差异、做一次规格更新 → 重新导入 → 回滚，
最后输出 `ALL CHECKS PASSED` 与 `evidence/verification-summary.json`。

业务工程自身的测试：

```bash
cd minimax/sample_app && python3 -m pytest tests -q   # 30 passed
```

样例说明见 [`docs/validation-example.md`](docs/validation-example.md)，
六项验收对照见 [`docs/acceptance-matrix.md`](docs/acceptance-matrix.md)，
一页技术说明见 [`TECHNICAL_NOTE.md`](TECHNICAL_NOTE.md)。

## 7. 材料清单

| 材料 | 位置 |
| --- | --- |
| 完整源码（上下文模块、MiniMax 接入、业务工程） | `context_module/`、`sample_app/`、`scripts/` |
| 运行说明 | 本文件 |
| 验证样例（任务/有效规格/初始数据/步骤/预期/重置） | `docs/validation-example.md` |
| 修改前代码快照 / 修改后代码 / 差异 | `sample_app/baseline/pricing.py`、`sample_app/src/ordercore/pricing.py`、`evidence/code-diff.patch` |
| 新增功能测试 / 回归测试 / 运行日志 | `sample_app/tests/`、`evidence/test-before.log`、`evidence/test-after.log` |
| MiniMax 开发记录 | `dev-records/*-minimax-dev-run.json`、`dev-records/summary.md` |
| 数据库查询记录 | `evidence/db-import.log`、`evidence/db-queries.log` |
| PowerContext 状态写入/复用记录 | `evidence/powercontext-save.json`、`evidence/powercontext-reload.json` |
| 一页技术说明 | `TECHNICAL_NOTE.md` |
| 验收汇总 | `evidence/verification-summary.json` |

## 8. 已知限制

- 嵌入式 seekdb（`pylibseekdb`）只提供 Linux/macOS wheel；Windows 上请用 WSL 或
  `SDD_SEEKDB_MODE=server` 连接已有 seekdb 服务。WSL 访问 `/mnt/<盘符>` 时需设置
  `SDD_DATA_DIR` 到原生目录。
- PowerContext 默认 `seekdb` 后端；若环境里 PyMySQL 版本与 `aiomysql 0.3.2` 不兼容，
  可 `POWERCONTEXT_BACKEND=sqlite` 降级（任务状态语义不变）。
- `dev-run` 需要 MiniMax 订阅 Key；模型的补丁不保证比特级可重现，提交物以
  `dev-records/` 中记录的那次真实调用与已提交代码差异为准。
- 上下文选择是确定性的关键词/符号匹配（不做语义向量检索），换取可复现与可核对；
  `materials.py` 的中文切分采用字符二元组以适配 seekdb 的 space 解析器。
- 样本工程有意保持小体量（13 个代码单元、30 个测试），便于评审逐条核对来源。