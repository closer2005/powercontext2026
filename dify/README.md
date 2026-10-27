# 离谱法庭 · The Absurd Court

> 2026 数据库大赛 · 生态伙伴题「Dify」参赛作品
> 用 Dify Chatflow 编排一场**可以起诉任何东西**的荒诞庭审，用 **seekdb** 存储知识库向量与案卷数据。

```
⚖️  本官升堂——你可以在线起诉任何东西：
    通敌的充电线、恶意循环的周一、非法占床的猫、半夜回放的尴尬回忆。
    AI 法官「包青天 2.0」开庭，被告（物件成精）当庭狡辩，
    你补充证据自由辩论，最后法官检索《荒诞法典》并翻出你自己的旧案底，
    当庭宣读一份离谱判决书，案卷永久归档——下次开庭，本官会引用你的案底。
```

---

## 1. 作品创意与玩法

### 1.1 一句话

一个"什么都能告"的荒诞法庭：**低门槛**（一句话立案）、**高意外**（每个被告都能狡辩出花）、
**有连续性**（判例与案底会反噬你）、**可分享**（判决书本身就是段子）。

### 1.2 游戏循环（五步）

| 步骤 | 用户操作 | 系统行为 |
|---|---|---|
| 1️⃣ 立案 | 输入「我要起诉我家的充电线，罪名是通敌，要求它当庭道歉」 | LLM 解析出被告/罪名/诉求，书记员服务生成案号（`#0042`，来自 seekdb 自增 id） |
| 2️⃣ 开庭 | （自动） | 检索你名下的历史判例 → 法官宣读开庭词（含案号）→ 被告以第一人称狡辩/反诉 |
| 3️⃣ 辩论 | 继续补充证据、威胁、求情、胡搅蛮缠 | 法官点评新证据，被告继续回嘴（多轮，携带会话记忆） |
| 4️⃣ 宣判 | 输入「宣判」 | 从《荒诞法典》知识库做**向量检索**（seekdb）→ 结合先例逐条写判决书：罪名成立/不成立、荒诞罚则、法官金句 |
| 5️⃣ 归档 | （自动） | 判决写入 seekdb `cases` 表，返回归档回执与累计结案数 |

另外两个随时可用的指令：

- 输入「怎么玩」→ 返回玩法说明（不会被误判为新案件）；
- 输入「查阅我的案底」→ 返回立案数、胜败战绩、高频被告与你的**玩家称号**：
  法庭新鲜人 → 偶尔较真的市民 → 法庭常客 → 无理取闹大师 → 让法官都害怕的原告
  （特例：≥3 案且从未胜诉 → 「屡战屡败的执着原告」）。

### 1.3 验收演示动作（评审可按此复现）

同一浏览器/同一 `user` 连打 3 场官司 → 第 2/3 场开庭时法官会引用第 1 场案号判例 →
最后输入「查阅我的案底」看到统计与称号。完整输入/输出见 `VERIFICATION.md` 的 V1~V5。

## 2. 技术分工：Dify × seekdb

```
┌────────────────────────── Dify 1.18.0（Docker Compose） ──────────────────────────┐
│  Chatflow《离谱法庭》 = 应用核心编排（25 节点 / 28 连线 / 6 会话变量）              │
│    Start → IF/ELSE 意图路由 → 立案解析 LLM → Code 解析 → HTTP 建案卷/查先例          │
│            → 开庭 LLM → Answer                                                     │
│            辩论 LLM → Answer                                                       │
│            宣判：Template 拼检索词 → Knowledge Retrieval → Code 拼法条 → 判决 LLM   │
│                  → Code 解析 JSON（含先例确定性清洗）→ HTTP 归档                       │
│                  → 重置会话变量 → Answer                                             │
│            查案底：HTTP /api/stats → Answer                                          │
└───────────────┬───────────────────────────────┬───────────────────────────────────┘
                │ DB（SQLAlchemy）              │ 知识库向量（VECTOR_STORE=seekdb）
                ▼                               ▼
┌──────────────────────────── seekdb（单实例，容器内 2881）─────────────────────────┐
│ ① dify        ：Dify 部署主数据库（账号/应用/会话/工作流，约 172 张表）              │
│ ① dify_plugin ：Dify 插件数据库（plugin_daemon 以 MySQL 驱动连接）                  │
│ ② dify_vector ：知识库《荒诞法典》的 embedding 向量（Knowledge Retrieval 从这里召回）│
│ ③ absurd_court：应用案卷库（cases 表：立案/先例/案底/归档）                         │
└────────────────────────────────┬──────────────────────────────────────────────────┘
                                 ▲ MySQL 协议（宿主机 127.0.0.1:2885）
                      ┌──────────┴───────────────────┐
                      │ 离谱法庭书记员服务（Python）   │
                      │ 标准库 http.server + PyMySQL │
                      │ 立案 / 先例检索 / 归档 / 案底  │
                      └──────────▲───────────────────┘
                                 │ HTTP（host.docker.internal:8899）
                        Dify HTTP Request 节点调用
```

