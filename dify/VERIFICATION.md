# 验证样例与运行证据（VERIFICATION）

> 本文件记录《离谱法庭 · The Absurd Court》在 **Dify 1.18.0 + seekdb** 本地环境中的真实运行结果。
> 所有请求/响应日志、截图、数据库查询输出均来自本地实际运行，原始文件见 `evidence/` 目录。
> 最后一次完整验证：**2026-10-28 04:31**（user=`demo-final`）。

## 0. 验证环境

| 项 | 值 |
|---|---|
| Dify | 1.18.0（官方 Docker Compose，镜像 `langgenius/dify-api:1.18.0` / `dify-web:1.18.0`） |
| Dify 数据库 | **seekdb**（`DB_TYPE=seekdb`）：`dify` 库 172 张表，`dify_plugin` 库 13 张表；`alembic_version=b9d3f7a5c102` |
| seekdb | `oceanbase/seekdb:latest`，服务端 `5.7.25-OceanBase seekdb-v1.4.0.0`；容器内 2881，宿主机 `127.0.0.1:2885` |
| 向量库 | **`VECTOR_STORE=seekdb`**：`dify_vector` 库，向量表 `vector_index_ac7f91e4_254c_42f4_bd83_08a975392e53_node`，**38 行**（=《荒诞法典》38 个分段） |
| 案卷库 | `absurd_court.cases`（同一 seekdb 实例，书记员服务读写） |
| LLM | OpenAI 兼容 `qwen2.5-3b-instruct`（llama.cpp b11935，`:8000`，ctx 4096 / max_tokens 2048） |
| Embedding | OpenAI 兼容 `bge-small-zh-v1.5`（llama.cpp b11935，`:8001`，**512 维**） |
| 插件 | 市场插件 OpenAI-API-compatible **0.0.73**（`langgenius/openai_api_compatible`） |
| 知识库 | 《荒诞法典》36 条 + 总则/附则，通用分段（分隔符 `\n## `，最大 500 / 重叠 50），高质量索引，向量检索 top_k=3 / score 0.2 |
| 书记员服务 | `memory-service` `0.0.0.0:8899`（PyMySQL → 127.0.0.1:2885/absurd_court） |
| 应用 | Chatflow《离谱法庭 · The Absurd Court》，已发布，Service API + WebApp 双入口 |
| 初始状态 | 验证前重置 `absurd_court`（DROP + 重新 `schema.sql`），案卷为空、`stage=idle`（conversation 变量默认值） |

## 1. 复现方式

```bash
# 1) 重置初始状态（清空案卷库）
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "DROP DATABASE IF EXISTS absurd_court;"
cd memory-service && python app.py --init-db

# 2) 启动书记员服务（连接 seekdb 宿主机端口 2885）
./run.ps1        # Windows；Linux: ./run.sh

# 3) 用应用 API Key 跑 V1~V5（脚本会写请求/响应日志到 evidence/logs/）
python evidence/run_verification.py --app-key "$APP_KEY" --base-url http://localhost/v1 --user demo-final

# 4) 采集 seekdb 证据（见 evidence/seekdb-queries.md）
```

> 同一 `user` 连打多场官司即可复现"跨场次记忆"：V1/V2 是第一场（conversation `dc0182ab-feca-4973-ba69-9e24dd2395af`），
> V3a 用**新会话、同一 user**再起诉充电线（conversation `8283fa18-6e2c-4e09-b7ed-66c77e23ba8f`），法官会引用第一场案号。

## 2. 验证样例与结果（全部通过）

### V1 · 立案 + 开庭 + 辩论

| 项 | 内容 |
|---|---|
| 初始条件 | `stage=idle`，新会话，user=`demo-final` |
| 输入 1 | `我要起诉我家的充电线，罪名是通敌，要求它当庭道歉` |
| 预期 1 | 返回含案号的立案词 + 被告「充电线」第一人称狡辩 + 尾注提示 |
| **实际 1**（57.8s，HTTP 200） | 见下方原文 |
| 输入 2（辩论） | `补充证据：它半夜三点偷偷发烫，还把我的手机电量从80%吸到20%` |
| 预期 2 | 法官点评新证据 + 被告继续反驳，合计 ≤160 字，保持当前案号 |
| **实际 2**（19.9s，HTTP 200） | 见下方原文 |
| seekdb 证据 | `cases` 表新增 `#0001`（`status=open`），见下方 cases 表 |
| 证据文件 | `evidence/logs/V1.log`、截图 `10-chat-1.png` |

