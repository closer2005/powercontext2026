import asyncio

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import EmbeddingResult, InferenceUsage
from powercontext.builtin.inference.coalescing import CoalescingEmbeddingModel


class Provider:
    profile = EmbeddingProfile(profile_id="test", model="offline", dimension=1)

    def __init__(self):
        self.calls = []

    async def embed(self, texts):
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=tuple((float(len(text)),) for text in texts),
            usage=InferenceUsage(requests=3, input_tokens=7, output_tokens=2),
        )


async def test_late_waiter_shares_running_batch_even_with_cache_disabled():
    class Blocked(Provider):
        def __init__(self):
            super().__init__()
            self.started, self.release = asyncio.Event(), asyncio.Event()

        async def embed(self, texts):
            self.started.set()
            await self.release.wait()
            return await super().embed(texts)

    provider = Blocked()
    model = CoalescingEmbeddingModel(provider, cache_size=0, coalesce_ms=0)
    original = asyncio.create_task(model.embed(("text", "text")))
    await provider.started.wait()
    late = asyncio.create_task(model.embed(("text",)))
    await asyncio.sleep(0)
    original.cancel()
    with pytest.raises(asyncio.CancelledError):
        await original
    provider.release.set()
    assert (await late).vectors == ((4.0,),)
    assert provider.calls == [("text",)]
    await model.embed(("text",))
    assert provider.calls == [("text",), ("text",)]


async def test_failed_batch_does_not_discard_other_batches_or_cache_failure():
    class Flaky(Provider):
        async def embed(self, texts):
            self.calls.append(texts)
            if "bad" in texts:
                raise RuntimeError
            return EmbeddingResult(vectors=tuple((1.0,) for _ in texts))

    provider = Flaky()
    model = CoalescingEmbeddingModel(provider, max_batch_size=1, coalesce_ms=0)
    failed, success = await asyncio.gather(model.embed(("bad",)), model.embed(("good",)), return_exceptions=True)
    assert isinstance(failed, RuntimeError)
    assert isinstance(success, EmbeddingResult)
    assert success.vectors == ((1.0,),)
    assert (await model.embed(("good",))).usage.requests == 0
    with pytest.raises(RuntimeError):
        await model.embed(("bad",))
    assert provider.calls.count(("bad",)) == 2


async def test_each_waiter_charges_provider_usage_once_for_each_shared_batch():
    model = CoalescingEmbeddingModel(Provider(), max_batch_size=2, coalesce_ms=0)
    first, second = await asyncio.gather(model.embed(("a", "b", "c", "a")), model.embed(("b", "c")))
    for result in (first, second):
        assert result.usage == InferenceUsage(requests=6, input_tokens=14, output_tokens=4)


async def test_asymmetric_query_and_document_vectors_have_separate_cache_entries():
    class Asymmetric(Provider):
        async def embed_query(self, texts):
            self.calls.append(("query", *texts))
            return EmbeddingResult(vectors=tuple((-1.0,) for _ in texts))

    provider = Asymmetric()
    model = CoalescingEmbeddingModel(provider, coalesce_ms=0)
    assert (await model.embed(("text",))).vectors == ((4.0,),)
    assert (await model.embed_query(("text",))).vectors == ((-1.0,),)
    await model.embed_query(("text",))
    await model.embed(("text",))
    assert len(provider.calls) == 2
