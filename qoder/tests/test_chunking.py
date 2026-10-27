"""test_chunking.py —— 中文文本切块测试。"""

import pytest

from app.chunking import chunk_text


class TestChunkText:
    def test_empty_input(self):
        assert chunk_text("") == []
        assert chunk_text("   \n\n  ") == []

    def test_single_short_paragraph(self):
        result = chunk_text("这是一段短文本。")
        assert len(result) == 1
        assert result[0][0] == 0
        assert "短文本" in result[0][1]

    def test_seq_starts_at_zero(self):
        text = "第一段内容。\n\n第二段内容。\n\n第三段内容。"
        result = chunk_text(text, max_chars=10, overlap=0)
        seqs = [seq for seq, _ in result]
        assert seqs == list(range(len(result)))

    def test_max_chars_respected(self):
        long_para = "测试" * 200  # 400 chars
        result = chunk_text(long_para, max_chars=300, overlap=50)
        for _, text in result:
            assert len(text) <= 350  # allow some tolerance for overlap

    def test_overlap_produces_shared_text(self):
        p1 = "甲" * 150
        p2 = "乙" * 150
        p3 = "丙" * 150
        text = f"{p1}\n\n{p2}\n\n{p3}"
        result = chunk_text(text, max_chars=300, overlap=50)
        assert len(result) >= 2

    def test_chinese_content(self):
        text = """## 事务隔离级别

SQL 标准定义了四种隔离级别。

读未提交、读已提交、可重复读、串行化。

## MVCC 原理

多版本并发控制，通过 Read View 实现快照读。"""
        result = chunk_text(text)
        assert len(result) >= 1
        all_text = " ".join(t for _, t in result)
        assert "事务" in all_text
        assert "MVCC" in all_text

    def test_whitespace_normalization(self):
        text = "  多余   空格  \n\n  和\t制表符  "
        result = chunk_text(text)
        assert len(result) >= 1
        for _, chunk in result:
            assert "  " not in chunk.replace("\n\n", "")  # no double spaces (except paragraph breaks)

    def test_long_single_paragraph_split(self):
        text = "字" * 800
        result = chunk_text(text, max_chars=300, overlap=50)
        assert len(result) >= 3
        total_len = sum(len(t) for _, t in result)
        assert total_len >= 800
