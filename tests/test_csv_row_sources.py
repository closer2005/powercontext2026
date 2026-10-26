from __future__ import annotations

import pytest

from powercontext.sources.csv_rows import CSVDocumentInput, CSVRowInput, csv_row_source_id, parse_csv_document


def test_identity_limit_applies_to_percent_encoded_components() -> None:
    assert len(csv_row_source_id("d", "k" * 250)) == 256
    assert len(csv_row_source_id("d", "汉" * 27)) == 249
    with pytest.raises(ValueError):
        csv_row_source_id("d", "k" * 251)
    with pytest.raises(ValueError):
        csv_row_source_id("d", "汉" * 28)


def test_quoted_empty_field_is_preserved_but_is_not_an_ignored_record() -> None:
    rows = parse_csv_document(CSVDocumentInput(document_id="d", primary_key="id", content=b'id,note\nk,""\n'))
    assert rows[0].values == ("k", "")
    with pytest.raises(ValueError):
        parse_csv_document(CSVDocumentInput(document_id="d", primary_key="id", content=b'id\n""\n'))


def test_legal_column_names_are_not_trimmed_or_case_folded() -> None:
    rows = parse_csv_document(CSVDocumentInput(document_id="d", primary_key=" id ", content=b"id, id ,ID\na,b,c\n"))
    assert rows[0].columns == ("id", " id ", "ID")
    assert rows[0].primary_key_value == "b"


def test_invalid_trailing_quoted_record_rejects_the_whole_document() -> None:
    with pytest.raises(ValueError):
        parse_csv_document(
            CSVDocumentInput(document_id="d", primary_key="id", content=b'id,note\nok,first\nbad,"last"oops\n')
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"values": ("other", "note")},
        {"values": ("key",)},
        {"columns": ("id", "id")},
        {"primary_key": "missing"},
    ],
)
def test_direct_row_inputs_cannot_introduce_inconsistent_evidence(changes: dict[str, object]) -> None:
    fields = {
        "document_id": "d",
        "primary_key": "id",
        "primary_key_value": "key",
        "columns": ("id", "note"),
        "values": ("key", "note"),
    }
    with pytest.raises(ValueError):
        CSVRowInput.model_validate(fields | changes)
