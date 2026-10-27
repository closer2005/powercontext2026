---
title: EXPLAIN 与慢查询排查
course: 数据库系统
topic: 索引与存储
tags: EXPLAIN 慢查询 执行计划 索引
source: 实验记录 2026-04-10
---

## 看哪几列
`EXPLAIN SELECT ...` 重点看：
- `type`：`const > eq_ref > ref > range > index > ALL`，出现 `ALL` 就是扫全表。
- `key`：实际用的索引，`NULL` 表示没走索引。
- `rows`：预估扫描行数，和实际差太多说明统计信息过期。
- `Extra`：`Using index` 好；`Using filesort`、`Using temporary` 要多看一眼。
- `possible_keys` 有值但 `key` 为 `NULL`，一般说明优化器判断走索引更贵，常见于范围条件太宽或区分度太差的列。

## 一次真实排查
```sql
SELECT * FROM notes
WHERE course = '数据库系统' AND title LIKE '%索引%'
ORDER BY created_at DESC LIMIT 20;
```
- 最初在 course 和 title 上各建单列索引，`Extra` 出现 `Using filesort`。
- 改成 (course, title) 联合索引后 `type=ref`，扫描行数从 4 万多降到 200 多。
- 记录：改前平均 180ms，改后 7ms。这是实验库的数据，不能当线上基准。

## 排查顺序
开 slow_query_log → 找 Top SQL → EXPLAIN → 看索引与回表 → 小流量验证 → 再上。别一上来就加索引。