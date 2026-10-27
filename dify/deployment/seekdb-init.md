# seekdb 初始化与验证（三重职责）

本文件覆盖 seekdb 在 Dify 1.18.0 部署中的三类数据职责的初始化与验证：

| # | 职责 | 库 | 初始化方式 |
|---|---|---|---|
| ① | Dify 部署主数据库 | `dify` | `deployment/patches/seekdb_init.sql` 建库 + Dify 迁移（含临时表补丁） |
| ①' | Dify 插件数据库 | `dify_plugin` | 同上（plugin_daemon 用 MySQL 驱动） |
| ② | 知识库向量存储 | `dify_vector` | Dify 自动建表（创建知识库并索引时） |
| ③ | 应用案卷库 | `absurd_court` | `memory-service/schema.sql`（或 `python app.py --init-db`） |

环境事实（本地取证环境；以实际部署为准）：

- seekdb 容器名 `seekdb`，镜像 `oceanbase/seekdb:latest`，服务端版本 **v1.4.0.0**（MySQL 协议 5.7.25）
- 容器内端口 **2881**；宿主机映射 **127.0.0.1:2885**（`SEEKDB_HOST_PORT=2885`）
- root 密码取 `.env` 的 `DB_PASSWORD` / `OCEANBASE_VECTOR_PASSWORD`（示例占位 `<SEEKDB_PASSWORD>`）

> 下文的 `$PW` 请替换成实际密码；PowerShell 里用 `$pw = "<密码>"` 后同样方式传参。

## 0. 确认容器就绪

```bash
docker compose ps seekdb
# NAME ... STATUS ... PORTS
# seekdb ... Up (healthy) ... 0.0.0.0:2885->2881/tcp
```

## 1. 连通性检查（宿主机 mysql 客户端 / 容器内命令均可）

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "SELECT VERSION();"
# 预期输出类似：5.7.25-OceanBase-seekdb-... 或 seekdb v1.4.x 版本串
```

从宿主机直连（验证 2885 映射，也是书记员服务的连接方式）：

```bash
mysql -h127.0.0.1 -P2885 -uroot -p"$PW" -e "SELECT VERSION();"
```

## 2. 职责 ① / ①'：Dify 主库与插件库

### 2.1 建库

```bash
docker exec -i seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" < deployment/patches/seekdb_init.sql
```

```sql
CREATE DATABASE IF NOT EXISTS dify;
CREATE DATABASE IF NOT EXISTS dify_plugin;
CREATE DATABASE IF NOT EXISTS dify_vector;
```

### 2.2 执行 Dify 迁移（含 seekdb 临时表补丁）

见 `deployment/patches/README.md`。成功后验证：

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "
  SELECT COUNT(*) AS dify_tables FROM information_schema.tables WHERE table_schema='dify';
  SELECT version_num FROM dify.alembic_version;
  SELECT COUNT(*) AS plugin_tables FROM information_schema.tables WHERE table_schema='dify_plugin';"
```

预期 `dify_tables ≈ 172`（Dify 1.18.0 全量迁移），`alembic_version` 为最新 revision。

## 3. 职责 ③：应用案卷库 `absurd_court`

### 3.1 执行 schema.sql

```bash
# 在仓库根目录执行
docker exec -i seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" < memory-service/schema.sql
```

或（推荐，幂等）：

```bash
cd memory-service
# config.env 里把 DB_HOST/DB_PORT 指向 seekdb：DB_HOST=127.0.0.1、DB_PORT=2885
python app.py --init-db --only-init
```

### 3.2 验证表结构

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "
  SHOW DATABASES LIKE 'absurd_court';
  USE absurd_court; SHOW TABLES; DESC cases;"
```

### 3.3 验证案卷写入（跑一场官司后）

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "
  SELECT id,case_no,plaintiff,defendant,charge,status,created_at
  FROM absurd_court.cases ORDER BY id DESC LIMIT 5;"
```

### 3.4 验证先例检索用的索引

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "
  SHOW INDEX FROM absurd_court.cases;"
```

## 4. 职责 ②：知识库向量库 `dify_vector`

### 4.1 查看向量表

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "
  USE dify_vector; SHOW TABLES;"
```

在结果中找到形如 `Vector_index_<dataset_id>_Node` 的表（每个知识库一张）。

### 4.2 统计向量行数

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "
  USE dify_vector;
  SELECT COUNT(*) AS vectors FROM \`<向量表名>\`;"
```

预期行数 = 知识库分段数（《荒诞法典》按 `##` 分段约 30~40 行）。

### 4.3 检索证据

Dify 控制台 → 知识库《荒诞法典》→ 召回测试 → 输入 `电器 通敌`，应命中
「第一条 · 电器通敌罪」；对照 `SELECT COUNT(*)` 的行数即可证明向量确实在 seekdb。
证据见 `evidence/seekdb-queries.md` 与 `evidence/screenshots/`。

## 5. 三条职责的汇总验证（一段 SQL）

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "
  SELECT '① dify 主库表数' AS item, COUNT(*) AS n FROM information_schema.tables WHERE table_schema='dify'
  UNION ALL SELECT '① plugin 库表数', COUNT(*) FROM information_schema.tables WHERE table_schema='dify_plugin'
  UNION ALL SELECT '② 向量库表数', COUNT(*) FROM information_schema.tables WHERE table_schema='dify_vector'
  UNION ALL SELECT '③ 案卷行数', COUNT(*) FROM absurd_court.cases;"
```

> 若 `dify_vector` 表数为 0，说明知识库尚未创建/索引，先完成 `knowledge/README.md` 的步骤。

## 6. 重置（重新验证时使用）

```bash
# 只清案卷库（保留 Dify 数据与知识库向量）
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "DROP DATABASE IF EXISTS absurd_court;"
cd memory-service && python app.py --init-db --only-init

# 或在 Dify 控制台删除知识库《荒诞法典》后重建（会清理 dify_vector 中对应向量表）
```

恢复初始状态后，按 `VERIFICATION.md` 的顺序重放 V1→V2→V3a→V3b→V4→V5。