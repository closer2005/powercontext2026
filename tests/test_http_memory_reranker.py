import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory.http_reranker import HTTPMemoryReranker
from powercontext.builtin.artifacts.memory.models import MemoryHit


def candidate():
    return MemoryHit(
        memory_ref=ArtifactRef(family="memory", artifact_id="m", revision=1),
        entry_id="entry",
        entry_version_id="version",
        text="evidence",
        score=1.0,
        matched_by=("fts",),
    )


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"scores": None},
        {"scores": [{"rank": True, "score": 1.0}]},
        {"scores": [{"rank": "1", "score": 1.0}]},
        {"scores": [{"rank": 1.0, "score": 1.0}]},
        {"scores": [{"rank": 1, "score": True}]},
        {"scores": [{"rank": 1, "score": "0.5"}]},
        {"scores": [{"rank": 1}]},
    ],
)
async def test_response_types_are_not_coerced(payload):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://scorer.invalid", client=client).rerank("q", (candidate(),), 1)


async def test_http_status_error_preserves_request_and_response():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            await HTTPMemoryReranker("https://scorer.invalid", client=client).rerank("q", (candidate(),), 1)
        assert error.value.response.status_code == 503
        assert error.value.request.url == "https://scorer.invalid"


async def test_later_batch_cannot_reuse_an_earlier_global_rank():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"scores": [{"rank": 1, "score": 0}]}))
    ) as client:
        with pytest.raises(ValueError):
            await HTTPMemoryReranker("https://scorer.invalid", client=client, batch_size=1).rerank(
                "q", (candidate(), candidate()), 1
            )
