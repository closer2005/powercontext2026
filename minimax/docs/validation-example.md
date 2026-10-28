# 验证样例

> 任务：`TASK-ORD-PRICING-V2` · 业务工程：`sample_app/`（`ordercore` 计费服务）
> 本文件给出「要改什么」「哪些原有行为必须保持」以及评审可逐条核对的步骤与预期。

## 1. 任务描述

按 **SPEC-ORD-001 revision 2**（2026-11-01 生效）改造 `ordercore` 计价：

1. 取消「满 3 件 95 折」体积折扣（`volume_discount_cents` 恒为 0）；
2. gold 会员且订单满 3 件时额外减 **500 分**；
3. 满 5 件免运费，未满 5 件按区域收运费：**east 800 分 / west 1200 分**；
4. 计算顺序：会员折扣 → 优惠券 → gold 奖励 → 运费；
5. 金额保持整数分、总价下限 0。

机器可读的任务声明在 `sample_app/task.yaml`（含 `specs`、`target_tests`、`regression_tests`、
`hints.symbols`、`hints.paths`）。

## 2. 初始数据（提交物内自带，无需外部文件）

| 数据 | 位置 | 说明 |
| --- | --- | --- |
| 生效规格 v2 | `sample_app/specs/SPEC-ORD-001.v2.md` | revision 2，`status: active`，含 C1–C5 变更与 R1–R7 规则 |
| 历史规格 v1 | `sample_app/specs/SPEC-ORD-001.v1.md` | revision 1，导入后应自动标为 `superseded`，不得出现在上下文 |
| 不变量规格 | `sample_app/specs/SPEC-ORD-002.v1.md` | 金额整数分、总价非负、空单为 0 等 |
| 基线代码 | `sample_app/baseline/pricing.py` | 修改前快照（v1 规则实现） |
| 当前代码 | `sample_app/src/ordercore/pricing.py` | MiniMax 修改后的实现 |
| 目标测试（改前红/改后绿） | `sample_app/tests/test_pricing_target.py` | 15 个用例 |
| 回归测试（前后都必须绿） | `sample_app/tests/test_pricing_regression.py` | 15 个用例 |

## 3. 操作步骤

```bash
cd minimax
pip install -r requirements.txt
cp .env.example .env      # 仅在复现 dev-run 时需要填 MINIMAX_API_KEY

export PYTHONPATH=$PWD/context_module
export SDD_SEEKDB_MODE=embedded          # 默认值；WSL 访问 Windows 盘符时另设 SDD_DATA_DIR
python3 -m sdd_context import --reset    # 1) 导入并建索引
python3 -m sdd_context context --out evidence/context-empty-state.json \
        --md evidence/context-empty-state.md                       # 2) 生成上下文
python3 -m sdd_context verify-context --context evidence/context-empty-state.json \
        --expect expectations.json                                 # 3) 核对来源
python3 -m sdd_context state-save --task-id TASK-ORD-PRICING-V2 --state-file <state.json>
python3 -m sdd_context state-show --task-id TASK-ORD-PRICING-V2   # 4) 状态写入/读回
(cd sample_app && python3 -m pytest tests -q)                      # 5) 测试
bash scripts/verify_all.sh                                         # 一键复核（含规格更新演示）
```

重置方法：`rm -rf minimax/runtime`（或删除 `$SDD_DATA_DIR`）即可回到空状态；重新执行
`import --reset` 会重建表与索引。代码层面 `git checkout -- minimax/sample_app/src` 可回到基线。

## 4. 预期结果（评审可逐条核对）

**4.1 上下文必须包含的来源**

| 类型 | 必备内容 |
| --- | --- |
| 规格 | `SPEC-ORD-001#r2`（含「取消满 3 件 95 折」「gold 会员满 3 件额外减 500 分」「满 5 件免运费」「east 800 分、west 1200 分」「会员折扣 → 优惠券 → gold 奖励 → 运费」）、`SPEC-ORD-002#r1`（含「总价下限 0」「空订单为 0」） |
| 规格（禁止） | `SPEC-ORD-001#r1` 不得出现（已被 revision 2 取代） |
| 代码 | `src/ordercore/pricing.py::final_price_cents`、`::loyalty_bonus_cents`、`::shipping_fee_cents`、`::volume_discount_cents`（并包含 `models.py` 的 `Item`/`Customer`/`Coupon`） |
| 目标测试（15） | `test_gold_member_with_three_items_gets_extra_500_off` … `test_total_floor_still_applies_after_shipping`（名单见 `expectations.json`） |
| 回归测试（15） | `test_subtotal_sums_line_totals` … `test_final_price_does_not_mutate_inputs`（名单见 `expectations.json`） |

**4.2 行为验证**

| 检查 | 预期 |
| --- | --- |
| 改前（`baseline/pricing.py`）跑目标测试 | **15 failed**，失败类型为 `AssertionError`（不是 ImportError/环境错误） |
| 改后跑全部测试 | **30 passed**（15 目标 + 15 回归） |
| 规格更新后重新导入 | 上下文出现 `DEMO-SPEC-UPDATE-MARKER` 与「额外减 600 分」；撤销并重新导入后 marker 消失 |
| 数据库 | `import.json` 中 `fulltext: true`，`db-queries.log` 含 `MATCH(tokenized) AGAINST (...)` 查询 |
| 状态复用 | 进程 1 `state-save` 写入，进程 2 `state-show` 读出 `task_id/status/done/todo/verifications`，进程 3 `context --with-state` 中 `state_loaded: true` |
| MiniMax 参与 | `dev-records/*-minimax-dev-run.json` 含上下文摘要、模型响应、token 用量、补丁与 30 测试通过结果；`check_dev_record.py` 证明其与提交代码差异一致 |

## 5. 一句话概括

「要改什么」= SPEC-ORD-001 v2 的 C1–C5；「必须保持」= SPEC-ORD-002 的 I1–I4
与 15 条回归测试；上下文模块必须找出这些来源并交给 MiniMax 完成修改，且测试前后红绿可复现。