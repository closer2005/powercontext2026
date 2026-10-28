"""PowerContext 任务状态封装。

优先使用 powercontext 官方包；当包不可用、或未配置 server（POWERCONTEXT_SERVER）时，
自动降级为本地 JSON 文件（目录取 POWERCONTEXT_STATE_DIR）。

状态复用验证：save 与 resume 是两次独立进程调用（见 cli.py），
状态文件路径统一基于 minimax/ 根目录解析，因此新进程能稳定读到同一份状态。

backend 标注（返回值里可核对）：
    * save_progress 返回 "<backend>:<state_id|path>" 字符串；
    * load_progress 返回的 dict 内含 "backend" 字段。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import DEFAULT_STATE_FILE, Config

BACKEND_POWERCONTEXT = "powercontext"
BACKEND_LOCAL = "local-json"


class StateError(RuntimeError):
    """状态读写相关的可预期错误；消息为中文。"""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ProgressStore:
    """任务进展（done / todo / evidence）的保存与读取。"""

    def __init__(self, state_dir: Path | str | None = None) -> None:
        self.cfg = Config.from_env()
        self.state_dir = Path(state_dir) if state_dir else self.cfg.powercontext_state_dir
        self.default_state_file = DEFAULT_STATE_FILE
        # 顺序：先初始化降级原因，再探测后端
        self._degrade_reason = ""
        self._pc = None
        self.backend = self._detect_backend()
        if self.backend == BACKEND_POWERCONTEXT:
            self._pc = self._import_powercontext()

    # ---- 后端探测 -----------------------------------------------------------
    def _detect_backend(self) -> str:
        if not self.cfg.powercontext_server:
            self._degrade_reason = (
                "未配置 POWERCONTEXT_SERVER，自动降级为本地 JSON 状态文件"
            )
            return BACKEND_LOCAL
        try:
            import powercontext  # noqa: F401
        except Exception as exc:  # pragma: no cover - 取决于环境
            self._degrade_reason = f"powercontext 包不可用（{exc}），已降级为本地 JSON"
            return BACKEND_LOCAL
        return BACKEND_POWERCONTEXT

    @staticmethod
    def _import_powercontext():
        import powercontext  # noqa: PLC0415

        return powercontext

    # ---- 路径与 IO ----------------------------------------------------------
    def _resolve(self, state_file: str) -> Path:
        p = Path(state_file)
        return p if p.is_absolute() else (self.state_dir / p)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _read_json(path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (TypeError, ValueError) as exc:
            raise StateError(f"状态文件解析失败（应为合法 JSON）：{path}（{exc}）") from exc

    # ---- PowerContext 尝试 --------------------------------------------------
    def _save_via_powercontext(self, record: dict) -> str:
        """尝试用 powercontext 保存；任何异常都向外抛出，由调用方降级。"""
        pc = self._pc
        for name in ("save_state", "save", "put", "store"):
            fn = getattr(pc, name, None)
            if callable(fn):
                result = fn(record.get("progress"))
                state_id = getattr(result, "id", None) or getattr(result, "state_id", None)
                return str(state_id or result or "state")
        raise StateError("powercontext 未提供可用的写入 API（save_state/save/put/store）")

    def _load_via_powercontext(self, state_id: str) -> Any:
        pc = self._pc
        for name in ("load_state", "load", "get"):
            fn = getattr(pc, name, None)
            if callable(fn):
                return fn(state_id)
        raise StateError("powercontext 未提供可用的读取 API（load_state/load/get）")

    # ---- 对外接口 -----------------------------------------------------------
    def save_progress(self, progress: dict, state_file: str | None = None) -> str:
        """保存任务进展。

        返回 "<backend>:<id|path>"，其中 backend 为 powercontext 或 local-json。
        PowerContext 写入失败时会自动降级为本地 JSON，绝不静默丢数据。
        """
        progress = dict(progress or {})
        record = {
            "progress": progress,
            "backend": self.backend,
            "updated_at": _now_iso(),
        }

        if self.backend == BACKEND_POWERCONTEXT:
            try:
                state_id = self._save_via_powercontext(record)
                # 同时落一份本地副本，保证新进程可无网读取
                self._write_json(self._resolve(state_file or self.default_state_file), record)
                return f"{BACKEND_POWERCONTEXT}:{state_id}"
            except Exception as exc:  # 运行期失败 -> 降级
                self._degrade_reason = f"PowerContext 写入失败（{exc}），已降级为本地 JSON"
                self.backend = BACKEND_LOCAL
                record["backend"] = BACKEND_LOCAL
                record["degrade_reason"] = self._degrade_reason

        path = self._resolve(state_file or self.default_state_file)
        self._write_json(path, record)
        return f"{BACKEND_LOCAL}:{path}"

    def load_progress(self, state_file: str) -> dict:
        """读取任务进展；返回 dict 内含 backend / state_id / updated_at。"""
        path = self._resolve(state_file)
        if not path.is_file():
            raise StateError(
                f"状态文件不存在：{path}（请先执行 save --state-file {state_file} 生成状态）"
            )
        data = self._read_json(path)
        if not isinstance(data, dict):
            raise StateError(f"状态文件格式非法（应为 JSON 对象）：{path}")

        progress = data.get("progress") or {}
        backend = data.get("backend", BACKEND_LOCAL)

        # 若记录声明为 powercontext 且当前进程也能用，则优先尝试远端读取
        if backend == BACKEND_POWERCONTEXT and self._pc is not None:
            try:
                remote = self._load_via_powercontext(str(data.get("state_id") or path.stem))
                if isinstance(remote, dict) and "progress" in remote:
                    progress = remote.get("progress") or progress
            except Exception:
                # 远端不可用不影响本地副本读取
                pass

        return {
            "done": list(progress.get("done", [])),
            "todo": list(progress.get("todo", [])),
            "evidence": dict(progress.get("evidence", {})),
            "backend": backend,
            "state_id": str(path),
            "updated_at": data.get("updated_at"),
        }

    def describe_backend(self) -> str:
        """返回一句后端说明，便于 CLI 打印。"""
        text = f"backend={self.backend}"
        if self._degrade_reason:
            text += f"（{self._degrade_reason}）"
        return text