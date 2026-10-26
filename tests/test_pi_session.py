import json

import pytest

from powercontext.sources import ConnectorBinding, SourceDefinitionRegistry, SourceRef
from powercontext.sources.connectors import ConnectorLifecycle
from powercontext.sources.pi_session import (
    PI_EVENT_SOURCE_DEFINITION,
    PiSessionConnector,
    PiSessionInput,
    parse_pi_session,
)


def archive(records, session_id="session"):
    return "\n".join(
        json.dumps(row, ensure_ascii=False) for row in [{"type": "session", "version": 3, "id": session_id}, *records]
    ).encode()


def message(event_id, parent, text):
    return {"type": "message", "id": event_id, "parentId": parent, "message": {"role": "user", "content": text}}


def test_json_string_line_separators_and_multiline_blocks_are_lossless():
    record = message("a", None, "before\u2028after\u2029end\n")
    events = parse_pi_session(PiSessionInput(content=archive([record])))
    assert events[0].content == "user: before\u2028after\u2029end\n"
    assert events[0].record == record


async def test_long_unicode_identity_and_delimiter_pairs_remain_distinct():
    registry = SourceDefinitionRegistry((PI_EVENT_SOURCE_DEFINITION,))
    pairs = [("a:b", "c"), ("a", "b:c"), ("会话" * 1000, "事件" * 1000)]
    sources = [
        await registry.resolve(parse_pi_session(PiSessionInput(content=archive([message(event, None, "x")], sid)))[0])
        for sid, event in pairs
    ]
    assert len({source.name for source in sources}) == len(sources)
    assert all(len(source.name) <= 256 for source in sources)


@pytest.mark.parametrize(
    "suffix",
    [
        b'{"type":"model_change","id":"off-branch","parentId":"missing"}',
        b'{"type":"model_change","id":"off-branch"}',
        b"null",
        b"{bad json}",
    ],
)
def test_selected_earlier_leaf_does_not_hide_invalid_later_records(suffix):
    raw = archive([message("root", None, "root")]) + b"\n" + suffix
    with pytest.raises(ValueError):
        parse_pi_session(PiSessionInput(content=raw, leaf_id="root"))


class Checkpoints:
    value = None

    async def load(self, binding):
        return self.value

    async def save(self, binding, checkpoint, *, expected):
        assert self.value == expected
        self.value = checkpoint


class Sink:
    def __init__(self):
        self.records = {}
        self.fail_on = None

    async def submit(self, binding, item_id, definition_name, value):
        if value.event_id == self.fail_on:
            raise OSError
        if item_id in self.records:
            assert self.records[item_id] == value
        self.records[item_id] = value
        return SourceRef(source_type=definition_name, source_id=item_id)


async def test_partial_sink_failure_keeps_checkpoint_and_replay_recovers(tmp_path):
    path = tmp_path / "session.jsonl"
    records = [message("root", None, "root"), message("tail", "root", "tail")]
    path.write_bytes(archive(records))
    sink, checkpoints = Sink(), Checkpoints()
    binding = ConnectorBinding(scope_id="s", binding_id="p", connector_name="pi-session-history", connector_version="1")
    sink.fail_on = "tail"
    with pytest.raises(OSError):
        await ConnectorLifecycle(sink=sink, checkpoints=checkpoints).run(PiSessionConnector(path), binding)
    assert checkpoints.value is None and len(sink.records) == 1
    sink.fail_on = None
    result = await ConnectorLifecycle(sink=sink, checkpoints=checkpoints).run(PiSessionConnector(path), binding)
    assert len(sink.records) == 2 and result.committed_checkpoint is not None
    replay = await ConnectorLifecycle(sink=sink, checkpoints=checkpoints).run(PiSessionConnector(path), binding)
    assert replay.items == ()
    committed = checkpoints.value
    records[-1]["message"]["content"] = "modified abandoned branch"
    records.append(message("other", "root", "other"))
    path.write_bytes(archive(records))
    with pytest.raises(ValueError):
        await ConnectorLifecycle(sink=sink, checkpoints=checkpoints).run(PiSessionConnector(path, "other"), binding)
    assert checkpoints.value == committed and len(sink.records) == 2
