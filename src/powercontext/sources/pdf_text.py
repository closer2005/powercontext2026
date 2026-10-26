# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0

"""Recover positioned PDF text without treating glyph controls as line moves."""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, cast

from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

if TYPE_CHECKING:
    from pypdf import PageObject


def _normalize_font_controls(container: DictionaryObject, visited: set[int]) -> None:
    """Repair in-memory character maps; the original document stays unchanged.

    A control character painted by Tj/TJ has no line-positioning semantics.
    Preserve that distinction from actual Td/Tm/T* positioning operations.
    """
    if id(container) in visited:
        return
    visited.add(id(container))
    resources_ref = container.get("/Resources")
    if resources_ref is None:
        return
    resources = cast(DictionaryObject, resources_ref.get_object())
    fonts_ref = resources.get("/Font")
    fonts = cast(DictionaryObject, fonts_ref.get_object()) if fonts_ref is not None else {}
    for reference in fonts.values():
        font = cast(DictionaryObject, reference.get_object())
        if id(font) in visited:
            continue
        visited.add(id(font))
        mapping = font.get("/ToUnicode")
        if mapping is None:
            continue
        data = cast(DecodedStreamObject, mapping.get_object()).get_data().replace(b"\r", b"\n")
        updated = re.sub(rb"beginbfchar\b.*?endbfchar", _normalize_character_block, data, flags=re.DOTALL)
        updated = re.sub(rb"beginbfrange\b.*?endbfrange", _normalize_range_block, updated, flags=re.DOTALL)
        if updated != data:
            stream = DecodedStreamObject()
            stream.set_data(updated)
            font[NameObject("/ToUnicode")] = stream
    objects_ref = resources.get("/XObject")
    objects = cast(DictionaryObject, objects_ref.get_object()) if objects_ref is not None else {}
    for reference in objects.values():
        obj = cast(DictionaryObject, reference.get_object())
        if obj.get("/Subtype") == "/Form":
            _normalize_font_controls(obj, visited)


def _normalize_character_block(match: re.Match[bytes]) -> bytes:
    return re.sub(rb"(?m)^([ \t]*<[0-9a-fA-F]+>[ \t]*)<(?:000[Aa]|000[Dd])>([ \t]*$)", rb"\1<200B>\2", match.group())


def _normalize_range_block(match: re.Match[bytes]) -> bytes:
    # Only singleton ranges: changing a range's base would remap later glyphs.
    return re.sub(
        rb"(?m)^([ \t]*<([0-9a-fA-F]+)>[ \t]*<\2>[ \t]*)<(?:000[Aa]|000[Dd])>([ \t]*$)",
        rb"\1<200B>\3",
        match.group(),
    )


def extract_positioned_text(page: PageObject, visited: set[int]) -> str:
    """Join adjacent same-baseline font runs, retaining ordinary word spaces."""
    _normalize_font_controls(page, visited)
    fragments: list[str] = []
    previous: tuple[float, float, float] | None = None

    def visit(text: str, cm: list[float], tm: list[float], _font: DictionaryObject | None, size: float) -> None:
        nonlocal previous
        if not text:
            return
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        height = abs(size) * math.hypot(cm[2], cm[3])
        if fragments and previous and fragments[-1].endswith("\n"):
            before = fragments[-1].rstrip("\n")
            same_line = abs(y - previous[1]) <= max(0.01, min(height, previous[2]) * 0.1)
            if (
                same_line
                and x >= previous[0]
                and "\n" not in before
                and re.search(r"[A-Za-z\xa0]$", before)
                and re.match(r"[a-z]", text)
            ):
                fragments[-1] = before
        fragments.append(text)
        previous = (x, y, height)

    raw = page.extract_text(visitor_text=visit) or ""
    reconstructed = "".join(fragments)
    # Form-XObject callbacks can repeat nested output. Never duplicate or lose
    # characters when callbacks differ from the parser's authoritative result.
    if re.sub(r"\s+", "", reconstructed) != re.sub(r"\s+", "", raw):
        reconstructed = raw
    return reconstructed.replace("\u200b", "")
