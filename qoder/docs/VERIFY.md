# CiteSeek 知源 · 验证样例（VERIFY）

> 目的：评审照着做即可验证 **seekdb 在项目里真的在起作用**——向量语义召回、全文关键词、结构化过滤在引擎内融合，且检索 / 复习数据持久化在 seekdb。
> 前置：已按 [RUNBOOK.md](RUNBOOK.md) §3 启动服务（`SEED_ON_START=1` 时示例数据随启动自动导入，也可按 §4 手动载入）；所有命令在**宿主机**执行。
> 相关：[DESIGN.md](DESIGN.md)（API 契约 §5、§7）、[ARCHITECTURE.md](ARCHITECTURE.md)（请求链路 §3、职责划分 §4）、[示例数据说明](../data/samples/README.md)。

## 0. 约定与公共准备

- 服务地址：`BASE=http://localhost:8000`（下文命令直接用 `http://localhost:8000`）。
- Windows 用户请用 `curl.exe`（PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名），或使用 Git Bash。
- 若 PowerShell 下中文 JSON 请求体乱码，把请求体存成 UTF-8 文件后用 `curl.exe --data-binary @query.json -H "Content-Type: application/json"`，或改用 Git Bash。
- 每次检索都会写入 `search_log`，这是「seekdb 参与检索」的直接证据；`/api/logs/search` 只读最近 N 条。
- 想从零重做全部验证：按 RUNBOOK §7.4 清理数据 → 重新启动（`SEED_ON_START=1` 会自动导入，也可手动「载入示例数据」后再开始）。
- 本文的预期值与当前实现（`app/*.py`）核对过；若后续实现调整字段口径，以实际响应为准并同步更新本文件。
- 示例数据基线（载入后首次查询前可先记录）：

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/stats
```

> 预期基线：`/api/health` 的 `status=ok`、`seekdb.connected=true`、`collection=citeseek_chunks_v1`、`embed.dim=512`；`/api/stats` 的 `notes=27`、`chunks=62`（实测约 62，随切块参数浮动；DESIGN 验收要求 `>=60`）、`searches=5`（按本文档完整执行后为 5 次查询；全新实例载入数据后为 0）。
> 若 `embed.mode=hash`、`degraded=true`，说明模型降级，**样例 1 的「换说法」部分会明显变弱**，其余验证不受影响（见 §1.5）。

字段含义速查见 [附录 A](#附录-a字段速查)。

---

## 样例 1：语义检索——换个说法也能找到（含关键词对照）

**被验证的能力**：查询向量由应用层计算、经 pyseekdb 的 `hybrid_search` 在 seekdb 内与全文、结构化过滤一起完成召回与 RRF 融合；结果带出处。

### 1.1 初始数据

- 已载入示例数据（27 篇），与本次验证相关的笔记：

| 文件 | 标题 | 课程 / 主题 | 说明 |
|---|---|---|---|
| `db-01-transaction-isolation.md` | 事务隔离级别与 MVCC | 数据库系统 / 事务与并发 | 正文同时含「事务隔离级别」「隔离级别」「快照读」 |
| `db-02-mvcc-read-view.md` | MVCC 版本链与 Read View | 数据库系统 / 事务与并发 | 用「可见性判断」「Read View」等近义表达 |
| `db-03-locks-2pl-deadlock.md` | 锁、两段锁协议与死锁排查 | 数据库系统 / 事务与并发 | 讨论隔离级别与锁范围、死锁 |
| `db-07-hybrid-search-rrf.md` | 混合检索与 RRF 融合排序 | 数据库系统 / 检索系统 | 正文也提到「隔离级别」与「并发可见性」，可能出现在召回结果中 |

- 前置记录（便于对比新增日志）：

```bash
curl -s "http://localhost:8000/api/logs/search?limit=5"
```

### 1.2 操作步骤

**① 关键词字面查询（对照组）**

```bash
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"隔离级别","course":"数据库系统","k":5}'
```

**② 换说法查询（实验组，语义召回）**

```bash
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"两个事务同时修改同一行数据，会不会互相看不见对方的改动","k":5}'
```

> ② 的句子与示例笔记**没有连续字面重合**：全文一路的 `$contains` 整串匹配基本失效，能召回主要依赖 query 向量与 chunk 向量（BGE 中文模型）的语义相似度。

### 1.3 预期结果（字段级）

**① 关键词查询**

| 字段 | 预期 |
|---|---|
| HTTP | `200` |
| `query` | `"隔离级别"` |
| `took_ms` | `> 0`（整数，通常几十毫秒内） |
| `mode` | `"hybrid"` |
| `results` | 非空；`k=5` 最多 5 条 |
| `results[0].title` | **`事务隔离级别与 MVCC`**（最相关片段来自 `db-01`，也可能先出现 `db-02`） |
| `results[*].course` | 全部 `数据库系统`（因为带了 `course` 过滤） |
| `results[*].text` | 至少有一条包含「隔离级别」或「事务隔离」字样 |
| `results[*].matched_by` | 含 `"vector"` 与 `"fulltext"`（当前实现正常 hybrid 路径对每个结果统一标记两路参与） |
| `results[*].chunk_id` / `note_id` | 32 位十六进制字符串；`note_id` 可用于联查笔记 |
| `results[*].score` / `distance` | 正常路径 `score = 1/distance`（降级路径为 RRF 分数）；`distance` 为余弦距离，可能为 `null` |
| `debug.degraded` | `false`（引擎支持 `hybrid_search`；若为 `true` 见 §1.6） |

**② 换说法查询**

| 字段 | 预期 |
|---|---|
| HTTP | `200`（非 400；query 非空） |
| `results` | 非空，且前 3 条中至少 1 条的 `title` ∈ {`事务隔离级别与 MVCC`, `MVCC 版本链与 Read View`, `锁、两段锁协议与死锁排查`} |
| `results[*].matched_by` | 通常为 `["vector","fulltext"]`（当前实现正常路径统一标记两路）；它**不代表全文腿字面命中**，语义召回结论以排名与片段内容为准 |
| `results[*].text` | 片段内容与「并发事务可见性 / 隔离级别 / 锁」相关 |
| `took_ms` | `> 0`；通常与 ① 同量级 |

### 1.4 技术证据

**证据 1：检索日志新增记录（证明走的是检索链路，而不是前端假数据）**

```bash
curl -s "http://localhost:8000/api/logs/search?limit=3"
```

预期最新两条对应上面两次查询：

| 字段 | ① 关键词查询 | ② 换说法查询 |
|---|---|---|
| `query` | `隔离级别` | `两个事务同时修改同一行数据，会不会互相看不见对方的改动` |
| `course` | `数据库系统` | 空 |
| `mode` | `hybrid` | `hybrid` |
| `used_vector` | `1` | `1` |
| `used_fulltext` | `1`（正常路径两路都参与融合） | `1`（同上口径；该字段表示融合包含全文一路，不代表 `$contains` 字面命中） |
| `took_ms` | `363（首次查询含模型预热）` | `48` |
| `result_count` | `5` | `5` |

补充：响应 `debug` 里还有 `used_vector` / `used_fulltext`，口径与 `search_log` 一致（正常路径均为 `1`），可用于即时核对。

**证据 2：seekdb 状态与数据量**

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/stats
```

