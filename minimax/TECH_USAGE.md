# TECH_USAGE —— speckit 技术使用记录

> 本文记录三种核心技术的实际参与情况，供评审核对：
> **MiniMax**（§1）、**seekdb**（§2）、**PowerContext**（§3）。
> 契约以 `minimax/DESIGN.md` 为权威；运行细节见 `minimax/README.md`。

**记录环境**：Windows 11 + git-bash；Python 3.12.10。
**凭据**：一律以占位符出现（如 `<your-key>`），仓库内不含任何真实 Key / Token / 私钥。

---

## 1. MiniMax 开发记录

### 1.1 接入方式

- 调用封装：`speckit/minimax.py::chat(prompt)`。
- 协议：OpenAI 兼容 HTTP —— `POST {MINIMAX_BASE_URL}/chat/completions`，
  请求头 `Authorization: Bearer <MINIMAX_API_KEY>`。
- 默认 `MINIMAX_BASE_URL=https://api.minimax.chat/v1`，`MINIMAX_MODEL=MiniMax-Text-01`。
- 提示词由 `speckit/cli.py::build_draft_prompt` 组装：把 `build` 检索到的规格 / 代码 / 测试
  （含 `source` 标注）连同 `service.py` 现有源码一起喂给模型，并要求只输出完整 `service.py`。
- 留痕：每次调用追加写入 `evidence/minimax_session.json`（含时间、请求 URL / model / 脱敏请求头 /
  payload / prompt 字符数，以及响应状态码 / body / text / usage）。
- 失败处理：未配置 Key 时抛 `MiniMaxError` 并中文提示，**绝不返回假内容**；
  网络 / HTTP 错误同样记录到 `minimax_session.json` 后再抛出。

### 1.2 调用记录（**待 Key 到位后补齐**）

> ⚠️ 本作品当前**未配置真实 `MINIMAX_API_KEY`**，故 `draft` 尚未产生真实调用。
> 下表为**待填模板**；Key 到位后运行
> `python -m speckit.cli draft --task "实现订单按状态筛选"`，
> 按下表逐项回填（数据来源：`evidence/minimax_session.json` 与 `evidence/diff.patch`）。

| 序号 | 调用时间 | prompt 摘要 | 返回摘要 | 对应 diff 位置 |
|---|---|---|---|---|
| 1 | *（待填）* | *任务：实现订单按状态筛选；上下文来源：`data/specs.json#SPEC-ORD-3`、`data/code_index.json#CODE-ORD-1`、`data/tests_index.json#TEST-ORD-T`；含现有 `service.py` 源码* | *（待填）模型返回的完整 `service.py` 文本摘要（关键改动：`status` 过滤分支）* | *（待填）`evidence/diff.patch` 中 `demo_project/orders/service.py` 的 `status` 分支 hunk* |

**字段说明**：

- **调用时间**：取自 `evidence/minimax_session.json` 中该条记录的 `timestamp`。
- **prompt 摘要**：取自该记录的 `request.payload.messages[0].content`（或 `request.prompt_chars` 佐证）。
- **返回摘要**：取自该记录的 `response.text`。
- **对应 diff 位置**：`evidence/diff.patch` 中应用补丁后产生的 hunk 行号 / 内容。

> 待补齐项在 `README.md` §10 与 `VERIFY.md` §5 步骤 4 中同样有标注。

---

## 2. 数据库（seekdb）查询记录

### 2.1 接入方式

- 封装：`speckit/store.py::SeekDBStore`，通过 **PyMySQL**（MySQL 协议，默认端口 `2881`）访问 seekdb。
- 表：`spec_items` / `code_items` / `test_items`（字段 `id` / `title_or_name` / `file` / `keywords` / `text` / `scope`）。
- 建库：`init_schema()` 执行 `CREATE DATABASE IF NOT EXISTS <库>` 后建表（幂等）。
- 写入：`import_from_json()` 读 `data/{specs,code_index,tests_index}.json`，走
  `INSERT ... ON DUPLICATE KEY UPDATE`（幂等，重复 init 不产生重复行）。
