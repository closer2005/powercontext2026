"""seekdb storage for engineering materials.

The module starts an embedded seekdb instance through ``pylibseekdb.aopen``
(returns MySQL connection options), then talks plain SQL over ``pymysql``.

Every statement executed for task context building is recorded so the
deliverable can show that database results - not hard-coded answers - drive the
context (see ``evidence/db-queries.log``).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .materials import Material, tokenize

TABLE = "sdd_materials"
IMPORTS_TABLE = "sdd_import_runs"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
  mat_id VARCHAR(191) NOT NULL,
  kind VARCHAR(16) NOT NULL,
  path VARCHAR(255) NOT NULL,
  anchor VARCHAR(255) NOT NULL,
  symbol VARCHAR(191) NULL,
  spec_id VARCHAR(64) NULL,
  revision INT NULL,
  status VARCHAR(16) NOT NULL,
  title VARCHAR(255) NOT NULL,
  content MEDIUMTEXT NOT NULL,
  tokenized MEDIUMTEXT NOT NULL,
  tags VARCHAR(512) NULL,
  line_start INT NULL,
  line_end INT NULL,
  digest VARCHAR(64) NOT NULL,
  updated_at VARCHAR(32) NOT NULL,
  PRIMARY KEY (mat_id),
  KEY idx_kind_status (kind, status),
  KEY idx_spec (spec_id, revision)
) DEFAULT CHARSET = utf8mb4
"""

