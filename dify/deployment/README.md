# 部署说明：Dify 1.18.0 + seekdb（单 seekdb 实例，三重职责）

本作品运行在 **Dify 1.18.0 官方 Docker Compose** 之上，**没有修改 Dify 业务源码**，
唯一改动是为了让 seekdb 承载 Dify 元数据库而打的 **1 个 Alembic 迁移兼容补丁**（见 `deployment/patches/`）。

## 1. seekdb 的三重职责（本题技术结合的核心）

本作品用**同一个 seekdb 实例**（容器 `oceanbase/seekdb`，容器内 2881，MySQL 协议 5.7.25）
承担三类真实数据存储，这是"seekdb 在部署运行和功能中都实际发挥作用"的直接体现：

| # | 职责 | 使用方 | 库 | 配置 | 证据 |
|---|---|---|---|---|---|
| ① | **Dify 部署主数据库** | Dify api / worker（SQLAlchemy，`DB_TYPE=seekdb`） | `dify`（Dify 自身约 172 张表：账号/应用/会话/工作流/消息…） | `DB_TYPE=seekdb`、`DB_HOST=seekdb`、`DB_PORT=2881`、`DB_USERNAME=root`、`DB_DATABASE=dify` | 迁移日志 + `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dify'` = 172；`dify.alembic_version` |
| ①' | **Dify 插件数据库** | plugin_daemon（Go，MySQL 驱动） | `dify_plugin` | `PLUGIN_DAEMON_DB_TYPE=mysql`、`DB_PLUGIN_DATABASE=dify_plugin` | `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dify_plugin'` |
| ② | **知识库向量存储** | Dify 知识库《荒诞法典》 | `dify_vector` | `VECTOR_STORE=seekdb`、`OCEANBASE_VECTOR_HOST=seekdb`、`OCEANBASE_VECTOR_PORT=2881`、`OCEANBASE_VECTOR_DATABASE=dify_vector` | 知识库召回测试截图 + `SHOW TABLES FROM dify_vector` / `SELECT COUNT(*)` 行数=分段数 |
| ③ | **应用案卷库** | 书记员服务 `memory-service`（PyMySQL） | `absurd_court`（表 `cases`） | 宿主机 `DB_HOST=127.0.0.1`、`DB_PORT=2885`（容器端口 2881 的宿主机映射） | 立案/归档/先例/案底 SQL 输出 + 服务访问日志 |

> 注：Dify 1.18.0 的 `VECTOR_STORE=seekdb` 复用官方 `dify_vdb_oceanbase` 向量实现
> （源码映射：`("SEEKDB", "dify_vdb_oceanbase.oceanbase_vector", "OceanBaseVectorFactory")`），
> 因此向量连接参数仍使用 `OCEANBASE_VECTOR_*`。`plugin_daemon` 是 Go 编写，只支持
> `postgresql|mysql` 两种 DB 驱动，故用 MySQL 驱动连同一 seekdb 实例（`DB_TYPE=mysql`），
> 数据仍然落在 seekdb 的 `dify_plugin` 库——这也是 seekdb 作为"Dify 部署数据库"的一部分。

## 2. 版本与前置条件

| 组件 | 版本 / 说明 |
|---|---|
| Dify | **1.18.0**（官方镜像 `langgenius/dify-api:1.18.0`、`langgenius/dify-web:1.18.0`、sandbox / plugin_daemon 等同版本） |
| seekdb | `oceanbase/seekdb:latest`，服务端版本 **v1.4.0.0**（MySQL 协议 5.7.25），容器内端口 2881 |
| 服务器 | Docker Engine/Desktop + Compose v2；**6 GB 以上空闲内存**（seekdb 默认 `MEMORY_LIMIT=2G` + Dify 各容器） |
| 模型服务 | OpenAI 兼容：chat `qwen2.5-3b-instruct`、embedding `bge-small-zh-v1.5`（512 维）。本作品用 llama.cpp（b11935）在宿主机提供 |
| 插件 | 市场插件 **OpenAI-API-compatible 0.0.73**（`langgenius/openai_api_compatible:0.0.73`，离线 `.difypkg` 安装） |
| 网络 | Dify 容器需能访问宿主机 `host.docker.internal:8000/8001`（模型）与 `:8899`（书记员服务） |

## 3. 获取 Dify 1.18.0

```bash
curl -L -o dify-1.18.0.zip https://github.com/langgenius/dify/archive/refs/tags/1.18.0.zip
unzip dify-1.18.0.zip && cd dify-1.18.0/docker
cp .env.example .env
```

## 4. 关键 .env 配置

把 `deployment/env.additions.example` 的内容追加/覆盖到 `docker/.env`（占位值替换成实际密码）：

```ini
# ---- ① Dify 主数据库 = seekdb ----
DB_TYPE=seekdb
DB_HOST=seekdb
DB_PORT=2881
DB_USERNAME=root
DB_PASSWORD=<SEEKDB_PASSWORD>
DB_DATABASE=dify
DB_PLUGIN_DATABASE=dify_plugin

