# 知识库《荒诞法典》导入与索引说明

本目录提供 Dify 知识库的唯一数据源文件 `absurd_codex.md`。它是《离谱法庭》的"法律依据"：宣判分支通过 Dify 的
**Knowledge Retrieval（知识检索）** 节点，从 seekdb 向量库中召回与当前案件相关的 2~3 条法条，再交给判决书 LLM 引用。

## 1. 数据来源

- **原创虚构文本**，随本仓库一同交付，无第三方版权素材、无真实法律条文、无人身指向。
- 共 **36 条**法条 + 总则 + 附则，标题统一为 `## 第N条 · 名称`，便于按标题分段。
- 每条 2~4 句，包含「适用场景 + 判决要点」，并在关键条目中标注 `★关键词`（如 `★充电线 ★通敌`），提高语义召回命中率。
- 内容安全基线：只调侃物品、抽象概念与生活现象（充电线、周一、影子、体重秤……），罚则一律荒诞无害，不针对真实个人或群体。

## 2. 在 Dify 中创建知识库

路径：Dify 控制台 → 知识库 → 创建知识库。

| 配置项 | 取值 | 说明 |
|---|---|---|
| 名称 | `荒诞法典` | 与 DSL 中的数据集名称一致；最终以 dataset_id 绑定 |
| 数据源 | 导入已有文本 → 上传 `absurd_codex.md` | 也可用「自定义文本」粘贴全文 |
| 分段模式 | **通用分段（General）** | 按 `##` 标题切分最容易命中单条法条 |
| 分段标识符 | `\n## ` | 以二级标题为主要断点 |
| 最大分段长度 | `500` | 单条法条约 100~200 字，留足上下文余量 |
| 分段重叠长度 | `50` | 防止条文跨段被截断 |
| 文本预处理 | 开启「替换连续空格、换行符」保持默认 | – |
| 索引方式 | **高质量索引（High Quality）** | 需要 embedding 模型 |
| Embedding 模型 | `bge-small-zh-v1.5`（OpenAI 兼容 provider） | 若换模型须重建索引 |
| 检索方式 | 向量检索（semantic） | 中文法条语义召回优先 |
| Top K | `3` | 与 DSL 中节点配置一致 |
| Score 阈值 | `0.2` | 与 DSL 中节点配置一致 |

> 索引完成后，「召回测试」输入 `电器 通敌`，应能命中「第一条 · 电器通敌罪」；
> 输入 `猫 占床`，应命中「第七条 · 毛茸茸非法占床罪」。

## 3. 与 DSL 的绑定（关键步骤）

DSL 导出文件里的 `dataset_ids` 是**本机工作区**的 UUID，换一个 Dify 环境导入后必然失效。重新绑定有两种方式：

**方式 A（推荐，UI 操作）**
1. 导入 `apps/absurd-court.chatflow.yml` 后，打开应用编排画布；
2. 找到 `retrieve_codex`（知识检索）节点，点开「知识库」下拉，重新选择 `荒诞法典`；
3. 保存草稿 → 右上角「发布」。

**方式 B（脚本生成）**
```bash
# 在 Dify 控制台/API 拿到 dataset_id 后，重新生成 DSL
python apps/build_dsl.py --dataset-id <DATASET_UUID> --out apps/absurd-court.chatflow.yml
```
再把新 DSL 导入即可；检索配置（top_k=3、score_threshold=0.2、向量检索）已写在 DSL 节点里。

## 4. 检索配置在 DSL 中的位置

`retrieve_codex` 节点（`type: knowledge-retrieval`）关键字段：

```yaml
retrieval_mode: multiple
multiple_retrieval_config:
  top_k: 3
  score_threshold: 0.2
  reranking_enable: false
  reranking_mode: reranking_model
  reranking_model: null
  weights: null
```

`join_codex`（Code 节点）把 `retrieve_codex.result` 中每条的 `content` 拼接为 ≤800 字文本，
经 `verdict_llm` 注入提示词，最终判决书会引用「根据《荒诞法典》第N条」。

## 5. seekdb 侧的验证

Dify 以 `VECTOR_STORE=seekdb` 运行时，本知识库的 embedding 向量保存在 seekdb 容器中。查询示例：

```sql
-- 在 Dify 的数据库（与向量表同实例）中查看向量表
SHOW TABLES;
SELECT COUNT(*) FROM embeddings;                    -- 表名以实际 Dify 版本为准
SELECT COUNT(*) FROM document_segments;             -- 分段数量
```

具体命令见 `deployment/seekdb-init.md` 与 `evidence/seekdb-queries.md`（实测截图/输出记录）。