- 检索：`search(keywords)` 在 SQL 内计算命中分（标题 4 分 > 关键词 3 分 > 正文 1 分），
  **所有关键词均以 `%s` 参数化传入，绝不拼进 SQL 文本**；`selector.py` 再叠加同 scope 加成（+2）后稳定排序。

### 2.2 导入条数（`init`）

`init` 会打印各类条目数与表计数。导入条数即 `data/` 三份索引的实际条目数：

| 表 | 来源文件 | 条目数 | 备注 |
|---|---|---|---|
| `spec_items` | `data/specs.json` | 4 | `SPEC-ORD-1` ~ `SPEC-ORD-4` |
| `code_items` | `data/code_index.json` | 1 | `CODE-ORD-1` |
| `test_items` | `data/tests_index.json` | 4 | `TEST-ORD-T` / `TEST-ORD-B1` / `TEST-ORD-B2` / `TEST-ORD-B3` |

`init` 预期打印（节选）：

```
已建表：spec_items / code_items / test_items
导入条目数：specs=4 code=1 tests=4
当前表计数：{"spec_items": 4, "code_items": 1, "test_items": 4}
```

> 复核方式：`python -m speckit.cli init`（或用等价的 `python scripts/init_data.py`）。
> 若 seekdb 不可连接，命令会打印中文排查指引并以退出码 `2` 退出（预期行为）。

### 2.3 `build` 检索来源（检索留痕）

`build --task "实现订单按状态筛选"` 的输出中，每一项都带 `source`，标识其**来自哪个索引文件与条目 id**，
可直接对照 `data/` 核验。本任务的关键检索来源：

| 输出分类 | source | 命中依据 |
|---|---|---|
| `specs[]` | `data/specs.json#SPEC-ORD-3` | 关键词「状态 / 筛选 / status」命中（标题 4 + 关键词 3 + 正文 1，另加 scope 加成） |
| `code[]` | `data/code_index.json#CODE-ORD-1` | 关键词「筛选 / status」命中 `list_orders` 符号索引 |
| `tests[]` | `data/tests_index.json#TEST-ORD-T` | 关键词「状态 / 筛选」命中 `test_filter_by_status` |

### 2.4 「检索非写死」的证据

`build` 输出完全由 SQL 查询结果决定：

1. `store.search` 返回带 `score` 的行 → `selector.build_context` 排序组装 → 每项标注 `source`；
2. 修改 `data/specs.json` 后重跑 `init` + `build`，输出随之变化
   （对照步骤见 `VERIFY.md` §7）。

以上两条共同证明「检索来自 seekdb，且规格更新后结果会变」，满足 DESIGN §8 的禁止项要求。

---

## 3. PowerContext 状态写入与复用记录

### 3.1 接入方式

- 封装：`speckit/state.py::ProgressStore`。
- 优先使用 `powercontext` 官方包（需要配置 `POWERCONTEXT_SERVER`）；
  未配置 server 或包不可用时，**自动降级为本地 JSON**（目录取 `POWERCONTEXT_STATE_DIR`，默认 `.powercontext`）。
- 状态结构：`{progress:{done,todo,evidence}, backend, updated_at}`。
- `done / todo / evidence` 由 `cli.py::_collect_progress` 按当前工作区状态自动汇总。
- 跨进程一致性：状态文件路径统一以 `minimax/` 根目录解析，故 `save` 与 `resume` 即使在不同进程、不同
  工作目录下也能定位到同一份状态。

### 3.2 写入 / 复用记录（两进程）

| 阶段 | 进程 | 命令 | state_id | backend |
|---|---|---|---|---|
| 写入 | 进程 A（`save`） | `python -m speckit.cli save --state-file task_state.json` | `<minimax 绝对路径>/.powercontext/task_state.json` | `local-json` |
| 读取 | 进程 B（`resume`，另起进程） | `python -m speckit.cli resume --state-file task_state.json` | 同上（路径一致） | `local-json` |

