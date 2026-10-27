# 示例笔记数据集（data/samples）

> CiteSeek 知源的演示与验证数据。27 个 Markdown 文件，模拟学生 / 科研工作者的真实学习笔记。
> 全部内容为**原创虚构**（以笔记口吻撰写），不包含真实个人信息、未发表数据或版权文本；仅用于功能演示与评审复现。

## 1. 概览

| 项目 | 值 |
|---|---|
| 文件数 | 27（不含本 README） |
| 语料规模 | 正文合计约 6 150 个汉字；含标点、英文术语和伪代码后约 10 400 个字符 |
| 单篇长度 | 160–283 个汉字（要求 150–400 字），平均约 228 字 |
| 篇章结构 | 每篇 3–4 个 `##` 小节，含要点式列表、少量公式 / SQL / Python 伪代码与英文术语 |
| 切块后规模 | 实测约 62 个 chunk（随切块参数浮动；当前实现段内聚合 `<=300` 字、相邻块重叠 `<=50` 字） |
| 课程 | 数据库系统、机器学习、高等数学、概率论与数理统计、科研方法 |
| 编码 | UTF-8（无 BOM）、LF 换行、YAML front-matter |
| 文件命名 | `<课程缩写>-<序号>-<主题>.md`，纯 ASCII，避免跨平台文件名编码问题 |

课程缩写：`db`=数据库系统、`ml`=机器学习、`math`=高等数学、`prob`=概率论与数理统计、`research`=科研方法。

## 2. 课程与主题分布

| 课程 | 篇数 | 覆盖主题 | 文件前缀 |
|---|---|---|---|
| 数据库系统 | 7 | 事务与并发（3）、索引与存储（2）、检索系统（2） | `db-` |
| 机器学习 | 8 | 序列建模（2）、神经网络（2）、表示学习（1）、模型评估（1）、概率模型（1）、检索与生成（1） | `ml-` |
| 高等数学 | 3 | 线性代数（2）、微积分（1） | `math-` |
| 概率论与数理统计 | 3 | 概率基础（2）、统计推断（1） | `prob-` |
| 科研方法 | 6 | 文献工作（2）、实验方法（2）、学术写作（1）、研究设计（1） | `research-` |
| **合计** | **27** | | |

## 3. front-matter 规范

每个文件第一行必须是 `---`，第二段 `---` 结束；字段与后端 `app/seed.py` 的解析约定一致，缺字段时按空字符串处理：

| 字段 | 必填 | 说明 | 示例 |
|---|---|---|---|
| `title` | 是 | 笔记标题，同时是导入幂等的判重键 | `事务隔离级别与 MVCC` |
| `course` | 是 | 课程，作为 collection 的 metadata 过滤字段 | `数据库系统` |
| `topic` | 是 | 主题，作为 metadata 过滤字段 | `事务与并发` |
| `tags` | 是 | 标签，**空格分隔**（不要用逗号） | `事务 隔离级别 MVCC` |
| `source` | 是 | 来源说明（课堂 / 教材 / 论文 / 实验记录 / 组会），对应 `notes.source` | `课堂笔记 第6讲` |

`note_id`、`created_day`、`seq`、`chunk_count` 等字段由 app 在导入时生成，**不写入** front-matter。

## 4. 检索词覆盖（演示与验收用）

以下检索词各至少命中 2 篇，覆盖「关键词字面命中」与「近义表达召回」两类演示：

