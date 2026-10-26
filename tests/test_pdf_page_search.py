# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Real Memory retrieval must preserve complementary PDF pages and document scope."""

import io
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.artifacts.memory.canonical import entry_content_hash, normalize_entry_text, normalize_text
from powercontext.builtin.artifacts.memory.protocols import MemoryCandidateRequest
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    SearchMemoryRequest,
    SubmitSourceObservation,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceObservation,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY


class PDFEvidencePipeline:
    async def extract(self, request: MemoryCandidateRequest, /) -> tuple[MemoryEntryInput, ...]:
        entries = []
        for source in request.sources:
            assert isinstance(source, SourceObservation)
            projection = source.projection(TEXT_EVIDENCE_PROJECTION_KEY)
            assert isinstance(projection, dict)
            content = projection["content"]
            assert isinstance(content, str)
            entries.append(MemoryEntryInput(kind="source-evidence", text=content, sources=(source,)))
        return tuple(entries)


def test_pdf_layout_padding_and_split_runs_preserve_page_boundaries() -> None:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })
    resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    content = (
        b"BT /F1 12 Tf 10 150 Td (Net\240income 42) Tj "
        b"0 -14 Td (Merchant\240cash\240advance\240r) Tj "
        b"0 -14 Td (eceivable 10) Tj ET",
        b"BT /F1 12 Tf 10 150 Td (Regular spaces 17) Tj ET",
    )
    for data in content:
        page = writer.add_blank_page(width=500, height=200)
        page[NameObject("/Resources")] = resources
        stream = DecodedStreamObject()
        stream.set_data(data)
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = io.BytesIO()
    writer.write(buffer)
    pages = parse_pdf_document(PDFDocumentInput(document_id="spacing", content=buffer.getvalue()))
    assert [page.page_number for page in pages] == [1, 2]
    assert pages[0].text == "Netincome 42\nMerchantcashadvancereceivable 10"
    assert pages[1].text == "Regular spaces 17"


def test_complete_pdf_body_limit_preserves_ordinary_memory_validation() -> None:
    body = "财报 page " * 2000
    references = ({"source_type": "pdf-page", "source_id": "captured-page"},)
    assert len(body.encode("utf-8")) > 8192
    assert normalize_entry_text(body, source_refs=references) == body.strip()
    assert entry_content_hash(kind="source-evidence", text=body, source_refs=references, artifact_refs=())
    with pytest.raises(ValueError, match="8192 UTF-8 bytes"):
        normalize_text(body)
    with pytest.raises(ValueError, match="8192 UTF-8 bytes"):
        normalize_entry_text(body, source_refs=({"source_type": "csv-row", "source_id": "row"},))
    with pytest.raises(ValueError, match="1048576 UTF-8 bytes"):
        normalize_entry_text("x" * (1024 * 1024 + 1), source_refs=references)


async def test_complementary_statements_survive_restart_and_other_document_noise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'pdf.db'}"))
    texts = [
        (
            "ALPHA_2024_10K",
            1,
            "Forward-looking information.\n" * 400
            + "\nConsolidated Statements of Income\nOperating profit 40. Net revenue 200.",
        ),
        (
            "ALPHA_2024_10K",
            2,
            "Consolidated Statements of Cash Flows\nDepreciation and amortization 10. Capital expenditures 5.",
        ),
        ("BETA_2024_10K", 1, "Consolidated Statements of Income\nOperating income and net sales."),
        (
            "BETA_2024_10K",
            2,
            "Consolidated Statements of Cash Flows\nDepreciation and amortization. Capital expenditures.",
        ),
        *(
            ("ALPHA_2024_10K", number, "Operating activities and EBITDA. Depreciation amortization capex " * 8)
            for number in range(3, 30)
        ),
    ]
    locations = {}
    async with open_builtin_runtime(config, candidate_pipeline=PDFEvidencePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="PDF", idempotency_key="reports"))
        other = await runtime.scopes.create(ScopeDraft(title="Other", summary="PDF", idempotency_key="other"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for scope_id, rows in ((scope.scope_id, texts), (other.scope_id, [("ALPHA_2024_10K", 99, texts[0][2])])):
            for document_id, page_number, text in rows:
                page = PDFPageInput(
                    document_id=document_id, document_sha256="1" * 64, page_number=page_number, text=text
                )
                observation = project_source_for_transport(registry, await registry.resolve(page))
                locations[observation.name] = (document_id, page_number)
                await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope_id, observation=observation))
            memory = runtime.memory.for_scope(scope_id)
            for _ in range(len(rows) + 1):
                if not (await memory.flush()).processed:
                    break
            else:
                pytest.fail("PDF evidence did not drain")
    async with open_builtin_runtime(config) as runtime:
        memory = runtime.memory.for_scope(scope.scope_id)
        for company in ("Alpha", "Beta"):
            citations = await search_pdf_pages(
                memory,
                f"Calculate FY2024 EBITDA less capex for {company}, using operating income and cash flows.",
                limit=6,
            )
            returned = set()
            for citation in citations:
                entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                returned.update(locations[source.source_id] for source in entry.sources)
            document = f"{company.upper()}_2024_10K"
            assert {(document, 1), (document, 2)} <= returned
            assert all(item[0] == document and item[1] != 99 for item in returned)
            assert len(citations) <= 6 and len(returned) == len(citations)
        # A lexical admission filter can yield no candidates even though real
        # PDF pages exist. Retrieval must still cite the current scoped entries.
        empty_shortlist = await memory.search(SearchMemoryRequest(query="nonexistentvocabulary", mode="fts"))
        assert not empty_shortlist.hits
        monkeypatch.setattr(memory, "search", AsyncMock(return_value=empty_shortlist))
        citations = await search_pdf_pages(
            memory, "Calculate FY2024 EBITDA for Alpha from operating income and cash flows.", limit=6
        )
        recovered = set()
        for citation in citations:
            entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
            recovered.update(locations[source.source_id] for source in entry.sources)
        assert {("ALPHA_2024_10K", 1), ("ALPHA_2024_10K", 2)} <= recovered
        assert all(document == "ALPHA_2024_10K" and number != 99 for document, number in recovered)