### 2.1 seekdb 的三重实际职责（均有运行证据）

| # | 职责 | 说明 | 证据 |
|---|---|---|---|
| **①** | **Dify 部署主数据库** | `DB_TYPE=seekdb`：Dify 自身的账号、应用、会话、工作流、消息等约 **172 张表**都在 seekdb 的 `dify` 库；插件库 `dify_plugin` 也在同一实例（plugin_daemon 用 MySQL 驱动） | 迁移日志 + `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dify'` = 172 + `dify.alembic_version` |
| **②** | **知识库向量存储** | `VECTOR_STORE=seekdb`：《荒诞法典》的 embedding 向量保存在 seekdb 的 `dify_vector` 库；`retrieve_codex` 节点每次召回的法条都来自 seekdb | 知识库召回测试截图 + `SHOW TABLES FROM dify_vector` / `SELECT COUNT(*)` 行数 |
| **③** | **应用数据存储（案卷库）** | 书记员服务通过 MySQL 协议读写 `absurd_court.cases`；立案/先例/案底/归档均来自 seekdb | `SELECT * FROM cases` 输出 + 服务访问日志 |

> seekdb 同时是**部署数据库**和**功能数据存储**——这是本题"Dify + seekdb"结合最深的方式：
> 去掉 seekdb，Dify 无法启动、知识库无法召回、案卷与先例全部消失。

### 2.2 Dify 的职责

整条业务流程编排：意图路由（IF/ELSE）、多轮会话状态（conversation variables）、
LLM 调用（5 个 LLM 节点，含多轮记忆）、知识库向量检索、HTTP 工具调用、Code 节点解析与容错、
答案渲染（Answer）。**Dify 承担应用核心流程，seekdb 承担部署数据库 + 向量存储 + 案卷库三类真实数据。**

### 2.3 为什么这算"技术结合有效"

- seekdb 是 **Dify 自身的数据库**（`DB_TYPE=seekdb`）：整个平台的账号、应用、会话、工作流草稿都在 seekdb；
- 没有 seekdb，知识库无法完成向量索引与语义召回（判决书引用《荒诞法典》就无从谈起）；
- 没有 seekdb，案号、先例、案底统计、归档回执全部消失，"越打越像常客"的核心体验不成立；
- 三类使用都可在迁移日志、应用运行记录与数据库查询中直接核对（见 `VERIFICATION.md` 与 `evidence/seekdb-queries.md`）。

## 3. 运行环境与版本

| 组件 | 版本 / 说明 |
|---|---|
| Dify | **1.18.0**（官方 Docker Compose：`langgenius/dify-api:1.18.0`、`langgenius/dify-web:1.18.0` 等；DSL 版本 `0.7.0`，`mode: advanced-chat`） |
| seekdb | `oceanbase/seekdb:latest`，服务端 **v1.4.0.0**（MySQL 协议 5.7.25）；容器内 2881，宿主机 `127.0.0.1:2885` |
| Dify 数据库 | **`DB_TYPE=seekdb`**：Dify 主库 `dify`（约 172 张表）+ 插件库 `dify_plugin`，均在同一个 seekdb 实例 |
| 向量库 | **`VECTOR_STORE=seekdb`**：知识库向量在 `dify_vector` 库（同一 seekdb 实例） |
| 案卷库 | `absurd_court.cases`（同一 seekdb 实例，书记员服务经 MySQL 协议读写） |
| seekdb 兼容补丁 | Dify 1.18.0 的 1 个 alembic 迁移改用普通表（seekdb v1.4 不支持 `CREATE TEMPORARY TABLE`），见 `deployment/patches/` |
| 书记员服务 | Python 3.10+，仅依赖 `PyMySQL`（标准库 `http.server`），默认端口 8899 |
| LLM | OpenAI 兼容接口。本地取证：llama.cpp **b11935** + `qwen2.5-3b-instruct`（端口 8000，可换任意更强的 OpenAI 兼容模型） |
| Embedding | OpenAI 兼容接口。本地取证：llama.cpp b11935 + `bge-small-zh-v1.5`（端口 8001，**维度 512**） |
| Rerank | **不使用**（知识检索节点 `reranking_enable=false`） |
| 插件 | 市场插件 **OpenAI-API-compatible 0.0.73**（`langgenius/openai_api_compatible:0.0.73`，离线 `.difypkg` 安装）；无自定义插件 |
| 浏览器 | Chrome / Edge 最新版（Dify Web 控制台） |

