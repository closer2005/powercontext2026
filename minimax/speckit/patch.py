"""补丁提取与应用。

extract_patch(text)
    从 MiniMax 返回文本中提取目标代码：
      * 优先取 ```python / ```py / ``` 围栏代码块；存在多个时取最长的一个（通常是完整文件）；
      * 无围栏时按整段文本处理。

apply(service_path, new_code)
    把新代码落到 demo_project/orders/service.py：
      * 写入前把旧内容快照到 evidence/before/service.py；
      * 写入后快照到 evidence/after/service.py，并生成 unified diff -> evidence/diff.patch。
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from .config import Config, REPO_ROOT

_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+#.-]*)[ \t]*\r?\n(.*?)```", re.S)
_PY_LANGS = ("python", "py", "python3")


class PatchError(RuntimeError):
    """补丁相关的可预期错误；消息为中文。"""


def extract_patch(text: str) -> str:
    """从模型输出中提取代码文本。"""
    if not text or not text.strip():
        raise PatchError("补丁文本为空，无法提取代码。")

    blocks = _FENCE_RE.findall(text)
    if blocks:
        preferred = [body for lang, body in blocks if lang.lower() in _PY_LANGS]
        pool = preferred or [body for _, body in blocks]
        code = max(pool, key=len)
    else:
        code = text

    code = code.strip("\n")
    if not code.strip():
        raise PatchError("未能从文本中提取到有效代码。")
    return code + "\n"


def make_diff(
    old: str,
    new: str,
    fromfile: str = "a/demo_project/orders/service.py",
    tofile: str = "b/demo_project/orders/service.py",
) -> str:
    """生成 unified diff 文本。"""
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=tofile,
        )
    )


def _rel(path: Path) -> str:
    for base in (REPO_ROOT, Config.from_env().demo_project_dir):
        try:
            return path.resolve().relative_to(base.resolve()).as_posix()
        except ValueError:
            continue
    return path.as_posix()


def apply(
    service_path: Path | str,
    new_code: str,
    *,
    config: Config | None = None,
) -> dict:
    """把新代码写入目标文件，并产出快照与 diff。"""
    cfg = config or Config.from_env()
    target = Path(service_path)

    if not target.is_file():
        raise PatchError(f"目标文件不存在：{target}")
    if not new_code or not new_code.strip():
        raise PatchError("新代码为空，拒绝写入。")

    new_code = new_code.replace("\r\n", "\n")
    old_code = target.read_text(encoding="utf-8")

    before_dir = cfg.evidence_dir / "before"
    after_dir = cfg.evidence_dir / "after"
    before_dir.mkdir(parents=True, exist_ok=True)
    after_dir.mkdir(parents=True, exist_ok=True)

    # 保存修改前 / 修改后快照
    before_snapshot = before_dir / target.name
    after_snapshot = after_dir / target.name
    before_snapshot.write_text(old_code, encoding="utf-8")
    target.write_text(new_code, encoding="utf-8")
    after_snapshot.write_text(new_code, encoding="utf-8")

    # 生成 unified diff
    diff = make_diff(old_code, new_code)
    diff_path = cfg.evidence_dir / "diff.patch"
    diff_path.write_text(diff, encoding="utf-8")

    return {
        "service_path": str(target),
        "before_snapshot": str(before_snapshot),
        "after_snapshot": str(after_snapshot),
        "diff_path": str(diff_path),
        "changed": old_code != new_code,
        "diff": diff,
    }


def apply_patch_file(
    patch_file: Path | str,
    service_path: Path | str | None = None,
    *,
    config: Config | None = None,
) -> dict:
    """读取补丁文件（模型输出 / 纯代码），提取并应用。"""
    cfg = config or Config.from_env()
    pf = Path(patch_file)
    if not pf.is_file():
        raise PatchError(f"补丁文件不存在：{pf}")
    new_code = extract_patch(pf.read_text(encoding="utf-8"))
    return apply(service_path or cfg.service_path, new_code, config=cfg)