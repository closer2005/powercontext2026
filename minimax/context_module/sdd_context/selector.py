"""Context selection: from one development task to a validated context pack.

Selection is query driven: specifications come from seekdb by spec id plus a
keyword search, code units by task hints plus keyword search, and tests from the
task's declared target/regression files. The output records every source with a
real path and line range so the graders can verify it exists.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .store import SeekDBStore


def load_task(project_root: Path) -> dict[str, Any]:
    path = project_root / "task.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"task file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("task.yaml must contain a mapping")
    return data


def _row_to_spec(row: dict[str, Any], why: str) -> dict[str, Any]:
    return {
        "spec_id": row["spec_id"],
        "revision": row["revision"],
        "path": row["path"],
        "anchor": row["anchor"],
        "title": row["title"],
        "status": row["status"],
        "digest": row["digest"],
        "content": row["content"],
        "why": why,
    }


def _row_to_code(row: dict[str, Any], why: str, score: float | int | None = None) -> dict[str, Any]:
    return {
        "path": row["path"],
        "symbol": row["symbol"],
        "anchor": row["anchor"],
        "line_start": row["line_start"],
        "line_end": row["line_end"],
        "digest": row["digest"],
        "content": row["content"],
        "why": why,
        "score": score,
    }


def _row_to_test(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": row["path"],
        "symbol": row["symbol"],
        "anchor": row["anchor"],
        "line_start": row["line_start"],
        "line_end": row["line_end"],
        "digest": row["digest"],
        "content": row["content"],
    }


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        key = row["mat_id"]
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _tests_for_files(store: SeekDBStore, files: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for relative in files:
        rows.extend(store.get_materials(kind="test", path=relative))
    return _dedupe(rows)


def select_specs(store: SeekDBStore, task: dict[str, Any], description: str, limit: int = 8) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for spec_id in task.get("specs") or []:
        rows = store.search(kind="spec", query=description, limit=limit, status="active", spec_id=spec_id)
        if not rows:
            rows = store.query(
                "SELECT mat_id, kind, path, anchor, symbol, spec_id, revision, status, title, content, "
                "line_start, line_end, digest, 0 AS score FROM sdd_materials "
                "WHERE kind = 'spec' AND spec_id = %s AND status = 'active' ORDER BY revision DESC LIMIT %s",
                (spec_id, limit), note=f"active spec lookup {spec_id}",
            )
        for row in rows:
            selected.append(_row_to_spec(row, f"task 声明规格 {spec_id}；关键词检索命中"))
    # Additional specs that the task did not name but keywords point at.
    for row in store.search(kind="spec", query=description, limit=limit, status="active"):
        selected.append(_row_to_spec(row, "按任务关键词检索到的有效规格"))
    deduped: dict[str, dict[str, Any]] = {}
    for item in selected:
        deduped.setdefault(item["anchor"], item)
    return list(deduped.values())


def select_code(store: SeekDBStore, task: dict[str, Any], description: str, limit: int = 10) -> list[dict[str, Any]]:
    hints = task.get("hints") or {}
    selected: list[dict[str, Any]] = []
    symbols = list(hints.get("symbols") or [])
    paths = list(hints.get("paths") or [])

    if symbols:
        for row in store.get_materials(kind="code", symbols=symbols):
            selected.append(_row_to_code(row, "任务提示符号命中", None))
    for path in paths:
        for row in store.get_materials(kind="code", path=path):
            selected.append(_row_to_code(row, "任务提示文件命中", None))
    for row in store.search(kind="code", query=description, limit=limit):
        selected.append(_row_to_code(row, "按任务关键词检索命中", row.get("score")))

    deduped: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in selected:
        if item["anchor"] not in deduped:
            deduped[item["anchor"]] = item
            order.append(item["anchor"])
    result = [deduped[key] for key in order]
    # Keep hint-declared units first, then keyword hits up to the limit.
    prioritized = [item for item in result if item["why"].startswith("任务提示")] + [
        item for item in result if not item["why"].startswith("任务提示")
    ]
    return prioritized[:limit]


def build_context(
    store: SeekDBStore,
    project_root: Path,
    task: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    limits = limits or {}
    description = f"{task.get('title', '')} {task.get('description', '')}".strip()
    specs = select_specs(store, task, description, limit=limits.get("specs", 8))
    code = select_code(store, task, description, limit=limits.get("code", 14))
    target_tests = _tests_for_files(store, list(task.get("target_tests") or []))
    regression_tests = _tests_for_files(store, list(task.get("regression_tests") or []))

    material_digests = sorted(
        [item["digest"] for item in specs] + [item["digest"] for item in code]
        + [item["digest"] for item in target_tests] + [item["digest"] for item in regression_tests]
    )
    digest = hashlib.sha256("|".join(material_digests).encode("utf-8")).hexdigest()
    context = {
        "task": task,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "context_digest": digest,
        "specs": specs,
        "code": code,
        "tests": {
            "target": [_row_to_test(row) for row in target_tests],
            "regression": [_row_to_test(row) for row in regression_tests],
        },
        "state": state or {},
        "queries": store.query_log.summary(),
        "counts": {
            "specs": len(specs),
            "code": len(code),
            "target_tests": len(target_tests),
            "regression_tests": len(regression_tests),
        },
    }
    return context


def validate_context(context: dict[str, Any], project_root: Path) -> list[str]:
    """Return human readable problems; an empty list means every source exists."""
    problems: list[str] = []
    if not context.get("specs"):
        problems.append("context contains no specification")
    if not context.get("code"):
        problems.append("context contains no code unit")
    if not context.get("tests", {}).get("target"):
        problems.append("context contains no target test")
    if not context.get("tests", {}).get("regression"):
        problems.append("context contains no regression test")

    def check_source(entry: dict[str, Any], label: str) -> None:
        path = project_root / entry["path"]
        if not path.is_file():
            problems.append(f"{label}: missing file {entry['path']}")
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        start = entry.get("line_start")
        end = entry.get("line_end")
        if start is None or end is None:
            problems.append(f"{label}: missing line range for {entry['path']}")
            return
        if start < 1 or end > len(lines) or start > end:
            problems.append(f"{label}: line range {start}-{end} outside {entry['path']} ({len(lines)} lines)")
            return
        excerpt = "\n".join(lines[start - 1 : end])
        content = entry.get("content") or ""
        if label in ("code", "test") and content and content.strip() not in excerpt and excerpt.strip() not in content:
            problems.append(f"{label}: content mismatch for {entry['path']}:{start}-{end}")

    for spec in context.get("specs", []):
        path = project_root / spec["path"]
        if not path.is_file():
            problems.append(f"spec: missing file {spec['path']}")
            continue
        if spec.get("content") and spec["content"].strip() not in path.read_text(encoding="utf-8"):
            problems.append(f"spec: stored content is stale for {spec['path']} (re-import needed)")
    for unit in context.get("code", []):
        check_source(unit, "code")
    for test in context.get("tests", {}).get("target", []):
        check_source(test, "test")
    for test in context.get("tests", {}).get("regression", []):
        check_source(test, "test")
    return problems


def render_markdown(context: dict[str, Any]) -> str:
    task = context.get("task", {})
    lines = [
        f"# 开发上下文 · {task.get('task_id', '')}",
        "",
        f"- 标题：{task.get('title', '')}",
        f"- 描述：{task.get('description', '')}",
        f"- 上下文摘要：`{context.get('context_digest', '')}`",
        f"- 生成时间：{context.get('generated_at', '')}",
        "",
        "## 适用规格",
        "",
    ]
    for spec in context.get("specs", []):
        lines.append(f"### {spec['spec_id']} revision {spec['revision']} · {spec['path']}")
        lines.append(f"- 锚点：`{spec['anchor']}`")
        lines.append(f"- 选择原因：{spec['why']}")
        body = (spec.get("content") or "").strip().splitlines()
        lines.append("")
        lines.extend(body[:40])
        lines.append("")
    lines.append("## 需要修改的代码")
    lines.append("")
    for unit in context.get("code", []):
        lines.append(f"### {unit['path']}::{unit['symbol']}  ({unit['line_start']}-{unit['line_end']})")
        lines.append(f"- 选择原因：{unit['why']}")
        lines.append("```python")
        lines.extend((unit.get("content") or "").rstrip().splitlines())
        lines.append("```")
        lines.append("")
    lines.append("## 验证测试")
    lines.append("")
    lines.append("### 目标测试（改前失败，改后必须通过）")
    for test in context.get("tests", {}).get("target", []):
        lines.append(f"- `{test['path']}::{test['symbol']}`")
    lines.append("")
    lines.append("### 回归测试（改前改后都必须通过）")
    for test in context.get("tests", {}).get("regression", []):
        lines.append(f"- `{test['path']}::{test['symbol']}`")
    lines.append("")
    lines.append("## 任务状态（PowerContext）")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(context.get("state") or {}, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## 数据库查询记录（seekdb）")
    lines.append("")
    for item in context.get("queries", []):
        lines.append(f"- rows={item['rows']} · {item['note']} · `{item['sql'][:160]}`")
    return "\n".join(lines) + "\n"