> **模型可替换**：DSL 中所有 LLM 节点默认 `provider=langgenius/openai_api_compatible/openai_api_compatible`、
> `model=qwen2.5-3b-instruct`；换成任意 OpenAI 兼容模型只需在画布中重新选择（或重新生成 DSL，见 §6）。

## 4. 交付物清单

```
dify/
├── README.md                       # 本文件：创意/玩法/技术分工/环境/步骤/入口/限制
├── VERIFICATION.md                 # 验证样例 V1~V5 + 实际运行证据
├── apps/
│   ├── absurd-court.chatflow.yml   # 主 DSL（Dify 1.18.0 可导入）
│   ├── build_dsl.py                # DSL 生成脚本（可复现）
│   └── README.md                   # 导入顺序、模型/知识库/服务地址重绑定
├── knowledge/
│   ├── absurd_codex.md             # 《荒诞法典》36 条（知识库源数据）
│   └── README.md                   # 导入/索引/检索配置、dataset 绑定步骤
├── memory-service/                 # 书记员服务（案卷库后端）
│   ├── app.py  schema.sql  requirements.txt  config.example.env
│   ├── run.ps1  run.sh  README.md
├── deployment/
│   ├── README.md                   # Dify 1.18 + seekdb 部署（含三重职责与启动顺序）
│   ├── env.additions.example       # DB_TYPE=seekdb / VECTOR_STORE=seekdb 等关键 env 片段
│   ├── docker-compose.override.yaml# 实际使用的 override（seekdb 宿主机端口、plugin_daemon 驱动）
│   ├── seekdb-init.md              # seekdb 三库 + 案卷库初始化/验证命令
│   └── patches/
│       ├── README.md               # seekdb 临时表兼容补丁：原因、diff、应用与验证步骤
│       ├── 2026_08_27_1200-..._migrate_legacy_model_types.py
│       └── seekdb_init.sql         # CREATE DATABASE dify / dify_plugin / dify_vector
└── evidence/
    ├── screenshots/*.png           # Dify UI 截图（聊天、知识库、工作流运行、seekdb 配置）
    ├── logs/*.log                  # 会话请求/响应日志、服务日志
    └── seekdb-queries.md           # 三重职责的 seekdb 真实查询输出
```

## 5. 从零启动（完整步骤）

### 5.0 前置条件

- Docker Desktop / Docker Engine + Compose v2；**6 GB 以上空闲内存**（seekdb 默认 2G + Dify 各容器）
- Python 3.10+（宿主机，用于书记员服务）
- 一个 OpenAI 兼容的模型服务（本作品用 llama.cpp 在宿主机提供 chat:8000 + embedding:8001）
- 网络：Dify 容器需能访问宿主机 `host.docker.internal:8899`（书记员）与 `:8000/:8001`（模型）

### 5.1 部署 Dify 1.18.0 + seekdb

完整步骤与原理见 `deployment/README.md`（含 seekdb 三重职责、建库、补丁、验证）。核心命令：

