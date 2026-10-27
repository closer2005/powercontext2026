"""业务编排：import_note、search、review add/due/answer、stats。"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app import db, vector_store
from app.chunking import chunk_text
from app.embeddings import get_embedder

logger = logging.getLogger(__name__)


def import_note(
    title: str,
    content: str,
    course: str = "",
    topic: str = "",
    tags: str = "",
    source: str = "",
) -> Dict[str, Any]:
    """导入笔记：切块 → 嵌入 → 写入 DB + collection。返回 {id, chunk_count}。"""
    embedder, _, _ = get_embedder()

    chunks = chunk_text(content)
    if not chunks:
        raise ValueError("内容为空，无法切块")

    note_id = db.insert_note(
        title=title, content=content, course=course, topic=topic, tags=tags, source=source
    )

    texts = [t for _, t in chunks]
    embeddings = embedder.embed_documents(texts)

    created_day = datetime.now().strftime("%Y-%m-%d")
    chunk_records = []
    for (seq, text), emb in zip(chunks, embeddings):
        chunk_id = uuid.uuid4().hex[:32]
        chunk_records.append({
            "id": chunk_id,
            "embedding": emb,
            "document": text,
            "metadata": {
                "note_id": note_id,
                "title": title,
                "course": course,
                "topic": topic,
                "tags": tags,
                "source": source,
                "created_day": created_day,
                "seq": seq,
            },
        })

    vector_store.upsert_chunks(chunk_records)
    vector_store.refresh()
    db.update_note_chunk_count(note_id, len(chunk_records))

    logger.info("Imported note '%s' (%s): %d chunks", title, note_id, len(chunk_records))
    return {"id": note_id, "chunk_count": len(chunk_records)}


def _query_substrings(query: str, min_len: int = 2) -> List[str]:
    """Extract all continuous substrings of length >= min_len from query."""
    q = query.strip()
    if len(q) < min_len:
        return [q] if q else []
    substrs = set()
    for i in range(len(q)):
        for j in range(i + min_len, len(q) + 1):
            substrs.add(q[i:j])
    return list(substrs)


def _text_matches_query(text: str, query: str) -> bool:
    """Check if text contains any >=2 char continuous substring of query."""
    if not text or not query:
        return False
    substrs = _query_substrings(query, min_len=2)
    if not substrs:
        return False
    text_lower = text.lower()
    return any(s.lower() in text_lower for s in substrs)


def search(
    query: str,
    course: str = "",
    topic: str = "",
    k: int = 8,
    mode: str = "hybrid",
) -> Dict[str, Any]:
    """检索：计算 query 向量 → 构造过滤 → hybrid_search → 组装结果 → 记录日志。"""
    embedder, _, _ = get_embedder()
    query_vec = embedder.embed_query(query)

    where: Optional[Dict] = None
    conditions: List[Dict] = []
    if course:
        conditions.append({"course": {"$eq": course}})
    if topic:
        conditions.append({"topic": {"$eq": topic}})
    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    t0 = time.time()
    try:
        results = vector_store.hybrid_search(
            query_vec=query_vec,
            query_text=query,
            where=where,
            k=k,
        )
    except Exception as e:
        logger.error("Search failed: %s", e)
        results = {
            "ids": [], "documents": [], "metadatas": [], "distances": [],
            "knn_count": 0, "fulltext_count": 0, "degraded": True,
        }
    took_ms = int((time.time() - t0) * 1000)

    ids = results.get("ids", [])
    docs = results.get("documents", [])
    metas = results.get("metadatas", [])
    dists = results.get("distances", [])
    knn_count = results.get("knn_count", 0)
    fulltext_count = results.get("fulltext_count", 0)

    formatted = []
    ft_hits = 0
    for rank, cid in enumerate(ids):
        meta = metas[rank] if rank < len(metas) else {}
        text = docs[rank] if rank < len(docs) else ""
        dist = dists[rank] if rank < len(dists) else None

        score = 1.0 / (60 + rank + 1)

        mb = ["vector"]
        if _text_matches_query(text, query):
            mb.append("fulltext")
            ft_hits += 1

        seq_val = meta.get("seq")
        if seq_val is not None:
            try:
                seq_val = int(seq_val)
            except (ValueError, TypeError):
                seq_val = None

        formatted.append({
            "chunk_id": cid,
            "note_id": meta.get("note_id", ""),
            "title": meta.get("title", ""),
            "course": meta.get("course", ""),
            "topic": meta.get("topic", ""),
            "tags": meta.get("tags", ""),
            "text": text,
            "seq": seq_val,
            "score": round(score, 6),
            "distance": round(dist, 6) if dist is not None else None,
            "matched_by": mb,
        })

    used_vector = len(ids) > 0
    used_fulltext = ft_hits > 0

    # 同一篇笔记最多保留 2 个片段，保证结果多样性（再按 k 截断）
    diversified = []
    per_note: Dict[str, int] = {}
    for item in formatted:
        key = item.get("title") or item.get("note_id") or item["chunk_id"]
        if per_note.get(key, 0) >= 2:
            continue
        per_note[key] = per_note.get(key, 0) + 1
        diversified.append(item)
        if len(diversified) >= k:
            break
    formatted = diversified

    try:
        db.insert_search_log(
            query=query,
            course=course,
            topic=topic,
            mode=mode,
            k=k,
            took_ms=took_ms,
            result_count=len(formatted),
            used_vector=used_vector,
            used_fulltext=used_fulltext,
        )
    except Exception as e:
        logger.warning("Failed to write search_log: %s", e)

    return {
        "query": query,
        "took_ms": took_ms,
        "mode": mode,
        "results": formatted,
        "debug": {
            "degraded": results.get("degraded", False),
            "used_vector": used_vector,
            "used_fulltext": used_fulltext,
            "knn_hits": knn_count,
            "fulltext_hits": ft_hits,
        },
    }


def review_add(chunk_id: str) -> Dict[str, Any]:
    """将 chunk 加入复习队列（立即可复习）。"""
    # seekdb 的 DATETIME 列不带小数秒，写入时会按秒四舍五入；
    # 这里回退 2 秒，保证「加入后立刻出现在待复习列表」。
    now = datetime.now() - timedelta(seconds=2)

    note_id = ""
    try:
        col = vector_store.get_collection()
        items = col.get(ids=[chunk_id], include=["metadatas"])
        metas = items.get("metadatas") or [] if isinstance(items, dict) else []
        if metas and isinstance(metas[0], list):
            metas = metas[0]
        meta = metas[0] if metas else None
        if isinstance(meta, dict):
            note_id = meta.get("note_id", "") or ""
    except Exception:
        pass

    db.upsert_review_item(
        chunk_id=chunk_id,
        note_id=note_id,
        due_at=now,
        interval_days=0,
        ease=2.5,
        reps=0,
        lapses=0,
        last_grade=None,
    )
    return {"ok": True, "due_at": now.isoformat()}


def review_due(limit: int = 10) -> Dict[str, Any]:
    """获取到期复习条目。"""
    items = db.get_due_items(limit=limit)
    enriched = []
    for item in items:
        chunk_id = item["chunk_id"]
        try:
            col = vector_store.get_collection()
            res = col.get(ids=[chunk_id], include=["documents", "metadatas"])
            docs = res.get("documents") or [] if isinstance(res, dict) else []
            mets = res.get("metadatas") or [] if isinstance(res, dict) else []
            if docs and isinstance(docs[0], list):
                docs = docs[0]
            if mets and isinstance(mets[0], list):
                mets = mets[0]
            if docs:
                item["text"] = docs[0]
                meta = mets[0] if mets else {}
                if isinstance(meta, dict):
                    item["title"] = item.get("title") or meta.get("title", "")
                    item["course"] = item.get("course") or meta.get("course", "")
                    item["topic"] = item.get("topic") or meta.get("topic", "")
            else:
                item["text"] = ""
        except Exception:
            item["text"] = ""
        enriched.append(item)

    return {"total": len(enriched), "items": enriched}


def review_answer(chunk_id: str, grade: int) -> Dict[str, Any]:
    """SM-2 评分更新。grade ∈ {0,1,2,3}。"""
    if grade not in (0, 1, 2, 3):
        raise ValueError("grade must be 0-3")

    item = db.get_review_item(chunk_id)
    if not item:
        raise KeyError(f"review_item {chunk_id} not found")

    reps = item["reps"] if isinstance(item["reps"], int) else int(item.get("reps", 0) or 0)
    interval_days = item["interval_days"] if isinstance(item["interval_days"], int) else int(item.get("interval_days", 0) or 0)
    ease = float(item.get("ease", 2.5) or 2.5)
    lapses = int(item.get("lapses", 0) or 0)
    note_id = item.get("note_id", "")

    now = datetime.now()

    if grade >= 2:
        reps += 1
        if reps == 1:
            interval_days = 1
        elif reps == 2:
            interval_days = 3
        else:
            interval_days = round(interval_days * ease)
        ease = ease + (0.1 - (3 - grade) * 0.08)
        ease = max(1.3, min(2.8, ease))
    else:
        lapses += 1
        reps = 0
        interval_days = 1
        ease = max(1.3, ease - 0.2)

    due_at = now + timedelta(days=interval_days)

    db.upsert_review_item(
        chunk_id=chunk_id,
        note_id=note_id,
        due_at=due_at,
        interval_days=interval_days,
        ease=ease,
        reps=reps,
        lapses=lapses,
        last_grade=grade,
    )

    return {
        "ok": True,
        "interval_days": interval_days,
        "ease": round(ease, 2),
        "due_at": due_at.isoformat(),
        "reps": reps,
    }


def get_stats() -> Dict[str, Any]:
    """聚合统计。"""
    try:
        notes_count = db.count_notes()
    except Exception:
        notes_count = 0
    try:
        chunks_count = vector_store.count()
    except Exception:
        chunks_count = 0
    try:
        review_count = db.count_review_items()
    except Exception:
        review_count = 0
    try:
        due_count = db.count_due_items()
    except Exception:
        due_count = 0
    try:
        summary = db.get_stats_summary()
    except Exception:
        summary = {"searches": 0, "avg_latency_ms": 0, "top_queries": [], "last_search_at": None}

    return {
        "notes": notes_count,
        "chunks": chunks_count,
        "review_items": review_count,
        "review_due": due_count,
        **summary,
    }
