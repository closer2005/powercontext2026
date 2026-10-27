# CiteSeek 知源

可溯源的笔记混合检索助手 —— 把散落在笔记软件、论文摘录、课堂记录里的零散文字导入 seekdb，用自然语言提问即可找回相关片段，并明确给出出处。

> OceanBase 2026 数据库大赛 · Qoder 赛题（题目 600078）参赛作品。
> 作品展示网站（Qoder Sites 发布，公开可访问）：**https://citeseek-gzqd7ingk4d.qoder.zone**
> 开发方式：Qoder CN CLI（账号 `nick1732629033`，UID `01a17ebb-b33f-7606-8a7e-d48daeafdadf`），开发记录见 [docs/QODER_DEV_RECORD.md](docs/QODER_DEV_RECORD.md)。

## 快速开始

推荐使用 Docker Compose 一键启动（seekdb + 应用）：

```bash
docker compose up -d --build
# 打开 http://localhost:8000
```

国内网络构建较慢时可指定 pip 镜像源：

```bash
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ docker compose up -d --build
```

本地开发方式：

```bash
# 1. 只启动 seekdb
docker compose up -d seekdb

# 2. 本机启动应用（Python 3.11+）
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 3. 打开浏览器
# http://localhost:8000
```

首次使用请点击「载入示例数据」导入 27 篇示例笔记（或 `docker compose` 默认 `SEED_ON_START=1` 自动导入）。

## 目录结构

```
qoder_work/
├── app/                    # 后端核心
│   ├── main.py             # FastAPI 入口 + 路由
│   ├── config.py           # 环境变量配置
│   ├── db.py               # pymysql CRUD（notes/review_items/search_log）
│   ├── vector_store.py     # pyseekdb 封装（collection/hybrid_search/refresh）
│   ├── embeddings.py       # 嵌入模型（BGE ONNX / Hash / API）
│   ├── chunking.py         # 中文文本切块
│   ├── services.py         # 业务编排（导入/检索/复习）
│   └── seed.py             # 示例数据导入（幂等）
├── web/                    # 前端（原生 HTML/CSS/JS）
│   ├── index.html          # 单页入口
│   ├── app.js              # 前端逻辑
│   └── style.css           # 样式
├── data/samples/           # 示例笔记（Markdown + YAML front-matter）
├── tests/                  # 测试
├── site/                   # 作品展示网站
├── docs/                   # 设计文档（DESIGN/RUNBOOK/VERIFY/ARCHITECTURE）
├── docker-compose.yml      # seekdb + citeseek 双服务
├── Dockerfile              # citeseek 应用镜像
├── requirements.txt
├── .env.example
└── README.md
```

## 前端使用说明

前端位于 `web/` 目录，由 FastAPI 托管在 `/static/*` 路径，访问 `http://localhost:8000/` 即可打开。

### 三个主视图

| 视图 | 功能 |
|---|---|
| **检索** | 输入自然语言问题，返回混合检索结果（向量语义 + 全文关键词 + 结构化过滤），每条结果带出处、课程/主题标签、分数条、段落序号、匹配来源徽标 |
| **资料库** | 手动导入笔记（标题/课程/主题/标签/来源/正文），载入示例数据，查看/筛选/删除笔记 |
| **复习** | 按 SM-2 间隔重复算法安排复习，四档评分（忘了/模糊/记住了/很熟练） |

### 技术面板

页面底部固定的技术面板（点击展开），展示：
- **系统状态**：seekdb 连接、collection 名称、向量数、嵌入模式、维度、是否降级
- **Collection 统计**：笔记数、chunk 数、复习条目数、检索次数、平均耗时
- **最近检索日志**：最近 5 条检索记录，含查询、耗时、结果数、向量/全文命中

面板数据来源：`/api/health`、`/api/stats`、`/api/logs/search`。

## Docker 部署

```bash
# 一键启动
docker compose up -d --build

# 查看日志
docker compose logs -f citeseek

# 验证
curl http://localhost:8000/api/health
```

docker-compose 中 citeseek 服务已配置 `SEED_ON_START=1`，首次启动会自动导入示例数据。
可通过 `.env` 文件覆盖默认配置（可选，不存在不报错）。

## 常见问题

| 问题 | 解决 |
|---|---|
| 启动后 `/api/health` 返回 degraded | seekdb 尚未就绪，等待 healthcheck 通过后重试 |
| 检索无结果 | 先载入示例数据或手动导入笔记；检查嵌入模式是否降级（hash 模式语义匹配较弱） |
| 向量检索质量不佳 | 确保 `EMBED_MODE=auto` 且 BGE 模型下载成功（首次需联网）；无网环境可用 `EMBED_MODE=hash` |
| Docker 构建慢 | 已移除 Dockerfile 中不必要的 gcc 安装；onnxruntime/tokenizers 均有预编译 wheel |
| 前端页面空白 | 检查浏览器控制台是否有 CORS 或网络错误；确认 `web/` 目录存在 |