```bash
# 1) 获取 Dify 1.18.0
cd dify-1.18.0/docker && cp .env.example .env

# 2) 写入 seekdb 三重职责配置（详见 deployment/env.additions.example）
cat >> .env <<'EOF'
DB_TYPE=seekdb
DB_HOST=seekdb
DB_PORT=2881
DB_USERNAME=root
DB_PASSWORD=<SEEKDB_PASSWORD>
DB_DATABASE=dify
DB_PLUGIN_DATABASE=dify_plugin
PLUGIN_DAEMON_DB_TYPE=mysql
VECTOR_STORE=seekdb
OCEANBASE_VECTOR_HOST=seekdb
OCEANBASE_VECTOR_PORT=2881
OCEANBASE_VECTOR_USER=root
OCEANBASE_VECTOR_PASSWORD=<SEEKDB_PASSWORD>
OCEANBASE_VECTOR_DATABASE=dify_vector
SEEKDB_MEMORY_LIMIT=2G
SEEKDB_HOST_PORT=2885
EOF
cp deployment/docker-compose.override.yaml .        # seekdb 宿主机端口 + plugin_daemon 驱动

# 3) 起 seekdb → 建三个库 → 打迁移补丁 → 跑迁移（见 deployment/patches/README.md）
docker compose --profile seekdb up -d seekdb
docker exec -i seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$SEEKDB_PASSWORD" < deployment/patches/seekdb_init.sql
docker compose up -d api
docker cp deployment/patches/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py \
  "$(docker compose ps -q api)":/app/api/migrations/versions/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py
docker compose run --rm --no-deps -e MODE=migration api

# 4) 启动全部服务
docker compose up -d
docker compose ps
```

打开 `http://localhost` 完成管理员初始化。

### 5.2 配置模型供应商

Dify 控制台 → 设置 → 模型供应商 → 安装 **OpenAI-API-compatible** 插件 → 添加：

- LLM：`qwen2.5-3b-instruct`，Base URL `http://host.docker.internal:8000/v1`，上下文 8192
- Text Embedding：`bge-small-zh-v1.5`，Base URL `http://host.docker.internal:8001/v1`，**维度 512**

详见 `deployment/README.md` §6。

### 5.3 建知识库并索引

见 `knowledge/README.md`：控制台 → 知识库 → 创建《荒诞法典》→ 上传 `knowledge/absurd_codex.md`
→ 通用分段（分隔符 `\n## `，最大 500 / 重叠 50）→ 高质量索引（`bge-small-zh-v1.5`）
→ 检索向量 semantic / top_k=3 / score 阈值 0.2。

### 5.4 导入 DSL 并绑定

见 `apps/README.md`：

```bash
# 可选：把真实 dataset_id 写进 DSL 再导入
python apps/build_dsl.py --dataset-id <DATASET_UUID>
```

Dify 控制台 → 创建应用 → 导入 DSL `apps/absurd-court.chatflow.yml`
→ 画布中检查 `retrieve_codex` 节点的知识库是否为《荒诞法典》、5 个 LLM 节点模型是否可用
→ 保存 → **发布**。

### 5.5 初始化 seekdb 案卷库 + 启动书记员服务

```bash
cd memory-service
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.env config.env                 # 改 DB_PORT=2885（宿主机映射端口）与 DB_PASSWORD
python app.py --init-db                          # 在 seekdb 创建 absurd_court 库 + cases 表（幂等）
.\run.ps1        # Windows；Linux/macOS: ./run.sh
```

> `DB_HOST=127.0.0.1`、`DB_PORT=2885` 是宿主机侧端口；容器内 seekdb 仍是 2881。
> 若 seekdb 直接发布在 2881，改成 2881 即可。

验证：

```bash
curl -s http://127.0.0.1:8899/healthz            # ok
docker compose exec api curl -s http://host.docker.internal:8899/healthz   # ok（容器内可达）
```

### 5.6 应用入口

- **Web 体验**：Dify 控制台 → 应用《离谱法庭 · The Absurd Court》→ 「预览」/「运行」
- **Service API**：应用 → 访问 API → 创建 API Key，然后：

```bash
curl -X POST 'http://localhost/v1/chat-messages' \
  -H 'Authorization: Bearer <APP_API_KEY>' \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{},"query":"我要起诉我家的充电线，罪名是通敌，要求它当庭道歉","response_mode":"blocking","user":"demo-user-001","conversation_id":""}'
```

多轮对话把返回的 `conversation_id` 回传；`user` 标识原告，决定案底与先例归属。

## 6. 重新绑定与调参

