# CiteSeek 知源 · 设计规格（v1）

> 本文件是给实现者（Qoder / 工程同事）的权威规格。实现时如遇冲突，以本文件为准；需要偏离时先在 `docs/DECISIONS.md` 记录理由。

## 1. 项目定位

**CiteSeek 知源**：面向学生与科研工作者的「可溯源」个人笔记 / 文献片段混合检索助手。

一句话：把平时散落在笔记软件、论文摘录、课堂记录里的零散文字导入 seekdb，用自然语言提问即可找回相关片段，并明确给出它来自哪份资料的哪一段；再配合"间隔复习"把找回来的知识真正用起来。

**要解决的真实痛点**（来自团队同学的日常）：
- 期末复习时只记得"老师讲过某个概念"，翻遍十几个 Markdown/Word 文件找不到原话。
- 关键词检索依赖原词，换个说法（同义表达）就搜不到；纯向量检索又常常召回"意思差不多但事实不对"的内容。
- 找到内容后没有出处，无法判断可信度；也不会顺手复习，下次还得再找一遍。

**核心价值**：
1. **混合检索**：向量语义 + 全文关键词 + 结构化条件（课程/主题/时间）在 seekdb 内一次完成，RRF 融合排序，比单一模式更稳。
2. **出处优先**：每条结果都带资料名、课程/主题、导入时间，回答里可以放心引用。
3. **检索即复习**：一键把命中的片段加入复习清单，按间隔重复算法安排复习，学习进度同样存在 seekdb 里，越用越贴合自己的薄弱点。

## 2. 技术栈（必须遵守）

- Python 3.11+
- Web 框架：FastAPI + Uvicorn
- 检索数据库：**seekdb**（Docker `oceanbase/seekdb:latest`，MySQL 协议 2881 端口）
- Python 检索 SDK：**pyseekdb**（远程 server 模式）
- 结构化业务表：pymysql 直连 seekdb（MySQL 兼容）
- 向量模型：`BAAI/bge-small-zh-v1.5`（512 维，ONNX，本地 CPU 推理；通过 `hf-mirror.com` 下载，可离线缓存），ONNX Runtime + tokenizers
- 前端：原生 HTML/CSS/JS（无构建步骤、无 CDN 依赖），由 FastAPI 托管静态文件
- 测试：pytest

## 3. 目录结构（实现时严格遵守）

```
qoder/
├── README.md                 # 项目说明 + 快速开始
├── docker-compose.yml        # seekdb + citeseek 两个服务
├── Dockerfile                # citeseek 应用镜像
├── requirements.txt
├── .env.example
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI 入口、路由、静态文件托管
│   ├── config.py             # 环境变量配置
│   ├── db.py                 # pymysql 连接池 + 建表 + CRUD（notes/review/search_log）
│   ├── embeddings.py         # BGE-zh ONNX 嵌入 + hash 兜底 + API 模式
│   ├── vector_store.py       # pyseekdb collection 封装：upsert / hybrid_search / refresh
│   ├── chunking.py           # 文本切块（按段落/句子，带重叠）
│   ├── services.py           # 业务编排：导入、检索、复习
│   └── seed.py               # 导入示例数据（幂等）
├── web/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── data/samples/             # 示例笔记（Markdown，每篇带 front-matter）
├── tests/
│   ├── test_chunking.py
│   ├── test_embeddings.py
│   └── test_api.py
├── docs/
│   ├── DESIGN.md             # 本文件
│   ├── RUNBOOK.md            # 运行说明（环境/依赖/启动/验证）
│   ├── VERIFY.md             # 验证样例（输入/步骤/预期/技术证据）
│   ├── ARCHITECTURE.md
│   └── QODER_DEV_RECORD.md   # Qoder 开发记录
└── site/                     # 作品展示网站（Qoder Sites 发布）
```

## 4. 数据模型

### 4.1 seekdb collection（向量 + 全文）

- collection 名称：`citeseek_chunks_v1`
- 维度：`512`，距离：`cosine`，HNSW 索引
- `embedding_function=None`（嵌入一律由应用层计算并显式传入，便于控制 query 前缀与降级）
- id：chunk id（uuid4 hex）
- document：chunk 原文（中文，<= 400 字）
- metadata 字段（全部用于 `where` 过滤）：
  - `note_id` (str)
  - `title` (str)
  - `course` (str)
  - `topic` (str)
  - `tags` (str，空格分隔)
  - `source` (str，可选：文件名/来源)
  - `created_day` (str，`YYYY-MM-DD`)
  - `seq` (int，chunk 在原文中的序号)

### 4.2 MySQL 业务表（pymysql）

