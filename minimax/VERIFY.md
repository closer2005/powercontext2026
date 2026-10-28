# VERIFY —— speckit 验证样例

> 本文给出**可直接照做**的验证样例：任务描述、有效规格、初始数据、操作步骤、预期结果与重置方法。
> 契约以 `minimax/DESIGN.md` 为权威；运行细节见 `minimax/README.md`。

文中所有命令都在 `minimax/` 目录下执行：

```bash
cd minimax
```

---

## 1. 任务描述

```
实现订单按状态筛选
```

对应业务需求：`demo_project/orders/service.py::list_orders` 需支持 `status` 参数过滤
（`status=None` 时不过滤）。现状：`status` 分支为 `# TODO: status filter not implemented yet`，传入后被忽略。

---

## 2. 有效规格

由 `data/specs.json` 提供的**权威规格**（本任务直接相关的关键一条为 `SPEC-ORD-3`）：

| id | title | scope | keywords |
|---|---|---|---|
| `SPEC-ORD-1` | 订单列表默认返回全部订单 | orders | 列表 / 全部 / 默认 |
| `SPEC-ORD-2` | 支持按最低金额过滤 | orders | 金额 / 最低 |
| **`SPEC-ORD-3`** | **订单列表必须支持按状态筛选** | orders | **状态 / 筛选 / status** |
| `SPEC-ORD-4` | 筛选结果保持原有排序 | orders | 排序 |

`SPEC-ORD-3` 正文：

> `list_orders` 需接受 `status` 参数，仅返回匹配状态的订单；`status` 为 None 时不过滤。
> 合法状态取值为 paid / pending / cancelled。

---

## 3. 初始数据（改动前）

| 数据文件 | 条目数 | 关键条目 |
|---|---|---|
| `data/specs.json` | 4 | `SPEC-ORD-1` … `SPEC-ORD-4` |
| `data/code_index.json` | 1 | `CODE-ORD-1`（`demo_project/orders/service.py::list_orders`） |
| `data/tests_index.json` | 4 | `TEST-ORD-T`、`TEST-ORD-B1`、`TEST-ORD-B2`、`TEST-ORD-B3` |

测试现状（**修改前**）：

| 测试文件 | 用例 | 结果 |
|---|---|---|
| `test_orders_baseline.py` | `test_list_orders_returns_all` | PASS |
| `test_orders_baseline.py` | `test_filter_by_min_amount` | PASS |
| `test_orders_baseline.py` | `test_sorted_by_id` | PASS |
| `test_orders_target.py` | `test_filter_by_status` | **FAIL** |

合计：**1 failed, 3 passed**。

---

## 4. 上下文中必须包含的来源

`python -m speckit.cli build --task "实现订单按状态筛选"` 的输出中，
以下三项 `source` 是判定「SDD 上下文正确」的**硬性要求**，必须出现：

| 必须包含的 source | 对应条目 | 类型 |
|---|---|---|
| `data/specs.json#SPEC-ORD-3` | 订单列表必须支持按状态筛选 | 规格 |
| `data/code_index.json#CODE-ORD-1` | `list_orders` 符号索引 | 代码 |
| `data/tests_index.json#TEST-ORD-T` | `test_filter_by_status` | 测试 |

核对方式（在 `build` 输出中检索这三个字符串）：

```bash
python -m speckit.cli build --task "实现订单按状态筛选" | grep -E "SPEC-ORD-3|CODE-ORD-1|TEST-ORD-T"
```

三者都命中，即视为「规格—代码—测试」三要素齐备，上下文正确。

---

## 5. 操作步骤

### 步骤 0：环境准备

```bash
python -m pip install -r requirements.txt
# 配置 .env（复制 .env.example），并确保 seekdb 已启动、可连接
```

### 步骤 1：初始化索引

```bash
python -m speckit.cli init
```

### 步骤 2：组装上下文并核对来源

```bash
python -m speckit.cli build --task "实现订单按状态筛选"
```

查看 JSON 输出，确认 §4 的三个 `source` 均出现。

### 步骤 3：修改前测试（before）

```bash
python -m speckit.cli verify
```

### 步骤 4：调用 MiniMax 生成候选补丁（需 Key）

```bash
python -m speckit.cli draft --task "实现订单按状态筛选"
```

产生 `evidence/candidate_service.py`、`evidence/diff.patch`、`evidence/minimax_session.json`。

> **待补齐**：本步需要 `MINIMAX_API_KEY`（Key 到位后补跑，并回填 `TECH_USAGE.md` §1）。

### 步骤 5：应用补丁

```bash
python -m speckit.cli apply --patch evidence/diff.patch
```

产生 `evidence/before/service.py`、`evidence/after/service.py`、`evidence/diff.patch`。

### 步骤 6：修改后测试（after）

```bash
python -m speckit.cli verify --after
```

### 步骤 7：保存任务状态

```bash
python -m speckit.cli save --state-file task_state.json
```

### 步骤 8：另起进程读取状态

**新开一个终端 / 新起一个进程**（不要在同一 shell 里紧接执行，以体现「跨进程复用」）：

