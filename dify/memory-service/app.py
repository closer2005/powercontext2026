#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离谱法庭 · 书记员服务（The Absurd Court · Clerk Service）

纯标准库 http.server + PyMySQL 实现的 HTTP 服务，供 Dify Chatflow 的 HTTP Request 节点调用。
所有接口一律返回 text/plain 文本（Dify 直接取 response.body 文本，避免 JSON 解析兼容问题）。

接口（DESIGN §5）：
    POST /api/cases           立案，返回 "案号：#0042"
    POST /api/cases/verdict   归档判决，返回 "⚖️ 已归档：案卷 #0042 · 判决：罪名成立"
    POST /api/cases/search    先例检索，返回多行文本（无先例时返回固定提示）
    POST /api/stats           原告案底统计，返回多行文本
    GET  /healthz             健康检查，返回 "ok"

环境变量见 config.example.env；也支持同目录 config.env（优先级：环境变量 > config.env）。
启动：python app.py             （初始化建库建表：python app.py --init-db）
"""

import json
import os
import re
import socket
import sys
import threading
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import pymysql
    from pymysql.constants import CLIENT
except ImportError:  # pragma: no cover - 给使用者一个清晰提示
    sys.stderr.write(
        "[离谱法庭] 缺少依赖 PyMySQL，请先执行：pip install -r requirements.txt\n"
    )
    raise

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


def _load_config_env():
    """读取同目录 config.env（若存在），返回 dict；不覆盖已存在的环境变量。"""
    path = os.path.join(BASE_DIR, "config.env")
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            values[key] = val
    return values


_FILE_CFG = _load_config_env()


def cfg(name, default=""):
    if name in os.environ and os.environ[name] != "":
        return os.environ[name]
    return _FILE_CFG.get(name, default)


DB_HOST = cfg("DB_HOST", "127.0.0.1")
DB_PORT = int(cfg("DB_PORT", "2881"))
DB_USER = cfg("DB_USER", "root")
DB_PASSWORD = cfg("DB_PASSWORD", "")
DB_NAME = cfg("DB_NAME", "absurd_court")
HOST = cfg("HOST", "0.0.0.0")
PORT = int(cfg("PORT", "8899"))
LOG_FILE = cfg("LOG_FILE", "")

_LOCK = threading.Lock()


def log(msg):
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:
        pass
    if LOG_FILE:
        try:
            with _LOCK:
                with open(LOG_FILE, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------


def connect(with_db=True):
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME if with_db else None,
        charset="utf8mb4",
        autocommit=False,
        connect_timeout=5,
        read_timeout=15,
        write_timeout=15,
    )


def init_db():
    """执行 schema.sql（支持多语句）。返回语句数量，失败抛异常。"""
    schema_path = os.path.join(BASE_DIR, "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as fh:
        sql = fh.read()
    conn = connect(with_db=False)
    try:
        conn.client_flag |= CLIENT.MULTI_STATEMENTS
        with conn.cursor() as cur:
            cur.execute(sql)
            while cur.nextset():
                pass
        conn.commit()
        return len([s for s in sql.split(";") if s.strip()])
    finally:
        conn.close()


def fmt_case_no(case_id):
    return "#%04d" % int(case_id)


def normalize_case_no(raw):
    """把 '#0042' / '0042' / '42' / '案卷 #0042' 统一成 '#0042'。"""
    text = str(raw or "").strip()
    m = re.search(r"(\d{1,12})", text)
    if not m:
        return ""
    return "#" + m.group(1).zfill(4)


def _keywords(q):
    """把 "充电线 通敌" 切成关键词列表；中文没有空格时整串作为一个词。"""
    text = str(q or "").replace("｜", " ").replace("|", " ").replace("，", " ")
    parts = [p.strip() for p in re.split(r"[\s,;、]+", text) if p.strip()]
    seen, out = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:6]


# ---------------------------------------------------------------------------
# 业务逻辑（每个函数返回纯文本）
# ---------------------------------------------------------------------------

VERDICT_WIN = "罪名成立"
VERDICT_LOSE = "罪名不成立"

TITLE_RULES = [  # (最少案件数, 称号)
    (10, "让法官都害怕的原告"),
    (6, "无理取闹大师"),
    (3, "法庭常客"),
    (1, "偶尔较真的市民"),
    (0, "法庭新鲜人"),
]


def create_case(payload):
    """立案：写入 cases（status=open），返回 '案号：#0042'。"""
    plaintiff = str(payload.get("plaintiff") or "").strip()[:64] or "匿名原告"
    defendant = str(payload.get("defendant") or "").strip()[:128] or "某个说不清的东西"
    charge = str(payload.get("charge") or "").strip()[:255] or "非法存在"
    claim = str(payload.get("claim") or "").strip()[:500] or "要求被告当庭道歉"
    evidence = str(payload.get("evidence") or "").strip()

    conn = connect()
    try:
        with conn.cursor() as cur:
            tmp_no = "TMP-%d-%d" % (os.getpid(), datetime.now().microsecond)
            cur.execute(
                "INSERT INTO cases (case_no, plaintiff, defendant, charge, claim, evidence, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'open')",
                (tmp_no, plaintiff, defendant, charge, claim, evidence),
            )
            case_id = cur.lastrowid
            case_no = fmt_case_no(case_id)
            cur.execute("UPDATE cases SET case_no=%s WHERE id=%s", (case_no, case_id))
        conn.commit()
        return case_no
    finally:
        conn.close()


def archive_verdict(payload):
    """归档判决：按案号更新 status=closed，返回归档回执。"""
    case_no = normalize_case_no(payload.get("case_no"))
    verdict = str(payload.get("verdict") or "").strip()[:32] or "悬而未决"
    penalty = str(payload.get("penalty") or "").strip()[:500]
    judgment = str(payload.get("judgment") or "").strip()
    if not case_no:
        return "⚠️ 归档失败：缺少案号，本院无从落卷。"

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE cases SET verdict=%s, penalty=%s, judgment=%s, status='closed' "
                "WHERE case_no=%s",
                (verdict, penalty, judgment, case_no),
            )
            affected = cur.rowcount
            if affected == 0:
                conn.rollback()
                return "⚠️ 归档失败：未找到案卷 %s，请先立案。" % case_no
            cur.execute("SELECT COUNT(*) FROM cases WHERE status='closed'")
            closed_total = cur.fetchone()[0]
        conn.commit()
        return "⚖️ 已归档：案卷 %s · 判决：%s（本院累计已结 %d 案）" % (
            case_no,
            verdict,
            closed_total,
        )
    finally:
        conn.close()


def _precedent_line(row, own):
    case_no, defendant, charge, verdict, penalty = row
    line = "- %s｜被告：%s｜罪名：%s｜判决：%s｜罚则：%s" % (
        case_no,
        defendant,
        charge,
        verdict or "未宣判",
        penalty or "—",
    )
    if own:
        line += "｜★原告旧案"
    return line


def search_precedent(payload):
    """先例检索：先查原告自己的旧案（记仇），再查全库关键词匹配；返回多行文本。"""
    plaintiff = str(payload.get("plaintiff") or "").strip()[:64]
    q = str(payload.get("q") or "")
    try:
        limit = int(payload.get("limit") or 3)
    except (TypeError, ValueError):
        limit = 3
    limit = max(1, min(limit, 5))

    keywords = _keywords(q)
    patterns = ["%" + k + "%" for k in keywords] or ["%%"]

    def like_clause(column):
        # 注意：这里返回的是带 %s 占位符的 SQL 片段，不能再用 % 运算符拼接整条 SQL，
        # 因此下面的语句全部用字符串相加构建，参数单独绑定。
        return " OR ".join([column + " LIKE %s"] * len(patterns))

    rows, own_ids = [], set()
    conn = connect()
    try:
        with conn.cursor() as cur:
            sql_own = (
                "SELECT case_no, defendant, charge, verdict, penalty FROM cases "
                "WHERE plaintiff=%s AND status='closed' AND ("
                + like_clause("defendant")
                + " OR "
                + like_clause("charge")
                + ") ORDER BY id DESC LIMIT "
                + str(limit)
            )
            params = [plaintiff] + patterns + patterns
            cur.execute(sql_own, params)
            for row in cur.fetchall():
                rows.append(row)
                own_ids.add(row[0])

            remain = limit - len(rows)
            if remain > 0:
                sql_global = (
                    "SELECT case_no, defendant, charge, verdict, penalty FROM cases "
                    "WHERE status='closed' AND ("
                    + like_clause("defendant")
                    + " OR "
                    + like_clause("charge")
                    + ") ORDER BY id DESC LIMIT "
                    + str(remain * 3)
                )
                cur.execute(sql_global, patterns + patterns)
                for row in cur.fetchall():
                    if row[0] in own_ids:
                        continue
                    rows.append(row)
                    if len(rows) >= limit:
                        break
    finally:
        conn.close()

    if not rows:
        return "【先例】首次出现的被告类型，无历史判例。"
    lines = ["【先例】"]
    for row in rows[:limit]:
        lines.append(_precedent_line(row, own=row[0] in own_ids))
    return "\n".join(lines)


def pick_title(total, won, lost):
    """称号规则（DESIGN §5）；特例优先。"""
    if total >= 3 and won == 0 and lost >= 1:
        return "屡战屡败的执着原告"
    for threshold, title in TITLE_RULES:
        if total >= threshold:
            return title
    return "法庭新鲜人"


def stats(payload):
    """案底统计：立案数 / 胜败 / 称号 / 最近案号 / 高频被告。"""
    plaintiff = str(payload.get("plaintiff") or "").strip()[:64]
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM cases WHERE plaintiff=%s", (plaintiff,))
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT verdict, COUNT(*) FROM cases WHERE plaintiff=%s AND status='closed' "
                "GROUP BY verdict",
                (plaintiff,),
            )
            verdicts = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute(
                "SELECT COUNT(*) FROM cases WHERE plaintiff=%s AND status='open'", (plaintiff,)
            )
            open_count = cur.fetchone()[0]
            cur.execute(
                "SELECT case_no, defendant FROM cases WHERE plaintiff=%s ORDER BY id DESC LIMIT 1",
                (plaintiff,),
            )
            last = cur.fetchone()
            cur.execute(
                "SELECT defendant, COUNT(*) AS c FROM cases WHERE plaintiff=%s "
                "GROUP BY defendant ORDER BY c DESC, MAX(id) DESC LIMIT 3",
                (plaintiff,),
            )
            hot = cur.fetchall()
    finally:
        conn.close()

    won = verdicts.get(VERDICT_WIN, 0)
    lost = verdicts.get(VERDICT_LOSE, 0)
    other = sum(v for k, v in verdicts.items() if k not in (VERDICT_WIN, VERDICT_LOSE))
    title = pick_title(total, won, lost)

    lines = [
        "📜 本院案底档案 · 原告：%s" % (plaintiff or "匿名原告"),
        "立案总数：%d ｜ 已结案：%d ｜ 在审：%d" % (total, won + lost + other, open_count),
        "战绩：胜诉（罪名成立）%d ｜ 败诉（罪名不成立）%d%s"
        % (won, lost, (" ｜ 其他：%d" % other) if other else ""),
        "称号：%s" % title,
    ]
    if last:
        lines.append("最近案号：%s（被告：%s）" % (last[0], last[1]))
    else:
        lines.append("最近案号：暂无（你还没在本院开过庭）")
    if hot:
        lines.append("高频被告：" + " ｜ ".join("%s ×%d" % (name, cnt) for name, cnt in hot))
    else:
        lines.append("高频被告：暂无")
    if open_count:
        lines.append("提示：还有 %d 场官司在审，输入「宣判」即可结案。" % open_count)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP 层
# ---------------------------------------------------------------------------

ROUTES = {
    "/api/cases": ("POST", create_case),
    "/api/cases/verdict": ("POST", archive_verdict),
    "/api/cases/search": ("POST", search_precedent),
    "/api/stats": ("POST", stats),
}


class ClerkHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AbsurdCourtClerk/" + APP_VERSION

    # ---- helpers -----------------------------------------------------
    def _send_text(self, text, status=200):
        body = (text or "").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
            return data if isinstance(data, dict) else {}
        except (ValueError, TypeError):
            return {}

    # ---- verbs -------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path in ("/healthz", "/api/healthz", "/"):
            try:
                connect().close()
                self._send_text("ok")
            except Exception as exc:  # 数据库不可用时也能说明情况
                self._send_text("degraded: %s" % exc, status=503)
            return
        self._send_text("404 这里是法庭，不办这个业务。", status=404)

    def do_HEAD(self):  # noqa: N802
        self.do_GET()

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        route = ROUTES.get(path)
        if not route:
            self._send_text("404 这里是法庭，不办这个业务。", status=404)
            return
        _method, handler = route
        payload = self._read_json()
        try:
            result = handler(payload)
            log("POST %s -> 200 %s" % (path, (result or "").replace("\n", " / ")[:160]))
            self._send_text(result)
        except Exception as exc:  # 业务异常也返回 200 文本，保证 Chatflow 不中断
            detail = "%s: %s" % (type(exc).__name__, exc)
            log("POST %s -> ERROR %s\n%s" % (path, detail, traceback.format_exc()))
            self._send_text(
                "【书记员系统提示】案卷库暂时忙不过来（%s），请稍等片刻再试。" % detail
            )

    def log_message(self, fmt, *args):  # 覆盖默认 stderr 访问日志，统一走 log()
        log("HTTP %s - %s" % (self.address_string(), fmt % args))

    def log_error(self, fmt, *args):
        # Dify 的 HTTP 节点使用 keep-alive，空闲连接超时是正常现象，不记为错误
        msg = fmt % args
        if "timed out" in msg or "TimeoutError" in msg:
            return
        log("HTTP %s - ERROR %s" % (self.address_string(), msg))


def main(argv):
    if "--init-db" in argv:
        try:
            count = init_db()
            log("初始化完成：已执行 schema.sql（%d 条语句），库 %s" % (count, DB_NAME))
        except Exception as exc:
            log("初始化失败：%s\n%s" % (exc, traceback.format_exc()))
            return 1
        if "--only-init" in argv:
            return 0
        return 0

    try:
        conn = connect()
        conn.close()
        log("seekdb 连接正常：%s@%s:%s/%s" % (DB_USER, DB_HOST, DB_PORT, DB_NAME))
    except Exception as exc:
        log("⚠️ seekdb 连接失败（服务仍会启动，请求时会重试）：%s" % exc)

    server = ThreadingHTTPServer((HOST, PORT), ClerkHandler)
    server.daemon_threads = True
    log("离谱法庭书记员服务已开庭：http://%s:%s  （版本 %s）" % (HOST, PORT, APP_VERSION))
    log("接口：POST /api/cases | POST /api/cases/verdict | POST /api/cases/search | "
        "POST /api/stats | GET /healthz")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("书记员下班，法庭休庭。")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    try:  # Windows 控制台默认 GBK，emoji 会炸，统一切 UTF-8
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        socket.setdefaulttimeout(20)
    except Exception:
        pass
    sys.exit(main(sys.argv[1:]))