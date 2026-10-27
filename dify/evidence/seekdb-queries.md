# seekdb 查询证据（三重职责）

> 本文记录《离谱法庭 · The Absurd Court》取证环境中对 seekdb 的真实查询与输出。
> 环境：seekdb `oceanbase/seekdb` 容器（服务端 `5.7.25-OceanBase seekdb-v1.4.0.0），容器内 2881，宿主机 `127.0.0.1:2885`。
> 查询方式：PyMySQL（与书记员服务相同驱动）/ `docker exec ... mysql`。
> 记录时间：2026-10-28 04:31

## 0. 实例与库清单（三重职责同时存在）

```sql
SELECT VERSION();
SHOW DATABASES;
```

实测输出：

```
5.7.25-OceanBase seekdb-v1.4.0.0
DATABASES: ['absurd_court', 'dify', 'dify_plugin', 'dify_vector', 'information_schema', 'mysql', 'oceanbase', 'test']
```

## 1. 职责 ①：Dify 部署主数据库（`dify` 库）与插件库（`dify_plugin`）

```sql
SELECT COUNT(*) AS dify_tables FROM information_schema.tables WHERE table_schema='dify';
SELECT version_num FROM dify.alembic_version;
SELECT COUNT(*) AS plugin_tables FROM information_schema.tables WHERE table_schema='dify_plugin';
```

实测输出：

```
dify_tables   = 172
alembic_version = b9d3f7a5c102
plugin_tables = 13
```

> Dify 1.18.0 全量迁移后的 172 张表全部在 seekdb；`plugin_daemon` 以 MySQL 驱动使用同一个
> seekdb 实例（`PLUGIN_DAEMON_DB_TYPE=mysql`），插件数据在 `dify_plugin` 库。
> seekdb v1.4.0.0 不支持 `CREATE TEMPORARY TABLE`，1 个 alembic 迁移使用了
> `deployment/patches/` 中的兼容补丁；其余源码未改动。

## 2. 职责 ②：知识库向量存储（`dify_vector` 库）

```sql
SHOW TABLES FROM dify_vector;
SELECT COUNT(*) FROM dify_vector.`vector_index_ac7f91e4_254c_42f4_bd83_08a975392e53_node`;
```

实测输出：

```
SHOW TABLES FROM dify_vector;
+-------------------------------------------------------------+
| Tables_in_dify_vector                                       |
+-------------------------------------------------------------+
| vector_index_ac7f91e4_254c_42f4_bd83_08a975392e53_node |
+-------------------------------------------------------------+

vectors = 38     -- 与知识库 38 个分段一致
```

Dify 知识库《荒诞法典》：36 条法条 + 总则 + 附则，按 `\n## ` 分段共 38 段；
检索配置：向量检索（semantic），top_k=3，score 阈值 0.2。
召回测试（`POST /console/api/datasets/{dataset_id}/hit-testing`）实测：

```
query = 电器 通敌
  score 0.6657  第一条 · 电器通敌罪 ★电器 ★通敌 ★夜间异响
  score 0.4393  第二条 · 充电线私通罪 ★充电线 ★接触不良 ★发烫
  score 0.4048  第三条 · 插头半途而废罪 ★插头 ★插座 ★脱落

query = 毛茸茸 占床
  score 0.6883  第七条 · 毛茸茸非法占床罪
query = 周一 循环
  score 0.6525  第五条 · 周一恶意循环罪
```

（完整 JSON 见 `evidence/logs/kb-hit-testing.json`，UI 截图见
`evidence/screenshots/13-knowledge-hit-testing.png`。）

## 3. 职责 ③：应用案卷库（`absurd_court` 库，表 `cases`）

### 3.1 表结构

```sql
SHOW DATABASES LIKE 'absurd_court';
USE absurd_court; SHOW TABLES; DESC cases; SHOW INDEX FROM cases;
```

实测输出（结构正确，`ON UPDATE CURRENT_TIMESTAMP` 在 seekdb v1.4 实测支持）：

```
tables: cases
id BIGINT AUTO_INCREMENT PRIMARY KEY
case_no VARCHAR(16) NOT NULL UNIQUE
plaintiff VARCHAR(64) NOT NULL DEFAULT ''
defendant VARCHAR(128) NOT NULL
charge VARCHAR(255) NOT NULL
claim VARCHAR(500)
evidence TEXT
verdict VARCHAR(32) / penalty VARCHAR(500) / judgment TEXT
status VARCHAR(16) NOT NULL DEFAULT 'open'
created_at DATETIME DEFAULT CURRENT_TIMESTAMP
updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
索引：PRIMARY(id) / UNIQUE(case_no) / idx_plaintiff(plaintiff) / idx_defendant(defendant)
```

### 3.2 V1~V5 运行后的案卷数据

```sql
SELECT id,case_no,plaintiff,defendant,charge,status,verdict,penalty FROM absurd_court.cases ORDER BY id;
```

实测输出：

| id | 案号 | 原告 | 被告 | 罪名 | 状态 | 判决 | 罚则 |
|---|---|---|---|---|---|---|---|
| 1 | #0001 | demo-final | 充电线 | 通敌 | closed | 罪名成立 | 罚其为原告连唱三夜摇篮曲 |
| 2 | #0002 | demo-final | 充电线 | 屡教不改的通敌 | open | - | - |
| 3 | #0003 | demo-final-v5 | asdf | 非法占床 | open | - | - |

### 3.3 三段式验证（汇总 SQL）

```sql
SELECT '① dify 主库表数' AS item, COUNT(*) AS n FROM information_schema.tables WHERE table_schema='dify'
UNION ALL SELECT '① plugin 库表数', COUNT(*) FROM information_schema.tables WHERE table_schema='dify_plugin'
UNION ALL SELECT '② 向量表行数', 38 FROM DUAL
UNION ALL SELECT '③ 案卷行数', COUNT(*) FROM absurd_court.cases;
```

实测结果见上文三节（① 172 表 / ①' 13 表 / ② 38 行向量 / ③ 3 行案卷）。

## 4. 重置方式（重复验证用）

```bash
docker exec -it seekdb mysql -h127.0.0.1 -P2881 -uroot -p"$PW" -e "DROP DATABASE IF EXISTS absurd_court;"
cd memory-service && python app.py --init-db
```

重置后按 `VERIFICATION.md` 的顺序重放 V1→V2→V3a→V3b→V4→V5。