# ---- ② 知识库向量存储 = seekdb ----
VECTOR_STORE=seekdb
OCEANBASE_VECTOR_HOST=seekdb
OCEANBASE_VECTOR_PORT=2881
OCEANBASE_VECTOR_USER=root
OCEANBASE_VECTOR_PASSWORD=<SEEKDB_PASSWORD>
OCEANBASE_VECTOR_DATABASE=dify_vector

# ---- seekdb 容器 ----
SEEKDB_MEMORY_LIMIT=2G
SEEKDB_HOST_PORT=2885        # 宿主机端口；容器内仍是 2881

# ---- plugin_daemon（Go）用 MySQL 驱动连 seekdb ----
PLUGIN_DAEMON_DB_TYPE=mysql

# ---- Web 入口 ----
EXPOSE_NGINX_PORT=80
```

`deployment/docker-compose.override.yaml`（本作品实际使用的 override）做三件事：

```yaml
services:
  seekdb:
    ports: !override
      - "${SEEKDB_HOST_PORT:-2885}:2881"     # 宿主机 2881 可能被别的容器占用
  plugin_daemon:
    environment:
      DB_TYPE: ${PLUGIN_DAEMON_DB_TYPE:-mysql}
    volumes: !override
      - plugin_daemon_storage:/app/storage   # 规避 Windows bind mount 下插件安装超时

volumes:
  plugin_daemon_storage:
    name: dify600076_plugin_daemon_storage
```

放到 `dify-1.18.0/docker/docker-compose.override.yaml` 即可（compose 自动叠加）。
命名卷的原因：Windows Docker Desktop 下插件 venv 的成千上万小文件在 bind mount 上 `stat()` 极慢，
插件 2 分钟内完不成就绪握手会报 `timed out on waiting for plugin to be ready`（详见
`deployment/patches/README.md` §4）。

## 5. 启动顺序（含 seekdb 建库与迁移补丁）

### 5.1 启动 seekdb，创建 Dify 三个库

```bash
docker compose --profile seekdb up -d seekdb
docker compose ps seekdb                     # 等 STATUS=healthy

docker exec -i seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$SEEKDB_PASSWORD" \
  < deployment/patches/seekdb_init.sql
# CREATE DATABASE dify / dify_plugin / dify_vector
```

### 5.2 应用 seekdb 迁移补丁并执行 Dify 数据库迁移

seekdb v1.4 不支持 `CREATE TEMPORARY TABLE`，Dify 1.18.0 有一个 Alembic 迁移用到它。
补丁、原理与完整步骤见 **`deployment/patches/README.md`**，速览：

```bash
# 1) 让 api 容器先起来（迁移会失败退出，正常）
docker compose up -d api

# 2) 覆盖被 patch 的迁移文件
docker cp deployment/patches/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py \
  "$(docker compose ps -q api)":/app/api/migrations/versions/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py

# 3) 跑迁移（官方镜像内置 MODE=migration）
docker compose run --rm --no-deps -e MODE=migration api
```

成功标志：`Database migration successful! / Migration completed, exiting normally`。

### 5.3 启动全部服务并验证

```bash
docker compose up -d
docker compose ps

docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$SEEKDB_PASSWORD" -e "
  SELECT COUNT(*) AS dify_tables FROM information_schema.tables WHERE table_schema='dify';
  SELECT version_num FROM dify.alembic_version;
  SELECT COUNT(*) AS plugin_tables FROM information_schema.tables WHERE table_schema='dify_plugin';
  SHOW TABLES FROM dify_vector;"
```

预期：`dify_tables ≈ 172`；`dify_vector` 为空（等知识库创建）；`dify_plugin` 有插件守护进程的表。

## 6. 控制台初始化与模型配置

打开 `http://localhost`（`EXPOSE_NGINX_PORT`）→ 设置管理员账号 → 登录。

模型供应商（设置 → 模型供应商）：

1. 安装市场插件 **OpenAI-API-compatible 0.0.73**（`langgenius/openai_api_compatible`）：
   - 在线：插件市场搜索安装；
   - 离线（推荐，避免市场网络慢）：下载官方插件包
     `https://marketplace.dify.ai/api/v1/plugins/langgenius/openai_api_compatible/0.0.73/download`，
     然后 插件 → 安装插件 → 本地插件包上传（或 `POST /console/api/workspaces/current/plugin/upload/pkg`）。
   - 若在 Windows Docker Desktop 上安装超时，先按 §4 把 `plugin_daemon` 的存储改成命名卷。
