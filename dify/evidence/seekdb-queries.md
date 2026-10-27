# seekdb 查询证据（三重职责）

> 本文记录《离谱法庭 · The Absurd Court》取证环境中对 seekdb 的真实查询与输出。
> 环境：seekdb `oceanbase/seekdb` 容器（服务端 `5.7.25-OceanBase seekdb-v1.4.0.0`），
> 容器内 2881，宿主机 `127.0.0.1:2885`。查询方式：PyMySQL / `docker exec ... mysql`。
>
> **状态：初稿（知识库创建后补全向量表行数）**

## 0. 实例与库清单（三重职责同时存在）

```sql
SELECT VERSION();
SHOW DATABASES;
```

实测输出：

```
VERSION: 5.7.25-OceanBase seekdb-v1.4.0.0
DATABASES:
  absurd_court      -- ③ 应用案卷库（书记员服务）
  dify              -- ① Dify 部署主数据库
  dify_plugin       -- ①' Dify 插件数据库（plugin_daemon 用 MySQL 驱动）
  dify_vector       -- ② 知识库向量存储
  information_schema
  mysql
  oceanbase
  test
```

## 1. 职责 ①：Dify 部署主数据库（`dify` 库）

```sql
SELECT COUNT(*) AS dify_tables
FROM information_schema.tables WHERE table_schema='dify';
SELECT version_num FROM dify.alembic_version;
```

实测输出（Dify 1.18.0 全量迁移后）：

```
dify_tables = 172
alembic_version = b9d3f7a5c102
```

> 迁移日志见 `evidence/logs/dify-migrate-seekdb.log`（节选）：
> `Database migration successful!` / `Migration completed, exiting normally`。
> seekdb v1.4 不支持 `CREATE TEMPORARY TABLE`，Dify 1.18.0 的 1 个 alembic 迁移使用了
> `deployment/patches/` 中的兼容补丁；除此之外未修改 Dify 源码。

### 1.1 职责 ①'：插件数据库（`dify_plugin` 库）

```sql
SELECT COUNT(*) AS plugin_tables
FROM information_schema.tables WHERE table_schema='dify_plugin';
```

实测输出：

```
plugin_tables = 13
```

## 2. 职责 ②：知识库向量存储（`dify_vector` 库）

```sql
SHOW TABLES FROM dify_vector;
```

<!-- TODO: 知识库创建并索引后补全：

```
+--------------------------------------------+
| Tables_in_dify_vector                      |
+--------------------------------------------+
| Vector_index_<dataset_id>_Node             |
+--------------------------------------------+
```

```sql
SELECT COUNT(*) AS vectors FROM dify_vector.`Vector_index_<dataset_id>_Node`;
```

实测输出：

```
vectors = <分段数>
```
-->

截图：`evidence/screenshots/v2-knowledge-retrieval.png`（知识库召回测试命中「第一条 · 电器通敌罪」）。

## 3. 职责 ③：应用案卷库（`absurd_court` 库）

```sql
SHOW DATABASES LIKE 'absurd_court';
USE absurd_court;
SHOW TABLES;
DESC cases;
SHOW INDEX FROM cases;
```

实测输出：

```
tables: cases
字段：id / case_no / plaintiff / defendant / charge / claim / evidence /
      verdict / penalty / judgment / status / created_at / updated_at
索引：PRIMARY(id) / UNIQUE(case_no) / idx_plaintiff(plaintiff) / idx_defendant(defendant)
```

（`ON UPDATE CURRENT_TIMESTAMP` 在 seekdb v1.4 实测支持，schema.sql 无需降级。）

### 3.1 运行期数据（立案/归档/先例/案底）

```sql
SELECT id,case_no,plaintiff,defendant,charge,status,verdict,LEFT(penalty,30) AS penalty
FROM absurd_court.cases ORDER BY id DESC LIMIT 10;
```

<!-- TODO: V1~V5 跑完后填入真实输出（立案 status=open，宣判后 status=closed + verdict/penalty/judgment） -->

## 4. 一段 SQL 汇总三重职责

```sql
SELECT '① dify 主库表数' AS item, COUNT(*) AS n FROM information_schema.tables WHERE table_schema='dify'
UNION ALL SELECT '① plugin 库表数', COUNT(*) FROM information_schema.tables WHERE table_schema='dify_plugin'
UNION ALL SELECT '② 向量库表数', COUNT(*) FROM information_schema.tables WHERE table_schema='dify_vector'
UNION ALL SELECT '③ 案卷行数', COUNT(*) FROM absurd_court.cases;
```

<!-- TODO: 最终评测时填入实测输出 -->