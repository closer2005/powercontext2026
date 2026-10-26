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

"""Shared in-flight embedding batches and bounded successful-vector caching."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel, QueryEmbeddingModel, embed_query

_Key = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _ComputedVector:
    vector: EmbeddingVector
    batch: object
    usage: InferenceUsage


class CoalescingEmbeddingModel:
    """Share provider work on one event loop without sharing caller cancellation."""

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size <= 0:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")  # noqa: TRY003
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms must be a finite non-negative number")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[_Key, EmbeddingVector] = OrderedDict()
        self._inflight: dict[_Key, asyncio.Future[_ComputedVector]] = {}
        self._queued: dict[_Key, asyncio.Future[_ComputedVector]] = {}
        self._dispatcher: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        return await self._embed(texts, "document")

    async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        # Asymmetric providers must not reuse document vectors for query encoding.
        mode = "query" if isinstance(self._model, QueryEmbeddingModel) else "document"
        return await self._embed(texts, mode)

    async def _embed(self, texts: tuple[str, ...], mode: str) -> EmbeddingResult:
        loop = asyncio.get_running_loop()
        cached: dict[str, EmbeddingVector] = {}
        waiting: dict[str, asyncio.Future[_ComputedVector]] = {}
        for text in texts:
            key = (mode, text)
            if key in self._cache:
                cached[text] = self._cache[key]
                self._cache.move_to_end(key)
            else:
                future = self._inflight.get(key)
                if future is None:
                    future = loop.create_future()
                    # All callers may cancel; a later provider failure still needs observing.
                    future.add_done_callback(_observe_failure)
                    self._inflight[key] = future
                    self._queued[key] = future
                waiting[text] = future
        if self._queued and self._dispatcher is None:
            self._dispatcher = asyncio.create_task(self._dispatch())
        results = await asyncio.gather(*(asyncio.shield(future) for future in waiting.values()))
        vectors = dict(cached)
        batches: dict[object, InferenceUsage] = {}
        for text, result in zip(waiting, results, strict=True):
            vectors[text] = result.vector
            batches[result.batch] = result.usage
        usage = tuple(batches.values())
        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in texts),
            usage=InferenceUsage(
                requests=sum(item.requests for item in usage),
                input_tokens=_sum_tokens(tuple(item.input_tokens for item in usage)),
                output_tokens=_sum_tokens(tuple(item.output_tokens for item in usage)),
            ),
        )

    async def _dispatch(self) -> None:
        await asyncio.sleep(self._coalesce_seconds)
        queued = self._queued
        self._queued = {}
        self._dispatcher = None
        for mode in dict.fromkeys(key[0] for key in queued):
            items = [(key, future) for key, future in queued.items() if key[0] == mode]
            for offset in range(0, len(items), self._max_batch_size):
                task = asyncio.create_task(self._run_batch(mode, items[offset : offset + self._max_batch_size]))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _run_batch(self, mode: str, items: list[tuple[_Key, asyncio.Future[_ComputedVector]]]) -> None:
        texts = tuple(key[1] for key, _ in items)
        try:
            result = await (embed_query(self._model, texts) if mode == "query" else self._model.embed(texts))
            if len(result.vectors) != len(items):
                # Broadcast malformed provider responses through the same batch-failure path.
                raise ValueError("Embedding provider returned the wrong vector count")  # noqa: TRY003, TRY301
        except (Exception, asyncio.CancelledError) as error:
            for _, future in items:
                if not future.done():
                    future.set_exception(error)
        else:
            batch = object()
            for (key, future), vector in zip(items, result.vectors, strict=True):
                self._remember(key, vector)
                future.set_result(_ComputedVector(vector=vector, batch=batch, usage=result.usage))
        finally:
            for key, future in items:
                if self._inflight.get(key) is future:
                    del self._inflight[key]

    def _remember(self, key: _Key, vector: EmbeddingVector) -> None:
        if self._cache_size:
            self._cache[key] = vector
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)


def _sum_tokens(values: tuple[int | None, ...]) -> int | None:
    known = tuple(value for value in values if value is not None)
    return sum(known) if known else None


def _observe_failure(future: asyncio.Future[_ComputedVector]) -> None:
    if not future.cancelled():
        future.exception()


__all__ = ["CoalescingEmbeddingModel"]