**实际响应原文（V1 立案/开庭）：**

```
📁 立案成功，案号：#0001


离谱#0001，本官升堂，大胆问，你为何通敌？带充电线上来！
被告「充电线」：我只是传输电能，日久见人心，我心无二心！
（补充证据继续辩论，或输入「宣判」结案）
```

**实际响应原文（V1 补充证据辩论）：**

```
法官：这点证据有点意思，被告你怎么解释？
被告「充电线」："我只是发热，又不是发疯，本官明察！"
（补充证据继续辩论，或输入「宣判」结案）
```

### V2 · 宣判 + 法典引用 + 归档

| 项 | 内容 |
|---|---|
| 输入 | `宣判`（同一会话，`stage=debate`） |
| 预期 | 知识库召回《荒诞法典》→ 判决书含「本院认为」、引用法典条文、荒诞罚则 → 返回 `已归档` 回执 → seekdb 中该案 `status=closed` |
| **实际**（62.7s，HTTP 200；latency 59.126s，total_tokens 1272） | 见下方原文 |
| seekdb 证据 | `#0001` 变为 `status=closed`，`verdict=罪名成立`、`penalty/judgment` 有值（见下方 cases 表） |
| 知识库证据 | 召回测试截图 `13-knowledge-hit-testing.png`：`电器 通敌` → 第一条 电器通敌罪 score 0.67 |
| 证据文件 | `evidence/logs/V2.log`、`evidence/logs/kb-hit-testing.json`、截图 `10-chat-2.png` |

**实际响应原文：**

```
⚖️ 本官宣判：罪名成立

根据《荒诞法典》第第二条，本院认为被告在深夜私自发烫，影响原告手机电量，罪名成立。退庭。

🔨 罚则：罚其为原告连唱三夜摇篮曲

⚖️ 已归档：案卷 #0001 · 判决：罪名成立（本院累计已结 1 案）
——————
（输入「查阅我的案底」看统计，或直接发起下一场诉讼。）
```

### V3a · 跨场次记忆（同一 user，新会话）

| 项 | 内容 |
|---|---|
| 输入 | 新会话（同一 `user`）输入 `我要再次起诉我家那根充电线，罪名是屡教不改的通敌，要求它赔偿我一整个周末` |
| 预期 | 法官在开庭词中引用上一场案号判例（从重/从轻） |
| **实际**（82.3s，HTTP 200） | 见下方原文：`📜 本官翻了案底：此被告有旧案 #0001，本次参照旧案 #0001 从重审理。` |
| seekdb 证据 | 开庭前 `POST /api/cases/search` 返回 `- #0001｜被告：充电线｜罪名：通敌｜判决：罪名成立｜罚则：…｜★原告旧案`（书记员日志） |
| 证据文件 | `evidence/logs/V3a.log`、截图 `11-chat-v3a-1.png` |

**实际响应原文：**

```
📁 立案成功，案号：#0002

📜 本官翻了案底：此被告有旧案 #0001，本次参照旧案 #0001 从重审理。
离谱刑初字第0002号，大胆起来，原告，本官给你整不会了！
被告「充电线」：通敌又如何，至少我还让我的数据线在你手中发挥余热，让它继续传输数据，至少没直接通敌到电脑上！
（补充证据继续辩论，或输入「宣判」结案）
```

### V3b · 案底统计

| 项 | 内容 |
|---|---|
| 输入 | `查阅我的案底`（V3a 会话，已 2 场官司：1 结案 1 在审） |
| 预期 | 立案数、胜败战绩、称号（≥1 场后） |
| **实际**（1.0s，HTTP 200） | 见下方原文（立案总数 2 / 已结案 1 / 称号：偶尔较真的市民） |
| seekdb 证据 | `POST /api/stats` 由 `SELECT … FROM cases WHERE plaintiff=…` 聚合得到；服务日志见 `evidence/logs/clerk.log` |
| 证据文件 | `evidence/logs/V3b.log`、截图 `10-chat-3.png` |

**实际响应原文：**

