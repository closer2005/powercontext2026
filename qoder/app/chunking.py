"""中文友好文本切块：按段落聚合到 <=300 字，chunk 间 50 字重叠。"""

from __future__ import annotations

import logging
import re
from typing import List, Tuple

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 300
OVERLAP_CHARS = 50


def _normalize_whitespace(text: str) -> str:
    """合并多余空白（保留换行用于段落分割）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


def _split_paragraphs(text: str) -> List[str]:
    """按空行分割段落，过滤空段。"""
    blocks = re.split(r"\n\s*\n", text)
    return [b.strip() for b in blocks if b.strip()]


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS, overlap: int = OVERLAP_CHARS) -> List[Tuple[int, str]]:
    """将文本切块为 [(seq, text)]，seq 从 0 开始。

    策略：
    1. 按空行分段
    2. 贪心聚合段落直到超过 max_chars
    3. 相邻 chunk 间保留 overlap 个字符的重叠
    """
    text = _normalize_whitespace(text)
    if not text:
        return []

    paragraphs = _split_paragraphs(text)
    if not paragraphs:
        return []

    chunks: List[Tuple[int, str]] = []
    current_parts: List[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)
        if current_parts and current_len + 1 + para_len > max_chars:
            chunk_text_str = "\n\n".join(current_parts)
            chunks.append((len(chunks), chunk_text_str))
            if overlap > 0:
                tail = chunk_text_str[-overlap:] if len(chunk_text_str) > overlap else chunk_text_str
                current_parts = [tail]
                current_len = len(tail)
            else:
                current_parts = []
                current_len = 0
        if para_len > max_chars and not current_parts:
            for i in range(0, para_len, max_chars - overlap):
                seg = para[i : i + max_chars]
                if seg.strip():
                    chunks.append((len(chunks), seg.strip()))
                if len(para) - i <= max_chars:
                    break
            current_parts = []
            current_len = 0
        else:
            if current_parts:
                current_parts.append(para)
                current_len += 1 + para_len
            else:
                current_parts = [para]
                current_len = para_len

    if current_parts:
        chunk_text_str = "\n\n".join(current_parts).strip()
        if chunk_text_str:
            chunks.append((len(chunks), chunk_text_str))

    result = [(i, text) for i, (_, text) in enumerate(chunks)]
    return result
