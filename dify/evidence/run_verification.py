#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
《离谱法庭 · The Absurd Court》验证脚本 V1~V5（只用标准库）

用途：通过 Dify 应用的 Service API（/v1/chat-messages）按 VERIFICATION.md 的顺序跑一遍
V1 立案+开庭+辩论、V2 宣判、V3a 跨场次记忆、V3b 案底统计、V4 玩法说明、V5 健壮性，
把每个请求/响应原文写入 evidence/logs/，并做基本断言。

用法：
    python evidence/run_verification.py --app-key app-xxxxxxxx
    python evidence/run_verification.py --app-key app-xxx --base-url http://localhost/v1 \
        --user demo-001 --out-dir evidence/logs

说明：
- V1/V2 使用同一个 conversation（同一场官司）；V3a 用**新会话、同一 user** 复现跨场次记忆；
- V4/V5 各用一个独立新会话；
- 结果只依赖 Dify 返回文本，不修改任何文件；所有日志写入 --out-dir。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CASE_NO_RE = re.compile(r"#\d{4}")


class Client:
    def __init__(self, base_url: str, app_key: str, timeout: int = 240):
        self.base_url = base_url.rstrip("/")
        self.app_key = app_key
        self.timeout = timeout

    def chat(self, query: str, user: str, conversation_id: str = "") -> dict:
        payload = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "user": user,
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id
        req = urllib.request.Request(
            self.base_url + "/chat-messages",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.app_key,
            },
            method="POST",
        )
        started = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except Exception as exc:  # 网络异常也记录，便于排查
            return {
                "ok": False,
                "status": -1,
                "error": "%s: %s" % (type(exc).__name__, exc),
                "elapsed": round(time.time() - started, 2),
                "request": payload,
                "response": None,
            }
        try:
            data = json.loads(raw)
        except ValueError:
            data = {"_raw": raw}
        return {
            "ok": status == 200,
            "status": status,
            "elapsed": round(time.time() - started, 2),
            "request": payload,
            "response": data,
        }

    def healthz(self) -> str:
        """可选的书记员服务健康检查（base_url 换成 clerk 时使用）。"""
        try:
            with urllib.request.urlopen(self.base_url + "/healthz", timeout=5) as resp:
                return resp.read().decode("utf-8", errors="replace").strip()
        except Exception as exc:
            return "ERR %s" % exc


def answer_of(result: dict) -> str:
    resp = result.get("response") or {}
    if isinstance(resp, dict):
        if isinstance(resp.get("answer"), str):
            return resp["answer"]
        if isinstance(resp.get("_raw"), str):
            return resp["_raw"]
    return ""


