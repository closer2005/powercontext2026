"""MiniMax development run: render context -> ask MiniMax -> apply the patch.

The development record is the evidence the graders check against the committed
diff, so every attempt (prompt, raw response, extracted patch, apply result,
test result) is written to ``dev-records/`` with credentials excluded.

Patch application is done by a small in-process unified-diff applier: model
output is validated by exact context matching instead of relying on
``git apply`` (which is sensitive to line-number/whitespace noise), and the
canonical diff for the record is produced by ``git diff`` after the edit.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .minimax_client import MiniMaxClient, MiniMaxError

SYSTEM_PROMPT = """你是一名资深 Python 工程师，在一个真实的软件仓库里工作。
用户会给你一个开发任务，以及该任务当前有效的规格（spec）、相关代码和测试。

工作要求：
1. 严格按规格实现，不要改动测试文件、规格文件或其他无关文件；
2. 修改后既有回归测试必须继续通过，目标测试必须转为通过；
3. 只输出一个统一的 unified diff（git apply 可应用），不要输出解释性正文；
4. diff 的文件路径以业务工程根目录为基准，形如 `--- a/src/ordercore/pricing.py` 和 `+++ b/src/ordercore/pricing.py`；
5. 如果你需要新增辅助函数或调整私有函数签名，允许，但必须保持公开函数的既有行为兼容（除非规格明确要求改变）。
"""

USER_TEMPLATE = """## 开发任务
task_id: {task_id}
标题: {title}
描述: {description}

## 当前有效规格（必须遵守）
{specs}

## 相关代码（需要修改或阅读）
{code}

## 验证测试
### 目标测试（当前应失败，修改后必须全部通过）
{target_tests}

### 回归测试（修改前后都必须全部通过）
{regression_tests}

## 任务状态（来自 PowerContext）
{state}