2. 添加 **LLM**：模型名 `qwen2.5-3b-instruct`，
   `Base URL = http://host.docker.internal:8000/v1`，API Key 任意占位值，上下文 4096，最大输出 2048；
3. 添加 **Text Embedding**：模型名 `bge-small-zh-v1.5`，
   `Base URL = http://host.docker.internal:8001/v1`，维度 **512**，上下文 512；
4. 设置 →「系统模型设置」里把 **默认 LLM** 设为 `qwen2.5-3b-instruct`、
   **默认 Embedding** 设为 `bge-small-zh-v1.5`（不设默认 embedding，创建知识库会报
   `Default model not found for text-embedding`）。

> 模型端口以实际环境为准；若模型跑在另一台机器，把 `host.docker.internal` 换成该机 IP。
> **Linux** 上 Docker 不内置 `host.docker.internal`，需给 api/worker 加
> `extra_hosts: ["host.docker.internal:host-gateway"]`。

## 7. 建知识库、导入应用、绑定与发布

1. **知识库**：控制台 → 知识库 → 创建《荒诞法典》→ 上传 `knowledge/absurd_codex.md`
   → 通用分段（分隔符 `\n## `、最大 500 / 重叠 50）→ 高质量索引（`bge-small-zh-v1.5`，512 维）。
   详细配置见 `knowledge/README.md`。
2. **导入 DSL**：创建应用 → 导入 DSL → `apps/absurd-court.chatflow.yml`（导入后画布 25 节点/28 连线）。
3. **绑定知识库**：画布中打开 `retrieve_codex` 节点，重新选择《荒诞法典》（或带 `--dataset-id` 重新生成 DSL）。
4. **检查模型**：5 个 LLM 节点（`parse_llm` / `opening_llm` / `defendant_llm` / `debate_llm` / `verdict_llm`）选中 `qwen2.5-3b-instruct`。
5. **检查服务地址**：4 个 HTTP 节点 URL 为 `http://host.docker.internal:8899/...`。
6. 保存 → **发布** → 访问 API → 创建应用 API Key（`app-` 开头）。

## 8. 案卷库初始化与书记员服务（职责 ③）

```bash
cd memory-service
cp config.example.env config.env
# 编辑 config.env：DB_PORT=2885（宿主机映射端口）、DB_PASSWORD=<SEEKDB_PASSWORD>
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py --init-db        # 在 seekdb 创建 absurd_court 库 + cases 表
.\run.ps1                      # 或 ./run.sh
```

验证（宿主机 + 容器内）：

```bash
curl -s http://127.0.0.1:8899/healthz
docker compose exec api curl -s http://host.docker.internal:8899/healthz   # ok
```

## 9. 端口与网络

| 服务 | 宿主机 | 容器内 / 说明 |
|---|---|---|
| Dify Web / API | `http://localhost:80`（`EXPOSE_NGINX_PORT`） | 控制台、应用 Web、`/v1` Service API |
| seekdb（MySQL 协议） | `127.0.0.1:2885` → 容器 2881 | Dify api/worker、plugin_daemon、书记员服务都连它 |
| 书记员服务 | `127.0.0.1:8899` | Dify 容器内用 `host.docker.internal:8899` |
| 模型服务 | `127.0.0.1:8000`（chat）/ `:8001`（embedding） | Dify 容器内用 `host.docker.internal:8000/8001` |

## 10. 停止、重置与复现初始状态

```bash
docker compose down            # 保留数据卷
docker compose down -v         # 清空所有数据（seekdb 里的 dify / dify_vector / absurd_court 全部清空）

# 只重置案卷库（保留知识库向量与 Dify 数据）
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$SEEKDB_PASSWORD" -e "DROP DATABASE IF EXISTS absurd_court;"
cd memory-service && python app.py --init-db
```

## 11. 已知限制

- 本作品面向单机演示：未配置 HTTPS 域名、未开启多工作区/RBAC 高级特性；Dify 控制台账号仅本机使用。
- seekdb 容器默认 2 GB 内存上限（`SEEKDB_MEMORY_LIMIT`），如机器内存充裕可调大。
- 为兼容 seekdb v1.4 的临时表限制，Dify 1.18.0 的 **1 个 alembic 迁移文件**使用了补丁
  （`deployment/patches/`），升级 Dify 版本时需重新核对该迁移是否仍存在。
- 本地 `qwen2.5-3b-instruct` 推理较慢（约 5~10 tok/s），单次开庭响应约 5~20 秒；换用更强/更快的
  OpenAI 兼容模型即可显著改善（DSL 无需改动，UI 重绑即可）。