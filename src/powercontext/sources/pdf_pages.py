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


"""Complete captured PDF pages and offline, citation-preserving page retrieval."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
from collections import Counter
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, Field, field_validator
from pypdf import PdfReader

from powercontext.artifacts import MemoryCitation
from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import ScopedMemoryApplication


class PDFDocumentInput(BaseModel):
    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be blank")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    document_id: str = Field(min_length=1)
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1, strict=True)
    text: str

    @field_validator("document_id")
    @classmethod
    def nonblank_id(cls, value: str) -> str:
        return PDFDocumentInput.nonblank_id(value)


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page before returning any result."""
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        if not value.content.startswith(b"%PDF-") or b"%%EOF" not in value.content[-4096:]:
            raise ValueError("Missing PDF header or end marker")  # noqa: TRY003, TRY301
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")  # noqa: TRY003, TRY301
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=page.extract_text() or "",
            )
            for number, page in enumerate(reader.pages, 1)
        )
        if not pages:
            raise ValueError("PDF contains no pages")  # noqa: TRY003, TRY301
    except Exception as error:
        raise ValueError("Cannot completely parse PDF document") from error  # noqa: TRY003
    return pages


class PDFPageSource(Source, PDFPageInput):
    """A full, immutable physical page, including its document revision."""


class _PDFPageAdapter:
    name = "pdf-page"
    input_class = PDFPageInput
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        identity = json.dumps(
            [value.document_id, value.document_sha256, value.page_number], ensure_ascii=False, separators=(",", ":")
        )
        return PDFPageSource(
            name="pdf:" + hashlib.sha256(identity.encode("utf-8")).hexdigest(),
            materialization=SourceMaterialization.CAPTURED,
            **value.model_dump(),
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput.model_validate(source.model_dump())


class _PDFTextProjection:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = cast(
    SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput],
    AdapterSourceDefinition(_PDFPageAdapter(), projections=(_PDFTextProjection(),)),
)

_NOISE = frozenset([
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "to",
    "of",
    "for",
    "and",
    "or",
    "by",
    "from",
    "with",
    "what",
    "which",
    "how",
    "does",
    "do",
    "did",
    "is",
    "was",
    "are",
    "were",
    "has",
    "have",
    "had",
    "its",
    "their",
    "company",
    "year",
    "fiscal",
    "fy",
    "please",
    "calculate",
    "based",
    "according",
    "provide",
    "answer",
    "statement",
    "statements",
    "report",
    "reported",
    "financial",
    "annual",
    "10",
    "k",
    "10k",
])
_FACETS = (
    (r"\b(ebitda|depreciation|amortization)\b", "operating income depreciation amortization"),
    (r"\b(capex|capital expenditure|capital spending)\b", "capital expenditures purchases property plant equipment"),
    (r"\b(geograph|countr|region|primarily operat)", "geographic segments countries international operations"),
    (r"\b(legal|litigation|lawsuit|battles)\b", "legal proceedings litigation contingencies"),
    (r"\brestructur", "restructuring charges costs impairment"),
    (r"\bmargin\b", "net revenue sales operating income"),
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+", text.lower())


async def search_pdf_pages(  # noqa: C901
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Retrieve complementary lexical facets, then rank complete, persisted pages.

    Financial terminology expansion is independent of document identity and never
    consults answers or page annotations. Every returned identity came from search.
    """
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a nonnegative integer")  # noqa: TRY003
    if limit == 0 or not question.strip():
        return ()
    terms = tuple(dict.fromkeys(token for token in _tokens(question) if token not in _NOISE))
    facets = [text for pattern, text in _FACETS if re.search(pattern, question.lower())]
    queries = list(dict.fromkeys([" ".join(terms[:24]), *facets]))
    # Shorter overlapping queries rescue evidence that lacks most question words.
    topical = [term for term in terms if not term.isdigit()]
    queries.extend(" ".join(topical[start : start + 4]) for start in range(0, len(topical), 3))
    candidates: dict[tuple[str, str], tuple[MemoryCitation, str]] = {}
    ranks: Counter[tuple[str, str]] = Counter()
    for query in dict.fromkeys(queries):
        if not query:
            continue
        found = await memory.search(SearchMemoryRequest(query=query, mode="fts", limit=100))
        for rank, hit in enumerate(found.hits):
            key = (hit.entry_id, hit.entry_version_id)
            candidates[key] = (
                MemoryCitation(memory_ref=hit.memory_ref, entry_id=hit.entry_id, entry_version_id=hit.entry_version_id),
                hit.text,
            )
            ranks[key] += 1 / (60 + rank)
    if not candidates:
        return ()
    counts = {key: Counter(_tokens(text)) for key, (_, text) in candidates.items()}
    lengths = {key: sum(value.values()) for key, value in counts.items()}
    average = sum(lengths.values()) / len(lengths)
    weights = Counter(dict.fromkeys(terms, 1.0))
    for facet in facets:
        for term in _tokens(facet):
            weights[term] += 0.45
    frequencies = Counter(term for value in counts.values() for term in value)

    def score(key: tuple[str, str]) -> float:
        total = ranks[key]
        for term, weight in weights.items():
            frequency = counts[key][term]
            if frequency:
                inverse = math.log(1 + (len(counts) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
                total += (
                    weight
                    * inverse
                    * frequency
                    * 2.2
                    / (frequency + 1.2 * (0.25 + 0.75 * lengths[key] / max(average, 1)))
                )
        return total

    results: list[MemoryCitation] = []
    seen: set[tuple[str, str]] = set()
    for key in sorted(candidates, key=lambda key: (-score(key), key)):
        citation = candidates[key][0]
        entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
        pages = tuple(
            (source.source_type, source.source_id) for source in entry.sources if source.source_type == "pdf-page"
        )
        if not pages or any(page in seen for page in pages):
            continue
        seen.update(pages)
        results.append(citation)
        if len(results) >= limit:
            break
    return tuple(results)