```bash
python -m speckit.cli resume --state-file task_state.json
```

---

## 6. 预期结果

| 步骤 | 命令 | 预期 |
|---|---|---|
| 1 | `init` | 打印 `specs=4 code=1 tests=4` |
| 2 | `build` | JSON 含 `SPEC-ORD-3` / `CODE-ORD-1` / `TEST-ORD-T` 三个 source |
| 3 | `verify` | 目标 FAIL、回归 PASS → 返回码 `1`；写 `evidence/test_before.log` |
| 4 | `draft` | 写 `evidence/candidate_service.py` + `evidence/diff.patch` + `evidence/minimax_session.json` |
| 5 | `apply` | 改写 `service.py`，写 `evidence/before|after/service.py` |
| 6 | `verify --after` | 目标 PASS、回归 PASS → 返回码 `0`；写 `evidence/test_after.log` |
| 7 | `save` | 打印 `状态已保存：local-json:...` 与 `backend=...` |
| 8 | `resume` | 打印含 `done` / `todo` / `evidence` 的 JSON 与 `[backend]` |

核心判定（对应 DESIGN §1「代码修改有效」「状态能够复用」）：

- `test_orders_target.py::test_filter_by_status`：**步骤 3 FAIL → 步骤 6 PASS**。
- `test_orders_baseline.py` 三例：**步骤 3 与步骤 6 均 PASS**。
- `resume` 在**另一个进程**中成功读到 `save` 写入的 `done / todo / evidence`。

---

## 7. 「规格更新后重跑，输出必须变化」对照步骤

本项证明 `build` 的输出**来自 seekdb 检索**，而非写死的固定答案。

> ⚠️ 该对照会**临时修改** `data/specs.json`，验证后**必须还原**（见 7.4）。

### 7.1 基线输出

```bash
python -m speckit.cli build --task "实现订单按状态筛选" | grep "SPEC-ORD-3"
```

基线预期：`SPEC-ORD-3` **出现**在 `specs[]` 中（命中「状态 / 筛选 / status」关键词），
且分数较高（含 scope 加成）。

### 7.2 临时修改规格

编辑 `data/specs.json` 中的 `SPEC-ORD-3`，把它改成与「状态筛选」不再相关的规格，例如：

```json
{
  "id": "SPEC-ORD-3",
  "title": "库存盘点结果导出为 CSV",
  "scope": "orders",
  "keywords": ["库存", "导出", "csv"],
  "text": "盘点结果需支持导出为 CSV 文件，字段包含 id 与数量。"
}
```

### 7.3 重新 init + build，观察差异

```bash
python -m speckit.cli init
python -m speckit.cli build --task "实现订单按状态筛选" | grep "SPEC-ORD-3"
```

**必须**观察到输出发生变化，例如：

- `SPEC-ORD-3` 从 `specs[]` 中**消失**（关键词不再命中）；或
- 即便仍出现，其 `title` / `score` 也随新规格内容改变。

任一变化成立，即证明 `build` 的输出随 `data/specs.json` 变化，检索确由 seekdb 驱动。

### 7.4 还原（务必执行）

把 `data/specs.json` 中 `SPEC-ORD-3` 恢复为原始内容（`keywords: ["状态","筛选","status"]`，
`title: "订单列表必须支持按状态筛选"`），然后重跑：

```bash
python -m speckit.cli init
python -m speckit.cli build --task "实现订单按状态筛选" | grep "SPEC-ORD-3"
```

确认 `SPEC-ORD-3` 重新以原内容出现，即完成还原。
（若仓库纳入版本控制，可直接 `git checkout -- minimax/data/specs.json`。）

---

## 8. 重置方法

### 8.1 重置业务代码（撤销 `apply`）

```bash
# 用修改前快照覆盖（若 evidence/before/service.py 已生成）
cp evidence/before/service.py demo_project/orders/service.py
```

或（版本控制下）：

```bash
git checkout -- minimax/demo_project/orders/service.py
```

重置后 `verify` 应回到「1 failed, 3 passed」。

### 8.2 清理运行产物

```bash
rm -rf evidence
rm -f .powercontext/task_state.json
```

> 删除 `evidence/` 与 `task_state.json` 后，可重新从 §5 步骤 1 完整复现；
> 二者会在相关命令运行时自动重建。

### 8.3 重置 seekdb 数据（可选）

索引为幂等 `INSERT ... ON DUPLICATE KEY UPDATE`，重复 `init` 不会产生重复数据。
如需彻底清空，可在 seekdb 侧执行：

```sql
DROP DATABASE IF EXISTS speckit;
```

随后用 `python -m speckit.cli init` 重新建库建表并导入。

### 8.4 重置后自检

```bash
python -m speckit.cli verify   # 期望：1 failed, 3 passed（返回码 1）
```

---

## 9. 一键复现

上述步骤可由脚本一次性执行：

```bash
bash scripts/run_all.sh
```

（需 seekdb 可用；`draft` / `apply` 需 `MINIMAX_API_KEY`，或设 `SPECKIT_AUTO_MINIMAX=1` 自动执行。）