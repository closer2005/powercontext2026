import json

import pytest

from powercontext.builtin.runtime.context_pack import (
    ContextPack,
    ContextPackDelta,
    ContextPackError,
    apply_context_pack_delta,
)


@pytest.mark.parametrize("capacity", [4, 5, 7, 16, 512])
def test_unicode_chunks_obey_byte_bounds_and_preserve_every_character(capacity):
    content = "A海洋🙂\r\n\x00e\u0301" * 137
    pack = ContextPack.from_content(content, chunk_bytes=capacity)
    assert b"".join(pack.items) == content.encode()
    assert all(len(chunk) <= capacity and chunk.decode().encode() == chunk for chunk in pack.items)
    assert ContextPack.from_bytes(pack.to_bytes()) == pack


@pytest.mark.parametrize("capacity", [True, 0, -1, 1.5, "512"])
def test_chunk_capacity_is_a_strict_positive_integer(capacity):
    with pytest.raises(ContextPackError):
        ContextPack.from_content("", chunk_bytes=capacity)


@pytest.mark.parametrize("encoded", ["!!!!", "YQ", "YR==", "/w==", " YQ=="])
def test_wire_chunks_reject_noncanonical_base64_and_invalid_utf8(encoded):
    pack = ContextPack.build(())
    delta = ContextPackDelta.between(pack, pack)
    payload = {**json.loads(delta.to_bytes()), "appended": [encoded]}
    with pytest.raises(ContextPackError):
        ContextPackDelta.from_bytes(json.dumps(payload).encode())


def test_none_empty_context_and_independent_receiver():
    empty = ContextPack.from_content(None)
    assert empty.items == ()
    pack = ContextPack.from_content("some evidence " * 100)
    delta = ContextPackDelta.between(pack, empty)
    restored = apply_context_pack_delta(
        ContextPack.from_bytes(pack.to_bytes()), ContextPackDelta.from_bytes(delta.to_bytes())
    )
    assert restored == empty


def test_noncanonical_json_may_decode_but_duplicate_fields_and_wrong_count_fail():
    pack = ContextPack.from_content("evidence")
    payload = json.loads(pack.to_bytes())
    assert ContextPack.from_bytes(json.dumps(payload, indent=2).encode()) == pack
    payload["byte_count"] += 1
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(json.dumps(payload).encode())
    raw = pack.to_bytes().replace(b'{"byte_count":', b'{"byte_count":0,"byte_count":', 1)
    with pytest.raises(ContextPackError):
        ContextPack.from_bytes(raw)