```
📜 本院案底档案 · 原告：demo-final
立案总数：2 ｜ 已结案：1 ｜ 在审：1
战绩：胜诉（罪名成立）1 ｜ 败诉（罪名不成立）0
称号：偶尔较真的市民
最近案号：#0002（被告：充电线）
高频被告：充电线 ×2
提示：还有 1 场官司在审，输入「宣判」即可结案。
```

### V4 · 玩法说明（不误判为新案件）

| 项 | 内容 |
|---|---|
| 输入 | `怎么玩`（任意阶段） |
| 预期 | 返回四步玩法说明与示例输入，**不**产生新案号 |
| **实际**（0.5s，HTTP 200） | 见下方原文；调用前后 `cases` 行数不变 |
| 证据文件 | `evidence/logs/V4.log` |

**实际响应原文（节选）：**

```
⚖️ 欢迎来到离谱法庭 · The Absurd Court

【四步玩法】
1️⃣ 立案：直接说你要起诉什么，例如「我要起诉我家的充电线，罪名是通敌，要求它当庭道歉」。
2️⃣ 开庭：本官当庭宣读案号并检索你的旧案底，被告（物件成精）会当场狡辩或反诉。
3️⃣ 辩论：继续补充证据、威胁、求情、胡搅蛮缠，法官和被告都会接话。
4️⃣ 宣判：输入「宣判」，本官检索《荒诞法典》并参考先例，当庭宣读离谱判决书，案卷归档进 seekdb。

📜 输入「查阅我的案底」可查看立案数、胜败战绩与你的法庭称号。
🧾 示例：「我要起诉周一，罪名是恶意循环，要求它赔偿一个周末」

（想结案请输入「宣判」；想换一场官司请先宣判，或随时输入「怎么玩」回来看说明。）
```

### V5 · 健壮性

| 项 | 内容 |
|---|---|
| 输入 | `asdf`（无意义输入，独立 user=`demo-final-v5`） |
| 预期 | 不崩溃：仍能拆出合理默认被告/罪名完成立案开庭，或友好提示 |
| **实际**（51.8s，HTTP 200） | 成功立案 `#0003` 并开庭（被告「asdf」），工作流无异常；见下方原文 |
| 证据文件 | `evidence/logs/V5.log` |

**实际响应原文：**

```
📁 立案成功，案号：#0003


离谱刑初字第0003号，大胆问你，昨晚你到底在哪儿睡觉？
被告「asdf」：你太夸张了吧，我只是表示我还在充电，没有占床。
（补充证据继续辩论，或输入「宣判」结案）
```

## 3. seekdb 三重职责的运行证据

### 3.1 职责 ①：Dify 部署主数据库（`dify` + `dify_plugin` 库）

```sql
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dify';
SELECT version_num FROM dify.alembic_version;
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dify_plugin';
```

实测输出：

```
dify_tables          = 172
alembic_version      = b9d3f7a5c102
plugin_tables        = 13
```

> seekdb v1.4.0.0 不支持 `CREATE TEMPORARY TABLE`，Dify 1.18.0 的一个 alembic 迁移使用
> `deployment/patches/` 中的兼容补丁完成迁移；其余 Dify 源码/镜像未改动。

### 3.2 职责 ②：知识库向量存储（`dify_vector` 库）

```sql
SHOW TABLES FROM dify_vector;
SELECT COUNT(*) FROM dify_vector.`vector_index_ac7f91e4_254c_42f4_bd83_08a975392e53_node`;
```

实测输出：

```
vector table = vector_index_ac7f91e4_254c_42f4_bd83_08a975392e53_node
vectors      = 38   -- 与《荒诞法典》38 个分段完全一致
```

配合召回测试截图 `13-knowledge-hit-testing.png`（`电器 通敌` → 第一条 电器通敌罪，score 0.67），
证明知识检索节点的每次召回都来自 seekdb 中的向量数据。

### 3.3 职责 ③：应用案卷库（`absurd_court.cases`）

```sql
SELECT id,case_no,plaintiff,defendant,charge,status,verdict,penalty FROM absurd_court.cases ORDER BY id;
```

实测输出：

