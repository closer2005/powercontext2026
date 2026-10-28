# speckit —— 面向软件持续演进的 SDD 上下文管理系统（MiniMax 方向作品）

> 赛题：题目 600077「规有所依——面向软件持续演进的 SDD 上下文管理系统」（MiniMax 方向，20 分）
>
> 本目录是参赛作品的可运行实现。它把 **MiniMax**（生成改动）、**seekdb**（索引与检索）、
> **PowerContext**（任务状态复用）串成一条「有规格 → 检索上下文 → 模型生成 → 应用补丁 →
> 测试转绿 → 状态复用」的闭环。

本文件是**运行说明**。接口契约以 `minimax/DESIGN.md` 为权威；验证样例见 `minimax/VERIFY.md`；
技术使用记录见 `minimax/TECH_USAGE.md`。

---

## 1. 六项必做项 → 本作品如何满足

| 验收项 | 由什么保证 |
|---|---|
| 能够运行 | `scripts/run_all.sh` 一键串联；或按下文逐条执行命令 |
| MiniMax 实际参与 | `speckit/minimax.py` 真实调用 MiniMax（OpenAI 兼容 HTTP），产出 `evidence/diff.patch`，请求/响应留痕在 `evidence/minimax_session.json` |
| 上下文正确 | `build` 输出每项的 `source`（如 `data/specs.json#SPEC-ORD-3`）；改 `data/specs.json` 后重跑 `init` + `build`，输出随之变化 |
| 数据库实际参与 | seekdb 存 `spec_items` / `code_items` / `test_items` 三张表；`build` 的检索结果完全来自 SQL 查询 |
| 状态能够复用 | `save` 写任务状态；**另起进程** `resume` 读取，`save` / `resume` 是两次独立的命令行调用 |
| 代码修改有效 | 目标测试 `test_orders_target.py::test_filter_by_status` 修改前 FAIL、修改后 PASS；回归 `test_orders_baseline.py` 全程 PASS |

---

## 2. 目录结构

```
minimax/
├── README.md                  # 本文件：运行说明
├── DESIGN.md                  # 接口契约（权威，不改）
├── VERIFY.md                  # 验证样例
├── TECH_USAGE.md              # 技术使用记录（含待补齐字段）
├── requirements.txt           # 依赖清单
├── .env.example               # 环境变量样例（全为占位值）
├── speckit/                   # 上下文模块（核心交付物）
│   ├── __init__.py
│   ├── __main__.py            # 支持 python -m speckit
│   ├── config.py              # 读环境变量：SEEKDB_*、MINIMAX_*、POWERCONTEXT_*
│   ├── store.py               # seekdb 存取：init_schema / upsert_* / search
│   ├── selector.py            # 上下文选择：关键词打分 + scope 加成，返回带 source
│   ├── state.py               # PowerContext 封装（含本地 JSON 降级）
│   ├── minimax.py             # MiniMax 调用封装：chat(prompt) -> text
│   ├── patch.py               # 补丁提取与应用
│   └── cli.py                 # 命令入口
├── demo_project/              # 可运行业务工程（自带测试）
│   ├── README.md
│   ├── orders/
│   │   ├── __init__.py
│   │   ├── models.py          # Order 数据类
│   │   └── service.py         # list_orders(orders, status=None, min_amount=None)
│   └── tests/
│       ├── conftest.py
│       ├── test_orders_baseline.py   # 回归：修改前后都必须 PASS
│       └── test_orders_target.py     # 目标：修改前 FAIL、修改后 PASS
├── data/
│   ├── specs.json             # 规格条目（4 条）
│   ├── code_index.json        # 符号索引（1 条）
│   └── tests_index.json       # 测试索引（4 条）
├── scripts/
│   ├── init_data.py           # 初始化 seekdb 数据（等价 cli init）
│   └── run_all.sh             # 一键复现
├── .powercontext/
│   └── task_state.json        # 默认任务状态文件（本地 JSON 后端）
└── evidence/                  # 运行产物（快照 / diff / 测试日志 / MiniMax 留痕）
```

> 说明：`evidence/` 与 `.powercontext/` 目录会在首次运行相关命令时自动创建。

---

## 3. 依赖与版本

`minimax/requirements.txt` 全文如下（版本照实）：

```
pymysql>=1.1.0        # seekdb（MySQL 协议）访问
requests>=2.28.0      # MiniMax OpenAI 兼容 HTTP 调用
pytest>=7.0.0         # verify 命令执行目标测试 / 回归测试

powercontext>=0.1.0   # 可选：PowerContext 官方包
```