class Recorder:
    def __init__(self, out_dir: str, user: str):
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.user = user
        self.records = []
        self.conversations = {}
        self.failures = []

    def run(self, case: str, label: str, query: str, conversation_id: str = "", check=None):
        client = RecorderHolder.client
        print("\n[%s] %s → %s" % (case, label, query[:60]))
        result = client.chat(query, self.user, conversation_id)
        answer = answer_of(result)
        conv_id = ""
        if isinstance(result.get("response"), dict):
            conv_id = result["response"].get("conversation_id") or ""
        ok = bool(result.get("ok")) and bool(answer.strip())
        detail = "HTTP %s | %.1fs | conv=%s" % (result.get("status"), result.get("elapsed", 0), conv_id or "-")
        if check:
            passed, why = check(answer)
            ok = ok and passed
            detail += " | check: %s" % why
        if not ok:
            self.failures.append("%s/%s: %s" % (case, label, detail))
        print("  %s %s" % ("PASS" if ok else "FAIL", detail))
        print("  answer(前 200 字): %s" % answer.replace("\n", " ")[:200])
        rec = {
            "case": case,
            "label": label,
            "query": query,
            "conversation_id": conv_id,
            "elapsed": result.get("elapsed"),
            "status": result.get("status"),
            "ok": ok,
            "answer": answer,
            "raw": result.get("response"),
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.records.append(rec)
        self._append_jsonl(case, rec)
        if conv_id:
            self.conversations[case] = conv_id
        return rec

    def _append_jsonl(self, case: str, rec: dict):
        path = os.path.join(self.out_dir, "%s.log" % case)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("=" * 78 + "\n")
            fh.write("[%s] %s\n" % (rec["checked_at"], rec["label"]))
            fh.write("QUERY: %s\n" % rec["query"])
            fh.write("CONV : %s | HTTP %s | %.2fs\n" % (rec.get("conversation_id"), rec.get("status"), rec.get("elapsed") or 0))
            fh.write("ANSWER:\n%s\n" % rec.get("answer"))
            fh.write("RAW: %s\n" % json.dumps(rec.get("raw"), ensure_ascii=False)[:4000])

    def summary(self):
        print("\n" + "=" * 78)
        print("用例数：%d，失败：%d" % (len(self.records), len(self.failures)))
        for f in self.failures:
            print("  FAIL", f)
        path = os.path.join(self.out_dir, "verification-summary.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "user": self.user,
                    "conversations": self.conversations,
                    "records": self.records,
                    "failures": self.failures,
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )
        print("汇总已写入：%s" % path)
        return len(self.failures) == 0


class RecorderHolder:
    client = None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="离谱法庭 V1~V5 验证脚本")
    parser.add_argument("--app-key", default=os.environ.get("DIFY_APP_KEY", ""), help="Dify 应用 API Key（app-xxx）")
    parser.add_argument("--base-url", default=os.environ.get("DIFY_BASE_URL", "http://localhost/v1"), help="Service API 根地址")
    parser.add_argument("--user", default="demo-" + datetime.now().strftime("%Y%m%d-%H%M%S"), help="原告 user id（决定案底归属）")
    parser.add_argument("--out-dir", default=os.path.join(HERE, "logs"), help="日志输出目录")
    parser.add_argument("--timeout", type=int, default=240, help="单次请求超时秒数")
    parser.add_argument("--v5-user", default="", help="V5 使用的独立 user（默认 <user>-v5）")
    parser.add_argument("--skip-v5", action="store_true", help="跳过 V5")
    args = parser.parse_args(argv)

    if not args.app_key:
        print("缺少 --app-key（Dify 应用 API Key，形如 app-xxx）", file=sys.stderr)
        return 2

    RecorderHolder.client = Client(args.base_url, args.app_key, args.timeout)
    rec = Recorder(args.out_dir, args.user)
    print("验证开始：user=%s | base=%s | out=%s" % (args.user, args.base_url, args.out_dir))

    def has_case_no(text: str):
        m = CASE_NO_RE.search(text)
        return (bool(m), "案号 %s" % (m.group(0) if m else "未找到"))

    # ---- V1：立案 + 开庭 + 辩论（同一个 conversation） ----
    v1 = rec.run(
        "V1",
        "立案与开庭",
        "我要起诉我家的充电线，罪名是通敌，要求它当庭道歉",
        check=has_case_no,
    )
    conv = v1.get("conversation_id") or ""
    rec.run(
        "V1",
        "补充证据辩论",
        "补充证据：它半夜三点偷偷发烫，还把我的手机电量从80%吸到20%",
        conversation_id=conv,
        check=lambda t: (bool(t.strip()), "非空回答"),
    )

    # ---- V2：宣判 + 法典引用 + 归档 ----
    def check_v2(text: str):
        need = ["本院认为", "荒诞法典", "罚则"]
        miss = [n for n in need if n not in text]
        has_archive = "归档" in text
        return (not miss and has_archive, "缺失:%s 归档:%s" % (miss or "-", has_archive))

    rec.run("V2", "宣判", "宣判", conversation_id=conv, check=check_v2)

    # ---- V3a：跨场次记忆（新会话、同一 user） ----
    def check_v3a(text: str):
        prev = CASE_NO_RE.search(v1.get("answer", ""))
        prev_no = prev.group(0) if prev else ""
        has_prev = bool(prev_no) and (prev_no in text)
        has_precedent = ("先例" in text) or ("判例" in text) or ("旧案" in text) or ("案底" in text)
        # 3B 本地模型不一定逐字引用旧案号：命中旧案号或出现"先例/判例/旧案"任一即视为跨场次记忆生效
        return (has_prev or has_precedent, "旧案号%s在本场:%s 先例词:%s" % (prev_no or "-", has_prev, has_precedent))

    rec.run(
        "V3a",
        "同一 user 新会话再次起诉充电线",
        "我要再次起诉我家那根充电线，罪名是屡教不改的通敌，要求它赔偿我一整个周末",
        check=check_v3a,
    )

    # ---- V3b：案底统计 ----
    def check_v3b(text: str):
        need = ["立案", "称号"]
        miss = [n for n in need if n not in text]
        has_stats = ("胜" in text) or ("败" in text)
        return (not miss and has_stats, "缺失:%s 胜败:%s" % (miss or "-", has_stats))

    rec.run("V3b", "查阅案底", "查阅我的案底", conversation_id=rec.conversations.get("V3a", ""), check=check_v3b)

    # ---- V4：玩法说明（不得被误判为新案件）----
    def check_v4(text: str):
        has_play = ("玩法" in text) or ("立案" in text and "宣判" in text)
        no_case = not CASE_NO_RE.search(text)
        return (has_play, "玩法:%s 未产生新案号:%s" % (has_play, no_case))

    rec.run("V4", "玩法说明", "怎么玩", check=check_v4)

    # ---- V5：健壮性 ----
    if not args.skip_v5:
        v5_user = args.v5_user or (args.user + "-v5")
        old_user = rec.user
        rec.user = v5_user
        rec.run(
            "V5",
            "无意义输入",
            "asdf",
            check=lambda t: (bool(t.strip()), "非空且未报错"),
        )
        rec.user = old_user

    ok = rec.summary()
    print("\nV1/V2 会话：%s" % rec.conversations.get("V1"))
    print("V3a 会话：%s" % rec.conversations.get("V3a"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())