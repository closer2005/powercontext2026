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


"""Durable scope-local dependency graphs over immutable evidence references."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select, update

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.persistence.artifact_governance import ArtifactGovernanceRepository, ArtifactLifecycleState
from powercontext.builtin.persistence.database import AsyncDatabase
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_TABLE
from powercontext.builtin.runtime.models import GetMemoryEntryRequest
from powercontext.builtin.sources.journal import validate_scope_id
from powercontext.sources import SourceMaterialization, SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime


class SourceLifecycleError(ValueError):
    """A binding, event or generation request violates the evidence graph."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class SourceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    node_id: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool
    reason: str

    @field_validator("node_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")  # noqa: TRY003
        return value


class _Node(BaseModel):
    kind: Literal["source", "memory", "topic"]
    reference: SourceRef | MemoryCitation | ArtifactRef
    revision: int | None = None
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    event: SourceLifecycleEvent | None = None


class _Graph(BaseModel):
    nodes: dict[str, _Node] = Field(default_factory=dict)
    pending: SourceLifecycleEvent | None = None

    def available(self) -> set[str]:
        # Registration requires existing parents, so insertion order is topological.
        active: set[str] = set()
        for node_id, node in self.nodes.items():
            if node.kind == "source":
                enabled = node.event is None or node.event.available
            else:
                supported = [parent in active for parent in node.parents]
                enabled = all(supported) if node.policy == "all" else any(supported)
            if enabled:
                active.add(node_id)
        return active


class SourceLifecycleApplication:
    def __init__(
        self, runtime: BuiltinRuntime, database: AsyncDatabase | None, sources: SourceRepository | None
    ) -> None:
        self.runtime = runtime
        self.database = database
        self.sources = sources

    def for_scope(self, scope_id: str) -> ScopedSourceLifecycle:
        if self.database is None or self.sources is None:
            raise SourceLifecycleError("Lifecycle persistence is not configured")  # noqa: TRY003
        return ScopedSourceLifecycle(self.runtime, self.database, self.sources, validate_scope_id(scope_id))


