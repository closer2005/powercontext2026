"""pyseekdb 封装：collection 连接、upsert、hybrid_search、refresh。"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

import pyseekdb

from app.config import COLLECTION_NAME, EMBED_DIM, SEEKDB_DATABASE, SEEKDB_HOST, SEEKDB_PASSWORD, SEEKDB_PORT, SEEKDB_USER

logger = logging.getLogger(__name__)

_client: Optional[Any] = None
_collection: Optional[Any] = None


def connect() -> Any:
    """创建 pyseekdb Client，确保数据库和 collection 存在。"""
    global _client, _collection

    admin = pyseekdb.AdminClient(
        host=SEEKDB_HOST,
        port=SEEKDB_PORT,
        tenant="sys",
        user=SEEKDB_USER,
        password=SEEKDB_PASSWORD or "",
    )
    existing = [db.name for db in admin.list_databases()]
    if SEEKDB_DATABASE not in existing:
        logger.info("Creating database %s", SEEKDB_DATABASE)
        admin.create_database(SEEKDB_DATABASE)

    _client = pyseekdb.Client(
        host=SEEKDB_HOST,
        port=SEEKDB_PORT,
        tenant="sys",
        database=SEEKDB_DATABASE,
        user=SEEKDB_USER,
        password=SEEKDB_PASSWORD or "",
    )

    hnsw_config = pyseekdb.HNSWConfiguration(dimension=EMBED_DIM, distance="cosine")
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        configuration=hnsw_config,
        embedding_function=None,
    )
    logger.info("Collection '%s' ready (dim=%d, cosine)", COLLECTION_NAME, EMBED_DIM)
    return _collection


def get_collection() -> Any:
    if _collection is None:
        raise RuntimeError("Vector store not connected. Call connect() first.")
    return _collection


def upsert_chunks(chunks: List[Dict[str, Any]]) -> None:
    """批量 upsert chunks 到 collection。

    每个 chunk dict 需包含: id, embedding, document, metadata
    """
    if not chunks:
        return
    col = get_collection()
    ids = [c["id"] for c in chunks]
    embeddings = [c["embedding"] for c in chunks]
    documents = [c["document"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    col.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def delete_note_chunks(note_id: str) -> None:
    col = get_collection()
    col.delete(where={"note_id": note_id})


def count() -> int:
    col = get_collection()
    return col.count()


def refresh() -> None:
    col = get_collection()
    col.refresh_index()


def hybrid_search(
    query_vec: List[float],
    query_text: str,
    where: Optional[Dict] = None,
    k: int = 8,
) -> Dict[str, Any]:
    """混合检索：hybrid_search 优先，失败降级为 vector + fulltext 应用层 RRF。

    返回格式:
    {
        "ids": [...],
        "documents": [...],
        "metadatas": [...],
        "distances": [...],
        "knn_count": int,
        "fulltext_count": int,
        "degraded": bool,
    }
    """
    col = get_collection()
    n_fetch = max(k * 4, 20)
    degraded = False

    ft_query: Optional[Dict] = None
    if query_text and query_text.strip():
        ft_query = {"where_document": {"$contains": query_text}}
        if where:
            ft_query["where"] = where
        ft_query["n_results"] = n_fetch

    knn_query: Dict = {
        "query_embeddings": [query_vec],
        "n_results": n_fetch,
    }
    if where:
        knn_query["where"] = where

    try:
        results = col.hybrid_search(
            query=ft_query,
            knn=knn_query,
            rank={"rrf": {"rank_window_size": 60, "rank_constant": 60}},
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )
        return _format_hybrid_results(results, k, degraded=False)
    except Exception as e:
        logger.warning("hybrid_search failed (%s), falling back to vector+fulltext RRF", e)
        degraded = True

    return _fallback_rrf(col, query_vec, query_text, where, k, n_fetch)


def _fallback_rrf(
    col: Any,
    query_vec: List[float],
    query_text: str,
    where: Optional[Dict],
    k: int,
    n_fetch: int,
) -> Dict[str, Any]:
    """应用层 RRF 融合 vector + fulltext 结果。"""
    vector_results = col.query(
        query_embeddings=[query_vec],
        where=where,
        n_results=n_fetch,
        include=["documents", "metadatas", "distances"],
    )

    fulltext_results = None
    if query_text and query_text.strip():
        try:
            fulltext_results = col.get(
                where_document={"$contains": query_text},
                where=where,
                limit=n_fetch,
                include=["documents", "metadatas"],
            )
        except Exception as e2:
            logger.warning("fulltext fallback also failed: %s", e2)

    return _merge_rrf(vector_results, fulltext_results, k)


def _merge_rrf(
    vector_res: Dict,
    fulltext_res: Optional[Dict],
    k: int,
) -> Dict[str, Any]:
    """RRF 合并两路结果，按融合后名次排序。"""
    RRF_K = 60
    scores: Dict[str, float] = {}
    knn_set: set = set()
    ft_set: set = set()

    v_ids = vector_res.get("ids", [[]])[0]
    v_distances = vector_res.get("distances", [[]])[0]
    for rank, (cid, _dist) in enumerate(zip(v_ids, v_distances)):
        s = 1.0 / (RRF_K + rank + 1)
        scores[cid] = scores.get(cid, 0.0) + s
        knn_set.add(cid)

    if fulltext_res:
        f_ids = fulltext_res.get("ids", [])
        for rank, cid in enumerate(f_ids):
            s = 1.0 / (RRF_K + rank + 1)
            scores[cid] = scores.get(cid, 0.0) + s
            ft_set.add(cid)

    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:k]

    all_ids = vector_res.get("ids", [[]])[0]
    all_docs = vector_res.get("documents", [[]])[0]
    all_metas = vector_res.get("metadatas", [[]])[0]
    all_dists = vector_res.get("distances", [[]])[0]
    lookup = {}
    for i, cid in enumerate(all_ids):
        lookup[cid] = {
            "doc": all_docs[i] if i < len(all_docs) else "",
            "meta": all_metas[i] if i < len(all_metas) else {},
            "dist": all_dists[i] if i < len(all_dists) else 1.0,
        }

    if fulltext_res:
        ft_ids = fulltext_res.get("ids", [])
        ft_docs = fulltext_res.get("documents", [])
        ft_metas = fulltext_res.get("metadatas", [])
        for i, cid in enumerate(ft_ids):
            if cid not in lookup:
                lookup[cid] = {
                    "doc": ft_docs[i] if i < len(ft_docs) else "",
                    "meta": ft_metas[i] if i < len(ft_metas) else {},
                    "dist": 1.0,
                }

    result_ids = []
    result_docs = []
    result_metas = []
    result_dists = []
    for cid in sorted_ids:
        info = lookup.get(cid, {"doc": "", "meta": {}, "dist": 1.0})
        result_ids.append(cid)
        result_docs.append(info["doc"])
        result_metas.append(info["meta"])
        result_dists.append(info["dist"])

    return {
        "ids": result_ids,
        "documents": result_docs,
        "metadatas": result_metas,
        "distances": result_dists,
        "knn_count": len(knn_set),
        "fulltext_count": len(ft_set),
        "degraded": True,
    }


def _format_hybrid_results(results: Dict, k: int, degraded: bool) -> Dict[str, Any]:
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    return {
        "ids": ids[:k],
        "documents": docs[:k],
        "metadatas": metas[:k],
        "distances": dists[:k],
        "knn_count": len(ids[:k]),
        "fulltext_count": 0,
        "degraded": degraded,
    }
