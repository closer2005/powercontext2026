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

"""Lossless Pi v3 branch evidence and durable incremental acquisition."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Literal, TypeGuard, cast

from pydantic import BaseModel, Field, JsonValue

from powercontext.sources.connectors import (
    ConnectorRunCompletion,
    ConnectorRunSession,
    ConnectorRunStatus,
    ConnectorSubmissionStatus,
)
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence


class PiSessionInput(BaseModel):
    """A complete UTF-8 JSONL archive and an optional selected endpoint."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event, including the unabridged original JSON record."""

    session_id: str
    event_id: str
    parent_id: str | None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


class PiEventSource(Source, PiEventInput):
    """Captured evidence independent of the current archive and branch."""


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _identity(session_id: str, event_id: str) -> str:
    # Hash an unambiguous pair, keeping even long Unicode IDs within Source limits.
    return "pi:" + hashlib.sha256(_canonical([session_id, event_id]).encode("utf-8")).hexdigest()


def _nonempty_string(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value.strip())


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Non-JSON numeric constant: {value}")  # noqa: TRY003


def _parse_archive(content: bytes) -> tuple[str, dict[str, dict[str, JsonValue]]]:
    try:
        records = [
            json.loads(line, parse_constant=_invalid_constant)
            for line in content.decode("utf-8-sig").split("\n")
            if line.strip()
        ]
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("Invalid UTF-8 Pi JSONL archive") from error  # noqa: TRY003
    if not records or not all(isinstance(record, dict) for record in records):
        raise ValueError("Pi archives must contain JSON objects")  # noqa: TRY003
    header = records[0]
    if header.get("type") != "session" or header.get("version") != 3 or not _nonempty_string(header.get("id")):
        raise ValueError("Pi archive must start with a version 3 session header")  # noqa: TRY003
    nodes: dict[str, dict[str, JsonValue]] = {}
    for record in records[1:]:
        event_id = record.get("id")
        if not _nonempty_string(event_id) or event_id in nodes:
            raise ValueError("Pi entry IDs must be non-empty and unique")  # noqa: TRY003
        if "parentId" not in record:
            raise ValueError("Pi entry is missing parentId")  # noqa: TRY003
        parent = record["parentId"]
        if parent is not None and (not isinstance(parent, str) or parent not in nodes):
            raise ValueError("Pi parentId must refer to an earlier entry or be null")  # noqa: TRY003
        if not _nonempty_string(record.get("type")):
            raise ValueError("Pi entry is missing its type")  # noqa: TRY003
        nodes[event_id] = record
    return header["id"], nodes


def _blocks(value: JsonValue | None, *, tool_calls: bool = False) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for block in value:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if block.get("type") == "text" and isinstance(text, str):
            parts.append(text)
        elif tool_calls and block.get("type") == "toolCall":
            arguments = _canonical(block.get("arguments", {}))
            parts.append(f"[tool_call {block.get('name', '')} {block.get('id', '')}] {arguments}")
    return "\n".join(parts)


def _visible_event(session_id: str, record: dict[str, JsonValue]) -> PiEventInput | None:
    event_type = cast(str, record["type"])
    if event_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            raise ValueError("Pi message must declare a role")  # noqa: TRY003
        role = message.get("role")
        if not _nonempty_string(role):
            raise ValueError("Pi message must declare a role")  # noqa: TRY003
        body = _blocks(message.get("content"), tool_calls=True)
        if role == "toolResult" and body:
            body = f"[tool_result {message.get('toolName', '')} {message.get('toolCallId', '')}] {body}"
        elif role == "bashExecution":
            command, output = message.get("command", ""), message.get("output", "")
            if not isinstance(command, str) or not isinstance(output, str):
                raise ValueError("Pi bash command and output must be strings")  # noqa: TRY003
            body = f"$ {command}\n{output}" if command or output else ""
    elif event_type in {"compaction", "branch_summary"}:
        role, body = event_type, _blocks(record.get("summary"))
    elif event_type == "custom_message":
        role, body = "custom", _blocks(record.get("content"))
    else:
        return None
    if not body:
        return None
    return PiEventInput(
        session_id=session_id,
        event_id=cast(str, record["id"]),
        parent_id=cast(str | None, record["parentId"]),
        event_type=event_type,
        role=role,
        content=f"{role}: {body}",
        record=record,
    )


def _branch_events(
    session_id: str, nodes: dict[str, dict[str, JsonValue]], leaf_id: str | None
) -> tuple[PiEventInput, ...]:
    leaf = leaf_id if leaf_id is not None else next(reversed(nodes), None)
    if leaf is not None and leaf not in nodes:
        raise ValueError("Selected Pi leaf does not exist")  # noqa: TRY003
    branch = []
    while leaf is not None:
        record = nodes[leaf]
        branch.append(record)
        leaf = cast(str | None, record["parentId"])
    return tuple(event for record in reversed(branch) if (event := _visible_event(session_id, record)) is not None)


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Validate the whole graph, then expose all visible ancestors of the leaf."""

    session_id, nodes = _parse_archive(value.content)
    return _branch_events(session_id, nodes, value.leaf_id)


class _PiEventAdapter:
    input_class = PiEventInput
    source_class = PiEventSource
    name = "pi-event"

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        return PiEventSource(
            name=_identity(value.session_id, value.event_id),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput.model_validate(source.model_dump())


class _PiTextEvidenceProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pi-event",
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_DEFINITION: SourceDefinition[PiEventInput, PiEventSource, PiEventInput] = AdapterSourceDefinition(
    _PiEventAdapter(), projections=(_PiTextEvidenceProjection(),)
)


class _Checkpoint(BaseModel):
    version: Literal[1] = 1
    sessions: dict[str, dict[str, str]] = Field(default_factory=dict)


def _fingerprint(record: dict[str, JsonValue]) -> str:
    return hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()


class PiSessionConnector:
    """Acquire new branch events; ConnectorLifecycle owns checkpoint commits."""

    name = "pi-session-history"
    version = "1"
    source_definitions = frozenset({"pi-event"})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        session_id, nodes = _parse_archive(await asyncio.to_thread(self.path.read_bytes))
        events = _branch_events(session_id, nodes, self.leaf_id)
        checkpoint = _Checkpoint.model_validate(session.checkpoint) if session.checkpoint is not None else _Checkpoint()
        imported = checkpoint.sessions.setdefault(session_id, {})
        # Check all previously imported branches before the first durable submission.
        for event_id, fingerprint in imported.items():
            if event_id not in nodes or _fingerprint(nodes[event_id]) != fingerprint:
                raise ValueError("Previously imported Pi event was removed or rewritten")  # noqa: TRY003
        for event in events:
            if event.event_id in imported:
                continue
            outcome = await session.submit(_identity(session_id, event.event_id), "pi-event", event)
            if outcome.status is not ConnectorSubmissionStatus.ACCEPTED:
                return ConnectorRunCompletion(status=ConnectorRunStatus.INCOMPLETE, checkpoint=session.checkpoint)
            imported[event.event_id] = _fingerprint(event.record)
        return ConnectorRunCompletion(status=ConnectorRunStatus.COMPLETE, checkpoint=checkpoint.model_dump(mode="json"))


__all__ = [
    "PI_EVENT_SOURCE_DEFINITION",
    "PiEventInput",
    "PiEventSource",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
]
