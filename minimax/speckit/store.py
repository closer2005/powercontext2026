"""seekdb 存取层（PyMySQL / MySQL 协议）。

职责：
    init_schema()             建库（若不存在）并创建 spec_items / code_items / test_items 三张表
    upsert_specs/code/tests   幂等写入 data/ 三份索引
    load_specs/code/tests     读取全部条目
    search(keywords)          关键词命中打分检索，返回带 score 的行（供 selector 排序）

硬性约束（见 minimax/DESIGN.md §8）：
    * 所有 SQL 一律参数化，任何来自文件/用户的数据都不拼接进 SQL 文本；
    * 连接失败必须抛出 StoreError，并附中文排查指引，绝不静默失败；
    * 检索结果完全来自 SQL 查询，代码内不写死任何答案。

表结构说明：三张表共享同一结构，包含契约要求的 5 个字段
（id / title_or_name / file / keywords / text），并额外带一个 scope 列。
原因：DESIGN §3.1 的规格条目含 scope 字段，selector 需要按 scope 做过滤与加成，
因此把 scope 作为独立列（非规格条目的 scope 由 file 路径推断，缺省为空串）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import pymysql
from pymysql.cursors import DictCursor

from .config import Config

# 连接超时（秒），避免网络不通时长时间挂起
CONNECT_TIMEOUT = 8

_SAFE_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")

_TABLES = ("spec_items", "code_items", "test_items")

# 三张表的 DDL（结构一致，索引名不同）
_DDL: dict[str, str] = {
    "spec_items": (
        "CREATE TABLE IF NOT EXISTS spec_items ("
        " id VARCHAR(128) NOT NULL,"
        " title_or_name VARCHAR(512) NOT NULL DEFAULT '',"
        " file VARCHAR(512) NULL,"
        " keywords TEXT NULL,"
        " text LONGTEXT NULL,"
        " scope VARCHAR(64) NOT NULL DEFAULT '',"
        " PRIMARY KEY (id),"
        " KEY idx_spec_items_scope (scope)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
    ),
    "code_items": (
        "CREATE TABLE IF NOT EXISTS code_items ("
        " id VARCHAR(128) NOT NULL,"
        " title_or_name VARCHAR(512) NOT NULL DEFAULT '',"
        " file VARCHAR(512) NULL,"
        " keywords TEXT NULL,"
        " text LONGTEXT NULL,"
        " scope VARCHAR(64) NOT NULL DEFAULT '',"
        " PRIMARY KEY (id),"
        " KEY idx_code_items_scope (scope)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
    ),
    "test_items": (
        "CREATE TABLE IF NOT EXISTS test_items ("
        " id VARCHAR(128) NOT NULL,"
        " title_or_name VARCHAR(512) NOT NULL DEFAULT '',"
        " file VARCHAR(512) NULL,"
        " keywords TEXT NULL,"
        " text LONGTEXT NULL,"
        " scope VARCHAR(64) NOT NULL DEFAULT '',"
        " PRIMARY KEY (id),"
        " KEY idx_test_items_scope (scope)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci"
    ),
}


class StoreError(RuntimeError):
    """seekdb 相关的可预期错误；消息为中文，便于直接展示给使用者。"""


def _json_dumps(value: Any) -> str:
    """把 keywords 序列化为 JSON 字符串（统一 UTF-8，不转义中文）。"""
    if value is None:
        return "[]"
    if isinstance(value, str):
        # 已经是 JSON / 逗号串，尽量规整成 JSON 数组
        try:
            parsed = json.loads(value)
            return json.dumps(parsed, ensure_ascii=False)
        except (TypeError, ValueError):
            items = [s.strip() for s in value.split(",") if s.strip()]
            return json.dumps(items, ensure_ascii=False)
    if isinstance(value, (list, tuple, set)):
        return json.dumps([str(v) for v in value], ensure_ascii=False)
    return json.dumps([str(value)], ensure_ascii=False)


def _json_loads(value: Any) -> list[str]:
    """把 keywords 列反序列化为 list[str]（对脏数据容错）。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
        return [str(parsed)]
    except (TypeError, ValueError):
        return [s.strip() for s in text.split(",") if s.strip()]


def infer_scope(file_path: Any) -> str:
    """从文件路径推断 scope（如 demo_project/orders/service.py -> orders）。"""
    if not file_path:
        return ""
    parts = Path(str(file_path)).parts
    for prefix in ("demo_project",):
        if parts and parts[0] == prefix:
            parts = parts[1:]
            break
    return parts[0] if len(parts) > 1 else ""