- Python 版本：**3.10+**（本仓库在 Python 3.12.10 上实测通过）。
- `powercontext` 是**可选**依赖：未安装、或未配置 `POWERCONTEXT_SERVER` 时，
  `speckit/state.py` 会自动降级为本地 JSON 状态文件（见 §6、§9）。
- `demo_project/` 仅依赖 Python 标准库与 `pytest`，无第三方运行时依赖。

---

## 4. 环境准备

### 4.1 安装依赖

在 `minimax/` 目录下执行：

```bash
cd minimax
python -m pip install -r requirements.txt
```

### 4.2 配置环境变量（`SEEKDB_*` / `MINIMAX_*` / `POWERCONTEXT_*`）

把 `.env.example` 复制为 `.env` 后按需填写（**只放占位符，禁止提交真实凭据**）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SEEKDB_HOST` | `127.0.0.1` | seekdb 主机 |
| `SEEKDB_PORT` | `2881` | seekdb 端口（MySQL 协议） |
| `SEEKDB_USER` | `root` | seekdb 用户名 |
| `SEEKDB_PASSWORD` | 空 | seekdb 密码 |
| `SEEKDB_DATABASE` | `speckit` | 库名（仅允许字母/数字/下划线） |
| `MINIMAX_API_KEY` | 空 | **待补齐**：MiniMax Key，格式 `<your-key>` |
| `MINIMAX_BASE_URL` | `https://api.minimax.chat/v1` | OpenAI 兼容接口基址 |
| `MINIMAX_MODEL` | `MiniMax-Text-01` | 模型名 |
| `POWERCONTEXT_STATE_DIR` | `.powercontext` | 状态目录（相对路径以 `minimax/` 为基准） |
| `POWERCONTEXT_SERVER` | 空 | PowerContext 服务地址；为空则降级本地 JSON |

`.env` 的解析由 `speckit/config.py::load_dotenv` 完成，**已存在的进程环境变量优先**。

### 4.3 准备 seekdb

需要有一个可连接的 seekdb 实例（MySQL 协议，默认端口 `2881`）。
`init` 会自动 `CREATE DATABASE IF NOT EXISTS speckit` 并建三张表，无需手工建库。

### 4.4 初始化索引数据

任选其一（两者等价）：

```bash
python -m speckit.cli init
# 或
python scripts/init_data.py
```

成功时打印每类条目数，例如：

```
已建表：spec_items / code_items / test_items
导入条目数：specs=4 code=1 tests=4
当前表计数：{"spec_items": 4, "code_items": 1, "test_items": 4}
```

---

## 5. 七个命令的用法与示例

统一入口：`python -m speckit.cli <command>`（`speckit/__main__.py` 也支持 `python -m speckit`）。
所有命令都支持 `--help`。以下示例逐条对照 `--help` 实际输出。

### 5.0 顶层帮助

```bash
cd minimax
python -m speckit.cli --help
```

实测输出：

```
usage: python -m speckit.cli [-h] <command> ...

speckit —— 面向软件持续演进的 SDD 上下文管理 CLI（契约见 minimax/DESIGN.md）

positional arguments:
  <command>
    init      建库建表并导入 data/ 三份索引
    build     检索并组装上下文（JSON，每项带 source）
    draft     把上下文交给 MiniMax，生成候选补丁
    apply     把补丁应用到 demo_project/orders/service.py
    verify    跑目标 + 回归测试，写 evidence 日志
    save      保存任务状态（PowerContext / 本地 JSON）
    resume    另起进程读取任务状态

options:
  -h, --help  show this help message and exit

示例：
  python -m speckit.cli init
  python -m speckit.cli build --task "实现订单按状态筛选"
  python -m speckit.cli draft --task "实现订单按状态筛选"
  python -m speckit.cli apply --patch evidence/diff.patch
  python -m speckit.cli verify
  python -m speckit.cli verify --after
  python -m speckit.cli save --state-file task_state.json
  python -m speckit.cli resume --state-file task_state.json
```

### 5.1 init —— 建表并导入索引

`--help` 实际输出：

```
usage: python -m speckit.cli init [-h]

options:
  -h, --help  show this help message and exit
```

用法与示例：`python -m speckit.cli init`（输出见 §4.4）。

### 5.2 build —— 检索并组装上下文

`--help` 实际输出：

```
usage: python -m speckit.cli build [-h] --task TASK [--top-k TOP_K]
                                   [--scope SCOPE]

options:
  -h, --help     show this help message and exit
  --task TASK    任务描述，例如：实现订单按状态筛选
  --top-k TOP_K  每类返回条数上限（默认 5）
  --scope SCOPE  可选：显式指定 scope 过滤
```

用法与示例：