```sql
CREATE TABLE IF NOT EXISTS notes (
  id VARCHAR(32) PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  course VARCHAR(64) DEFAULT '',
  topic VARCHAR(128) DEFAULT '',
  tags VARCHAR(255) DEFAULT '',
  source VARCHAR(255) DEFAULT '',
  content MEDIUMTEXT NOT NULL,
  chunk_count INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS review_items (
  chunk_id VARCHAR(32) PRIMARY KEY,
  note_id VARCHAR(32) NOT NULL,
  due_at DATETIME NOT NULL,
  interval_days INT DEFAULT 0,
  ease FLOAT DEFAULT 2.5,
  reps INT DEFAULT 0,
  lapses INT DEFAULT 0,
  last_grade INT DEFAULT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_due (due_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS search_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  query VARCHAR(512) NOT NULL,
  course VARCHAR(64) DEFAULT '',
  topic VARCHAR(128) DEFAULT '',
  mode VARCHAR(16) DEFAULT 'hybrid',
  k INT DEFAULT 0,
  took_ms INT DEFAULT 0,
  result_count INT DEFAULT 0,
  used_vector TINYINT DEFAULT 0,
  used_fulltext TINYINT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

启动时自动建表（重试等待 seekdb ready）。

## 5. 检索逻辑（核心，必须按此实现）

`POST /api/search`：

1. 计算 query 向量：`embeddings.embed_query(query)`（BGE 中文模型需要加查询前缀 `为这个句子生成表示以用于检索相关文章：`，入库的文档不加）。
2. 构造过滤条件 `where`：course/topic 非空时加入 `{"course": {"$eq": ...}}` 等（`$and` 组合）。
3. 调 `collection.hybrid_search`：
   ```python
   collection.hybrid_search(
       query={"where_document": {"$contains": query}, "where": where or None, "n_results": max(k*4, 20)},
       knn={"query_embeddings": [query_vec], "where": where or None, "n_results": max(k*4, 20)},
       rank={"rrf": {"rank_window_size": 60, "rank_constant": 60}},
       n_results=k,
       include=["documents", "metadatas", "distances"],
   )
   ```
   - `$contains` 为空字符串时不能传（构建时省略 `where_document`）。
   - 若 `hybrid_search` 抛错（例如旧版引擎不支持），降级：先 `query`（向量）再 `get(where_document={"$contains": ...})`，用 RRF 在应用层融合，并在响应的 `debug.degraded` 标记。
4. 结果组装：`chunk_id, note_id, title, course, topic, tags, text, score(=RRF score 或 1/distance), distance, matched_by(["vector","fulltext"])`；全文匹配用 `text` 中是否包含 query 的任一 2 字以上子串做近似标记；高亮用前端完成。
5. 写入 `search_log`（took_ms、result_count、used_vector/used_fulltext）。
6. 返回 `{"query", "took_ms", "mode", "results": [...], "debug": {...}}`。

`refresh_index()`：每次批量导入/删除之后调用一次（seekdb 向量索引是异步构建的，不刷新会查不到新数据）。检索接口本身不强制刷新。

## 6. 复习算法（简化 SM-2）

- 新加入：`due_at = now`，`interval_days=0`，`ease=2.5`，`reps=0`。
- 评分 grade ∈ {0,1,2,3}：0=忘了，1=模糊，2=记住了，3=很熟练。
  - `grade >= 2`：`reps += 1`；`interval_days = 1 if reps==1 else 3 if reps==2 else round(interval_days * ease)`；`ease = clamp(ease + (0.1 - (3-grade)*0.08), 1.3, 2.8)`
  - `grade < 2`：`lapses += 1`；`reps = 0`；`interval_days = 1`；`ease = clamp(ease - 0.2, 1.3, 2.8)`
  - `due_at = now + interval_days 天`
- `GET /api/review/due` 返回 `due_at <= now` 的条目（联表取 chunk 文本与 note 标题、课程）。

## 7. API 契约（全部 JSON，UTF-8）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/api/health` | - | `{status, seekdb:{connected, database, collection, count}, embed:{mode, model, dim, degraded}, version}` |
| GET | `/api/stats` | - | `{notes, chunks, review_items, review_due, searches, avg_latency_ms, top_queries:[{query,count}], last_search_at}` |
| GET | `/api/notes?limit=100&course=` | - | `{total, notes:[{id,title,course,topic,tags,source,chunk_count,created_at}]}` |
| POST | `/api/notes` | `{title, course?, topic?, tags?, source?, content}` | `{id, chunk_count}`；空 content/title → 400 |
| DELETE | `/api/notes/{id}` | - | `{deleted:true}`（同时删 collection 中该 note 的 chunks 与 review_items） |
| POST | `/api/import/samples` | - | `{imported, skipped}`（幂等：按 title 判重） |
| POST | `/api/search` | `{query, course?, topic?, k=8, mode="hybrid"}` | 见 §5；query 为空 → 400 |
| POST | `/api/review/{chunk_id}/add` | - | `{ok:true, due_at}` |
| GET | `/api/review/due?limit=10` | - | `{total, items:[{chunk_id,note_id,title,course,topic,text,due_at,reps,interval_days}]}` |
| POST | `/api/review/{chunk_id}/answer` | `{grade:0-3}` | `{ok, interval_days, ease, due_at, reps}` |
| GET | `/api/logs/search?limit=20` | - | `{items:[{query,mode,took_ms,result_count,used_vector,used_fulltext,created_at}]}`（技术证据） |
| GET | `/` | - | 前端页面 `web/index.html` |