| 需要改什么 | 怎么做 |
|---|---|
| 换 LLM 模型 | UI 中改 5 个 LLM 节点；或 `python apps/build_dsl.py --model <name> --provider <id>` 重新生成并导入 |
| 换 Embedding 模型 | 知识库设置中修改 embedding 模型并**重建索引**（向量维度/语义空间变了必须重建） |
| 书记员服务地址/端口 | UI 改 4 个 HTTP 节点 URL；或 `python apps/build_dsl.py --clerk-base http://host:port` |
| 知识库 dataset | 画布中 `retrieve_codex` 重新选择《荒诞法典》；或带 `--dataset-id` 重新生成 DSL |
| 检索条数/阈值 | `retrieve_codex` 节点 `top_k` / `score_threshold`（默认 3 / 0.2），与知识库检索配置保持一致 |

## 7. 外部服务、网络与资源条件

- **模型服务**：本作品不内置模型。需自行提供 OpenAI 兼容的 chat 与 embedding 服务：
  - 本地 llama.cpp 示例（两个服务，本作品取证使用 8000/8001 端口）：
    ```bash
    llama-server -m qwen2.5-3b-instruct-q4_k_m.gguf --port 8000 -c 8192 --jinja
    llama-server -m bge-small-zh-v1.5-f16.gguf --embeddings --port 8001
    ```
  - 或用任意在线 OpenAI 兼容服务（把 Base URL / API Key 填进 Dify 供应商配置即可，无需改 DSL）。
- **网络条件**：
  - Dify 容器 → 宿主机书记员服务 `host.docker.internal:8899`（Linux 需 `extra_hosts: host-gateway`）；
  - Dify 容器 → 模型服务 `host.docker.internal:8000/8001`；
  - 安装 OpenAI-API-compatible 插件需要访问 Dify 插件市场（或离线导入 `.difypkg`）。
- **资源**：6 GB+ 内存（seekdb 默认上限 2G）；3B 模型 CPU 推理约 5~10 tok/s，建议 8 核以上。
- **端口**：80（Dify）、**2885（seekdb 宿主机映射，容器内 2881）**、8899（书记员）、8000/8001（模型）。

## 8. 已知功能限制

- **seekdb 兼容补丁**：seekdb v1.4.0.0 不支持 `CREATE TEMPORARY TABLE`，Dify 1.18.0 的
  1 个 alembic 迁移（`migrate_legacy_model_types`）已改为普通表 + 显式 DROP（`deployment/patches/`），
  除此之外 Dify 源码/镜像无任何改动；升级 Dify 版本时需重新核对该迁移。
- 本地 `qwen2.5-3b-instruct` 中文创意与 JSON 遵循能力有限：判决书风格一般，
  但 `parse_code / verdict_code` 节点做了容错（去代码围栏、截取首个 JSON、兜底字段），流程不会崩。
  换 7B+ 模型可显著提升观感。
- 先例检索是"关键词 + 原告优先"的 SQL 模糊匹配，不是语义检索；这是刻意的轻量设计（案卷库只存结构化数据），
  语义检索能力由 seekdb 上的知识库向量检索承担。
- 同一 `user` 的案底永久累积；目前未提供"清空案底"的用户界面（可直接清 `absurd_court.cases` 表重置）。
- 书记员服务为单进程标准库 HTTP 服务，适合单机演示，未做鉴权与高并发优化。
- 本作品所有法条、判决均为**虚构娱乐内容**，不构成任何现实法律意见。

## 9. 来源与致谢

- Dify（Apache-2.0）：https://github.com/langgenius/dify — 本作品基于官方 1.18.0 Docker Compose；
  仅对 1 个 alembic 迁移打 seekdb 兼容补丁（见 `deployment/patches/`），业务代码未改动。
- seekdb（OceanBase 开源）：https://github.com/oceanbase/seekdb — 同时作为 **Dify 部署主数据库 +
  知识库向量存储 + 应用案卷库**。
- 《荒诞法典》36 条、提示词、书记员服务、DSL 均为本作品**原创**；
  未复用第三方 DSL/工作流/数据集。DSL 字段依据 Dify 1.18.0 源码与官方测试夹具编写。

## 10. 验证与证据

验证样例（V1 立案+开庭+辩论、V2 宣判+法典引用、V3a 跨场次记忆、V3b 案底统计、V4 玩法说明、V5 健壮性）
的输入、预期与实际运行结果见 **`VERIFICATION.md`**；原始截图、日志与 seekdb 查询输出见 `evidence/`。