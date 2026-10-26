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
from powercontext.sources.pdf_text import extract_positioned_text
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


def _normalize_pdf_spacing(text: str) -> str:
    """Remove encoded layout padding and reconnect short split font runs.

    Some financial PDFs paint nonbreaking padding between text fragments and
    split a single word across consecutive runs. Preserve ordinary spaces and
    physical page boundaries; only normalize those encoded layout separators.
    """
    if "\xa0" in text:
        text = re.sub(r"(?<=\xa0)([a-zA-Z]{1,6})\n(?=[a-z])", r"\1", text)
        text = text.replace("\xa0", "")
    return text


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every physical page before returning any result."""
    digest = hashlib.sha256(value.content).hexdigest()
    try:
        if not value.content.startswith(b"%PDF-") or b"%%EOF" not in value.content[-4096:]:
            raise ValueError("Missing PDF header or end marker")  # noqa: TRY003, TRY301
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a password")  # noqa: TRY003, TRY301
        visited: set[int] = set()
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=number,
                text=_normalize_pdf_spacing(extract_positioned_text(page, visited)),
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

# Query instructions and units contribute little evidence about a financial page.
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
    "who",
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
    "any",
    "as",
    "it",
    "that",
    "if",
    "then",
    "state",
    "explicitly",
    "directly",
    "outlined",
    "shown",
    "details",
    "use",
    "using",
    "can",
    "only",
    "give",
    "respond",
    "response",
    "question",
    "assuming",
    "assume",
    "perspective",
    "investment",
    "analyst",
    "million",
    "millions",
    "usd",
    "dollars",
    "percent",
    "quantity",
    "define",
    "less",
    "most",
    "important",
    "ongoing",
    "materially",
    "s",
    "primary",
    "roughly",
    "than",
    "more",
    "each",
])

# Short queries deliberately fit the public Memory API's lexical admission floor.
# Each aspect has alternate vocabulary and a heading cue; none identifies a
# particular company, document, question or annotated evidence location.
_ASPECTS = (
    (
        r"\b(income|earnings|profit|ebitda|margin|cogs|inventory\s+turnover|capital.intensive|restructur\w*)\b|\bp\s*&\s*l\b",
        ("statements income", "operating profit"),
        r"(?m)^\s*(?:(?:condensed|consolidated|combined)\s+)*statements?\s+(?:of\s+)?(?:income|operations|earnings|loss)\b",
    ),
    (
        r"\b(cash\s*flow\w*|ebitda|depreciation|amorti[sz]ation|capex|capital.intensive|capital\s+expenditure\w*)\b|\bd\s*&\s*a\b",
        ("cash flows", "depreciation amortization"),
        r"(?m)^\s*(?:(?:condensed|consolidated|combined)\s+)*statements?\s+(?:of\s+)?cash\s*flows?\b",
    ),
    (
        r"\b(revenue\w*|sales|margin|growth)\b",
        ("net revenue", "net sales"),
        r"(?m)^\s*(?:net\s+(?:sales|revenue)|(?:consolidated\s+)?statements?\s+(?:of\s+)?(?:income|operations))\b",
    ),
    (
        r"\b(balance\s+sheet\w*|financial\s+position|assets?|liabilit\w*|debt|equity|working\s+capital|"
        r"(?:quick|current)\s+ratio|liquidity|inventory|payables?|capital.intensive|leverage)\b",
        ("balance sheets", "assets liabilities"),
        r"(?m)^\s*(?:(?:condensed|consolidated|combined)\s+)*(?:balance\s+sheets?|"
        r"statements?\s+(?:of\s+)?financial\s+(?:position|condition))\b",
    ),
    (
        r"\b(geograph\w*|countr\w*|region\w*|primarily\s+operat\w*)\b",
        (
            "geographic segments",
            "international operations",
            "countries divisions",
            "north america europe asia africa",
            "latin america middle east pacific",
        ),
        r"(?m)^\s*(?:item\s+\d+[.:]?\s*)?(?:geograph\w*|business\b|our\s+(?:divisions|business))",
    ),
    (
        r"\b(legal|litigation|lawsuit\w*|battles?|contingen\w*)\b",
        ("legal proceedings", "litigation contingencies", "lawsuits claims"),
        r"(?m)^\s*(?:(?:item|note)\s+\d+[.:]?\s*)?(?:legal\s+proceedings|litigation|(?:commitments\s+and\s+)?contingencies)\b",
    ),
    (
        r"\b(restructur\w*|impairment\w*)\b",
        ("restructuring charges", "restructuring costs"),
        r"(?m)^\s*(?:(?:note\s+)?\d+[.:]?\s*)?(?:restructuring|impairment)\b",
    ),
    (
        r"\b(tax|taxes|taxation)\b",
        ("income taxes", "effective tax"),
        r"(?m)^\s*(?:(?:note\s+)?\d+[.:]?\s*)?(?:income\s+taxes|effective\s+tax)\b",
    ),
    (
        r"\b(dividend\w*|repurchase\w*|buybacks?|shares?|stock)\b",
        ("shares repurchased", "dividends stock"),
        r"(?m)^\s*(?:dividends|repurchases|stockholders|shareholders)\b",
    ),
    (
        r"\b(segment\w*|categor\w*|customers?|products?|services?|divisions?)\b",
        ("business segments", "products services", "principal customers"),
        r"(?m)^\s*(?:(?:summary\s+of\s+)?business\s+segments?|segments?\s+(?:data|information)|our\s+(?:customers|business))\b",
    ),
    (
        r"\b(cyclic\w*|season\w*)\b",
        ("cyclical demand", "seasonal business"),
        r"(?m)^\s*(?:cyclic\w*|season\w*|business|risk\s+factors)\b",
    ),
)


def _tokens(text: str) -> list[str]:
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    terms = re.findall(r"[a-z]+|\d+", text.lower())
    # Light inflection normalization affects ranking, while Memory receives the
    # original words and explicit vocabulary alternatives above.
    return [
        "cyclic"
        if term.startswith("cyclic")
        else term[:-3] + "y"
        if len(term) > 5 and term.endswith("ies")
        else term[:-1]
        if len(term) > 4 and term.endswith("s") and not term.endswith(("ss", "us", "is"))
        else term
        for term in terms
    ]


def _query_weights(
    raw_terms: tuple[str, ...],
    label_terms: set[str],
    aspects: tuple[tuple[str, tuple[str, ...], str], ...],
) -> dict[str, float]:
    weights = {term: 1.0 for term in _tokens(" ".join(raw_terms)) if not term.isdigit() and term not in label_terms}
    for _, alternatives, _ in aspects:
        for term in _tokens(" ".join(alternatives)):
            if term not in _NOISE and term not in label_terms:
                weights.setdefault(term, 0.4)
    return weights


def _rank_pdf_candidates(
    candidates: dict[tuple[str, str], tuple[MemoryCitation, str]],
    votes: dict[tuple[str, str], float],
    raw_terms: tuple[str, ...],
    aspects: tuple[tuple[str, tuple[str, ...], str], ...],
    question: str,
    limit: int,
) -> list[tuple[str, str]]:
    """Rank retrieved pages with document alignment and requested-aspect coverage."""
    labels = {key: text.partition("\n")[0].lower() for key, (_, text) in candidates.items()}
    bodies = {key: text.partition("\n")[2] for key, (_, text) in candidates.items()}
    question_words = set(re.findall(r"[a-z0-9]+", question.lower()))
    question_compact = "".join(re.findall(r"[a-z0-9]+", question.lower()))
    generic_labels = {"10k", "10q", "annual", "report", "form", "financial"}
    acronyms = {term.lower() for term in re.findall(r"\b[A-Z]{2,7}\b", question)} - {"fy", "usd"}

    def matches_document(label: str) -> bool:
        names = [term for term in re.findall(r"[a-z0-9]+", label) if term not in generic_labels and not term.isdigit()]
        return any(
            term in question_words
            or (len(term) >= 3 and term in question_compact)
            or any(len(short) >= 3 and term.startswith(short) for short in acronyms)
            for term in names
        )

    matched = {key for key, label in labels.items() if matches_document(label)}
    if not matched and acronyms:
        # Natural queries may use an abbreviation absent from a compact file
        # label. Infer it only from the persisted report's own occurrences.
        alias_labels = {
            labels[key]
            for key in candidates
            if any(re.search(r"\b" + re.escape(alias) + r"\b", bodies[key], re.IGNORECASE) for alias in acronyms)
        }
        if len(alias_labels) == 1:
            matched = {key for key in candidates if labels[key] in alias_labels}
    eligible = matched or set(candidates)
    counts = {key: Counter(_tokens(bodies[key])) for key in eligible}
    lengths = {key: sum(value.values()) for key, value in counts.items()}
    numeric_density = {
        key: sum(count for term, count in value.items() if term.isdigit()) / max(lengths[key], 1)
        for key, value in counts.items()
    }
    average = sum(lengths.values()) / max(len(lengths), 1)
    frequencies = Counter(term for value in counts.values() for term in value)
    label_terms = set(_tokens(" ".join(labels[key] for key in eligible)))
    weights = _query_weights(raw_terms, label_terms, aspects)
    fiscal_years = re.findall(r"\bfy\s*((?:19|20)\d{2})\b", question, re.IGNORECASE)
    requested_years = fiscal_years or re.findall(r"\b(?:19|20)\d{2}\b", question)
    report_year = max(requested_years, default="")
    year_alignment = {
        key: 8.0 if report_year and report_year in re.findall(r"(?:19|20)\d{2}", labels[key]) else 0.0
        for key in eligible
    }

    def lexical_score(key: tuple[str, str], terms: dict[str, float]) -> float:
        total = 0.0
        for term, weight in terms.items():
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

    scores = {key: lexical_score(key, weights) + votes[key] + year_alignment[key] for key in eligible}
    ordered: list[tuple[str, str]] = []
    # Reserve at most half the output for separate requested financial aspects.
    # A cash-flow-heavy question must still be able to retrieve its income page.
    coverage_budget = min(limit // 2, len(aspects) * 2)
    for _, alternatives, heading in aspects:
        terms = {term: 1.0 for term in _tokens(" ".join(alternatives)) if term not in _NOISE}
        aspect_scores = {
            key: lexical_score(key, terms)
            + 8.0 * _has_heading(heading, bodies[key]) * (1 + min(2 * numeric_density[key], 1.0))
            + year_alignment[key]
            for key in eligible
        }
        for key in sorted(eligible, key=lambda key: (-aspect_scores[key], -scores[key], key))[:2]:
            if aspect_scores[key] > 0 and key not in ordered and len(ordered) < coverage_budget:
                ordered.append(key)
    ordered.extend(key for key in sorted(eligible, key=lambda key: (-scores[key], key)) if key not in ordered)
    return ordered


def _has_heading(pattern: str, text: str) -> bool:
    """Recognize headings whose font runs attach them to a company-name prefix."""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    compact_pattern = pattern.replace(r"\s+", r"\s*")
    return bool(
        re.search(pattern, text, re.IGNORECASE)
        or re.search(pattern.removeprefix(r"(?m)^\s*"), text[:700], re.IGNORECASE)
        or re.search(compact_pattern, text, re.IGNORECASE)
        or re.search(compact_pattern.removeprefix(r"(?m)^\s*"), text[:700], re.IGNORECASE)
    )


async def _persisted_pdf_candidates(
    memory: ScopedMemoryApplication,
) -> dict[tuple[str, str], tuple[MemoryCitation, str]]:
    """Read active PDF entry versions from the caller's scoped Memory head."""
    page = await memory.list()
    return {
        (record.entry.entry_id, record.entry.entry_version_id): (record.citation, record.entry.text)
        for record in page.entries
        if any(source.source_type == "pdf-page" for source in record.entry.sources)
    }


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Retrieve real pages and retain evidence for complementary query aspects."""
    from powercontext.builtin.runtime.models import GetMemoryEntryRequest, SearchMemoryRequest

    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a nonnegative integer")  # noqa: TRY003
    if limit == 0 or not question.strip():
        return ()
    raw_terms = tuple(dict.fromkeys(term for term in re.findall(r"[a-z]+|\d+", question.lower()) if term not in _NOISE))
    aspects = tuple(aspect for aspect in _ASPECTS if re.search(aspect[0], question.lower()))
    # A fixed-size lexical shortlist can omit the relevant statement when many
    # reports repeat the same financial vocabulary. Read the active, scoped
    # head through the public API so offline ranking can consider every real
    # PDF page. Citations come from persisted entry records, never source IDs
    # reconstructed outside Memory.
    candidates = await _persisted_pdf_candidates(memory)
    if not candidates:
        return ()
    votes = dict.fromkeys(candidates, 0.0)
    found = await memory.search(SearchMemoryRequest(query=" ".join(raw_terms[:24]) or question, mode="fts", limit=128))
    for rank, hit in enumerate(found.hits):
        key = (hit.entry_id, hit.entry_version_id)
        if key in candidates:
            votes[key] = 1 / (60 + rank)
    ordered = _rank_pdf_candidates(candidates, votes, raw_terms, aspects, question, limit)
    results: list[MemoryCitation] = []
    seen: set[tuple[str, str]] = set()
    for key in ordered:
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