IMPORTS_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {IMPORTS_TABLE} (
  run_id VARCHAR(64) NOT NULL,
  imported_at VARCHAR(32) NOT NULL,
  spec_count INT NOT NULL,
  code_count INT NOT NULL,
  test_count INT NOT NULL,
  note VARCHAR(512) NULL,
  PRIMARY KEY (run_id)
) DEFAULT CHARSET = utf8mb4
"""

_COLUMNS = (
    "mat_id", "kind", "path", "anchor", "symbol", "spec_id", "revision",
    "status", "title", "content", "tokenized", "tags", "line_start", "line_end",
    "digest", "updated_at",
)


class SeekDBError(RuntimeError):
    pass


class QueryLog:
    """Records executed statements for audit/evidence purposes."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.entries: list[dict[str, Any]] = []

    def record(self, sql: str, params: Any, rows: int, duration_ms: int, note: str = "") -> None:
        self.entries.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "sql": " ".join(sql.split()),
                "params": _jsonable(params),
                "rows": rows,
                "duration_ms": duration_ms,
                "note": note,
            }
        )

    def flush(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as handle:
            for entry in self.entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def summary(self) -> list[dict[str, Any]]:
        return [{"sql": item["sql"], "rows": item["rows"], "note": item["note"]} for item in self.entries]


def _jsonable(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class SeekDBStore:
    """Embedded or server-mode seekdb instance plus the material schema.

    ``mode="embedded"`` starts a local seekdb through ``pylibseekdb`` (default
    for a clean Linux reviewer environment); ``mode="server"`` connects to an
    already running seekdb/OceanBase over MySQL for development environments
    where the embedded wheel is unavailable (e.g. Windows or WSL without the
    wheel installed yet).
    """

    def __init__(
        self,
        db_path: Path,
        *,
        mode: str = "embedded",
        server: dict[str, Any] | None = None,
        database: str = "sdd",
        log_path: Path | None = None,
        echo: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.mode = mode.strip().lower()
        self.server = dict(server or {})
        self.database = database
        self.echo = echo
        self.query_log = QueryLog(log_path)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._instance: Any = None
        self._connection: Any = None
        self._fulltext: bool | None = None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> "SeekDBStore":
        import pymysql

        if self.mode == "server":
            connect_kwargs = {
                "host": str(self.server.get("host", "127.0.0.1")),
                "port": int(self.server.get("port", 2881)),
                "user": str(self.server.get("user", "root")),
                "password": str(self.server.get("password") or "") or None,
                "charset": "utf8mb4",
                "autocommit": True,
                "connect_timeout": 10,
            }
            if self.server.get("unix_socket"):
                connect_kwargs["unix_socket"] = str(self.server["unix_socket"])
            self._connection = pymysql.connect(**connect_kwargs)
        else:
            import pylibseekdb

            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            open_fn = getattr(pylibseekdb, "aopen", None)
            if open_fn is not None:
                self._loop = asyncio.new_event_loop()
                self._instance = self._loop.run_until_complete(open_fn(str(self.db_path)))
            elif hasattr(pylibseekdb, "open"):
                self._instance = pylibseekdb.open(str(self.db_path))  # type: ignore[attr-defined]
            else:  # pragma: no cover - defensive
                raise SeekDBError("pylibseekdb exposes neither aopen() nor open()")
            options = dict(self._instance.connection_options())
            connect_kwargs = {
                "host": str(options.get("host", "127.0.0.1")),
                "port": int(options.get("port") or 2881),
                "user": str(options.get("user", "root")),
                "password": str(options.get("password") or "") or None,
                "charset": "utf8mb4",
                "autocommit": True,
            }
            if options.get("unix_socket"):
                connect_kwargs["unix_socket"] = str(options["unix_socket"])
            self._connection = pymysql.connect(**connect_kwargs)
        self._select_database()
        return self

    def _select_database(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database}` DEFAULT CHARSET = utf8mb4")
            cursor.execute(f"USE `{self.database}`")

    def close(self) -> None:
        try:
            if self._connection is not None:
                self._connection.close()
        finally:
            self._connection = None
            if self._instance is not None:
                try:
                    self._instance.close()
                finally:
                    self._instance = None
            if self._loop is not None:
                self._loop.close()
                self._loop = None

    def __enter__(self) -> "SeekDBStore":
        return self.open()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # -- SQL helpers -------------------------------------------------------
    def execute(self, sql: str, params: Any = None, *, note: str = "") -> int:
        started = time.time()
        with self._connection.cursor() as cursor:
            rows = cursor.execute(sql, params)
        duration = int((time.time() - started) * 1000)
        self.query_log.record(sql, params, rows, duration, note)
        if self.echo:
            print(f"[seekdb] {sql.split()[0].upper()} rows={rows} {duration}ms {note}")
        return rows

    def query(self, sql: str, params: Any = None, *, note: str = "") -> list[dict[str, Any]]:
        started = time.time()
        with self._connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [item[0] for item in cursor.description or ()]
            rows = cursor.fetchall()
        duration = int((time.time() - started) * 1000)
        self.query_log.record(sql, params, len(rows), duration, note)
        if self.echo:
            print(f"[seekdb] SELECT rows={len(rows)} {duration}ms {note}")
        return [dict(zip(columns, row)) for row in rows]

    # -- schema ------------------------------------------------------------
    def init_schema(self, *, reset: bool = False) -> None:
        if reset:
            self.execute(f"DROP TABLE IF EXISTS {TABLE}", note="reset materials")
            self.execute(f"DROP TABLE IF EXISTS {IMPORTS_TABLE}", note="reset imports")
        self.execute(SCHEMA)
        self.execute(IMPORTS_SCHEMA)
        self._fulltext = None
        self._fulltext = self._try_enable_fulltext()

    def _fulltext_present(self) -> bool:
        try:
            rows = self.query(f"SHOW INDEX FROM {TABLE}", note="inspect indexes")
        except Exception:
            return False
        return any(str(row.get("Index_type") or "").upper() == "FULLTEXT" for row in rows)

    def _try_enable_fulltext(self) -> bool:
        # Idempotent: a second init_schema() must not downgrade a live index to
        # "absent" just because MySQL reports the duplicate index name.
        if self._fulltext_present():
            return True
        # The default ``space`` parser drops CJK bigrams (min token size 3), so
        # the index must be created with min_token_size=2; verified on seekdb
        # v1.4.0.0 (default parser: zero matches for 2-char Chinese terms).
        candidates = [
            f"ALTER TABLE {TABLE} ADD FULLTEXT INDEX ft_{TABLE}_tokenized (tokenized) "
            f"WITH PARSER space PARSER_PROPERTIES=(min_token_size=2,max_token_size=84)",
            f"ALTER TABLE {TABLE} ADD FULLTEXT INDEX ft_{TABLE}_tokenized (tokenized)",
            f"CREATE FULLTEXT INDEX ft_{TABLE}_tokenized ON {TABLE} (tokenized) "
            f"WITH PARSER space PARSER_PROPERTIES=(min_token_size=2,max_token_size=84)",
        ]
        for statement in candidates:
            try:
                self.execute(statement, note="enable fulltext index")
                if self._fulltext_present():
                    return True
            except Exception:
                continue
        return self._fulltext_present()

    def fulltext_query_expr(self) -> str:
        return "MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE)"

    def has_fulltext(self) -> bool:
        if not self._fulltext:
            self._fulltext = self._fulltext_present()
        return bool(self._fulltext)

    # -- writes ------------------------------------------------------------
    def upsert_materials(self, materials: Iterable[Material]) -> int:
        rows = []
        now = datetime.now(timezone.utc).isoformat()
        for material in materials:
            payload = asdict(material)
            payload.pop("meta", None)
            payload["updated_at"] = now
            rows.append(tuple(payload[column] for column in _COLUMNS))
        if not rows:
            return 0
        placeholders = ",".join(["%s"] * len(_COLUMNS))
        updates = ",".join(f"{column}=VALUES({column})" for column in _COLUMNS if column != "mat_id")
        sql = f"INSERT INTO {TABLE} ({','.join(_COLUMNS)}) VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}"
        count = 0
        for row in rows:
            count += self.execute(sql, row, note=f"upsert {row[0]}")
        return count

    def delete_materials(self, *, kind: str | None = None, spec_id: str | None = None) -> int:
        clauses, params = [], []
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)
        if spec_id is not None:
            clauses.append("spec_id = %s")
            params.append(spec_id)
        if not clauses:
            raise ValueError("refusing to delete every material without a filter")
        sql = f"DELETE FROM {TABLE} WHERE " + " AND ".join(clauses)
        return self.execute(sql, tuple(params), note=f"delete {kind or ''} {spec_id or ''}".strip())

    def record_import(self, run_id: str, counts: dict[str, int], note: str) -> None:
        self.execute(
            f"INSERT INTO {IMPORTS_TABLE} (run_id, imported_at, spec_count, code_count, test_count, note) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                counts.get("spec", 0),
                counts.get("code", 0),
                counts.get("test", 0),
                note[:500],
            ),
            note="record import run",
        )

    # -- reads -------------------------------------------------------------
    def count(self, kind: str | None = None, status: str | None = None) -> int:
        clauses, params = [], []
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.query(f"SELECT COUNT(*) AS n FROM {TABLE}{where}", tuple(params), note="count materials")
        return int(rows[0]["n"]) if rows else 0

    def spec_versions(self) -> list[dict[str, Any]]:
        return self.query(
            f"SELECT spec_id, revision, status, path, digest FROM {TABLE} WHERE kind = 'spec' "
            "ORDER BY spec_id, revision DESC",
            note="spec revisions",
        )

    def get_by_mat_id(self, mat_id: str) -> dict[str, Any] | None:
        rows = self.query(f"SELECT * FROM {TABLE} WHERE mat_id = %s", (mat_id,), note="get material")
        return rows[0] if rows else None

    def get_materials(self, *, kind: str, path: str | None = None, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        clauses = ["kind = %s"]
        params: list[Any] = [kind]
        if path is not None:
            clauses.append("path = %s")
            params.append(path)
        if symbols:
            placeholders = ",".join(["%s"] * len(symbols))
            clauses.append(f"symbol IN ({placeholders})")
            params.extend(symbols)
        sql = f"SELECT * FROM {TABLE} WHERE " + " AND ".join(clauses) + " ORDER BY path, line_start"
        return self.query(sql, tuple(params), note=f"get {kind}")

    def all_of_kind(self, kind: str, *, status: str | None = None) -> list[dict[str, Any]]:
        sql = f"SELECT * FROM {TABLE} WHERE kind = %s"
        params: list[Any] = [kind]
        if status is not None:
            sql += " AND status = %s"
            params.append(status)
        sql += " ORDER BY path, line_start"
        return self.query(sql, tuple(params), note=f"list {kind}")

    def search(
        self,
        *,
        kind: str,
        query: str,
        limit: int = 8,
        status: str | None = None,
        spec_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Keyword search restricted to one material kind; returns rows with score."""
        terms = [term for term in tokenize(query).split() if term]
        clauses = ["kind = %s"]
        params: list[Any] = [kind]
        if status is not None:
            clauses.append("status = %s")
            params.append(status)
        if spec_id is not None:
            clauses.append("spec_id = %s")
            params.append(spec_id)
        where = " AND ".join(clauses)

        if terms and self._fulltext:
            boolean = " ".join(_boolean_term(term) for term in terms[:40])
            sql = (
                f"SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, "
                f"content, line_start, line_end, digest, "
                f"MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE) AS score "
                f"FROM {TABLE} WHERE {where} AND MATCH(tokenized) AGAINST (%s IN BOOLEAN MODE) "
                f"ORDER BY score DESC, mat_id LIMIT %s"
            )
            rows = self.query(sql, tuple([boolean] + params + [boolean, limit]), note=f"{kind} fulltext search")
            if rows:
                return rows
            # BOOLEAN MODE with bigrams can be too strict; relax to OR terms.
            relaxed = " ".join(_boolean_term(term, required=False) for term in terms[:40])
            rows = self.query(sql, tuple([relaxed] + params + [relaxed, limit]), note=f"{kind} fulltext search (relaxed)")
            return rows

        if terms:
            score_parts = " + ".join(["(CASE WHEN tokenized LIKE %s THEN 1 ELSE 0 END)"] * len(terms[:20]))
            like_params = [f"%{term}%" for term in terms[:20]]
            sql = (
                f"SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, "
                f"content, line_start, line_end, digest, ({score_parts}) AS score "
                f"FROM {TABLE} WHERE {where} HAVING score > 0 ORDER BY score DESC, mat_id LIMIT %s"
            )
            return self.query(
                sql, tuple(like_params + params + [limit]), note=f"{kind} like score search"
            )

        return self.query(
            f"SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, "
            f"line_start, line_end, digest, 0 AS score FROM {TABLE} WHERE {where} "
            f"ORDER BY mat_id LIMIT %s",
            tuple(params + [limit]),
            note=f"{kind} unfiltered listing",
        )


def _boolean_term(term: str, required: bool = True) -> str:
    safe = "".join(ch for ch in term if ch.isalnum() or ch == "_")
    if not safe:
        return ""
    return f"+{safe}" if required else safe


def open_store(
    db_path: Path,
    *,
    reset: bool = False,
    log_path: Path | None = None,
    echo: bool = False,
    mode: str = "embedded",
    server: dict[str, Any] | None = None,
    database: str = "sdd",
) -> SeekDBStore:
    store = SeekDBStore(
        db_path, mode=mode, server=server, database=database, log_path=log_path, echo=echo
    )
    store.open()
    store.init_schema(reset=reset)
    return store