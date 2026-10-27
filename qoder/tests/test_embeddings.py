"""test_embeddings.py —— 嵌入模块测试（EMBED_MODE=hash）。"""

import os

import numpy as np
import pytest

os.environ.setdefault("EMBED_MODE", "hash")

from app.embeddings import HashEmbedder, get_embedder
from app.config import EMBED_DIM


class TestHashEmbedder:
    def setup_method(self):
        self.embedder = HashEmbedder()

    def test_dim_is_512(self):
        vec = self.embedder.embed_query("测试文本")
        assert len(vec) == EMBED_DIM
        assert len(vec) == 512

    def test_documents_dim(self):
        vecs = self.embedder.embed_documents(["文档一", "文档二"])
        assert len(vecs) == 2
        for v in vecs:
            assert len(v) == 512

    def test_l2_normalized(self):
        vec = self.embedder.embed_query("归一化测试")
        arr = np.array(vec)
        norm = np.linalg.norm(arr)
        assert abs(norm - 1.0) < 1e-5 or norm == 0.0

    def test_documents_normalized(self):
        vecs = self.embedder.embed_documents(["测试文档归一化"])
        arr = np.array(vecs[0])
        norm = np.linalg.norm(arr)
        assert abs(norm - 1.0) < 1e-5 or norm == 0.0

    def test_deterministic(self):
        v1 = self.embedder.embed_query("确定性测试")
        v2 = self.embedder.embed_query("确定性测试")
        assert v1 == v2

    def test_documents_deterministic(self):
        texts = ["文档A", "文档B", "文档C"]
        v1 = self.embedder.embed_documents(texts)
        v2 = self.embedder.embed_documents(texts)
        assert v1 == v2

    def test_different_texts_different_vecs(self):
        v1 = self.embedder.embed_query("数据库事务")
        v2 = self.embedder.embed_query("机器学习模型")
        assert v1 != v2

    def test_empty_string(self):
        vec = self.embedder.embed_query("")
        assert len(vec) == 512

    def test_query_prefix_does_not_change_dim(self):
        """query 前缀不应影响输出维度。"""
        prefix = "为这个句子生成表示以用于检索相关文章："
        v1 = self.embedder.embed_query(prefix + "事务隔离级别")
        v2 = self.embedder.embed_query("事务隔离级别")
        assert len(v1) == len(v2) == 512


class TestGetEmbedder:
    def test_hash_mode(self):
        embedder, degraded, mode = get_embedder("hash")
        assert isinstance(embedder, HashEmbedder)
        assert degraded is False
        assert mode == "hash"

    def test_singleton(self):
        e1, _, _ = get_embedder("hash")
        e2, _, _ = get_embedder("hash")
        assert e1 is e2

    def test_embed_query_via_get_embedder(self):
        embedder, _, _ = get_embedder("hash")
        vec = embedder.embed_query("通过单例获取")
        assert len(vec) == 512
