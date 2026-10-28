# MiniMax 赛题作品设计契约（先行固化，供各模块实现对齐）

> 题目：规有所依——面向软件持续演进的 SDD 上下文管理系统（题目 600077，20 分）
> 目标：六项必做项全部通过。本文件是所有子模块必须遵守的接口契约。

## 1. 六项必做项 → 对应实现

| 验收项 | 由什么保证 |
|---|---|
| 能够运行 | `scripts/run_all.sh` 一键：装依赖 → `ctx init` → `ctx build` → `ctx verify`（含修改前后测试）|
| MiniMax 实际参与 | `speckit/minimax.py` 真实调用 MiniMax（OpenAI 兼容），产出 `evidence/diff.patch`；`TECH_USAGE.md` 记录请求/上下文/响应与 diff 的对应 |
| 上下文正确 | `ctx build` 输出规格/代码/测试的来源 id；改 `data/specs.json` 后重跑 `ctx init` + `ctx build`，输出随之变化（有测试断言）|
| 数据库实际参与 | seekdb 存 specs/code/tests 索引，`ctx build` 的检索结果来自 SQL/向量查询，日志留痕 |
| 状态能够复用 | PowerContext 写任务状态；`ctx save` → 进程退出 → 新进程 `ctx resume` 读取并用于后续输出 |
| 代码修改有效 | 目标测试 `test_orders_target.py::test_filter_by_status` 修改前 FAIL、修改后 PASS；回归 `test_orders_baseline.py` 全程 PASS |

## 2. 目录与文件契约

```
minimax/
├── README.md                  # 运行说明
├── DESIGN.md                  # 本文件（一页技术说明的底稿）
├── VERIFY.md                  # 验证样例
├── TECH_USAGE.md              # 技术使用记录
├── requirements.txt
├── .env.example               # 占位凭据，禁止真实值
├── speckit/                   # 上下文模块（核心交付物）
│   ├── __init__.py
│   ├── config.py              # 读环境变量：SEEKDB_*、POWERCONTEXT_*、MINIMAX_*
│   ├── store.py               # seekdb 存取：init_schema / upsert_* / search
│   ├── selector.py            # 上下文选择：关键词打分 + 结构化过滤，返回带来源的结果
│   ├── state.py               # PowerContext 封装：save_progress / load_progress
│   ├── minimax.py             # MiniMax 调用封装：chat(prompt) -> text
│   ├── patch.py               # 应用/生成补丁
│   └── cli.py                 # 命令入口（见 §4）
├── demo_project/              # 可运行业务工程（自带测试）
│   ├── orders/__init__.py
│   ├── orders/service.py      # list_orders(orders, status=None, min_amount=None)
│   ├── orders/models.py
│   └── tests/
│       ├── test_orders_baseline.py   # 回归：修改前后都必须 PASS
│       └── test_orders_target.py     # 目标：修改前 FAIL、修改后 PASS
├── data/
│   ├── specs.json             # 规格条目
│   ├── code_index.json        # 符号索引
│   └── tests_index.json       # 测试索引
├── scripts/
│   ├── init_data.py           # 初始化 seekdb 数据
│   └── run_all.sh             # 一键复现
└── evidence/
    ├── before/service.py      # 修改前快照
    ├── after/service.py       # 修改后快照
    ├── diff.patch
    ├── test_before.log
    ├── test_after.log
    └── minimax_session.json   # MiniMax 请求/响应留痕
```

## 3. 数据契约

### 3.1 规格 `data/specs.json`

```json
[
  {"id": "SPEC-ORD-1", "title": "订单列表默认返回全部订单", "scope": "orders", "keywords": ["列表", "全部", "默认"], "text": "..."},
  {"id": "SPEC-ORD-2", "title": "支持按最低金额过滤", "scope": "orders", "keywords": ["金额", "最低"], "text": "..."},
  {"id": "SPEC-ORD-3", "title": "订单列表必须支持按状态筛选", "scope": "orders", "keywords": ["状态", "筛选", "status"], "text": "list_orders 需接受 status 参数，仅返回匹配状态的订单"},
  {"id": "SPEC-ORD-4", "title": "筛选结果保持原有排序", "scope": "orders", "keywords": ["排序"], "text": "..."}
]
```

