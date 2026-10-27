-- 离谱法庭 · 书记员服务数据库初始化脚本
-- 目标库：seekdb（MySQL 协议兼容，Dify 1.18 的 VECTOR_STORE=seekdb 容器，端口 2881）
-- 用法：
--   mysql -h127.0.0.1 -P2881 -uroot -p < schema.sql
--   或 python app.py --init-db（推荐，PyMySQL 直接执行）
--
-- 说明：Dify 知识库《荒诞法典》的向量表由 Dify 自己在同一 seekdb 实例中创建，
--       本脚本只负责应用数据存储（案卷库 absurd_court.cases）。

CREATE DATABASE IF NOT EXISTS absurd_court DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_general_ci;
USE absurd_court;

CREATE TABLE IF NOT EXISTS cases (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  case_no VARCHAR(16) NOT NULL UNIQUE,
  plaintiff VARCHAR(64) NOT NULL DEFAULT '',
  defendant VARCHAR(128) NOT NULL,
  charge VARCHAR(255) NOT NULL,
  claim VARCHAR(500) DEFAULT '',
  evidence TEXT,
  verdict VARCHAR(32) DEFAULT NULL,
  penalty VARCHAR(500) DEFAULT NULL,
  judgment TEXT,
  status VARCHAR(16) NOT NULL DEFAULT 'open',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_plaintiff (plaintiff),
  KEY idx_defendant (defendant)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;