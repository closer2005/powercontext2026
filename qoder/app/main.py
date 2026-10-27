"""FastAPI 应用入口：CORS、启动事件、静态托管、全部 API 路由、错误处理。"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config, db, services, vector_store
from app.embeddings import get_embedder, get_degraded_reason

logger = logging.getLogger(__name__)

# ──────────────────────── 全局状态 ────────────────────────

_db_ready = False
_vs_ready = False
_embedder = None
_embed_degraded = False
_embed_actual_mode = ""


# ──────────────────────── Lifespan ────────────────────────


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _db_ready, _vs_ready, _embedder, _embed_degraded, _embed_actual_mode

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 1. 初始化嵌入器
    try:
        _embedder, _embed_degraded, _embed_actual_mode = get_embedder()
        logger.info("Embedder ready: mode=%s, degraded=%s", _embed_actual_mode, _embed_degraded)
    except Exception as e:
        logger.error("Embedder init failed: %s", e)
        _embed_degraded = True
        _embed_actual_mode = "none"

    # 2. 等待 seekdb 并建表
    try:
        db.ensure_schema(max_retries=30, retry_delay=2.0)
        _db_ready = True
        logger.info("DB schema ready")
    except Exception as e:
        logger.error("DB init failed: %s", e)
        _db_ready = False

    # 3. 初始化 vector collection
    try:
        vector_store.connect()
        _vs_ready = True
        logger.info("Vector store connected")
    except Exception as e:
        logger.error("Vector store init failed: %s", e)
        _vs_ready = False

    # 4. 可选：自动导入示例数据
    if config.SEED_ON_START and _db_ready and _vs_ready:
        try:
            from app.seed import import_samples
            result = import_samples()
            logger.info("Seed import: %s", result)
        except Exception as e:
            logger.error("Seed import failed: %s", e)

    yield

    logger.info("Shutting down CiteSeek")


app = FastAPI(
    title="CiteSeek 知源",
    description="可溯源的笔记混合检索助手",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件托管（web/ 目录不存在时不崩溃）
_web_dir = Path(__file__).resolve().parent.parent / "web"
if _web_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_web_dir)), name="static")


# ──────────────────────── Request / Response models ────────────────────────


class NoteCreateRequest(BaseModel):
    title: str
    content: str
    course: str = ""
    topic: str = ""
    tags: str = ""
    source: str = ""


class SearchRequest(BaseModel):
    query: str
    course: str = ""
    topic: str = ""
    k: int = 8
    mode: str = "hybrid"


class ReviewAnswerRequest(BaseModel):
    grade: int = Field(..., ge=0, le=3)


# ──────────────────────── Routes ────────────────────────


@app.get("/")
async def root():
    index_path = _web_dir / "index.html"
    if index_path.is_file():
        return FileResponse(str(index_path))
    return {"message": "CiteSeek 知源 API is running. Frontend not found at web/."}


@app.get("/api/health")
async def health():
    embed_info: Dict[str, Any] = {
        "mode": _embed_actual_mode or config.EMBED_MODE,
        "model": config.EMBED_MODEL if _embed_actual_mode == "onnx" else "hash-ngram",
        "dim": config.EMBED_DIM,
        "degraded": _embed_degraded,
    }
    if _embed_degraded:
        embed_info["reason"] = get_degraded_reason()

    seekdb_info: Dict[str, Any] = {
        "connected": _db_ready and _vs_ready,
        "database": config.SEEKDB_DATABASE,
        "collection": config.COLLECTION_NAME,
        "count": 0,
    }
    if _vs_ready:
        try:
            seekdb_info["count"] = vector_store.count()
        except Exception:
            pass

    return {
        "status": "ok" if (_db_ready and _vs_ready) else "degraded",
        "seekdb": seekdb_info,
        "embed": embed_info,
        "version": "0.1.0",
    }


@app.get("/api/stats")
async def stats():
    _require_db()
    return services.get_stats()


@app.get("/api/notes")
async def list_notes(
    limit: int = Query(100, ge=1, le=1000),
    course: str = Query("", description="按课程筛选"),
):
    _require_db()
    notes = db.list_notes(limit=limit, course=course)
    return {"total": len(notes), "notes": notes}


@app.post("/api/notes")
async def create_note(req: NoteCreateRequest):
    _require_db()
    if not req.title or not req.title.strip():
        raise HTTPException(status_code=400, detail="title 不能为空")
    if not req.content or not req.content.strip():
        raise HTTPException(status_code=400, detail="content 不能为空")
    result = services.import_note(
        title=req.title.strip(),
        content=req.content,
        course=req.course.strip(),
        topic=req.topic.strip(),
        tags=req.tags.strip(),
        source=req.source.strip(),
    )
    return result


@app.delete("/api/notes/{note_id}")
async def delete_note(note_id: str):
    _require_db()
    if _vs_ready:
        try:
            vector_store.delete_note_chunks(note_id)
            vector_store.refresh()
        except Exception as e:
            logger.warning("Failed to delete chunks for note %s: %s", note_id, e)
    deleted = db.delete_note_by_id(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Note {note_id} not found")
    return {"deleted": True}


@app.post("/api/import/samples")
async def import_samples():
    _require_db()
    from app.seed import import_samples as do_import
    return do_import()


@app.post("/api/search")
async def search(req: SearchRequest):
    if not req.query or not req.query.strip():
        raise HTTPException(status_code=400, detail="query 不能为空")
    _require_db()
    return services.search(
        query=req.query.strip(),
        course=req.course.strip() if req.course else "",
        topic=req.topic.strip() if req.topic else "",
        k=req.k,
        mode=req.mode,
    )


@app.post("/api/review/{chunk_id}/add")
async def review_add(chunk_id: str):
    _require_db()
    return services.review_add(chunk_id)


@app.get("/api/review/due")
async def review_due(limit: int = Query(10, ge=1, le=100)):
    _require_db()
    return services.review_due(limit=limit)


@app.post("/api/review/{chunk_id}/answer")
async def review_answer(chunk_id: str, req: ReviewAnswerRequest):
    _require_db()
    try:
        return services.review_answer(chunk_id, req.grade)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"review_item {chunk_id} not found")


@app.get("/api/logs/search")
async def search_logs(limit: int = Query(20, ge=1, le=200)):
    _require_db()
    items = db.get_search_logs(limit=limit)
    return {"items": items}


# ──────────────────────── Helpers ────────────────────────


def _require_db():
    if not _db_ready:
        raise HTTPException(status_code=503, detail="数据库未就绪，请稍后重试")


# ──────────────────────── Error handlers ────────────────────────


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return {"detail": str(exc)}


@app.exception_handler(KeyError)
async def key_error_handler(request, exc):
    return {"detail": str(exc)}