| 字段 | 预期 |
|---|---|
| `seekdb.connected` | `true` |
| `seekdb.database` | `citeseek` |
| `seekdb.collection` | `citeseek_chunks_v1` |
| `seekdb.count` | 等于 `/api/stats.chunks`，实测 `62` |
| `stats.searches` | 比 1.1 前多 2（多次重跑按实际次数累加） |
| `stats.top_queries` | 出现 `隔离级别` 等查询词及计数 |

**证据 3：结果可溯源**

每条结果都带 `note_id / title / course / topic / tags`，前端卡片显示「来自第 N 段」与资料名；这说明检索返回的不是「凭空生成的答案」，而是**可回溯到原笔记片段**的内容。

### 1.5 降级模式对照（可选，验证「降级不崩」）

1. 把 `docker-compose.yml` 的 `EMBED_MODE` 改为 `hash`（或通过 `.env` 覆盖，以 compose 读取方式为准），执行 `docker compose up -d`；
2. `curl -s http://localhost:8000/api/health` → `embed.mode=hash`、`dim=512`；
3. 重跑 §1.2 ①（关键词）→ 仍应正常命中「事务隔离级别与 MVCC」；
4. 重跑 §1.2 ②（换说法）→ 语义召回明显变弱，这是 hash 字符 n-gram 的预期限制；此时演示「换说法」请以 ① 的字面关键词为准。