class ScopedSourceLifecycle:
    def __init__(
        self, runtime: BuiltinRuntime, database: AsyncDatabase, sources: SourceRepository, scope_id: str
    ) -> None:
        self._runtime = runtime
        self._database = database
        self._sources = sources
        self.scope_id = scope_id

    async def _load(self) -> _Graph:
        async with self._database.transaction() as connection:
            payload = await connection.scalar(
                select(SOURCE_LIFECYCLE_TABLE.c.payload).where(SOURCE_LIFECYCLE_TABLE.c.scope_id == self.scope_id)
            )
        return _Graph() if payload is None else _Graph.model_validate_json(payload)

    async def _save(self, graph: _Graph) -> None:
        table = SOURCE_LIFECYCLE_TABLE
        async with self._database.transaction() as connection:
            exists = await connection.scalar(select(table.c.scope_id).where(table.c.scope_id == self.scope_id))
            if exists is None:
                await connection.execute(insert(table).values(scope_id=self.scope_id, payload=graph.model_dump_json()))
            else:
                await connection.execute(
                    update(table).where(table.c.scope_id == self.scope_id).values(payload=graph.model_dump_json())
                )

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        if type(revision) is not int or revision <= 0 or not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("Source binding requires a reference and positive integer revision")  # noqa: TRY003
        await self._register(node_id, _Node(kind="source", reference=source_ref, revision=revision))

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: Literal["all", "any"]
    ) -> None:
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("Memory binding requires an exact citation")  # noqa: TRY003
        await self._register_derived(node_id, "memory", citation, parents, policy)

    async def register_topic(
        self, node_id: str, artifact_ref: ArtifactRef, *, parents: tuple[str, ...], policy: Literal["all", "any"]
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("Topic binding requires a Topic Memory reference")  # noqa: TRY003
        await self._register_derived(node_id, "topic", artifact_ref, parents, policy)

    async def _register_derived(
        self,
        node_id: str,
        kind: Literal["memory", "topic"],
        reference: MemoryCitation | ArtifactRef,
        parents: tuple[str, ...],
        policy: Literal["all", "any"],
    ) -> None:
        if policy not in {"all", "any"} or not parents or len(set(parents)) != len(parents):
            raise SourceLifecycleError("Derived bindings require distinct parents and an all/any policy")  # noqa: TRY003
        await self._register(node_id, _Node(kind=kind, reference=reference, parents=parents, policy=policy))

    async def _register(self, node_id: str, node: _Node) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("Node identity must not be blank")  # noqa: TRY003
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            graph = await self._load()
            previous = graph.nodes.get(node_id)
            if previous is not None:
                if previous.model_copy(update={"event": None}) != node:
                    raise SourceLifecycleError("Node identity is already bound differently")  # noqa: TRY003
            else:
                if graph.pending is not None:
                    raise SourceLifecycleError("Retry the interrupted event before extending the graph")  # noqa: TRY003
                if node_id in node.parents or any(parent not in graph.nodes for parent in node.parents):
                    raise SourceLifecycleError("Parents must already be registered in this scope")  # noqa: TRY003
                await self._validate_reference(node)
                graph.nodes[node_id] = node
                await self._save(graph)
            await self._synchronize(graph, "Evidence dependency registration")

    async def _validate_reference(self, node: _Node) -> None:
        try:
            records = self._runtime.records.for_scope(self.scope_id)
            if node.kind == "source":
                ref = cast(SourceRef, node.reference)
                async with self._database.transaction() as connection:
                    source = (await self._sources.get(connection, self.scope_id, ref)).value
                if source.materialization != SourceMaterialization.CAPTURED:
                    raise SourceLifecycleError("Lifecycle requires captured evidence")  # noqa: TRY003, TRY301
            elif node.kind == "memory":
                await self._runtime.memory.for_scope(self.scope_id).get(
                    GetMemoryEntryRequest(citation=cast(MemoryCitation, node.reference))
                )
            else:
                ref = cast(ArtifactRef, node.reference)
                await records.get_artifact_revision(ref.family, ref.artifact_id, ref.revision)
        except Exception as error:
            raise SourceLifecycleError("Registered evidence must exist and be readable in this scope") from error  # noqa: TRY003

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            graph = await self._load()
            node = graph.nodes.get(event.node_id)
            if node is None or node.kind != "source" or node.revision != event.revision:
                raise SourceLifecycleError("Event must match a registered Source lifecycle revision")  # noqa: TRY003
            if node.event is not None and (
                event.sequence < node.event.sequence or (event.sequence == node.event.sequence and event != node.event)
            ):
                raise SourceLifecycleError("Event sequence is stale or conflicts with an earlier event")  # noqa: TRY003
            if graph.pending is not None and graph.pending != event:
                raise SourceLifecycleError("Retry the interrupted event before applying another event")  # noqa: TRY003
            if node.event != event:
                node.event = event
                graph.pending = event
                # Persist the intended transition before changing native projections.
                # Replay compares native state, so a crash after any write is safe.
                await self._save(graph)
            await self._synchronize(graph, event.reason)
            if graph.pending is not None:
                graph.pending = None
                await self._save(graph)
            return sorted(graph.available())

    async def _synchronize(self, graph: _Graph, reason: str) -> None:
        active = graph.available()
        memories = {key: node for key, node in graph.nodes.items() if node.kind == "memory"}
        if memories:
            async with self._runtime._context(self.scope_id) as context:
                service = context.artifacts.memory
                current = await service.head(context.artifacts.memory_artifact_id)
                states = {item.entry_id: item for item in current.content.manifest.entries}
                entries = {item.entry_id: item for item in await service.entries(current)}
                memory_availability: dict[str, bool] = {}
                for node_id, node in memories.items():
                    ref = cast(MemoryCitation, node.reference)
                    state = states.get(ref.entry_id)
                    if state is None or state.entry_version_id != ref.entry_version_id:
                        raise SourceLifecycleError("Bound Memory body has changed or disappeared")  # noqa: TRY003
                    memory_availability[ref.entry_id] = (
                        memory_availability.get(ref.entry_id, False) or node_id in active
                    )
                for enabled in (False, True):
                    selected = [
                        entries[entry_id]
                        for entry_id, available in memory_availability.items()
                        if available == enabled and (states[entry_id].state == "active") != enabled
                    ]
                    if selected:
                        operation = service.reactivate if enabled else service.forget
                        current = await operation(current, entries=selected, reason=reason)
        governance = ArtifactGovernanceRepository()
        async with self._database.transaction() as connection:
            for node_id, node in graph.nodes.items():
                if node.kind != "topic":
                    continue
                ref = cast(ArtifactRef, node.reference)
                current = await governance.get(connection, self.scope_id, ref.family, ref.artifact_id)
                desired = ArtifactLifecycleState.ACTIVE if node_id in active else ArtifactLifecycleState.DEPRECATED
                if current.lifecycle_state != desired:
                    await governance.transition(
                        connection,
                        self.scope_id,
                        ref.family,
                        ref.artifact_id,
                        current.governance_generation,
                        desired,
                        None,
                    )

    async def resolve(
        self, node_id: str, *, purpose: Literal["generation", "audit"]
    ) -> SourceRef | MemoryCitation | ArtifactRef:
        async with self._runtime._scope_operation(self.scope_id), self._runtime._locked(self.scope_id):
            graph = await self._load()
            if node_id not in graph.nodes or purpose not in {"generation", "audit"}:
                raise SourceLifecycleError("Unknown node or resolution purpose")  # noqa: TRY003
            if purpose == "generation" and (graph.pending is not None or node_id not in graph.available()):
                raise SourceLifecycleError("Evidence is not available for generation")  # noqa: TRY003
            return graph.nodes[node_id].reference
