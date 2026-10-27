# Dify 应用 DSL 说明

本目录只有一份应用：`absurd-court.chatflow.yml` —— 《离谱法庭 · The Absurd Court》的 Chatflow DSL。

| 文件 | 用途 |
|---|---|
| `absurd-court.chatflow.yml` | 主 DSL（Dify 1.18.0 导出格式，`version: 0.7.0`，`mode: advanced-chat`），可直接导入 |
| `build_dsl.py` | DSL 生成脚本（可复现、可传参），DSL 即由它生成，勿手工编辑 YAML |
| `README.md` | 本文件 |

## 1. 导入顺序

1. **先建知识库**：《荒诞法典》（`knowledge/absurd_codex.md`，配置见 `knowledge/README.md`），记下 dataset_id；
2. **生成/导入 DSL**：
   - 若想一次导入即完成绑定：
     ```bash
     python apps/build_dsl.py --dataset-id <DATASET_UUID>
     ```
     然后在 Dify 控制台「创建应用 → 导入 DSL 文件」选择 `apps/absurd-court.chatflow.yml`；
   - 也可直接导入仓库中的 DSL，导入后在画布中把 `retrieve_codex` 节点的知识库重选为《荒诞法典》；
3. 检查模型节点是否绑定到可用的 OpenAI 兼容模型（见 §3）；
4. 确认书记员服务地址（见 §4）；
5. 保存草稿 → 右上角「发布」→「访问 API」创建 API Key。

> 导入时若提示 `知识库不存在`/`模型不可用`，属于跨环境正常提示：按 §2、§3 重新绑定即可，
> 不影响画布结构导入。

## 2. 应用结构速览

`advanced-chat`（Chatflow），25 个节点、28 条连线、6 个会话变量：

```
start ─► route(IF/ELSE)
          ├─ case_help     → help_answer（玩法说明，静态文本）
          ├─ case_stats    → stats_http → stats_answer（查案底）
          ├─ case_verdict_* ─► codex_query → retrieve_codex（Knowledge Retrieval）
          │                                   → join_codex → verdict_precedent（先例校验 Code）
          │                                   → verdict_llm → verdict_code → archive
          │                                   → reset_vars → verdict_answer
          ├─ case_debate   → debate_llm → debate_answer（多轮辩论）
          └─ else          → parse_llm → parse_code → create_case → search_precedent
                             → set_vars → precedent_note（先例确定性播报，Code）
                             → opening_llm（法官开庭词）→ defendant_llm（被告狡辩）
                             → opening_answer（新案件开庭，统一加被告标签）
```

> **与设计规格的实现差异**：为了让本地 3B 模型的输出格式与事实稳定，开庭环节拆成
> `opening_llm`（法官开庭词，含案号）和 `defendant_llm`（被告第一人称狡辩）两个 LLM 节点，
> 串行后由 `opening_answer` 合并输出（并统一加「被告「X」：」标签）——对应设计中 `opening_llm`
> 的"两段式输出"要求，语义与体验不变但可靠性更高。另外新增 `precedent_note`（Code 节点）：
> 从 `search_precedent.body` 确定性提取旧案号并生成"参照旧案 #NNNN"播报，无旧案时输出空串，
> 避免 3B 模型在首例时脑补旧案号。辩论节点 `debate_llm` 显式规定"恰好两行：法官：…／被告「…」："。

关键设计：

- **会话变量**（`workflow.conversation_variables`）：`stage / case_no / defendant / charge / claim / precedent`。
  `stage=debate` 表示正在庭审，此时任何非「宣判」输入都走辩论分支；宣判后 `reset_vars` 把 `stage` 置回 `idle`。
- **多轮记忆**：`opening_llm / debate_llm / verdict_llm` 均开启 memory（窗口 10），携带本会话上下文。
- **案卷/先例/统计**：三个 HTTP Request 节点调用书记员服务（`host.docker.internal:8899`），
  服务返回纯文本，节点取 `body` 字符串，避免 JSON 解析兼容问题。
- **宣判证据链**：`retrieve_codex` 从 Dify 知识库（seekdb 向量存储）召回 3 条法条 →
  `join_codex` 拼成 ≤800 字原文 → `verdict_llm` 输出严格 JSON → `verdict_code` 容错解析 →
  `archive` 写入 seekdb `absurd_court.cases`。
- **容错**：`parse_code / verdict_code` 都会去掉 ```json 围栏、截取第一个 `{...}`，解析失败时给出兜底字段；
  即使模型输出不合格式，工作流也不会崩。

## 3. 重新绑定模型（换任意 OpenAI 兼容模型）

DSL 里所有 LLM 节点默认使用：

```
provider: langgenius/openai_api_compatible/openai_api_compatible
model:    qwen2.5-3b-instruct
```

换模型有两种方式：

- **UI**：逐个打开 5 个 LLM 节点（`parse_llm` / `opening_llm` / `defendant_llm` / `debate_llm` / `verdict_llm`），
  在模型下拉中重新选择；
- **脚本**：重新生成 DSL 后导入：
  ```bash
  python apps/build_dsl.py \
    --provider langgenius/openai_api_compatible/openai_api_compatible \
    --model your-model-name
  ```

温度已按用途写在节点里：立案解析 `0.2`、开庭/辩论 `0.9`、判决 `0.8`。

## 4. 重新绑定书记员服务地址

默认地址 `http://host.docker.internal:8899`。若改了端口/主机：

- **UI**：编辑 4 个 HTTP 节点（`stats_http` / `archive` / `create_case` / `search_precedent`）的 URL；
- **脚本**：
  ```bash
  python apps/build_dsl.py --clerk-base http://<host>:<port>
  ```

## 5. 重新生成 DSL 的自检

`build_dsl.py` 生成后会做 YAML round-trip 自检；生成结果应满足：

```
节点 22 个，连线 25 条，会话变量 6 个
```

此外可用 `python apps/build_dsl.py` 后直接检查 YAML 头部注释与节点清单。

## 6. 应用入口

- **Dify Web 界面**：应用 → 《离谱法庭 · The Absurd Court》→ 「预览」/「运行」，直接对话即可；
- **Service API**：
  ```bash
  curl -X POST 'http://localhost/v1/chat-messages' \
    -H 'Authorization: Bearer <APP_API_KEY>' \
    -H 'Content-Type: application/json' \
    -d '{
      "inputs": {},
      "query": "我要起诉我家的充电线，罪名是通敌，要求它当庭道歉",
      "response_mode": "blocking",
      "user": "demo-user-001",
      "conversation_id": ""
    }'
  ```
  多轮时把返回的 `conversation_id` 带上即可；`user` 决定案底归属（对应 `sys.user_id`）。

## 7. 已知限制

- 知识库 `dataset_ids` 是环境相关的 UUID，换环境必须重新绑定（见 §1）。
- 本地 3B 模型偶尔会不按 JSON 格式输出：`parse_code / verdict_code` 已做容错兜底；
  若追求更好的"法庭"效果，建议在 UI 中换成 7B 以上模型（无需改 DSL 结构）。
- HTTP 节点依赖书记员服务在宿主机 `8899` 端口运行；服务未启动时这些分支会报节点错误，
  但玩法说明/查案底以外的对话仍可体验（Dify 会显示节点错误提示）。