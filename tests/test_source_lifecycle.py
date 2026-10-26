# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Evidence recovery must survive interruption after a native write commits."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.service import MemoryService
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceRef,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import CSV_ROW_SOURCE_DEFINITION, CSVDocumentInput, parse_csv_document


@pytest.mark.parametrize(
    ("field", "value"),
    [("node_id", " "), ("reason", ""), ("revision", True), ("sequence", "1"), ("available", 1)],
)
def test_event_rejects_coercion(field, value):
    values = {"node_id": "origin", "reason": "retract", "revision": 1, "sequence": 1, "available": False}
    values[field] = value
    with pytest.raises(ValidationError):
        SourceLifecycleEvent(**values)


async def test_captured_csv_source_can_participate_in_lifecycle():
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    row = parse_csv_document(
        CSVDocumentInput(document_id="sales", primary_key="id", content=b"id,value\n1,original\n")
    )[0]
    observation = project_source_for_transport(registry, await registry.resolve(row))
    reference = SourceRef(source_type="csv-row", source_id=observation.name)
    async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="CSV", summary="Lifecycle", idempotency_key="csv"))
        await runtime.ingestion.register(manifest_for_definition(CSV_ROW_SOURCE_DEFINITION))
        await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
        lifecycle = runtime.lifecycle.for_scope(scope.scope_id)
        await lifecycle.register_source("row", reference, revision=1)
        event = SourceLifecycleEvent(node_id="row", revision=1, sequence=1, available=False, reason="Retract row")
        assert await lifecycle.apply(event) == []
        await lifecycle.register_source("row", reference, revision=1)
        assert await lifecycle.resolve("row", purpose="audit") == reference
        with pytest.raises(SourceLifecycleError):
            await lifecycle.resolve("row", purpose="generation")
        assert await lifecycle.apply(event.model_copy(update={"available": True, "sequence": 2})) == ["row"]


async def test_committed_native_write_can_be_replayed_after_restart(tmp_path: Path, monkeypatch):
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}"))
    original_forget = MemoryService.forget

    async def interrupted(self, *args, **kwargs):
        await original_forget(self, *args, **kwargs)
        raise OSError("simulated failure after the native commit")  # noqa: TRY003

    async with open_builtin_runtime(config) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Evidence", summary="Recovery", idempotency_key="a"))
        other = await runtime.scopes.create(ScopeDraft(title="Other", summary="Isolation", idempotency_key="b"))
        service = runtime.lifecycle.for_scope(scope.scope_id)
        source = await runtime.sources.for_scope(scope.scope_id).capture(
            CaptureSource(source_id="origin", content="Original evidence", metadata={})
        )
        await service.register_source("origin", source.source_ref, revision=1)
        memory = runtime.memory.for_scope(scope.scope_id)
        record = await memory.remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text="Durable historical evidence"),))
        )
        assert record.entry is not None
        citation = record.entry.citation
        await service.register_memory("fact", citation, parents=("origin",), policy="all")
        event = SourceLifecycleEvent(node_id="origin", revision=1, sequence=1, available=False, reason="Retract")
        with monkeypatch.context() as patch:
            patch.setattr(MemoryService, "forget", interrupted)
            with pytest.raises(OSError, match="simulated failure"):
                await service.apply(event)
        with pytest.raises(SourceLifecycleError):
            await service.resolve("fact", purpose="generation")
        assert await service.resolve("fact", purpose="audit") == citation
        with pytest.raises(SourceLifecycleError):
            await runtime.lifecycle.for_scope(other.scope_id).resolve("origin", purpose="audit")

    async with open_builtin_runtime(config) as runtime:
        service = runtime.lifecycle.for_scope(scope.scope_id)
        memory = runtime.memory.for_scope(scope.scope_id)
        before = await memory.list(include_inactive=True)
        assert before.entries[0].state == "inactive"
        assert await service.apply(event) == []
        assert (await memory.list(include_inactive=True)).memory_ref == before.memory_ref
        await service.apply(event.model_copy(update={"sequence": 2, "available": True}))
        assert await service.resolve("fact", purpose="generation") == citation
        restored = await memory.list()
        assert restored.entries[0].entry.entry_version_id == citation.entry_version_id
        assert (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text == "Durable historical evidence"
