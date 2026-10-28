"""Import engineering materials into seekdb.

A full import replaces the material kinds it owns (specifications, code units,
tests), so deleting a spec revision or a test is reflected after the next import
instead of leaving stale rows behind.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .materials import all_materials
from .selector import load_task
from .store import SeekDBStore


def import_project(
    store: SeekDBStore,
    project_root: Path,
    *,
    reset: bool = False,
    note: str = "",
) -> dict[str, Any]:
    if reset:
        store.init_schema(reset=True)
    else:
        store.init_schema()

    task = load_task(project_root) if (project_root / "task.yaml").is_file() else {}
    # Index every Python source under src/: selection later prioritises the
    # files named by the task hints, while the rest stays searchable.
    materials = all_materials(project_root)

    for spec_id in sorted({material.spec_id for material in materials["spec"] if material.spec_id}):
        store.delete_materials(kind="spec", spec_id=spec_id)
    store.delete_materials(kind="code")
    store.delete_materials(kind="test")

    counts = {
        "spec": store.upsert_materials(materials["spec"]),
        "code": store.upsert_materials(materials["code"]),
        "test": store.upsert_materials(materials["test"]),
    }
    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
    store.record_import(run_id, counts, note or f"full import of {project_root}")
    return {
        "run_id": run_id,
        "project_root": str(project_root),
        "counts": counts,
        "specs": sorted({f"{material.spec_id}#r{material.revision}:{material.status}" for material in materials["spec"]}),
        "code_scope": "src/",
        "fulltext": store.has_fulltext(),
    }


def spec_versions(store: SeekDBStore) -> list[dict[str, Any]]:
    return store.spec_versions()