def _require_id(row: dict, label: str) -> str:
    rid = str(row.get("id") or "").strip()
    if not rid:
        raise StoreError(f"{label}条目缺少必填字段 id：{row!r}")
    return rid


class SeekDBStore:
    """seekdb（MySQL 协议）存取封装。"""

    def __init__(self, config: Config | None = None) -> None:
        self.cfg = config or Config.from_env()

    # ---- 连接 ---------------------------------------------------------------
    def _connect(self, database: str | None):
        """建立连接；失败抛出带中文说明的 StoreError。"""
        try:
            return pymysql.connect(
                host=self.cfg.seekdb_host,
                port=self.cfg.seekdb_port,
                user=self.cfg.seekdb_user,
                password=self.cfg.seekdb_password,
                database=database or None,
                charset="utf8mb4",
                cursorclass=DictCursor,
                connect_timeout=CONNECT_TIMEOUT,
                autocommit=True,
            )
        except (pymysql.MySQLError, OSError) as exc:
            raise StoreError(self._conn_hint(exc)) from exc

    def _conn_hint(self, exc: BaseException) -> str:
        return (
            "无法连接 seekdb（MySQL 协议）："
            f"host={self.cfg.seekdb_host} port={self.cfg.seekdb_port} "
            f"user={self.cfg.seekdb_user} database={self.cfg.seekdb_database}。"
            "请检查：1) seekdb 实例是否已启动并监听该端口；"
            "2) SEEKDB_HOST / SEEKDB_PORT / SEEKDB_USER / SEEKDB_PASSWORD 是否配置正确；"
            "3) 网络与防火墙是否放行。"
            f"原始错误：{exc}"
        )

    def _safe_db_name(self) -> str:
        """校验库名（库名无法参数化，必须白名单校验以防注入）。"""
        name = self.cfg.seekdb_database
        if not _SAFE_IDENT_RE.match(name):
            raise StoreError(
                f"SEEKDB_DATABASE 名称非法（仅允许字母/数字/下划线）：{name!r}"
            )
        return name

    # ---- 建库建表 -----------------------------------------------------------
    def init_schema(self) -> dict[str, int]:
        """幂等建库 + 建表；返回各表当前条目数。"""
        db = self._safe_db_name()

        # 1) 建库（不指定 database 连接，避免库不存在时连接失败）
        conn = self._connect(None)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{db}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
                )
        finally:
            conn.close()

        # 2) 建表
        conn = self._connect(db)
        try:
            with conn.cursor() as cur:
                for table in _TABLES:
                    cur.execute(_DDL[table])
        finally:
            conn.close()

        return self.stats()

    def stats(self) -> dict[str, int]:
        """返回 {table: 条目数}。"""
        conn = self._connect(self._safe_db_name())
        out: dict[str, int] = {}
        try:
            with conn.cursor() as cur:
                for table in _TABLES:
                    # 表名来自固定白名单，非用户输入
                    cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
                    row = cur.fetchone() or {}
                    out[table] = int(row.get("n") or 0)
        finally:
            conn.close()
        return out

    # ---- 写入 ---------------------------------------------------------------
    def _upsert(self, table: str, rows: Iterable[tuple]) -> int:
        rows = [r for r in rows if r]
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {table} (id, title_or_name, file, keywords, text, scope) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE "
            "title_or_name=VALUES(title_or_name), file=VALUES(file), "
            "keywords=VALUES(keywords), text=VALUES(text), scope=VALUES(scope)"
        )
        conn = self._connect(self._safe_db_name())
        try:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
        finally:
            conn.close()
        return len(rows)

    def _norm_spec(self, row: dict) -> tuple:
        return (
            _require_id(row, "规格"),
            str(row.get("title") or row.get("title_or_name") or "").strip(),
            row.get("file"),
            _json_dumps(row.get("keywords")),
            str(row.get("text") or ""),
            str(row.get("scope") or "").strip(),
        )

    def _norm_code(self, row: dict) -> tuple:
        return (
            _require_id(row, "代码"),
            str(row.get("symbol") or row.get("title_or_name") or "").strip(),
            row.get("file"),
            _json_dumps(row.get("keywords")),
            str(row.get("text") or ""),
            str(row.get("scope") or infer_scope(row.get("file"))).strip(),
        )

    def _norm_test(self, row: dict) -> tuple:
        return (
            _require_id(row, "测试"),
            str(row.get("name") or row.get("title_or_name") or "").strip(),
            row.get("file"),
            _json_dumps(row.get("keywords")),
            str(row.get("text") or ""),
            str(row.get("scope") or infer_scope(row.get("file"))).strip(),
        )

    def upsert_specs(self, rows: Iterable[dict]) -> int:
        return self._upsert("spec_items", [self._norm_spec(r) for r in rows or []])

    def upsert_code(self, rows: Iterable[dict]) -> int:
        return self._upsert("code_items", [self._norm_code(r) for r in rows or []])

    def upsert_tests(self, rows: Iterable[dict]) -> int:
        return self._upsert("test_items", [self._norm_test(r) for r in rows or []])

    # ---- 读取 ---------------------------------------------------------------
    @staticmethod
    def _row_to_dict(row: dict) -> dict:
        d = dict(row)
        d["keywords"] = _json_loads(d.get("keywords"))
        d["score"] = int(d.get("score") or 0)
        return d

    def _load(self, table: str) -> list[dict]:
        conn = self._connect(self._safe_db_name())
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, title_or_name, file, keywords, text, scope "
                    f"FROM {table} ORDER BY id"
                )
                return [self._row_to_dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def load_specs(self) -> list[dict]:
        return self._load("spec_items")

    def load_code(self) -> list[dict]:
        return self._load("code_items")

    def load_tests(self) -> list[dict]:
        return self._load("test_items")

    # ---- 检索（关键词命中打分，全参数化）------------------------------------
    @staticmethod
    def _score_expr(keywords: Sequence[str], params: list) -> str:
        """构造打分表达式：标题 4 分 > 关键词 3 分 > 正文 1 分。

        命中的关键词值通过 %s 参数传入，绝不拼进 SQL 文本。
        """
        if not keywords:
            return "0"
        parts: list[str] = []
        for kw in keywords:
            like = f"%{str(kw).lower()}%"
            parts.append(
                "(CASE WHEN LOWER(title_or_name) LIKE %s THEN 4 ELSE 0 END"
                " + CASE WHEN LOWER(keywords) LIKE %s THEN 3 ELSE 0 END"
                " + CASE WHEN LOWER(text) LIKE %s THEN 1 ELSE 0 END)"
            )
            params.extend([like, like, like])
        return " + ".join(parts)

    def _search_table(
        self, table: str, keywords: Sequence[str], limit: int, scope: str | None
    ) -> list[dict]:
        params: list = []
        score_expr = self._score_expr(keywords, params)
        inner = (
            f"SELECT id, title_or_name, file, keywords, text, scope, "
            f"({score_expr}) AS score FROM {table}"
        )
        if scope:
            inner += " WHERE scope = %s"
            params.append(scope)

        sql = f"SELECT * FROM ({inner}) AS scored"
        if keywords:
            sql += " WHERE score > 0"
        sql += " ORDER BY score DESC, id ASC LIMIT %s"
        params.append(int(limit))

        conn = self._connect(self._safe_db_name())
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return [self._row_to_dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def search(
        self, keywords: Sequence[str], limit: int = 10, scope: str | None = None
    ) -> dict[str, list[dict]]:
        """按关键词命中打分检索三类条目，返回带 score 的原始行。"""
        kws = [str(k).strip() for k in (keywords or []) if str(k).strip()]
        return {
            "specs": self._search_table("spec_items", kws, limit, scope),
            "code": self._search_table("code_items", kws, limit, scope),
            "tests": self._search_table("test_items", kws, limit, scope),
        }

    # ---- 从 data/ 导入 ------------------------------------------------------
    @staticmethod
    def _read_json(path: Path, warnings: list[str], label: str) -> list[dict]:
        if not path.is_file():
            warnings.append(f"{label}索引文件不存在，已跳过：{path}")
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (TypeError, ValueError) as exc:
            warnings.append(f"{label}索引文件解析失败（已跳过）：{path}（{exc}）")
            return []
        if isinstance(data, dict):
            # 兼容 {"items": [...]} 形式
            data = data.get("items") or data.get("data") or []
        if not isinstance(data, list):
            warnings.append(f"{label}索引文件格式应为 JSON 数组（已跳过）：{path}")
            return []
        return [r for r in data if isinstance(r, dict)]

    def import_from_json(
        self,
        specs_path: Path | None = None,
        code_path: Path | None = None,
        tests_path: Path | None = None,
    ) -> dict:
        """把 data/ 三份索引导入 seekdb，返回各类条目数与提示信息。"""
        warnings: list[str] = []
        specs = self._read_json(specs_path or self.cfg.specs_json, warnings, "规格")
        code = self._read_json(code_path or self.cfg.code_index_json, warnings, "代码")
        tests = self._read_json(tests_path or self.cfg.tests_index_json, warnings, "测试")
        return {
            "specs": self.upsert_specs(specs),
            "code": self.upsert_code(code),
            "tests": self.upsert_tests(tests),
            "warnings": warnings,
        }