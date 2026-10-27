# deployment/patches —— seekdb 兼容补丁（Dify 1.18.0 部署到 seekdb）

## 1. 为什么需要补丁

本作品按赛题鼓励的方式，用 **seekdb 作为 Dify 的部署主数据库**（`DB_TYPE=seekdb`）。
seekdb v1.4.0.0（MySQL 协议 5.7.25）与 Dify 1.18.0 的 Alembic 迁移基本兼容，但有一处不兼容：

| 项 | 内容 |
|---|---|
| seekdb 限制 | **不支持 `CREATE TEMPORARY TABLE`**（临时表语法） |
| 受影响的迁移 | `api/migrations/versions/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py` |
| 原逻辑 | 迁移旧模型类型时用 `CREATE TEMPORARY TABLE tmp_5578e028b2f2_credential_merges AS ...` 暂存中间结果，用完 `DROP TEMPORARY TABLE` |
| 现象 | 迁移执行到该 revision 时报错，Dify 无法完成数据库初始化（`dify` 库只有部分表） |
| 修复方式 | 改为**普通表** + 前后显式 `DROP TABLE IF EXISTS`（迁移在单实例上串行执行，语义等价，不影响结果） |

补丁文件：`deployment/patches/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py`
（即 Dify 1.18.0 原文件的最小改动版，文件头有 `# PATCHED for seekdb` 注释与原始路径）。

实际改动（diff 摘要）：

```diff
+ # PATCHED for seekdb (OceanBase seekdb v1.4 does not support MySQL-compatible temporary tables).
+ # Regular table + explicit DROP used instead. Original: migrations/versions/2026_08_27_1200-5578e028b2f2
+ op.execute(sa.text(f"DROP TABLE IF EXISTS {_CREDENTIAL_MERGES_TABLE}"))
+     f"""CREATE TABLE {_CREDENTIAL_MERGES_TABLE} AS ...
+ op.execute(sa.text(f"DROP TABLE {_CREDENTIAL_MERGES_TABLE}"))
- op.execute(sa.text(f"DROP TEMPORARY TABLE IF EXISTS {_CREDENTIAL_MERGES_TABLE}"))
-     f"""CREATE TEMPORARY TABLE {_CREDENTIAL_MERGES_TABLE} {table_options} AS ...
- op.execute(sa.text(f"DROP TEMPORARY TABLE {_CREDENTIAL_MERGES_TABLE}"))
```

> 这是**唯一**的 Dify 源码级改动；除该迁移脚本外，Dify 1.18.0 源码与官方者镜像完全一致。

## 2. 应用步骤（可复现）

前提：Dify 1.18.0 源码已解压，`docker/.env` 已按 `deployment/env.additions.example` 配置
（`DB_TYPE=seekdb`、seekdb 容器已建 `dify` / `dify_plugin` / `dify_vector` 三个库）。

### 方式 A：覆盖到运行中的 api 容器后执行迁移（最快，适合本地演示）

```bash
# 1) 启动 seekdb 并等健康
cd dify-1.18.0/docker
docker compose --profile seekdb up -d seekdb
docker compose ps seekdb

# 2) 建库（见 deployment/seekdb-init.md）
docker exec -i seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PASSWORD" < ../../deployment/patches/seekdb_init.sql

# 3) 先起一次 api 容器（迁移未完成时它会退出/重启，属正常）
docker compose up -d api

# 4) 把补丁覆盖进 api 容器
docker cp deployment/patches/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py \
  "$(docker compose ps -q api)":/app/api/migrations/versions/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py

# 5) 运行数据库迁移
docker compose run --rm --no-deps -e MODE=migration api

# 6) 继续启动全部服务
docker compose up -d
```

### 方式 B：compose override 挂载补丁（更持久，重建容器后仍生效）

在 `docker/docker-compose.override.yaml` 中增加：

```yaml
services:
  api:
    volumes:
      - ../../deployment/patches/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py:/app/api/migrations/versions/2026_08_27_1200-5578e028b2f2_migrate_legacy_model_types.py:ro
```

然后：

```bash
docker compose --profile seekdb up -d seekdb
docker exec -i seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PASSWORD" < deployment/patches/seekdb_init.sql
docker compose run --rm --no-deps -e MODE=migration api
docker compose up -d
```

> `MODE=migration` 是 Dify 官方 api 镜像内置的入口模式，等价于执行 `flask db upgrade` 后退出；
> 迁移日志可见 `Database migration successful! / Migration completed, exiting normally`。

### 验证迁移成功

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PASSWORD" -e "
  SELECT COUNT(*) AS dify_tables FROM information_schema.tables WHERE table_schema='dify';
  SELECT version_num FROM dify.alembic_version;"
```

预期：`dify_tables` 约 **172**（Dify 1.18.0 全量迁移后的表数，以实际版本为准），
`alembic_version.version_num` 为最新 revision（不再是卡住的那个 revision）。

## 3. 在本次提交中的实际使用

本作品本地取证环境（Windows + Docker Desktop）按 **方式 A** 应用补丁；
提交的 `deployment/docker-compose.override.yaml` 是本作品实际使用的 override：
seekdb 容器内端口保持 2881，宿主机端口改为 `SEEKDB_HOST_PORT=2885`（避免与本机其他容器冲突），
并让 `plugin_daemon` 用 MySQL 驱动连同一个 seekdb 实例（`PLUGIN_DAEMON_DB_TYPE=mysql`）。

复现时如宿主机 2881 可用，可以不改宿主机端口，只要把 `DB_PORT`/`OCEANBASE_VECTOR_PORT`
与 `memory-service` 的 `DB_PORT` 对齐即可。

## 4. 附：plugin_daemon 存储卷（部署层规避，非源码补丁）

Windows Docker Desktop 下如果 `plugin_daemon` 的 `/app/storage` 使用**绑定挂载**（官方 compose 默认
`./volumes/plugin_daemon:/app/storage`），安装插件时会因为插件 venv 内成千上万个小文件在 bind mount 上
`stat()` 极慢，导致插件 2 分钟内无法完成 stdio 握手 → 安装任务报
`timed out on waiting for plugin to be ready after 2m0s`。

**规避方式**（已写进 `deployment/docker-compose.override.yaml`）：把该目录改成命名卷。

```yaml
services:
  plugin_daemon:
    volumes: !override
      - plugin_daemon_storage:/app/storage

volumes:
  plugin_daemon_storage:
    name: dify600076_plugin_daemon_storage
```

改完后**离线安装**插件包（本作品使用 `langgenius/openai_api_compatible:0.0.73`）：

- UI：插件 → 安装插件 → 本地插件包上传；或
- API：`POST /console/api/workspaces/current/plugin/upload/pkg`（multipart）。
- 官方下载：`https://marketplace.dify.ai/api/v1/plugins/langgenius/openai_api_compatible/0.0.73/download`

> 这不是 Dify 源码补丁，只是 Docker Desktop/Windows 的部署环境规避；Linux 上使用官方 bind mount 通常不存在该问题。