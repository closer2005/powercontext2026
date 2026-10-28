"""Task state persistence through PowerContext.

Uses PowerContext's Builtin runtime through its Python SDK (an explicitly allowed
integration style: "SDK、HTTP API、MCP 或插件均可"). One Memory entry per task
scope holds the task state JSON, so a fresh process can read the previous run's
progress and feed it back into the next context.

PowerContext generates the scope id itself (``scp_…``); the mapping from the
competition task id to that scope id is persisted next to the runtime data so a
restarted process can find the same scope without re-registering it.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings

STATE_KIND = "sdd-task-state"
SCOPE_IDEMPOTENCY_PREFIX = "sdd-task::"


class PowerContextUnavailable(RuntimeError):
    pass


def scope_key_for(task_id: str) -> str:
    return f"{SCOPE_IDEMPOTENCY_PREFIX}{task_id}"


def _imports() -> dict[str, Any]:
    try:
        from powercontext.builtin.artifacts.memory import MemoryEntryInput
        from powercontext.builtin.runtime import (
            BuiltinConfig,
            RememberMemoryRequest,
            open_builtin_runtime,
        )
        from powercontext.builtin.scope import ScopeDraft
    except ModuleNotFoundError as error:  # pragma: no cover - environment dependent
        raise PowerContextUnavailable(
            "powercontext is not installed; run `pip install 'powercontext[seekdb]==1.2.0'`"
        ) from error
    return {
        "MemoryEntryInput": MemoryEntryInput,
        "BuiltinConfig": BuiltinConfig,
        "RememberMemoryRequest": RememberMemoryRequest,
        "open_builtin_runtime": open_builtin_runtime,
        "ScopeDraft": ScopeDraft,
    }


def _database(settings: Settings) -> Any:
    modules = _imports()
    BuiltinConfig = modules["BuiltinConfig"]
    backend = (settings.pc_backend or "seekdb").lower()
    if backend == "seekdb":
        from powercontext.builtin.persistence.seekdb import SeekDBConfig

        return BuiltinConfig(database=SeekDBConfig(path=settings.pc_db_path))
    from powercontext.builtin.persistence.sqlite import SQLiteConfig

    return BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{settings.pc_db_path}"))


def _scope_map_path(settings: Settings) -> Path:
    return settings.data_dir / "powercontext-scopes.json"


def _read_scope_map(settings: Settings) -> dict[str, str]:
    path = _scope_map_path(settings)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in data.items()}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_scope_map(settings: Settings, mapping: dict[str, str]) -> None:
    path = _scope_map_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8", newline="\n")


def new_state(task_id: str, *, status: str = "in_progress") -> dict[str, Any]:
    return {
        "task_id": task_id,
        "status": status,
        "done": [],
        "todo": [],
        "verifications": [],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def touch(state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    return state


def record_verification(
    state: dict[str, Any],
    *,
    name: str,
    command: str,
    returncode: int,
    detail: str = "",
    git_revision: str | None = None,
) -> dict[str, Any]:
    state.setdefault("verifications", []).append(
        {
            "name": name,
            "command": command,
            "returncode": returncode,
            "ok": returncode == 0,
            "detail": detail,
            "git_revision": git_revision,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return touch(state)


async def _create_scope(runtime: Any, task_id: str) -> str:
    """Register (idempotently) the PowerContext scope for a task and return its id."""
    modules = _imports()
    ScopeDraft = modules["ScopeDraft"]
    descriptor = await runtime.scopes.create(
        ScopeDraft(
            title=f"SDD task {task_id}",
            summary=f"Spec-driven development task {task_id} for the MiniMax competition entry.",
            idempotency_key=scope_key_for(task_id),
        )
    )
    return str(descriptor.scope_id)


async def _save_async(settings: Settings, task_id: str, state: dict[str, Any]) -> dict[str, Any]:
    modules = _imports()
    MemoryEntryInput = modules["MemoryEntryInput"]
    RememberMemoryRequest = modules["RememberMemoryRequest"]
    open_builtin_runtime = modules["open_builtin_runtime"]
    config = _database(settings)
    text = json.dumps(state, ensure_ascii=False, sort_keys=True)
    async with open_builtin_runtime(config) as runtime:
        scope_id = await _create_scope(runtime, task_id)
        memory = runtime.memory.for_scope(scope_id)
        result = await memory.remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind=STATE_KIND, text=text),))
        )
        mapping = _read_scope_map(settings)
        mapping[task_id] = scope_id
        _write_scope_map(settings, mapping)
        return {
            "scope_id": scope_id,
            "revision": result.memory_ref.revision,
            "memory_artifact_id": result.memory_ref.artifact_id,
            "state_bytes": len(text.encode("utf-8")),
        }


async def _load_async(settings: Settings, task_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    modules = _imports()
    open_builtin_runtime = modules["open_builtin_runtime"]
    mapping = _read_scope_map(settings)
    scope_id = mapping.get(task_id)
    if not scope_id:
        return None, {"reason": "no PowerContext scope recorded for this task", "scope_map": str(_scope_map_path(settings))}
    config = _database(settings)
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        try:
            page = await memory.list()
        except Exception as error:  # noqa: BLE001 - empty scope/memory is a valid state
            return None, {"scope_id": scope_id, "reason": f"memory not readable: {type(error).__name__}: {error}"}
        entries = getattr(page, "entries", ()) or ()
        for item in reversed(list(entries)):
            entry = getattr(item, "entry", None)
            kind = getattr(entry, "kind", None)
            if kind != STATE_KIND:
                continue
            text = getattr(entry, "text", "") or ""
            try:
                return json.loads(text), {"scope_id": scope_id, "entries": len(entries)}
            except json.JSONDecodeError:
                continue
        return None, {"scope_id": scope_id, "entries": len(entries), "reason": "no task-state entry"}


def save_state(settings: Settings, task_id: str, state: dict[str, Any]) -> dict[str, Any]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.pc_db_path is not None:
        settings.pc_db_path.parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_save_async(settings, task_id, touch(state)))


def load_state(settings: Settings, task_id: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if settings.pc_db_path is None:
        return None, {"reason": "powercontext database path is not configured"}
    return asyncio.run(_load_async(settings, task_id))


def describe_backend(settings: Settings) -> dict[str, Any]:
    return {
        "backend": settings.pc_backend,
        "database": str(settings.pc_db_path),
        "database_exists": Path(settings.pc_db_path).exists() if settings.pc_db_path else False,
        "scope_idempotency_prefix": SCOPE_IDEMPOTENCY_PREFIX,
        "state_kind": STATE_KIND,
        "scope_map": str(_scope_map_path(settings)),
    }