## 输出要求
只输出 unified diff，从 `diff --git` 或 `--- a/` 开始，放在一个 ```diff 代码块里。
不要输出任何其他文字。"""

FULL_FILE_TEMPLATE = """{base}

## 最后一次尝试失败
{feedback}

## 输出要求（本轮改为整文件回填）
请输出 **{target_file}** 修改后的完整文件内容，放在一个 ```python 代码块里。
不要输出任何解释；文件内容必须完整、可直接替换原文件。"""


# ---------------------------------------------------------------------------
# prompt construction
# ---------------------------------------------------------------------------

def _render_specs(context: dict[str, Any]) -> str:
    blocks = []
    for spec in context.get("specs", []):
        blocks.append(
            f"### {spec.get('spec_id')} revision {spec.get('revision')}  ({spec.get('path')})\n{spec.get('content', '')}"
        )
    return "\n\n".join(blocks) or "（无）"


def _render_code(context: dict[str, Any]) -> str:
    blocks = []
    for unit in context.get("code", []):
        blocks.append(
            f"### {unit.get('path')}::{unit.get('symbol')}  (lines {unit.get('line_start')}-{unit.get('line_end')})\n"
            f"```python\n{unit.get('content', '')}\n```"
        )
    return "\n\n".join(blocks) or "（无）"


def _render_tests(context: dict[str, Any], key: str) -> str:
    blocks = []
    for test in context.get("tests", {}).get(key, []):
        blocks.append(f"### {test.get('path')}::{test.get('symbol')}\n```python\n{test.get('content', '')}\n```")
    return "\n\n".join(blocks) or "（无）"


def _render_state(context: dict[str, Any]) -> str:
    state = context.get("state") or {}
    if not state:
        return "（空状态：这是本任务第一次运行）"
    return json.dumps(state, ensure_ascii=False, indent=2)


def build_messages(context: dict[str, Any]) -> list[dict[str, str]]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_content(context)}]


def user_content(context: dict[str, Any]) -> str:
    task = context.get("task", {})
    return USER_TEMPLATE.format(
        task_id=task.get("task_id", ""),
        title=task.get("title", ""),
        description=task.get("description", ""),
        specs=_render_specs(context),
        code=_render_code(context),
        target_tests=_render_tests(context, "target"),
        regression_tests=_render_tests(context, "regression"),
        state=_render_state(context),
    )


def target_file_for(context: dict[str, Any]) -> str:
    task = context.get("task") or {}
    hints = task.get("hints") or {}
    paths = list(hints.get("paths") or [])
    if paths:
        return str(paths[0])
    code = context.get("code") or []
    return str(code[0]["path"]) if code else "src/ordercore/pricing.py"


# ---------------------------------------------------------------------------
# unified diff parsing and application
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:diff|patch)?\s*\n(.*?)```", re.S)
_PY_FENCE_RE = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.S)
_HUNK_START = re.compile(r"(?m)^(diff --git |--- a/)")


@dataclass
class FilePatch:
    path: str
    old_path: str
    hunks: list[list[str]]


def extract_unified_diff(text: str) -> str | None:
    for match in _FENCE_RE.finditer(text):
        block = match.group(1)
        if "--- " in block and "+++ " in block:
            return block.strip("\n") + "\n"
    match = _HUNK_START.search(text)
    if match:
        candidate = text[match.start():].strip("\n")
        if "--- " in candidate and "+++ " in candidate:
            return candidate + "\n"
    return None


def extract_full_file(text: str) -> str | None:
    blocks = [match.group(1) for match in _PY_FENCE_RE.finditer(text)]
    if not blocks:
        return None
    return max(blocks, key=len).strip("\n") + "\n"


def _strip_prefix(path: str, prefix: str) -> str:
    path = path.strip()
    if path.startswith(("a/", "b/")):
        path = path[2:]
    if prefix and path.startswith(prefix + "/"):
        path = path[len(prefix) + 1 :]
    return path


def parse_unified_diff(diff: str, prefix: str = "") -> list[FilePatch]:
    """Parse a unified diff into per-file hunks of raw ``[-+ ]`` lines."""
    lines = diff.splitlines()
    files: list[FilePatch] = []
    current: FilePatch | None = None
    hunk: list[str] | None = None
    old_path = ""
    for line in lines:
        if line.startswith("diff --git "):
            current = None
            hunk = None
            continue
        if line.startswith("--- "):
            old_path = _strip_prefix(line[4:], prefix)
            continue
        if line.startswith("+++ "):
            path = _strip_prefix(line[4:], prefix)
            current = FilePatch(path=path, old_path=old_path, hunks=[])
            files.append(current)
            hunk = None
            continue
        if line.startswith("@@") and current is not None:
            hunk = []
            current.hunks.append(hunk)
            continue
        if hunk is not None and line[:1] in (" ", "-", "+", ""):
            if line.startswith("\\"):
                continue
            hunk.append(line if line else " ")
    return [item for item in files if item.hunks]


def _hunk_blocks(hunk: list[str]) -> tuple[list[str], list[str]]:
    """Split a hunk into its pre-image and post-image line blocks."""
    old_block = [line[1:] for line in hunk if line[:1] in (" ", "-")]
    new_block = [line[1:] for line in hunk if line[:1] in (" ", "+")]
    return old_block, new_block


def apply_file_patch(original: str, file_patch: FilePatch) -> tuple[str, list[dict[str, Any]]]:
    """Apply one file's hunks by exact context matching; returns new text."""
    lines = original.split("\n")
    trailing_newline = original.endswith("\n")
    if trailing_newline:
        lines = lines[:-1]
    report: list[dict[str, Any]] = []
    offset = 0
    for index, hunk in enumerate(file_patch.hunks, 1):
        old_block = [line[1:] for line in hunk if line[:1] in (" ", "-")]
        new_block = [line[1:] for line in hunk if line[:1] in (" ", "+")]
        position = _find_block(lines, old_block, start=max(0, offset))
        if position is None:
            position = _find_block(lines, old_block, start=0)
        if position is None:
            return "", [{"hunk": index, "ok": False, "reason": "context not found"}]
        lines[position : position + len(old_block)] = new_block
        offset = position + len(new_block)
        report.append({"hunk": index, "ok": True, "at": position + 1, "old_lines": len(old_block), "new_lines": len(new_block)})
    result = "\n".join(lines)
    if trailing_newline:
        result += "\n"
    return result, report


def _find_block(lines: list[str], block: list[str], start: int = 0) -> int | None:
    if not block:
        return None
    width = len(block)
    for position in range(start, len(lines) - width + 1):
        if lines[position : position + width] == block:
            return position
    return None