`save` 实测输出（节选）：

```
状态已保存：local-json:<minimax 绝对路径>/.powercontext/task_state.json
backend=local-json（未配置 POWERCONTEXT_SERVER，自动降级为本地 JSON 状态文件）
文件位置：<minimax 绝对路径>/.powercontext/task_state.json
进展概览：done=1 todo=2
```

`resume` 实测输出（节选）：

```json
{
  "done": [ ... ],
  "todo": [ ... ],
  "evidence": { ... },
  "backend": "local-json",
  "state_id": "<minimax 绝对路径>/.powercontext/task_state.json",
  "updated_at": "2026-10-28T10:42:08"
}
[backend] local-json
```

> 说明：`done / todo / evidence` 的内容取决于**保存时刻**的工作区状态
> （例如 `todo` 在初始状态下包含「实现 list_orders 的 status 过滤」，
> `done` 在 `apply` 与 `verify` 之后会随证据文件增多而增加）。上表两行的
> `state_id` 指向同一文件，即「另一进程成功复用了先前写入的状态」。

### 3.3 降级原因

- **降级后端**：`local-json`（非 `powercontext`）。
- **原因**：未配置 `POWERCONTEXT_SERVER`（环境变量或 `.env` 中该值为空），
  且 / 或未安装 `powercontext` 包；此时 `state.py::_detect_backend` 记下降级原因
  「未配置 POWERCONTEXT_SERVER，自动降级为本地 JSON 状态文件」。
- **影响**：不影响「状态复用」验证 —— `save` 写入本地 JSON，另一进程 `resume` 仍能读回
  同一份 `done / todo / evidence`；`save` 返回串与 `resume` 输出的 `backend` 字段均如实标注为 `local-json`。
- **升级路径**：配置 `POWERCONTEXT_SERVER` 并安装 `powercontext` 包后，`backend` 变为 `powercontext`，
  状态 id 由远端返回；本地 JSON 副本仍会保留一份，保证新进程可无网读取。

---

## 4. 待补齐项汇总（依赖 MiniMax Key）

| 位置 | 待补齐内容 |
|---|---|
| 本文 §1.2 | MiniMax 调用时间 / prompt 摘要 / 返回摘要 / 对应 diff 位置 |
| `evidence/minimax_session.json` | 首次真实 `draft` 后自动生成 |
| `README.md` §5.3 / §10 | `draft` 成功输出示例 |
| `README.md` §5.6 | `save` 的 `powercontext` 后端输出示例（配置 server 后） |
---

## 5. 云端实测记录（2026-10-28，AMD Radeon Cloud）

> 本节是**在真实 Linux + seekdb 环境上**跑出的结果，用于佐证 §2 / §3 的接入是实际生效的，而非仅文档描述。

### 5.1 环境

| 项 | 值 |
|---|---|
| 实例 | AMD Radeon Cloud `rgapi-hf-25715-6021f34e`（Ubuntu 24.04，EPYC 9334） |
| seekdb | `5.7.25-OceanBase seekdb-v1.4.0.0`，端口 `2881` |
| Python | 3.12（容器 `/opt/venv`） |
| 依赖 | pymysql 2.2.8 / requests 2.34.2 / pytest 9.0.3 |
| 作品路径 | `/workspace/mm/minimax` |

### 5.2 seekdb 实测（对应 §2）

```
$ python -m speckit.cli init
正在初始化 seekdb schema：127.0.0.1:2881/speckit
已建表：spec_items / code_items / test_items
导入条目数：specs=4 code=1 tests=4
当前表计数：{"spec_items": 4, "code_items": 1, "test_items": 4}

$ mysql -h127.0.0.1 -P2881 -uroot speckit -e 'show tables;'
code_items / spec_items / test_items
```

`build --task "实现订单按状态筛选"` 实际返回（节选，score 来自 SQL 打分）：

