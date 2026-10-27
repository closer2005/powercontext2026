# 验证样例与运行证据（VERIFICATION）

> 本文件记录《离谱法庭 · The Absurd Court》在 **Dify 1.18.0 + seekdb** 本地环境中的真实运行结果。
> 所有请求/响应日志、截图、数据库查询输出均来自本地实际运行，原始文件见 `evidence/` 目录。
>
> **状态：初稿（联调实测后更新为最终内容）**

## 0. 验证环境

| 项 | 值 |
|---|---|
| 日期 | <!-- TODO: 实测日期 --> |
| Dify | 1.18.0（Docker Compose） |
| seekdb | `oceanbase/seekdb:latest`（`VECTOR_STORE=seekdb`），MySQL 协议 `127.0.0.1:2881` |
| LLM | OpenAI 兼容 `qwen2.5-3b-instruct`（llama.cpp，本地） |
| Embedding | OpenAI 兼容 `bge-small-zh-v1.5`（llama.cpp，本地），维度 512 |
| 知识库 | 《荒诞法典》36 条，通用分段 `\n## `，高质量索引，top_k=3 / score 0.2 |
| 书记员服务 | `memory-service` `0.0.0.0:8899`，连接 seekdb `absurd_court` |
| 应用 | Chatflow《离谱法庭 · The Absurd Court》，已发布，Service API 调用 |
| 初始状态 | <!-- TODO: 清空 cases 表 + 新建会话，记录初始 case 数 --> |

## 1. 复现方式

```bash
# 1) 重置初始状态
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "DROP DATABASE IF EXISTS absurd_court;"
cd memory-service && python app.py --init-db

# 2) 启动书记员服务
./run.ps1      # 或 ./run.sh

# 3) 按顺序执行验证脚本（每个用例一个 conversation）
python evidence/run_verification.py --app-key "$APP_KEY" --base-url http://localhost/v1

# 4) 采集数据库证据
#  见 evidence/seekdb-queries.md 中的命令
```

> 同一浏览器/同一 `user` 连打多场官司即可复现"跨场次记忆"：
> V1/V2 是第一场（conversation A），V3a 用**新会话但同一 user**再起诉充电线（conversation B）。

## 2. 验证样例与结果

### V1 · 立案 + 开庭 + 辩论

| 项 | 内容 |
|---|---|
| 初始条件 | `stage=idle`，新会话，`user=demo-<date>` |
| 输入 1 | `我要起诉我家的充电线，罪名是通敌，要求它当庭道歉` |
| 预期 1 | 返回含案号（`离谱刑初字第NNNN号` / `#NNNN`）的立案词；被告「充电线」第一人称狡辩；尾注提示「输入宣判结案」 |
| 实际 1 | <!-- TODO: 实测响应原文 --> |
| 输入 2（辩论） | `补充证据：它半夜三点偷偷发烫，还把我的手机电量从80%吸到20%` |
| 预期 2 | 法官点评新证据 + 被告继续反驳，合计 ≤160 字，保持当前案号 |
| 实际 2 | <!-- TODO: 实测响应原文 --> |
| seekdb 证据 | `cases` 表新增一行 `status=open`（`SELECT case_no,defendant,charge,claim,status FROM absurd_court.cases`） |
| 截图 | `evidence/screenshots/v1-chat.png`、`v1-workflow-run.png` |
| 日志 | `evidence/logs/v1.log` |

### V2 · 宣判 + 法典引用 + 归档

| 项 | 内容 |
|---|---|
| 输入 | `宣判`（同一会话，`stage=debate`） |
| 预期 | ① 知识库召回《荒诞法典》法条；② 判决书含「本院认为」、引用「根据《荒诞法典》第N条」、荒诞罚则；③ 返回 `已归档` 回执；④ seekdb 中该案 `status=closed` 且 `verdict/penalty/judgment` 有值 |
| 实际 | <!-- TODO: 实测响应原文 + 归档回执 --> |
| seekdb 证据 | `SELECT case_no,verdict,penalty,status,LEFT(judgment,80) FROM absurd_court.cases;`<!-- TODO 实测输出 --> |
| 知识库证据 | 召回测试截图 `evidence/screenshots/v2-knowledge-retrieval.png` |
| 截图 | `evidence/screenshots/v2-verdict.png`、`v2-workflow-run.png` |
| 日志 | `evidence/logs/v2.log` |

