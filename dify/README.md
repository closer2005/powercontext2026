# 离谱法庭 · The Absurd Court

> 2026 数据库大赛生态伙伴题「Dify」参赛作品（Just for Fun）：用 Dify 做一个好玩的智能应用，并结合 OceanBase seekdb。

你可以起诉任何东西——通敌的充电线、恶意循环的周一、非法占床的猫。AI 法官「包青天 2.0」开庭、被告（物件成精）当庭狡辩、你补充证据自由辩论，最后法官检索《荒诞法典》并参考你过去的判例，当庭宣读一份离谱判决书；案卷永久归档在 seekdb，下次开庭时法官会引用你的旧案底。

## 技术选型

- **Dify 1.18.0**：Chatflow 承担全部核心编排（意图路由、LLM 开庭/辩论/判决、知识库检索、HTTP 工具调用、Code 解析、多轮状态）。
- **OceanBase seekdb**：既作为 Dify 部署数据库/知识库向量存储，也作为应用案卷库（`absurd_court.cases`），由「书记员服务」通过 MySQL 协议读写。

## 目录

| 路径 | 说明 |
|---|---|
| `apps/absurd-court.chatflow.yml` | Dify Chatflow DSL |
| `knowledge/absurd_codex.md` | 知识库《荒诞法典》源数据 |
| `memory-service/` | 书记员服务（案卷 CRUD / 先例检索 / 案底统计） |
| `deployment/` | Dify + seekdb 部署说明 |
| `evidence/` | 运行证据（日志、截图、seekdb 查询） |
| `VERIFICATION.md` | 验证样例与运行记录 |

## 快速开始

1. 按 `deployment/README.md` 部署 Dify 1.18.0 + seekdb。
2. 在 Dify 中创建知识库《荒诞法典》并导入 `knowledge/absurd_codex.md`。
3. 按 `memory-service/README.md` 初始化 seekdb 并启动书记员服务。
4. 导入 `apps/absurd-court.chatflow.yml`，重新绑定模型与知识库，发布应用。
5. 按 `VERIFICATION.md` 的样例体验。

> 本文件为作品说明（提交材料之一）。完整版运行说明与验证记录将随最终提交更新。