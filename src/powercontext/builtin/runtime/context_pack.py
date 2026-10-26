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

"""Portable context packs and independently verifiable prefix deltas."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass

_PACK_SCHEMA = "powercontext.context-pack.v1"
_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"


class ContextPackError(ValueError):
    """Invalid context bytes, wire data, or delta ancestry."""


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ContextPackError("Duplicate JSON fields")  # noqa: TRY003
    return result


def _decode(raw: bytes, schema: str, fields: set[str]) -> dict[str, object]:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    except (UnicodeError, ValueError, AttributeError) as error:
        raise ContextPackError("Invalid context pack JSON") from error  # noqa: TRY003
    if not isinstance(value, dict) or set(value) != fields or value.get("schema") != schema:
        raise ContextPackError("Invalid context pack schema or fields")  # noqa: TRY003
    return value


def _items(items: tuple[bytes, ...]) -> list[str]:
    if not isinstance(items, tuple) or any(not isinstance(item, bytes) for item in items):
        raise ContextPackError("Context chunks must be a tuple of bytes")  # noqa: TRY003
    try:
        for item in items:
            item.decode("utf-8")
    except UnicodeError as error:
        raise ContextPackError("Context chunks must be valid UTF-8") from error  # noqa: TRY003
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(value: object) -> tuple[bytes, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ContextPackError("Wire chunks must be Base64 string arrays")  # noqa: TRY003
    try:
        result = tuple(base64.b64decode(item, validate=True) for item in value)
    except (ValueError, binascii.Error) as error:
        raise ContextPackError("Invalid Base64 context chunk") from error  # noqa: TRY003
    if _items(result) != value:
        raise ContextPackError("Context chunks must use standard Base64 encoding")  # noqa: TRY003
    return result


def _validate_digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ContextPackError("Invalid context digest")  # noqa: TRY003
    return value


@dataclass(frozen=True, slots=True)
class ContextPack:
    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...]) -> ContextPack:
        payload = {"schema": _PACK_SCHEMA, "items": _items(items)}
        digest = "sha256:" + hashlib.sha256(_json(payload)).hexdigest()
        byte_count = 0
        while True:
            size = len(_json({**payload, "digest": digest, "byte_count": byte_count}))
            if size == byte_count:
                return cls(items, digest, byte_count)
            byte_count = size

    @classmethod
    def from_content(cls, content: str | bytes | None, *, chunk_bytes: int = 512) -> ContextPack:
        if type(chunk_bytes) is not int or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")  # noqa: TRY003
        try:
            raw = content.encode("utf-8") if isinstance(content, str) else content
            if raw is None:
                raw = b""
            if not isinstance(raw, bytes):
                raise ContextPackError("Context content must be text or bytes")  # noqa: TRY003
            raw.decode("utf-8")
        except UnicodeError as error:
            raise ContextPackError("Context must be valid UTF-8") from error  # noqa: TRY003
        items = []
        start = 0
        while start < len(raw):
            end = min(start + chunk_bytes, len(raw))
            while end < len(raw) and end > start and raw[end] & 0xC0 == 0x80:
                end -= 1
            if end == start:
                raise ContextPackError("chunk_bytes cannot hold the next UTF-8 character")  # noqa: TRY003
            items.append(raw[start:end])
            start = end
        return cls.build(tuple(items))

    def to_bytes(self) -> bytes:
        return _json({
            "schema": _PACK_SCHEMA,
            "items": _items(self.items),
            "digest": self.digest,
            "byte_count": self.byte_count,
        })

    @classmethod
    def from_bytes(cls, raw: bytes) -> ContextPack:
        value = _decode(raw, _PACK_SCHEMA, {"schema", "items", "digest", "byte_count"})
        pack = cls.build(_decode_items(value["items"]))
        if (
            type(value["byte_count"]) is not int
            or value["byte_count"] != pack.byte_count
            or value["digest"] != pack.digest
        ):
            raise ContextPackError("Context pack digest or byte count does not match")  # noqa: TRY003
        return pack


def _validate_pack(pack: ContextPack) -> None:
    if not isinstance(pack, ContextPack) or ContextPack.build(pack.items) != pack:
        raise ContextPackError("Invalid context pack")  # noqa: TRY003


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack) -> ContextPackDelta:
        _validate_pack(base)
        _validate_pack(target)
        prefix = 0
        for old, new in zip(base.items, target.items, strict=False):
            if old != new:
                break
            prefix += 1
        return cls(base.digest, target.digest, prefix, target.items[prefix:])

    def to_bytes(self) -> bytes:
        _validate_digest(self.base_digest)
        _validate_digest(self.target_digest)
        if type(self.prefix_items) is not int or self.prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")  # noqa: TRY003
        return _json({
            "schema": _DELTA_SCHEMA,
            "base_digest": self.base_digest,
            "target_digest": self.target_digest,
            "prefix_items": self.prefix_items,
            "appended": _items(self.appended),
        })

    @property
    def byte_count(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, raw: bytes) -> ContextPackDelta:
        value = _decode(raw, _DELTA_SCHEMA, {"schema", "base_digest", "target_digest", "prefix_items", "appended"})
        base_digest = _validate_digest(value["base_digest"])
        target_digest = _validate_digest(value["target_digest"])
        prefix = value["prefix_items"]
        if type(prefix) is not int or prefix < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")  # noqa: TRY003
        return cls(base_digest, target_digest, prefix, _decode_items(value["appended"]))


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta) -> ContextPack:
    """Rebuild a complete target using only the supplied base and wire delta."""

    _validate_pack(base)
    delta.to_bytes()
    if base.digest != delta.base_digest or delta.prefix_items > len(base.items):
        raise ContextPackError("Context delta base or prefix does not match")  # noqa: TRY003
    target = ContextPack.build(base.items[: delta.prefix_items] + delta.appended)
    if target.digest != delta.target_digest:
        raise ContextPackError("Context delta target digest does not match")  # noqa: TRY003
    return target


__all__ = ["ContextPack", "ContextPackDelta", "ContextPackError", "apply_context_pack_delta"]