### V3a · 跨场次记忆（同一 user，新会话）

| 项 | 内容 |
|---|---|
| 输入 | 新会话（同一 `user`）输入 `我要再次起诉我家那根充电线，罪名是屡教不改的通敌` |
| 预期 | 法官在开庭词中引用上一场案号判例（从重/从轻），体现 seekdb `cases` 表被真实检索 |
| 实际 | <!-- TODO: 实测响应原文（须出现上一场案号） --> |
| seekdb 证据 | `POST /api/cases/search` 的返回（书记员服务日志）及 V3a 开庭前 `SELECT` 输出 |
| 日志 | `evidence/logs/v3a.log` |
| 截图 | `evidence/screenshots/v3a-precedent.png` |

### V3b · 案底统计

| 项 | 内容 |
|---|---|
| 输入 | `查阅我的案底` |
| 预期 | 返回立案数、胜败战绩、称号（≥1 场后；本用例应在 2 场官司后执行为「偶尔较真的市民」） |
| 实际 | <!-- TODO: 实测响应原文 --> |
| 截图 | `evidence/screenshots/v3b-stats.png` |
| 日志 | `evidence/logs/v3b.log` |

### V4 · 玩法说明

| 项 | 内容 |
|---|---|
| 输入 | `怎么玩`（在任意阶段，含 `stage=idle`） |
| 预期 | 返回四步玩法说明与示例输入，**不**误判为新案件（`cases` 表不新增记录） |
| 实际 | <!-- TODO: 实测响应原文 --> |
| seekdb 证据 | 调用前后 `SELECT COUNT(*) FROM absurd_court.cases` 不变 |
| 日志 | `evidence/logs/v4.log` |

### V5 · 健壮性

| 项 | 内容 |
|---|---|
| 输入 | `asdf` |
| 预期 | 不崩溃：要么拆出合理默认被告/罪名完成立案并开庭，要么给出友好提示；工作流不出现未处理异常 |
| 实际 | <!-- TODO: 实测响应原文 --> |
| 日志 | `evidence/logs/v5.log` |

## 3. seekdb 作用证据汇总

### 3.1 职责 ①：知识库向量存储（VECTOR_STORE=seekdb）

<!-- TODO: 实测 SHOW TABLES / SELECT COUNT(*) 输出 -->

```
-- 待填：Dify 向量表所在库与表名、行数
```

截图：`evidence/screenshots/v2-knowledge-retrieval.png`（知识库召回测试命中「电器通敌罪」）。

### 3.2 职责 ②：案卷库（absurd_court.cases）

<!-- TODO: 实测 SELECT 输出（立案、归档、统计对应的数据） -->

## 4. 证据文件索引

| 文件 | 内容 |
|---|---|
| `evidence/logs/v1.log` ~ `v5.log` | 每个样例的请求/响应原文（含 conversation_id、耗时） |
| `evidence/logs/clerk.log` | 书记员服务访问日志（四个接口调用记录） |
| `evidence/logs/dify-workflow-run-*.json` | Dify 工作流运行详情（节点级输入输出） |
| `evidence/screenshots/*.png` | Dify 聊天界面、知识库召回、工作流运行详情、seekdb provider 配置 |
| `evidence/seekdb-queries.md` | 上述所有 seekdb SQL 与真实输出 |
| `evidence/run_verification.py` | 可复现的验证脚本（读取应用 API Key，按 V1~V5 顺序调用） |

## 5. 已知偏差与说明

<!-- TODO: 实测后填写，例如：
- 本地 3B 模型某项输出格式偏差（若有），如何被 code 节点容错；
- 实测对话轮数、耗时；
- 与 DESIGN 的任何差异。
-->