统一错误格式：`{"detail": "..."}`（FastAPI 默认），HTTP 400/404/500。

CORS：允许 `*`（仅为本地演示方便）。

## 8. 前端要求（web/）

单页应用，三个主视图（顶部 tab 切换）：

1. **检索**
   - 大搜索框 + Enter 搜索；下方两个下拉框（课程 / 主题，选项从 `/api/notes` 聚合）+ 结果数选择。
   - 结果卡片：标题（资料名）、课程/主题标签、片段（关键词 `<mark>` 高亮）、相似度/融合分数条、`来自第 N 段`、按钮「加入复习」。
   - 顶部显示 `took_ms`、`mode`、命中来源（向量/全文）徽标；无可信结果时给出"换个说法/放宽筛选"的提示文案。
   - 空态：引导"先到资料库导入或载入示例数据"。
2. **资料库**
   - 左侧导入表单（标题、课程、主题、标签、正文 textarea、来源），提交后刷新列表。
   - 右侧笔记列表（课程筛选、删除按钮），顶部「载入示例数据」按钮。
3. **复习**
   - 显示今日待复习卡片（片段 + 出处），四个评分按钮；完成后自动加载下一张；显示今日已复习数、剩余数。
4. **技术面板（固定底部或页脚卡片）**
   - 展示 seekdb 状态（`/api/health`）、最近检索日志（`/api/logs/search`，含耗时/结果数/向量与全文标记）、collection 统计。
   - 明确写出"向量检索 + 全文检索 + 结构化过滤 → RRF 融合"，让评审能直接看出 seekdb 的实际作用。

视觉：浅色主题，主色 `#0f766e`（teal）+ `#f59e0b` 点缀；卡片圆角 12px、柔和阴影；字体 `system-ui, "PingFang SC", "Microsoft YaHei"`；响应式（>=1024px 双栏，<768px 单栏）；无任何外部 CDN 资源。

## 9. 配置（.env）

```
SEEKDB_HOST=127.0.0.1
SEEKDB_PORT=2881
SEEKDB_USER=root
SEEKDB_PASSWORD=
SEEKDB_DATABASE=citeseek
EMBED_MODE=auto          # auto | onnx | hash | api
EMBED_MODEL=BAAI/bge-small-zh-v1.5
EMBED_CACHE_DIR=~/.cache/citeseek/models
HF_ENDPOINT=https://hf-mirror.com
EMBED_API_BASE=
EMBED_API_KEY=
EMBED_API_MODEL=
APP_PORT=8000
```

- `EMBED_MODE=auto`：优先加载 BGE ONNX；下载/加载失败则退化为 `hash`（512 维字符 n-gram 哈希，确定性、离线可用），`/api/health` 的 `embed.degraded=true` 并给出原因；全文检索仍完整可用。
- `EMBED_MODE=hash`：不联网（CI/无网环境）。
- `EMBED_MODE=api`：OpenAI 兼容 `/embeddings` 接口（失败同样退化为 hash）。

## 10. Docker 部署（评审复现路径）

`docker-compose.yml`：
```yaml
services:
  seekdb:
    image: oceanbase/seekdb:latest
    ports: ["2881:2881", "2886:2886"]
    volumes: ["./seekdb_data:/var/lib/seekdb"]
    healthcheck: ...
  citeseek:
    build: .
    ports: ["8000:8000"]
    environment:
      - SEEKDB_HOST=seekdb
      - SEEKDB_PORT=2881
      - SEEKDB_DATABASE=citeseek
      - EMBED_MODE=auto
    depends_on: [seekdb]
    volumes: ["citeseek_model_cache:/root/.cache/citeseek"]
volumes: {citeseek_model_cache: {}}
```
应用启动时等待 seekdb（重试 60s）、建库建表、初始化 collection。首次启动若无数据，前端提供「载入示例数据」按钮（也支持 `SEED_ON_START=1` 自动导入）。

## 11. 验收标准（实现完成的定义）

1. `docker compose up -d --build` 后，`curl http://localhost:8000/api/health` 返回 `status: ok` 且 `seekdb.connected: true`、`embed.dim: 512`。
2. 点击「载入示例数据」后 `/api/stats` 的 `notes >= 20`、`chunks >= 60`。
3. `POST /api/search {"query":"事务隔离级别"}` 返回结果中包含数据库课程相关片段，且 `took_ms` 有值、`search_log` 增加记录。
4. 加入复习后 `/api/review/due` 能取到该片段；评分后 `due_at` 被推后。
5. `pytest -q` 全绿（chunking / embeddings(hash 模式) / API 冒烟，API 测试在 seekdb 不可用时可 skip）。
6. 无外网时 `EMBED_MODE=hash` 仍可完整跑通检索（验证"降级不崩"）。

## 12. 非目标（本期不做）

- 多用户注册/登录、权限隔离
- PDF/Word 二进制解析（只支持粘贴文本与 Markdown/TXT 文件上传）
- 大模型生成式问答（只做检索 + 出处；如后续加，必须单独开关）
- 移动端 App、多语言