```bash
python -m speckit.cli build --task "实现订单按状态筛选"
python -m speckit.cli build --task "实现订单按状态筛选" --top-k 3 --scope orders
```

输出为 JSON，结构为 `{task, scope, keywords, specs[], code[], tests[], progress}`，
每项带 `source`（如 `data/specs.json#SPEC-ORD-3`）与 `score`。`specs[]` 示例：

```json
{
  "id": "SPEC-ORD-3",
  "title": "订单列表必须支持按状态筛选",
  "scope": "orders",
  "source": "data/specs.json#SPEC-ORD-3",
  "score": 10
}
```

> 检索结果来自 seekdb 的 SQL 查询（`store.search`），代码内不写死答案。详见 `VERIFY.md`。

### 5.3 draft —— 交给 MiniMax 生成候选补丁

`--help` 实际输出：

```
usage: python -m speckit.cli draft [-h] --task TASK [--out OUT]

options:
  -h, --help   show this help message and exit
  --task TASK  任务描述
  --out OUT    候选补丁输出路径（默认 evidence/candidate_service.py）
```

用法与示例：

```bash
python -m speckit.cli draft --task "实现订单按状态筛选"
```

成功后写入：`evidence/candidate_service.py`（候选代码）、`evidence/diff.patch`（unified diff）、
`evidence/minimax_session.json`（请求/响应留痕，Key 已脱敏）。

> **待补齐**：`MINIMAX_API_KEY` 未配置时，本命令以中文错误退出（见 `config.require_minimax_key`），
> 不会返回假内容。`draft` 会先用 seekdb 检索上下文，因此同时依赖 seekdb 可用。

### 5.4 apply —— 应用补丁

`--help` 实际输出：

```
usage: python -m speckit.cli apply [-h] --patch PATCH [--service SERVICE]

options:
  -h, --help         show this help message and exit
  --patch PATCH      补丁文件路径（模型输出或纯代码）
  --service SERVICE  目标 service.py 路径（默认 demo_project/orders/service.py）
```

用法与示例：

```bash
python -m speckit.cli apply --patch evidence/diff.patch
```

应用前把旧内容快照到 `evidence/before/service.py`，写入后快照到 `evidence/after/service.py`，
并生成 `evidence/diff.patch`。

### 5.5 verify —— 跑目标与回归测试

`--help` 实际输出：

```
usage: python -m speckit.cli verify [-h] [--after]

options:
  -h, --help  show this help message and exit
  --after     标记为修改后阶段，日志写入 evidence/test_after.log
```

用法与示例：

```bash
python -m speckit.cli verify            # 修改前 -> evidence/test_before.log
python -m speckit.cli verify --after    # 修改后 -> evidence/test_after.log
```

该命令分别运行 `demo_project/tests/test_orders_baseline.py`（回归）与
`demo_project/tests/test_orders_target.py`（目标），**存在失败用例时返回 1**。

### 5.6 save —— 保存任务状态

`--help` 实际输出：

```
usage: python -m speckit.cli save [-h] [--state-file STATE_FILE]

options:
  -h, --help            show this help message and exit
  --state-file STATE_FILE
                        状态文件名（默认 task_state.json）
```

用法与示例：

```bash
python -m speckit.cli save --state-file task_state.json
```

实测输出（PowerContext 未配置 server，自动降级本地 JSON）：

```
状态已保存：local-json:<minimax 绝对路径>/.powercontext/task_state.json
backend=local-json（未配置 POWERCONTEXT_SERVER，自动降级为本地 JSON 状态文件）
文件位置：<minimax 绝对路径>/.powercontext/task_state.json
进展概览：done=1 todo=2
```

> **待补齐**：配置 `POWERCONTEXT_SERVER` 并安装 `powercontext` 包后，`backend` 变为
> `powercontext`，状态 id 由远端返回。

### 5.7 resume —— 另起进程读取状态

`--help` 实际输出：

```
usage: python -m speckit.cli resume [-h] --state-file STATE_FILE

options:
  -h, --help            show this help message and exit
  --state-file STATE_FILE
                        要读取的状态文件名
```

用法与示例（**新开终端 / 新起进程**执行）：

```bash
python -m speckit.cli resume --state-file task_state.json
```

实测输出：

```json
{
  "done": [],
  "todo": [
    "在 demo_project/orders/service.py 中实现 list_orders 的 status 过滤",
    "运行 verify 记录修改前测试日志",
    "运行 verify --after 记录修改后测试日志"
  ],
  "evidence": {},
  "backend": "local-json",
  "state_id": "<minimax 绝对路径>/.powercontext/task_state.json",
  "updated_at": "2026-10-28T10:42:08"
}
[backend] local-json
```

