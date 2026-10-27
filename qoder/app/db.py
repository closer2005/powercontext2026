"""pymysql 连接管理 + 建表 + CRUD（notes / review_items / search_log）。"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymysql

from app.config import SEEKDB_DATABASE, SEEKDB_HOST, SEEKDB_PASSWORD, SEEKDB_PORT, SEEKDB_USER

logger = logging.getLogger(__name__)

_DDL_NOTES = """
CREATE TABLE IF NOT EXISTS notes (
  id VARCHAR(32) PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  course VARCHAR(64) DEFAULT '',
  topic VARCHAR(128) DEFAULT '',
  tags VARCHAR(255) DEFAULT '',
  source VARCHAR(255) DEFAULT '',
  content MEDIUMTEXT NOT NULL,
  chunk_count INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_DDL_REVIEW_ITEMS = """
CREATE TABLE IF NOT EXISTS review_items (
  chunk_id VARCHAR(32) PRIMARY KEY,
  note_id VARCHAR(32) NOT NULL,
  due_at DATETIME NOT NULL,
  interval_days INT DEFAULT 0,
  ease FLOAT DEFAULT 2.5,
  reps INT DEFAULT 0,
  lapses INT DEFAULT 0,
  last_grade INT DEFAULT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  KEY idx_due (due_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_DDL_SEARCH_LOG = """
CREATE TABLE IF NOT EXISTS search_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  query VARCHAR(512) NOT NULL,
  course VARCHAR(64) DEFAULT '',
  topic VARCHAR(128) DEFAULT '',
  mode VARCHAR(16) DEFAULT 'hybrid',
  k INT DEFAULT 0,
  took_ms INT DEFAULT 0,
  result_count INT DEFAULT 0,
  used_vector TINYINT DEFAULT 0,
  used_fulltext TINYINT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""


def _conn_kwargs() -> Dict[str, Any]:
    return dict(
        host=SEEKDB_HOST,
        port=SEEKDB_PORT,
        user=SEEKDB_USER,
        password=SEEKDB_PASSWORD or "",
        database=SEEKDB_DATABASE,
        charset="utf8mb4",
        connect_timeout=10,
        autocommit=True,
    )


@contextmanager
def get_connection(retries: int = 3, delay: float = 2.0):
    """获取短连接，支持重试。"""
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            conn = pymysql.connect(**_conn_kwargs())
            try:
                yield conn
            finally:
                conn.close()
            return
        except pymysql.err.OperationalError as e:
            last_err = e
            logger.warning("DB connection attempt %d failed: %s", attempt + 1, e)
            if attempt < retries - 1:
                time.sleep(delay)
    raise RuntimeError(f"Cannot connect to seekdb after {retries} attempts: {last_err}")


def ensure_database() -> None:
    """确保目标数据库存在（seekdb 初始只有 test/mysql 等内置库）。"""
    kwargs = _conn_kwargs()
    kwargs.pop("database", None)
    conn = pymysql.connect(**kwargs)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{SEEKDB_DATABASE}` "
                "DEFAULT CHARACTER SET utf8mb4"
            )
    finally:
        conn.close()


def ensure_schema(max_retries: int = 30, retry_delay: float = 2.0) -> None:
    """建表，等待 seekdb ready 时重试（先建库再建表）。"""
    for attempt in range(max_retries):
        try:
            ensure_database()
            with get_connection(retries=1) as conn:
                with conn.cursor() as cur:
                    cur.execute(_DDL_NOTES)
                    cur.execute(_DDL_REVIEW_ITEMS)
                    cur.execute(_DDL_SEARCH_LOG)
                logger.info("Schema ensured on attempt %d", attempt + 1)
                return
        except Exception as e:
            logger.warning("ensure_schema attempt %d failed: %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    raise RuntimeError(f"ensure_schema failed after {max_retries} attempts")


# ──────────────────────── notes CRUD ────────────────────────


def insert_note(
    title: str,
    content: str,
    course: str = "",
    topic: str = "",
    tags: str = "",
    source: str = "",
) -> str:
    """插入笔记，返回 note_id (uuid hex)。"""
    note_id = uuid.uuid4().hex
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notes (id, title, course, topic, tags, source, content) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (note_id, title, course, topic, tags, source, content),
            )
    return note_id


def update_note_chunk_count(note_id: str, chunk_count: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE notes SET chunk_count = %s WHERE id = %s", (chunk_count, note_id))


def list_notes(limit: int = 100, course: str = "") -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            if course:
                cur.execute(
                    "SELECT id, title, course, topic, tags, source, chunk_count, created_at "
                    "FROM notes WHERE course = %s ORDER BY created_at DESC LIMIT %s",
                    (course, limit),
                )
            else:
                cur.execute(
                    "SELECT id, title, course, topic, tags, source, chunk_count, created_at "
                    "FROM notes ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
    for r in rows:
        if isinstance(r.get("created_at"), datetime):
            r["created_at"] = r["created_at"].isoformat()
    return rows


def count_notes() -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM notes")
            return cur.fetchone()[0]


def get_note_by_id(note_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT * FROM notes WHERE id = %s", (note_id,))
            row = cur.fetchone()
    if row and isinstance(row.get("created_at"), datetime):
        row["created_at"] = row["created_at"].isoformat()
    return row


def get_note_by_title(title: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT id, title FROM notes WHERE title = %s", (title,))
            row = cur.fetchone()
    return row


def delete_note_by_id(note_id: str) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM review_items WHERE note_id = %s", (note_id,))
            cur.execute("DELETE FROM notes WHERE id = %s", (note_id,))
            return cur.rowcount > 0


# ──────────────────────── review_items CRUD ────────────────────────


def upsert_review_item(
    chunk_id: str,
    note_id: str,
    due_at: datetime,
    interval_days: int = 0,
    ease: float = 2.5,
    reps: int = 0,
    lapses: int = 0,
    last_grade: Optional[int] = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO review_items (chunk_id, note_id, due_at, interval_days, ease, reps, lapses, last_grade) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE due_at=VALUES(due_at), interval_days=VALUES(interval_days), "
                "ease=VALUES(ease), reps=VALUES(reps), lapses=VALUES(lapses), last_grade=VALUES(last_grade)",
                (chunk_id, note_id, due_at, interval_days, ease, reps, lapses, last_grade),
            )


def get_review_item(chunk_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT * FROM review_items WHERE chunk_id = %s", (chunk_id,))
            row = cur.fetchone()
    if row:
        for k in ("due_at", "updated_at"):
            if isinstance(row.get(k), datetime):
                row[k] = row[k].isoformat()
    return row


def get_due_items(limit: int = 10) -> List[Dict[str, Any]]:
    now = datetime.now().isoformat()
    with get_connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT r.chunk_id, r.note_id, n.title, n.course, n.topic, "
                "r.due_at, r.reps, r.interval_days, r.ease, r.lapses "
                "FROM review_items r "
                "LEFT JOIN notes n ON r.note_id = n.id "
                "WHERE r.due_at <= %s "
                "ORDER BY r.due_at ASC LIMIT %s",
                (now, limit),
            )
            rows = cur.fetchall()
    for r in rows:
        if isinstance(r.get("due_at"), datetime):
            r["due_at"] = r["due_at"].isoformat()
    return rows


def count_review_items() -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM review_items")
            return cur.fetchone()[0]


def count_due_items() -> int:
    now = datetime.now().isoformat()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM review_items WHERE due_at <= %s", (now,))
            return cur.fetchone()[0]


# ──────────────────────── search_log CRUD ────────────────────────


def insert_search_log(
    query: str,
    course: str = "",
    topic: str = "",
    mode: str = "hybrid",
    k: int = 0,
    took_ms: int = 0,
    result_count: int = 0,
    used_vector: bool = False,
    used_fulltext: bool = False,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO search_log (query, course, topic, mode, k, took_ms, result_count, "
                "used_vector, used_fulltext) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (query, course, topic, mode, k, took_ms, result_count, int(used_vector), int(used_fulltext)),
            )


def get_search_logs(limit: int = 20) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(
                "SELECT query, mode, took_ms, result_count, used_vector, used_fulltext, created_at "
                "FROM search_log ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
    for r in rows:
        if isinstance(r.get("created_at"), datetime):
            r["created_at"] = r["created_at"].isoformat()
    return rows


def get_stats_summary() -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM search_log")
            searches = cur.fetchone()["cnt"]
            cur.execute("SELECT AVG(took_ms) AS avg_ms FROM search_log")
            row = cur.fetchone()
            avg_ms = round(row["avg_ms"] or 0, 1)
            cur.execute(
                "SELECT query, COUNT(*) AS cnt FROM search_log "
                "GROUP BY query ORDER BY cnt DESC LIMIT 5"
            )
            top = cur.fetchall()
            cur.execute("SELECT MAX(created_at) AS last_at FROM search_log")
            last = cur.fetchone()
    last_at = last.get("last_at")
    if isinstance(last_at, datetime):
        last_at = last_at.isoformat()
    return {
        "searches": searches,
        "avg_latency_ms": avg_ms,
        "top_queries": [{"query": t["query"], "count": t["cnt"]} for t in top],
        "last_search_at": last_at,
    }
