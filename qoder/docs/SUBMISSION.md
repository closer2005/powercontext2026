# 提交与发布记录（Qoder 赛题 · 题目 600078）

> 本文件记录 CiteSeek 知源作品的最终交付物、Qoder Sites 发布记录、平台提测记录与可复核的验证证据。
> 生成时间：2026-10-28（Asia/Shanghai）

## 1. 交付物

| 材料 | 位置 | 核对方式 |
|---|---|---|
| 项目网站（Qoder Sites，public） | https://citeseek-gzqd7ingk4d.qoder.zone | 未登录可访问；Qoder Sites 页面右下角有 “Made with Qoder” 标识 |
| 代码仓库（公开） | https://github.com/closer2005/powercontext2026/tree/2026-competition-ecosystem/qoder | 分支 `2026-competition-ecosystem`，目录 `qoder/` |
| 最终提交 commit | `8700f32893e8741dba39d2e93d68f95dcfc46745` | 含 site / docs / app / web / tests / data |
| Qoder 账号 / UID | `nick1732629033` / `01a17ebb-b33f-7606-8a7e-d48daeafdadf` | 见 `docs/QODER_DEV_RECORD.md` |
| Qoder 开发记录 | `docs/QODER_DEV_RECORD.md`、`docs/dev_record.json` | 6 个真实会话、184 次请求、95.01 Credits（日志自动抽取） |
| 运行说明 | `docs/RUNBOOK.md`、README「快速开始」 | `docker compose up -d --build` → http://localhost:8000 |
| 验证样例 | `docs/VERIFY.md`、`docs/verify_output.json` | 3 组样例 + 真实输出 |
| 技术证据 | 站点「技术证据」区、`/api/logs/search`、`/api/stats` | search_log 含 query/耗时/结果数/向量与全文命中 |

## 2. Qoder Sites 发布记录

站点：`citeseek`（siteId `01a17efb-1a6b-7b58-a5a5-c9049903536e`，projectId `01a17efb-1a6a-70cd-8ecb-1c3ede551096`，public）

| # | 时间（+08:00） | actionId | 说明 |
|---|---|---|---|
| 1 | 04:09 | `dba3ca73-7852-4a65-bf32-f766241919c3` | 首次发布（项目介绍 / 演示 / 技术 / 开发记录） |
| 2 | 04:45 | `e3a19f40-e154-4919-b6f7-9a1b88a126ee` | 增加「提交材料索引」，修正示例数值 |
| 3 | 05:18 | `99906fb5-3719-4d9b-96d8-0c9cfdc26ca2` | 评委视角自审后修复：日志表/耗时改真实值，新增「内部自测与降级验证」 |
| 4 | 05:24 | `ac17afa1-c413-4739-a018-07fda3b65c6c` | 开发记录统计更新为 6 会话 / 184 请求 / 95 Credits |

每次发布均由 Qoder CN CLI 的 Sites 流程（prepare_site → publish_site → get_publish_status）完成，`published: true`、`readiness: publication_completed`、访问模式 `public` 保持不变。

## 3. 平台提测记录（题目 600078）

提测 payload（平台要求 `gitRepo` + `branch` + `commitId` + `extraParams.workUrl`）：

```json
{
  "questionId": 600078,
  "gitRepo": "https://<token>@github.com/closer2005/powercontext2026",
  "branch": "2026-competition-ecosystem",
  "commitId": "16090a21396df1015cee3e5d6d522f3fafe112f3",
  "extraParams": { "workUrl": "https://citeseek-gzqd7ingk4d.qoder.zone" }
}
```

| 记录 id | 提交时间（UTC） | 对应 commit | 状态 |
|---|---|---|---|
| 47221278 | 2026-10-27T20:31:56Z | a2e7d03 | 已受理，`taskStatus=0`（评测中） |
| 47221292 | 2026-10-27T20:55:16Z | 16090a2 | 已受理，`taskStatus=0`（评测中） |

- 两次提交平台均返回 `code=200 操作成功`。
- 公开评测进度（`subquestion` 接口）：子题「用 Qoder 做一个让学习、科研和工作更高效的项目」通过 37 / 未通过 25（62 份提交），评分列表 53 支队伍均为 0 分 —— 截至 2026-10-28 07:35 该赛题尚未出分，因此提测记录保持待评测属预期。
- 平台登录过期（`401`）时无法读取本队记录；`check_qoder_submission.py` 可在登录有效后一条命令复查。
- 建议：登录后用最终 commit `8700f32` 重新提测一次，使提测记录与仓库最终版本一致。

## 4. 验证证据（2026-10-28 实测）

### 4.1 本地应用（Python 3.13 + seekdb 容器 2882）
- `python -m pytest -q` → **20 passed**
- 健康检查：`{"status":"ok","seekdb":{"connected":true,"count":62},"embed":{"mode":"onnx","model":"BAAI/bge-small-zh-v1.5","dim":512,"degraded":false}}`
- 检索（真实日志）：`事务隔离级别有哪些` 187 ms / 7 条 / hybrid / 向量 8 / 全文 7
- 复习闭环：加入复习 → 待复习 1 条 → 评分「记住了」→ 当日复习完成

### 4.2 浏览器 UI 冒烟（headless Edge + CDP）
- 三个 Tab 正常：检索 / 资料库 / 复习
- 检索视图：结果卡片渲染 7 条、显示耗时/模式/命中来源
- 资料库：27 笔记、62 chunks、复习条目统计正常
- 复习视图：加入复习 toast「已加入复习队列」→ 卡片展示出处 → 评分后进入「今日复习完成」
- 控制台 **0 个 error / 0 个 exception**

### 4.3 Docker 复现路径（上一轮实测）
- `docker build` 成功；容器 `citeseek` healthcheck 通过
- 容器内 `/api/health`：`mode=onnx`、`count=62`；`SEED_ON_START=1` 自动导入 27 篇 / 62 chunks
- `docker compose config` 校验通过（含 `PIP_INDEX_URL` 构建参数、healthcheck、named volume）

### 4.4 线上站点（Qoder Sites）
- `GET /` → HTTP 200，85,838 bytes
- 10 个本地资源（css/js/png/gif）全部 200
- 11 个页面锚点全部可达；无「占位/待填/TODO」残留
- 必备内容齐全：项目简介、痛点、功能、演示、代码仓库、运行说明、验证样例、Qoder 开发记录 + UID、seekdb 技术结合、页脚参赛信息

## 5. 待办 / 阻塞

1. **等待平台出分**：题目 600078 尚未进入评分阶段（全体 0 分、子题通过数未变）；出分后按 AI 评审意见迭代。
2. **平台登录**：需账号本人重新登录 `open.oceanbase.com`（会话已过期）；登录后运行 `python check_qoder_submission.py` 查看记录，并用 commit `8700f32` 重新提测。
3. 建议补充真实使用效果（同学/同事试用、访问统计），赛题为鼓励项。