`《MVCC 版本链与 Read View》、《事务隔离级别与 MVCC》、《MVCC 版本链与 Read View》（hash 向量为降级方案，仍能返回相关片段）`

### 1.6 判据清单

- [ ] ① 关键词查询返回包含「事务隔离级别与 MVCC」的片段
- [ ] ② 换说法查询仍能召回隔离级别 / MVCC 相关笔记（`embed.mode=onnx` 时）
- [ ] `/api/logs/search` 新增记录，`used_vector=1`、`took_ms>0`、`result_count>0`
- [ ] `/api/health` 的 `seekdb.count` 与 `/api/stats.chunks` 一致
- [ ] 结果带 `note_id/title/course/topic` 等出处字段
- [ ] `EMBED_MODE=hash` 下关键词检索仍可用（降级不崩）
- [ ] 若 `debug.degraded=true`：确认 §1.2 是否仍能召回；说明引擎版本降级路径生效（见 ARCHITECTURE §7）

---

## 样例 2：结构化过滤——`course=数据库系统` 时结果只含该课程

**被验证的能力**：`course` / `topic` 作为 metadata 条件，在 `hybrid_search` 的 `where` 中**下推到 seekdb 引擎内**，同时作用于全文与向量两路（DESIGN §5.2）。

### 2.1 初始数据

- 已载入示例数据，课程分布：数据库系统 7、机器学习 8、高等数学 3、概率论与数理统计 3、科研方法 6。
- 检索词「索引」同时出现在数据库系统与机器学习课程中（用于对比过滤效果）：

| 文件 | 课程 | 含「索引」的位置 |
|---|---|---|
| `db-04-bplus-tree-index.md` | 数据库系统 | B+ 树索引 |
| `db-05-explain-slow-query.md` | 数据库系统 | 索引与慢查询 |
| `db-06-vector-search-ann.md` | 数据库系统 | 标题与正文「向量检索与 ANN 索引」 |
| `ml-08-rag-retrieval.md` | 机器学习 | 「建索引：把块编码成向量……」 |

### 2.2 操作步骤

**① 不加过滤（基线）**

```bash
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"索引","k":10}'
```

**② 加 course 过滤**

```bash
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"索引","course":"数据库系统","k":10}'
```

**③ 再加 topic 过滤**

```bash
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"检索","course":"数据库系统","topic":"检索系统","k":10}'
```

### 2.3 预期结果（字段级）

**① 不加过滤**

| 字段 | 预期 |
|---|---|
| `results` | 非空；`course` 至少出现 2 个不同值 |
| 典型结果 | 含 `B+ 树索引与回表`、`EXPLAIN 与慢查询排查`（数据库系统）；同时**至少 1 条非数据库系统课程**（如 `检索增强生成 RAG 阅读笔记`，机器学习），实测 `《检索增强生成 RAG 阅读笔记》（机器学习）、《文献综述写作方法》（科研方法）、《文献检索与筛选策略》（科研方法）` |
| `debug.degraded` | `false` |

**② 加 course 过滤**

| 字段 | 预期 |
|---|---|
| `results` | 非空（`db-04`、`db-05`、`db-06` 均含「索引」，至少命中其中两个） |
| `results[*].course` | **全部等于 `数据库系统`**（无一条例外） |
| `results[*].topic` | 全部为数据库系统课程主题（可能命中 `索引与存储`、`检索系统`、`事务与并发`）；不应出现 `文献工作`、`检索与生成`（机器学习） |
| 条数 | 通常 ≤ ① 的条数 |
| `took_ms` | `> 0` |