| id | 案号 | 原告 | 被告 | 罪名 | 状态 | 判决 | 罚则 |
|---|---|---|---|---|---|---|---|
| 1 | #0001 | demo-final | 充电线 | 通敌 | closed | 罪名成立 | 罚其为原告连唱三夜摇篮曲 |
| 2 | #0002 | demo-final | 充电线 | 屡教不改的通敌 | open | - | - |
| 3 | #0003 | demo-final-v5 | asdf | 非法占床 | open | - | - |

> 完整 SQL 与输出（含 `SHOW DATABASES`、`DESC cases`、`SHOW INDEX`）见 `evidence/seekdb-queries.md`。

## 4. 证据文件索引

### 4.1 日志

| 文件 | 内容 |
|---|---|
| `evidence/logs/verification-summary.json` | V1~V5 全部请求/响应原文、conversation_id、耗时、断言结果（本文件的原始数据） |
| `evidence/logs/V1.log` ~ `V5.log` | 按用例拆分的请求/响应原文 |
| `evidence/logs/clerk.log` | 书记员服务访问日志（四接口调用、立案/归档/先例/统计） |
| `evidence/logs/dsl-import.json` | DSL 导入结果 + draft 回读（节点数/会话变量/features） |
| `evidence/logs/kb-hit-testing.json` | 知识库召回测试（3 组 query 的命中法条与分数） |
| `evidence/run_verification.py` | 可复现的验证脚本（纯标准库，读取应用 API Key 顺序执行 V1~V5） |

### 4.2 截图

| 文件 | 说明 |
|---|---|
| `evidence/screenshots/00-console-login.png` | Dify 控制台登录页（浏览器实测） |
| `evidence/screenshots/01-apps-list.png` | 工作室应用列表（含《离谱法庭》） |
| `evidence/screenshots/02-workflow-canvas.png` | 工作流画布（节点/连线/会话变量） |
| `evidence/screenshots/03-chat-page.png` | 应用 Web 端欢迎页（开场白 + 建议问题） |
| `evidence/screenshots/04-knowledge-documents.png` | 知识库《荒诞法典》文档页（索引完成） |
| `evidence/screenshots/05-model-providers.png` | 模型供应商（OpenAI-API-compatible 两个本地模型） |
| `evidence/screenshots/06-datasets-list.png` | 知识库列表 |
| `evidence/screenshots/10-chat-1.png` | V1：立案/开庭（UI 实测，含案号与被告狡辩） |
| `evidence/screenshots/10-chat-2.png` | V2：宣判（UI 实测，判决书 + 罚则 + 归档回执） |
| `evidence/screenshots/10-chat-3.png` | V3b：查阅案底（UI 实测，统计与称号） |
| `evidence/screenshots/11-chat-v3a-1.png` | V3a：新会话再次起诉充电线（UI 实测，引用旧案 #0001） |
| `evidence/screenshots/12-workflow-logs.png` | 应用日志页（工作流运行记录） |
| `evidence/screenshots/13-knowledge-hit-testing.png` | 知识库召回测试：'电器 通敌' 命中第一条（score 0.67） |

## 5. 已知偏差与说明

- **本地 3B 模型能力限制**：`qwen2.5-3b-instruct` 在中文幽默与 JSON 遵循上偶有波动。为让玩法稳定，
  DSL 做了三处工程化处理：开庭拆成"法官开庭词 / 被告狡辩"两个 LLM 节点；先例引用改由 Code 节点
  确定性生成（无旧案时输出空串）；判决 JSON 解析节点在先例为空时清洗模型脑补的"参照判例"句子。
  即使模型输出不合格式，`parse_code / verdict_code` 也会兜底，工作流不崩。
- **判决书措辞**：3B 模型偶尔会把《荒诞法典》两条相近条文并列引用，或省略「本院认为」前的顺序词；
  内容仍符合"引用法典 + 荒谬罚则"的要求。换用 7B 以上模型即可显著改善（DSL 无需改动）。
- **先例检索语义**：书记员服务的先例检索是"原告优先 + 关键词模糊匹配"的 SQL 查询（案卷库结构化数据），
  知识库《荒诞法典》的语义向量检索由 seekdb 承担，两者分工不同，均真实可用。
- **角色扮演标签**：被告标签「被告「X」：」由 Answer 节点统一添加，确保不会因模型漏写而丢失。
- 本作品所有法条与判决均为**虚构娱乐内容**，不构成任何现实法律意见。
