---
title: MVCC 版本链与 Read View
course: 数据库系统
topic: 事务与并发
tags: MVCC ReadView 版本链 undo log 隔离级别
source: 教材《数据库系统概论》第5版 第10章 复盘
---

## 版本链
- InnoDB 每行有隐藏字段 `DB_TRX_ID`（最近修改事务）和 `DB_ROLL_PTR`（回滚指针）。
- 每次修改把旧值写进 undo log，`roll_ptr` 串成版本链，链头是最新版本。
- purge 线程负责清理不再被任何 Read View 需要的旧版本。

## Read View 判断可见性
关键字段：`m_ids`（活跃事务 id 集合）、`min_trx_id`、`max_trx_id`、`creator_trx_id`。

对一个版本 `trx_id = t`：
1. `t == creator_trx_id` → 可见；
2. `t < min_trx_id` → 可见；
3. `t >= max_trx_id` → 不可见；
4. 否则看 `t` 是否在 `m_ids` 中，在则不可见，不在则可见。

不可见就沿 `roll_ptr` 往回找，直到找到可见版本。

## 与隔离级别
事务隔离级别其实由「MVCC 的可见性判断 + 锁」共同实现，这篇只整理 MVCC 这一半。

- RC：每条 SELECT 重建 Read View，能读到别人已提交的新数据。
- RR：事务内复用同一个 Read View，于是可重复读。
- MVCC 只解决读不加锁，写写冲突仍然靠锁。老师说不要把「隔离级别」和「MVCC」当成同一个东西背。