**③ 加 topic 过滤**

| 字段 | 预期 |
|---|---|
| `results[*].course` | 全部 `数据库系统` |
| `results[*].topic` | 全部 `检索系统` |
| 典型结果 | `向量检索与 ANN 索引`（`db-06`）、`混合检索与 RRF 融合排序`（`db-07`） |
| 若为空 | 说明同时限制 course + topic 过严或该主题无匹配，属正常；放宽一个条件重试 |

### 2.4 技术证据

```bash
curl -s "http://localhost:8000/api/logs/search?limit=3"
```

| 字段 | ① 无过滤 | ② course 过滤 | ③ topic 过滤 |
|---|---|---|---|
| `course` | 空 | `数据库系统` | `数据库系统` |
| `topic` | 空 | 空 | `检索系统` |
| `result_count` | `8` | `8` | `4` |
| `used_vector` / `used_fulltext` | `1` / `1` | `1` / `1` | `1` / `1`（正常 hybrid 路径两路都标记） |

**为什么能证明过滤在 seekdb 内完成**：

- DESIGN §5.2 把同一个 `where` **同时**传给 `query.where`（全文一路）与 `knn.where`（向量一路）；
- 因此被过滤掉的类目不会出现在候选里，返回条数（`result_count`）与「过滤后仍命中」的条数一致；
- 若只在应用层过滤，需要先把全部候选取回再裁剪，日志里的 `result_count` 会偏大、耗时也会上升——可与实际 `/api/logs/search` 的 `result_count` 对照。
- 直接证据（可选）：容器内查看 `search_log` 行，确认 `course` 字段已落库：

```bash
curl -s "http://localhost:8000/api/logs/search?limit=5"
```

若需直接查库（可选，取决于镜像是否自带 mysql 客户端）：进入容器后用 MySQL 协议连接 `seekdb:2881` 的 `citeseek.search_log` 查看对应行。

### 2.5 判据清单

- [ ] ① 不加过滤时结果跨课程（含机器学习课程片段）
- [ ] ② `course=数据库系统` 时全部结果的 `course` 均为 `数据库系统`
- [ ] ③ 同时限制 `topic=检索系统` 时只返回 `db-06` / `db-07` 相关片段
- [ ] `/api/logs/search` 对应记录里 `course` / `topic` 字段与实际过滤条件一致
- [ ] 过滤后 `took_ms` 有值、`result_count` 合理（不超过未过滤时的候选规模）

---

## 样例 3：检索即复习——加入复习 → `/api/review/due` 出现 → 评分后 `due_at` 推后

**被验证的能力**：命中片段可一键加入复习；复习进度（SM-2 参数）写入 seekdb 的 MySQL 兼容表 `review_items`，重启后仍在；评分后 `due_at` 按算法推后。

### 3.1 初始数据

```bash
curl -s http://localhost:8000/api/review/due?limit=10
curl -s http://localhost:8000/api/stats
```

预期：`review.due.total` 为 `0`；`/api/stats.review_items` 为 `0`。

### 3.2 操作步骤

**① 检索并取一个 `chunk_id`**

```bash
curl -s -X POST http://localhost:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"隔离级别","course":"数据库系统","k":1}'
```

记下 `results[0].chunk_id`（32 位十六进制）。下文用 `$CID` 表示，例如：

```bash
CID=<把上面的 chunk_id 粘到这里>
```

**② 加入复习**

```bash
curl -s -X POST "http://localhost:8000/api/review/$CID/add"
```

**③ 查看到期列表**

```bash
curl -s "http://localhost:8000/api/review/due?limit=10"
```

**④ 持久化验证（可选但推荐）**

```bash
docker compose restart citeseek
# 等待 /api/health 恢复 ok 后
curl -s "http://localhost:8000/api/review/due?limit=10"
```

**⑤ 评分（grade=2「记住了」）**

```bash
curl -s -X POST "http://localhost:8000/api/review/$CID/answer" \
  -H "Content-Type: application/json" \
  -d '{"grade":2}'
```

**⑥ 再次查看到期列表**

```bash
curl -s "http://localhost:8000/api/review/due?limit=10"
```