def normalise_patch_paths(diff: str, prefix: str) -> str:
    """Prefix paths in the recorded diff so they are repository relative."""
    if not prefix:
        return diff
    prefix = prefix.strip("/")
    out = []
    for line in diff.splitlines(keepends=True):
        for marker in ("--- ", "+++ ", "diff --git "):
            if line.startswith(marker):
                break
        if line.startswith("--- ") or line.startswith("+++ "):
            head, _, tail = line.partition(" ")
            path = tail.strip()
            if path != "/dev/null":
                match = re.match(r"^([ab])/(.*)$", path)
                rest = match.group(2) if match else path
                if not rest.startswith(prefix + "/"):
                    rest = f"{prefix}/{rest}"
                line = f"{head} {match.group(1) if match else 'a'}/{rest}\n"
        elif line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                fixed = []
                for part in parts[2:4]:
                    match = re.match(r"^([ab])/(.*)$", part)
                    rest = match.group(2) if match else part
                    if not rest.startswith(prefix + "/"):
                        rest = f"{prefix}/{rest}"
                    fixed.append(f"{match.group(1)}/{rest}" if match else rest)
                line = " ".join(parts[:2] + fixed) + "\n"
        out.append(line)
    return "".join(out)


# ---------------------------------------------------------------------------
# git and test helpers
# ---------------------------------------------------------------------------