### 3.2 代码索引 `data/code_index.json`

```json
[
  {"id": "CODE-ORD-1", "file": "demo_project/orders/service.py", "symbol": "list_orders", "keywords": ["列表", "筛选", "status"], "text": "def list_orders(orders, status=None, min_amount=None): ..."}
]
```

### 3.3 测试索引 `data/tests_index.json`

```json
[
  {"id": "TEST-ORD-T", "file": "demo_project/tests/test_orders_target.py", "name": "test_filter_by_status", "keywords": ["状态", "筛选"], "text": "..."},
  {"id": "TEST-ORD-B1", "file": "demo_project/tests/test_orders_baseline.py", "name": "test_list_orders_returns_all", "keywords": ["全部"], "text": "..."}
]
```

## 4. CLI 契约（`python -m speckit.cli <cmd>`）

| 命令 | 作用 | 关键输出 |
|---|---|---|
| `init` | 建表并把 data/ 三份索引导入 seekdb | 各类条目数 |
| `build --task "..."` | 检索并组装上下文 | JSON：`specs[] / code[] / tests[] / progress`（每项带 `source`）|
| `draft --task "..."` | 把上下文喂给 MiniMax，得到补丁文本 | `evidence/minimax_session.json` + 候选补丁 |
| `apply --patch <file>` | 应用补丁到 demo_project | 改写后的 `service.py` |
| `verify` | 跑目标测试 + 回归测试，记录日志 | `evidence/test_before.log` / `test_after.log` |
| `save --state-file <f>` | 用 PowerContext 保存任务状态 | 状态 id |
| `resume --state-file <f>` | 新进程读取状态 | `done / todo / evidence` |

要求：`build` 每次进程独立；`resume` 必须是**另起进程**读取（验证"状态复用"）。

## 5. 业务工程的任务定义

- 现状：`list_orders(orders, status=None, min_amount=None)` 中 **`status` 参数未实现过滤**（仅 `min_amount` 生效）。
- 目标测试：`test_filter_by_status` 断言 `list_orders(orders, status="paid")` 只返回 paid 订单 → 现状 **FAIL**。
- 回归测试：`test_list_orders_returns_all`、`test_filter_by_min_amount` → 现状 **PASS**，改后仍 **PASS**。
- 修改点仅限 `demo_project/orders/service.py` 的 `status` 分支，不得改测试、不得改断言。

## 6. 技术分工

| 技术 | 承担 | 接入方式 |
|---|---|---|
| MiniMax | 生成 `status` 过滤的实现片段 | HTTP API（OpenAI 兼容），封装在 `speckit/minimax.py` |
| seekdb | 存 specs/code/tests 索引；`build` 的检索来自它 | PyMySQL（远程 2881），封装在 `speckit/store.py` |
| PowerContext | 保存/读取任务进展（done/todo/evidence） | `powercontext` 官方包，封装在 `speckit/state.py` |

## 7. 环境变量（`.env.example` 里全是占位）

```
SEEKDB_HOST=127.0.0.1
SEEKDB_PORT=2881
SEEKDB_USER=root
SEEKDB_PASSWORD=
SEEKDB_DATABASE=speckit
MINIMAX_API_KEY=<your-key>
MINIMAX_BASE_URL=https://api.minimax.chat/v1
MINIMAX_MODEL=MiniMax-Text-01
POWERCONTEXT_STATE_DIR=.powercontext
```

## 8. 一律禁止

- 提交真实凭据、Token、私钥
- 修改/跳过测试或断言来"让它过"
- `build` 返回写死的固定答案（必须来自 seekdb 检索，且规格更新后结果会变）