### 3.3 预期结果（字段级）

**② 加入复习**

| 字段 | 预期 |
|---|---|
| HTTP | `200` |
| `ok` | `true` |
| `due_at` | 约等于当前时间（DESIGN §6：新加入 `due_at = now`），实测 `2026-10-28T04:14:57.628353` |
| 重复调用 | 幂等或覆盖，不报 500（按实现；同 chunk 再次 add 仍应 200） |

**③ 到期列表**

| 字段 | 预期 |
|---|---|
| `total` | `>= 1`（刚加入的条目立刻到期） |
| `items[0].chunk_id` | 等于 `$CID` |
| `items[0].note_id` / `title` / `course` / `topic` | 来自联表：如 `事务隔离级别与 MVCC` / `数据库系统` / `事务与并发` |
| `items[0].text` | 即该 chunk 的原文片段（含「隔离级别」相关内容） |
| `items[0].due_at` | `<=` 当前时间（因此出现在 due 列表） |
| `items[0].reps` | `0`（新加入） |
| `items[0].interval_days` | `0`（新加入） |

**⑤ 评分响应**

| 字段 | 预期（grade=2，首次复习） |
|---|---|
| `ok` | `true` |
| `interval_days` | **`1`**（`reps` 从 0 变 1，按 DESIGN §6 `interval_days = 1`） |
| `reps` | **`1`** |
| `ease` | **`2.52`**（`2.5 + (0.1 - (3-2)×0.08)`，浮点展示允许 ±0.01 误差） |
| `due_at` | 评分时刻 + **1 天**，实测 `2026-10-29T04:15:01.687811` |

**⑥ 再次查看到期列表**

| 字段 | 预期 |
|---|---|
| `total` | 回到加入前水平（若本次验证只加了 1 条，则为 `0`） |
| 原因 | `due_at` 已被推后到次日，不再满足 `due_at <= now` |

### 3.4 评分算法对照表（可选，多答几次验证）

按 DESIGN §6 简化 SM-2，对同一片段连续评分（每次评分前先确认它已到期；未到期时可用另一个新片段测首答）：

| 场景 | `interval_days` | `ease` | `reps` | `lapses` |
|---|---|---|---|---|
| 首答 grade=2 | `1` | `2.52` | `1` | `0` |
| 首答 grade=3 | `1` | `2.60` | `1` | `0` |
| 首答 grade=1 或 0 | `1` | `2.30` | `0` | `1` |
| 连续第二次答 grade=2（`reps` 1→2） | `3` | `2.54` | `2` | `0` |
| 连续第三次答 grade=2（`reps` 2→3） | `round(3 × ease)` | 按公式累加 | `3` | `0` |

> `ease` 全程夹在 `[1.3, 2.8]`；失败（grade<2）时 `reps` 归零、`interval_days=1`、`ease -= 0.2`。

### 3.5 技术证据

```bash
curl -s http://localhost:8000/api/stats
```

| 字段 | 加入复习后 | 评分后 |
|---|---|---|
| `review_items` | 比验证前 +1（实测 `1`） | 保持 +1 |
| `review_due` | +1 | 回到 0（实测 `0`） |

- `review_items` / `review_due` 来自 seekdb 的 MySQL 兼容表 `review_items`（`due_at` 有 `idx_due` 索引），说明复习进度**持久化在数据库**，不是前端内存；
- 步骤 ④ 重启应用容器后 `/api/review/due` 仍能取到该条目，进一步证明数据在 seekdb 的 MySQL 表（named volume `seekdb_data`，容器重建不丢）；
- `/api/review/due` 的 `title/course/topic/text` 来自 `review_items` 与 `notes` 的联表查询，体现「复习也带出处」。

### 3.6 判据清单

- [ ] `POST /api/review/{chunk_id}/add` 返回 `ok=true` 且 `due_at` 可用
- [ ] `/api/review/due` 立刻出现该条目，且带 `title/course/topic/text` 出处信息
- [ ] 重启 `citeseek` 后条目仍在（持久化）
- [ ] `answer` 返回 `interval_days=1`、`ease≈2.52`、`reps=1`
- [ ] 评分后该条目不再出现在 `/api/review/due`，`/api/stats.review_due` 回落
- [ ] `/api/stats.review_items` 增加并保持