def git(repo_root: Path, *args: str) -> tuple[int, str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def git_rev(repo_root: Path) -> str:
    code, out = git(repo_root, "rev-parse", "HEAD")
    return out.strip() if code == 0 else ""


def git_diff(repo_root: Path, paths: list[str]) -> str:
    code, out = git(repo_root, "diff", "--", *paths)
    return out if code == 0 else ""


def git_checkout(repo_root: Path, paths: list[str]) -> None:
    git(repo_root, "checkout", "--", *paths)


def run_pytest(project_root: Path, targets: list[str], *, timeout: int = 300) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", *targets, "-q"]
    started = __import__("time").time()
    result = subprocess.run(
        command, cwd=str(project_root), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    tail = "\n".join((result.stdout or "").strip().splitlines()[-12:])
    return {
        "command": " ".join(command),
        "cwd": str(project_root),
        "targets": targets,
        "returncode": result.returncode,
        "duration_s": round(__import__("time").time() - started, 3),
        "tail": tail,
    }


# ---------------------------------------------------------------------------
# development run orchestration
# ---------------------------------------------------------------------------

def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def run_development(
    settings: Settings,
    context: dict[str, Any],
    *,
    repo_root: Path,
    patch_prefix: str = "minimax/sample_app",
    model: str | None = None,
    apply: bool = True,
    test_targets: list[str] | None = None,
    max_rounds: int = 3,
) -> dict[str, Any]:
    """Ask MiniMax for a patch, apply it, run tests, and persist the record."""
    client = MiniMaxClient(
        settings.require_api_key(),
        settings.minimax_base_url,
        model or settings.minimax_model,
    )
    target_file = target_file_for(context)
    base_messages = build_messages(context)
    messages = list(base_messages)
    tests: dict[str, Any] | None = None
    applied_diff = ""
    applied_ok = False
    attempts: list[dict[str, Any]] = []
    before_rev = git_rev(repo_root)
    selected_model = model or settings.minimax_model
    feedback = ""

    for round_index in range(1, max_rounds + 1):
        mode = "diff" if round_index == 1 else "full-file"
        attempt: dict[str, Any] = {
            "round": round_index,
            "mode": mode,
            "model": selected_model,
            "messages_digest": _digest(messages),
            "context_digest": _digest(context),
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            result = client.chat(messages)
        except MiniMaxError as error:
            attempt.update({"error": str(error), "status": error.status, "body": error.body[:1000]})
            attempts.append(attempt)
            break
        attempt.update(
            {
                "response": result.content,
                "usage": result.usage,
                "latency_ms": result.latency_ms,
                "request_id": result.request_id,
            }
        )

        # --- obtain the edit -------------------------------------------------
        if mode == "diff":
            diff = extract_unified_diff(result.content)
            if diff is None:
                attempt["error"] = "no unified diff in response"
                attempts.append(attempt)
                feedback = "上一次回答没有给出可解析的 unified diff。"
                messages = base_messages + [
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": FULL_FILE_TEMPLATE.format(
                        base="", feedback=feedback, target_file=target_file)},
                ]
                continue
            attempt["model_patch"] = normalise_patch_paths(diff, patch_prefix)
            file_patches = parse_unified_diff(diff)
            if not file_patches:
                attempt["error"] = "diff parsed to zero file sections"
                attempts.append(attempt)
                feedback = "上一次 diff 无法解析出文件段。"
                messages = [base_messages[0], {"role": "user", "content": FULL_FILE_TEMPLATE.format(
                    base=user_content(context), feedback=feedback, target_file=target_file)}]
                continue
            project_relative = _strip_prefix(file_patches[0].path, patch_prefix)
            target_path = settings.project_root / project_relative
            original = target_path.read_text(encoding="utf-8")
            new_text, hunk_report = apply_file_patch(original, file_patches[0])
            attempt["hunks"] = hunk_report
            if any(not item["ok"] for item in hunk_report) or not new_text:
                attempt["error"] = "hunk context mismatch"
                attempts.append(attempt)
                feedback = f"上一次 diff 的上下文无法匹配：{hunk_report}"
                messages = base_messages + [
                    {"role": "assistant", "content": result.content},
                    {"role": "user", "content": FULL_FILE_TEMPLATE.format(
                        base="", feedback=feedback, target_file=target_file)},
                ]
                continue
            if apply:
                target_path.write_text(new_text, encoding="utf-8", newline="\n")
        else:  # full-file fallback
            content = extract_full_file(result.content)
            if content is None:
                attempt["error"] = "no python code block in response"
                attempts.append(attempt)
                feedback = "上一次回答没有给出完整文件代码块。"
                messages = [base_messages[0], {"role": "user", "content": FULL_FILE_TEMPLATE.format(
                    base="", feedback=feedback, target_file=target_file)}]
                continue
            attempt["full_file"] = content
            if apply:
                (settings.project_root / target_file).write_text(content, encoding="utf-8", newline="\n")

        # --- verify ----------------------------------------------------------
        tests = run_pytest(settings.project_root, test_targets or ["tests"]) if apply else None
        attempt["tests"] = tests
        if tests is not None and tests["returncode"] == 0:
            applied_ok = True
            applied_diff = git_diff(repo_root, [f"{patch_prefix}/{target_file}"])
            attempts.append(attempt)
            break

        # failed tests -> revert and retry with feedback
        if apply:
            git_checkout(repo_root, [f"{patch_prefix}/{target_file}"])
        attempts.append(attempt)
        feedback = (tests or {}).get("tail", "unknown failure")
        messages = [base_messages[0], {"role": "user", "content": FULL_FILE_TEMPLATE.format(
            base=user_content(context), feedback=feedback, target_file=target_file)}]

    after_rev = git_rev(repo_root)
    record = {
        "task_id": (context.get("task") or {}).get("task_id"),
        "model": selected_model,
        "base_url": settings.minimax_base_url,
        "api_style": "openai-compatible",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "context_digest": _digest(context),
        "context_summary": {
            "specs": [f"{s.get('spec_id')} r{s.get('revision')} ({s.get('path')})" for s in context.get("specs", [])],
            "code": [f"{c.get('path')}::{c.get('symbol')}" for c in context.get("code", [])],
            "target_tests": [t.get("symbol") for t in (context.get("tests") or {}).get("target", [])],
            "regression_tests": [t.get("symbol") for t in (context.get("tests") or {}).get("regression", [])],
            "state_present": bool(context.get("state")),
            "state": context.get("state") or None,
        },
        "target_file": target_file,
        "attempts": attempts,
        "applied_diff": applied_diff,
        "applied": applied_ok,
        "git_revision_before": before_rev,
        "git_revision_after": after_rev,
        "tests": tests,
        "result": "applied-and-tested" if applied_ok else ("applied-tests-failed" if apply else "not-applied"),
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = settings.dev_record_dir / f"{stamp}-minimax-dev-run.json"
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    record["record_path"] = str(json_path)
    return record