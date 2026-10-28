"""上下文选择：把任务文本映射为 specs / code / tests 检索结果并组装。

打分策略（在 store 的 SQL 关键词命中分基础上叠加）：
    1. 关键词命中分：由 store.search 在 SQL 中计算（标题 4 / 关键词 3 / 正文 1）；
    2. 同 scope 加成：命中规格的主导 scope 与条目 scope 一致时 +2，做结构化过滤；
    3. 稳定排序：分数降序、id 升序，保证同一输入可复现。

输出每一项都带 source（形如 data/specs.json#SPEC-ORD-3），可直接对照 data/ 核对该条目来源。
结果完全来自 store 的查询——修改 data/specs.json 后重新 init + build，输出随之变化，
代码内不写死任何答案。
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from .store import SeekDBStore

# 各类型条目对应的来源文件（source 的前半部分）
SOURCE_FILES: dict[str, str] = {
    "specs": "data/specs.json",
    "code": "data/code_index.json",
    "tests": "data/tests_index.json",
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")

# 命中检索时给每类预留的候选倍率（最终还会裁剪到 top_k）
_CANDIDATE_FACTOR = 4

SCOPE_BONUS = 2


def extract_keywords(task: str, max_terms: int = 24) -> list[str]:
    """从任务描述中提取检索关键词（英文 token + 中文片段滑窗）。"""
    text = task or ""
    terms: list[str] = []

    for token in _TOKEN_RE.findall(text):
        terms.append(token.lower())

    for seg in _CJK_RE.findall(text):
        if len(seg) <= 3:
            terms.append(seg)
        else:
            # 2 字滑窗覆盖“状态/筛选”这类关键词，同时保留整段以命中长词
            for i in range(len(seg) - 1):
                terms.append(seg[i : i + 2])
            terms.append(seg)

    seen: set[str] = set()
    out: list[str] = []
    for term in terms:
        term = term.strip()
        if term and term not in seen:
            seen.add(term)
            out.append(term)
    return out[:max_terms]


def _dedup(rows: Sequence[dict]) -> list[dict]:
    """同一 id 只保留得分最高的一行。"""
    best: dict[str, dict] = {}
    for row in rows:
        rid = str(row.get("id"))
        if rid not in best or int(row.get("score") or 0) > int(best[rid].get("score") or 0):
            best[rid] = row
    return list(best.values())


def _rank(rows: Sequence[dict], main_scope: str | None, top_k: int) -> list[dict]:
    """叠加 scope 加成并稳定排序，取前 top_k。"""
    scored: list[dict] = []
    for row in rows:
        item = dict(row)
        bonus = 0
        if main_scope and str(item.get("scope") or "") == main_scope:
            bonus = SCOPE_BONUS
        item["score"] = int(item.get("score") or 0) + bonus
        scored.append(item)
    scored.sort(key=lambda r: (-int(r.get("score") or 0), str(r.get("id"))))
    return scored[:top_k]


def _source(kind: str, item_id: Any) -> str:
    return f"{SOURCE_FILES[kind]}#{item_id}"


def _pick_main_scope(
    spec_rows: Sequence[dict], explicit: str | None
) -> str | None:
    """主导 scope：优先用显式指定，否则取命中规格中分数最高条目的 scope。"""
    if explicit:
        return explicit
    ranked = sorted(spec_rows, key=lambda r: (-int(r.get("score") or 0), str(r.get("id"))))
    for row in ranked:
        scope = str(row.get("scope") or "").strip()
        if scope:
            return scope
    return None


def build_context(
    task: str,
    store: SeekDBStore | None = None,
    top_k: int = 5,
    scope: str | None = None,
    progress: dict | None = None,
) -> dict:
    """检索并组装上下文。

    返回结构（DESIGN §4）::

        {
          "task": "...",
          "specs": [{"id","title","source","score"}],
          "code":  [{"id","file","symbol","source","score"}],
          "tests": [{"id","file","name","source","score"}],
          "progress": {"done":[],"todo":[],"evidence":{}}
        }
    """
    store = store or SeekDBStore()
    keywords = extract_keywords(task)
    raw = store.search(keywords, limit=max(top_k * _CANDIDATE_FACTOR, 12))

    spec_rows = _dedup(raw.get("specs", []))
    code_rows = _dedup(raw.get("code", []))
    test_rows = _dedup(raw.get("tests", []))

    main_scope = _pick_main_scope(spec_rows, scope)

    specs = [
        {
            "id": row.get("id"),
            "title": row.get("title_or_name"),
            "scope": row.get("scope"),
            "source": _source("specs", row.get("id")),
            "score": int(row.get("score") or 0),
        }
        for row in _rank(spec_rows, main_scope, top_k)
    ]
    code = [
        {
            "id": row.get("id"),
            "file": row.get("file"),
            "symbol": row.get("title_or_name"),
            "source": _source("code", row.get("id")),
            "score": int(row.get("score") or 0),
        }
        for row in _rank(code_rows, main_scope, top_k)
    ]
    tests = [
        {
            "id": row.get("id"),
            "file": row.get("file"),
            "name": row.get("title_or_name"),
            "source": _source("tests", row.get("id")),
            "score": int(row.get("score") or 0),
        }
        for row in _rank(test_rows, main_scope, top_k)
    ]

    return {
        "task": task,
        "scope": main_scope,
        "keywords": keywords,
        "specs": specs,
        "code": code,
        "tests": tests,
        "progress": progress if progress is not None else {"done": [], "todo": [], "evidence": {}},
    }