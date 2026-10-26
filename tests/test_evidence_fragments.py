import json

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.runtime.models import PrepareContextRequest
from powercontext.builtin.runtime.prepared_context import PreparedContextBuilder, PreparedMemoryCandidates


def group(scope, text):
    memory = ArtifactRef(family="memory", artifact_id="shared-id", revision=1)
    return PreparedMemoryCandidates(
        scope_id=scope,
        memory_ref=memory,
        hits=(
            MemoryHit(
                memory_ref=memory,
                entry_id="entry",
                entry_version_id="version",
                text=text,
                score=1.0,
                matched_by=("fts",),
            ),
        ),
    )


def test_identical_artifact_ids_across_scopes_keep_distinct_origins():
    groups = (group("left", "Cobalt records the left reading."), group("right", "Cobalt records the right reading."))
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="cobalt", max_bytes=1800, evidence_selection=True),
        current_scope_id="left",
        memory_candidates=groups,
    )
    assert {fragment.address.memory.scope_id for fragment in result.fragments} == {"left", "right"}
    assert result.origins == tuple(fragment.address for fragment in result.fragments)
    for fragment in result.fragments:
        original = next(item.hits[0].text for item in groups if item.scope_id == fragment.address.memory.scope_id)
        assert fragment.text == original[fragment.start : fragment.end]


def test_adjacent_evidence_merges_without_fabricating_text_or_repeating_citations():
    text = "Cobalt sensor calibration is complete.  Cobalt sensor calibration uses 37 degrees.\n"
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="cobalt sensor calibration", max_bytes=1400, evidence_selection=True),
        current_scope_id="left",
        memory_candidates=(group("left", text),),
    )
    assert len(result.fragments) == 1
    fragment = result.fragments[0]
    assert fragment.text == text and fragment.start == 0 and fragment.end == len(text)
    assert result.context.content is not None
    payload = json.loads(result.context.content.splitlines()[-2])
    assert payload["items"][0]["content"] == text
    assert result.context.content_bytes == len(result.context.content.encode()) <= 1400


def test_too_small_budget_returns_an_empty_context_with_no_unbacked_origins():
    result = PreparedContextBuilder().build_scopes_result(
        request=PrepareContextRequest(query="cobalt", max_bytes=512, evidence_selection=True),
        current_scope_id="left",
        memory_candidates=(group("left", "Cobalt " + "evidence " * 500 + "."),),
    )
    assert result.context.content is None
    assert result.context.content_bytes == 0
    assert result.fragments == result.origins == ()