| 检索词 | 命中篇数 | 命中文件（`data/samples/` 下） |
|---|---|---|
| 事务隔离级别 | 2 | `db-01-transaction-isolation.md`、`db-02-mvcc-read-view.md` |
| MVCC | 2 | `db-01-transaction-isolation.md`、`db-02-mvcc-read-view.md` |
| 注意力机制 | 2 | `ml-01-attention-transformer.md`、`ml-07-rnn-to-attention.md` |
| Transformer | 2 | `ml-01-attention-transformer.md`、`ml-07-rnn-to-attention.md` |
| 反向传播 | 3 | `ml-02-backprop-gradient-descent.md`、`ml-03-training-regularization.md`、`math-03-taylor-expansion-gradient.md` |
| 贝叶斯公式 | 2 | `ml-06-naive-bayes.md`、`prob-01-bayes-total-probability.md` |
| 特征值 | 4 | `math-01-eigenvalues-eigenvectors.md`、`math-02-svd-matrix-factorization.md`、`ml-04-pca-dimensionality-reduction.md`、`prob-02-covariance-matrix.md` |
| PCA | 4 | 同上（4 篇） |
| 向量检索 | 5 | `db-06-vector-search-ann.md`、`db-07-hybrid-search-rrf.md`、`ml-08-rag-retrieval.md`、`research-01-literature-review.md`、`research-02-literature-search-screening.md` |
| 混合检索 | 4 | `db-06-vector-search-ann.md`、`db-07-hybrid-search-rrf.md`、`ml-08-rag-retrieval.md`、`research-02-literature-search-screening.md` |
| 文献综述 | 3 | `research-01-literature-review.md`、`research-05-paper-writing-imrad.md`、`research-06-proposal-research-hypothesis.md` |
| 实验记录 | 4 | `db-05-explain-slow-query.md`、`ml-03-training-regularization.md`、`ml-05-model-evaluation-cv.md`、`research-03-lab-notebook-reproducibility.md` |
| 对照实验 | 3 | `ml-05-model-evaluation-cv.md`、`research-03-lab-notebook-reproducibility.md`、`research-04-controlled-experiment-design.md` |

说明：同一概念在不同笔记里用了不同说法（例如「隔离级别 / 并发可见性 / 快照读」「向量检索 / 语义检索 / dense retrieval」「文献综述 / 相关工作」），用于验证「换个说法也能搜到」；`事务隔离级别` 这一整串同时出现在 `db-01` 与 `db-02` 正文里，保证全文检索能字面命中。

## 5. 如何被 app 导入

DESIGN §7 的 `POST /api/import/samples` 对应后端 `app/seed.py`：扫描 `data/samples/*.md`（Docker 容器内为 `/app/data/samples/*.md`），逐篇解析 front-matter 与正文。流程：

1. 解析 front-matter → `title / course / topic / tags / source` 与正文；
2. 按 `title` 判重（幂等）：已存在则计入 `skipped`（单篇导入失败也计入 `skipped` 并写日志）；
3. 写 `notes` 表（note_id 由应用生成），正文交给 `app/chunking.py` 切块；
4. 调 `app/embeddings.py` 为每个 chunk 计算 512 维向量，写入 collection `citeseek_chunks_v1`（metadata 带 note_id / title / course / topic / tags / source / created_day / seq）；
5. 每篇写入 collection 后调用 `refresh_index()`（seekdb 的向量索引异步构建，不刷新可能查不到新数据；批量导入时逐篇刷新）；
6. 返回 `{"imported": N, "skipped": M}`。

触发方式（任选其一）：

- 前端「资料库 → 载入示例数据」按钮；
- `curl -X POST http://localhost:8000/api/import/samples`；
- `SEED_ON_START=1`（`docker-compose.yml` 默认值）：应用启动时自动导入（需 compose 透传该变量；若启动后 `notes` 仍为 0，用前两种方式手动导入即可）。

预期结果：首次导入 `{"imported":27,"skipped":0}`，再次触达 `{"imported":0,"skipped":27}`；之后 `/api/stats` 的 `notes=27`，`chunks` 实测约 62（随切块参数浮动；当前实现按空行分段、贪心聚合到 `<=300` 字、相邻 chunk 重叠 `<=50` 字；DESIGN 验收要求 `chunks>=60`），`/api/health` 的 `seekdb.count` 与 `chunks` 一致。

## 6. 维护与边界

- 增删文件后，请同步更新本 README 的统计表与检索词覆盖表。
- 修改正文后重新导入**不会覆盖**同 title 的旧笔记（按 title 判重）；需要先删除旧笔记（`DELETE /api/notes/{id}`）或清理数据（RUNBOOK §7.4）后再导入。
- 新增笔记时保持 front-matter 五个字段齐全、`tags` 空格分隔、正文 150–400 字。
- 不要写入真实个人信息、密钥、未发表数据；引用他人观点请转述并标注来源。
- 本数据集只用于功能演示与复现验证，不构成学术结论、评测基准或训练数据。