---

## 附录 A：字段速查

### `POST /api/search` 响应

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | string | 原始查询 |
| `took_ms` | int | 服务端耗时（毫秒） |
| `mode` | string | 检索模式，默认 `hybrid` |
| `results[].chunk_id` | string | chunk 的 uuid4 hex（32 位） |
| `results[].note_id` | string | 所属笔记 id |
| `results[].title` | string | 资料名（笔记标题） |
| `results[].course` / `topic` / `tags` | string | metadata 过滤 / 展示字段 |
| `results[].text` | string | chunk 原文（中文，`<= 400` 字） |
| `results[].score` | float | 正常路径 `1/distance`，降级路径为 RRF 融合分 |
| `results[].distance` | float/null | 向量距离（若实现返回） |
| `results[].matched_by` | string[] | `["vector"]` / `["fulltext"]` / 两者；当前实现正常 hybrid 路径对每个结果统一标记 `["vector","fulltext"]`，仅表示两路都参与了融合，不代表字面命中 |
| `debug.degraded` | bool | `true` = `hybrid_search` 不可用时的应用层融合降级 |
| `debug.used_vector` / `debug.used_fulltext` | int/bool | 本次检索向量 / 全文两路是否参与（正常路径均为 `1`） |
| `debug.*` | object | 其它调试信息（以实现为准） |

### `GET /api/logs/search`

| 字段 | 说明 |
|---|---|
| `query` / `mode` | 查询与模式 |
| `took_ms` / `result_count` | 耗时与结果数 |
| `used_vector` / `used_fulltext` | 本次检索向量 / 全文两路是否参与（`0/1`） |
| `created_at` | 写入时间（`search_log` 表） |

### `GET /api/health`

| 字段 | 说明 |
|---|---|
| `status` | `ok`（seekdb 连接与 collection 正常） |
| `seekdb.connected` / `database` / `collection` / `count` | seekdb 连接状态、库名、collection 名、chunk 总数 |
| `embed.mode` / `model` / `dim` / `degraded` | 实际嵌入模式（`onnx` / `hash` / `api`）、模型名（ONNX 为 `BAAI/bge-small-zh-v1.5`，hash 为 `hash-ngram`）、维度 512、是否降级；降级时另有 `embed.reason` |
| `version` | 应用版本 |

### `GET /api/stats`

| 字段 | 说明 |
|---|---|
| `notes` / `chunks` | 笔记数 / chunk 数 |
| `review_items` / `review_due` | 复习条目总数 / 今日到期数 |
| `searches` / `avg_latency_ms` / `last_search_at` | 检索次数 / 平均耗时 / 最近检索时间 |
| `top_queries` | `[{query, count}]` 高频查询 |

### `GET /api/review/due`

| 字段 | 说明 |
|---|---|
| `total` / `items` | 到期条目数 / 条目列表 |
| `items[].chunk_id` / `note_id` | 片段与笔记 id |
| `items[].title` / `course` / `topic` / `text` | 联表取得的出处与内容 |
| `items[].due_at` / `reps` / `interval_days` | 到期时间、已复习次数、当前间隔 |

## 附录 B：一键核对脚本（bash，可选）

```bash
BASE=http://localhost:8000

echo '--- health ---';    curl -s $BASE/api/health
echo; echo '--- stats ---';   curl -s $BASE/api/stats
echo; echo '--- search ---'
curl -s -X POST $BASE/api/search -H 'Content-Type: application/json' \
  -d '{"query":"隔离级别","course":"数据库系统","k":5}'
echo; echo '--- logs ---';    curl -s "$BASE/api/logs/search?limit=5"
echo
```

- 若安装了 `jq`，可把 `curl -s ...` 换成 `curl -s ... | jq` 便于阅读。
- 无 `jq` 时看 `used_vector` / `used_fulltext` / `took_ms` / `result_count` 等字段即可，均为明文 JSON。