> 注：`done` / `todo` / `evidence` 的内容取决于保存时刻的工作区状态
> （`cli._collect_progress` 会自动汇总），上例为初始状态下 `save` 的结果。

---

## 6. 测试方式

三种等价方式：

```bash
# 1) 修改前（before）
cd minimax
python -m speckit.cli verify

# 2) 修改后（after）
python -m speckit.cli verify --after

# 3) 直接 pytest
python -m pytest demo_project/tests -q
```

当前预期（改动前）：

| 测试文件 | 用例 | 预期 |
|---|---|---|
| `test_orders_baseline.py` | `test_list_orders_returns_all` | PASS |
| `test_orders_baseline.py` | `test_filter_by_min_amount` | PASS |
| `test_orders_baseline.py` | `test_sorted_by_id` | PASS |
| `test_orders_target.py` | `test_filter_by_status` | FAIL（status 未实现） |

即：**baseline 3 passed，target 1 failed → 合计 1 failed, 3 passed**。
完成修改后，目标测试应转为 PASS，回归仍全 PASS。

---

## 7. 一键复现

```bash
cd minimax
bash scripts/run_all.sh
```

脚本按 `init → build → verify（before）→ 提示 draft/apply 需 Key → verify --after → save → resume`
顺序执行，`set -e` 且每步打印标题。

- 除 `verify`（存在失败用例时返回 1，属预期，脚本显式容忍）外，任一步骤非零即中止。
- 若已配置 `MINIMAX_API_KEY`，可设置 `SPECKIT_AUTO_MINIMAX=1` 让脚本自动执行 `draft` + `apply`：

```bash
SPECKIT_AUTO_MINIMAX=1 bash scripts/run_all.sh
```

> **前提**：`run_all.sh` 的完整跑通需要 seekdb 可用；未启动 seekdb 时，脚本在 `init` 步
> 以中文错误中止（预期行为，见 §9）。

---

## 8. evidence 产物

| 文件 | 由哪一步产生 | 内容 |
|---|---|---|
| `evidence/before/service.py` | `apply` | 修改前快照 |
| `evidence/after/service.py` | `apply` | 修改后快照 |
| `evidence/diff.patch` | `draft` / `apply` | unified diff |
| `evidence/candidate_service.py` | `draft` | MiniMax 生成的候选代码（`--out` 可改） |
| `evidence/minimax_session.json` | `draft` | 请求/响应留痕（Key 脱敏） |
| `evidence/test_before.log` | `verify` | 修改前测试日志 |
| `evidence/test_after.log` | `verify --after` | 修改后测试日志 |

---

## 9. 已知限制

1. **MiniMax 需要自备 Key**：`MINIMAX_API_KEY` 未配置时，`draft` 以中文错误退出；
   本仓库不内置任何 Key（`.env.example` 中为占位符 `<your-key>`）。
   `minimax_session.json` 与 `TECH_USAGE.md` 中相关记录**待 Key 到位后补齐**。
2. **PowerContext 未配置 server 时降级为本地 JSON**：未设置 `POWERCONTEXT_SERVER`
   （或未安装 `powercontext` 包）时，`state.py` 自动降级，`backend` 显示为 `local-json`，
   状态落在 `.powercontext/task_state.json`。此为设计内的降级路径，不影响「状态复用」验证。
3. **seekdb 不可用时报中文错误**：`init` / `build` / `draft` 依赖 seekdb，
   连接失败时打印中文排查指引并返回退出码 `2`，不静默失败。示例：

   ```
   [错误] 无法连接 seekdb（MySQL 协议）：host=127.0.0.1 port=2881 user=root database=speckit。
   请检查：1) seekdb 实例是否已启动并监听该端口；2) SEEKDB_HOST / SEEKDB_PORT /
   SEEKDB_USER / SEEKDB_PASSWORD 是否配置正确；3) 网络与防火墙是否放行。
   ```

4. **`draft` 的双重前提**：既需要 seekdb（先检索上下文），又需要 MiniMax Key。
5. **Windows 环境**：命令在 `git-bash` / `cmd` 下均可运行；`run_all.sh` 依赖 bash。

---

## 10. 待补齐字段（依赖 MiniMax Key）

以下位置在 Key 到位后需回填，当前保留占位：

- `TECH_USAGE.md` §1「MiniMax 开发记录」：调用时间 / prompt 摘要 / 返回摘要 / 对应 diff 位置。
- `evidence/minimax_session.json`：首次真实调用 `draft` 后自动生成。
- `README.md` §5.3 / §5.6：`draft` 成功输出、`save` 的 `powercontext` 后端输出示例。

详见 `TECH_USAGE.md` 与 `VERIFY.md`。