```json
"specs": [
  {"id":"SPEC-ORD-3","title":"订单列表必须支持按状态筛选","source":"data/specs.json#SPEC-ORD-3","score":30},
  {"id":"SPEC-ORD-4","title":"筛选结果保持原有排序","source":"data/specs.json#SPEC-ORD-4","score":10},
  {"id":"SPEC-ORD-1","title":"订单列表默认返回全部订单","source":"data/specs.json#SPEC-ORD-1","score":8},
  {"id":"SPEC-ORD-2","title":"支持按最低金额过滤","source":"data/specs.json#SPEC-ORD-2","score":3}
],
"code": [{"id":"CODE-ORD-1","file":"demo_project/orders/service.py","symbol":"list_orders","source":"data/code_index.json#CODE-ORD-1"}]
```

### 5.3 「规格更新 → 输出变化」实测（对应 §2.4）

把 `SPEC-ORD-3` 的标题改为「（2026-10 修订版）」、关键词改为 `["库存","盘点"]`，重新 `init` + `build`：

```
改前：SPEC-ORD-3  title=订单列表必须支持按状态筛选          score=30
改后：SPEC-ORD-3  title=订单列表必须支持按状态筛选（2026-10 修订版）  score=22
还原：SPEC-ORD-3  title=订单列表必须支持按状态筛选          score=30
```

标题与分数同步变化，**证明输出来自 seekdb 检索而非写死**；`data/specs.json` 已还原。

### 5.4 代码修改有效性实测（对应六项必做项之六）

```
修改前：python -m pytest demo_project/tests -q  → 1 failed, 3 passed
        FAILED test_orders_target.py::test_filter_by_status
        assert [1, 2, 3, 4] == [1, 3]

应用补丁：python -m speckit.cli apply --patch <patch>
  → 修改前快照 evidence/before/service.py
  → 修改后快照 evidence/after/service.py
  → unified diff evidence/diff.patch

修改后：python -m speckit.cli verify --after → 4 passed（exit_code=0）
```

`evidence/diff.patch` 的 hunk（真实产出）：

```diff
@@ -34,11 +34,9 @@
-    # ---- 未实现：状态过滤 ----
-    # TODO: status filter not implemented yet
+    # ---- 已实现：状态过滤 ----
     if status is not None:
-        # 当前忽略 status 参数，直接返回（待实现按状态筛选）
-        pass
+        result = [order for order in result if order.status == status]
```

> ⚠️ 本次 `apply` 用的补丁是**人工构造**的，用于先打通 apply → verify 链路；正式提交前需由 `draft`（MiniMax 真实调用）重新生成补丁，以满足「MiniMax 实际参与」。

### 5.5 发现的真实兼容性问题（已在代码中修复）

seekdb 不支持 `utf8mb4_unicode_ci`：

```
OperationalError: (1273, "Unknown collation: 'utf8mb4_unicode_ci'")
```

已把 `speckit/store.py` 中 4 处 `utf8mb4_unicode_ci` 改为 `utf8mb4_general_ci`（建库 1 处 + 三张表各 1 处），修复后 `init` 正常。这类问题只在真实 seekdb 上才会暴露，本地 Windows 无法发现。

### 5.6 六项必做项对照

| 验收项 | 状态 | 证据 |
|---|---|---|
| 能够运行 | ✅ 云端实测 | §5.1~5.4 |
| MiniMax 实际参与 | ⏳ 待 Key | §1.2（待填） |
| 上下文正确 | ✅ 实测 | §5.2 + §5.3（规格更新输出变化） |
| 数据库实际参与 | ✅ 实测 | §5.2（init 4/1/4、build 检索结果带 source） |
| 状态能够复用 | ✅ 实测 | §3.2（save → 另起进程 resume，同一 state_id） |
| 代码修改有效 | ⚠️ 链路已验证 | §5.4（before 1 failed → after 4 passed），补丁需换成 MiniMax 产出 |