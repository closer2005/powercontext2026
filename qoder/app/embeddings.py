"""嵌入模块：BGE-zh ONNX / Hash 兜底 / API 模式。

线程安全单例，auto 模式优先 BGE 失败降级 Hash。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.config import (
    EMBED_API_BASE,
    EMBED_API_KEY,
    EMBED_API_MODEL,
    EMBED_CACHE_DIR,
    EMBED_DIM,
    EMBED_MODE,
    HF_ENDPOINT,
)

logger = logging.getLogger(__name__)

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

_HASH_DIM = EMBED_DIM


# ──────────────────────────── 下载工具 ────────────────────────────


def _download_file(url: str, dest: str, retries: int = 4, timeout: int = 90) -> None:
    """下载文件，指数退避重试（hf-mirror 偶发 SSL EOF，需要多次重试）。"""
    dest_path = Path(dest)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    last_err: Optional[Exception] = None
    delay = 1.5
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CiteSeek/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if not data:
                raise RuntimeError("empty response body")
            dest_path.write_bytes(data)
            logger.info("Downloaded %s -> %s (%d bytes)", url, dest, len(data))
            return
        except Exception as e:
            last_err = e
            logger.warning("Download attempt %d/%d failed for %s: %s", attempt + 1, retries + 1, url, e)
            if attempt < retries:
                time.sleep(delay)
                delay = min(delay * 2, 20.0)
    raise RuntimeError(f"Failed to download {url} after {retries + 1} attempts: {last_err}")


# ──────────────────────────── BgeZhEmbedder ────────────────────────────


class BgeZhEmbedder:
    """BAAI/bge-small-zh-v1.5 ONNX 推理，512 维，CLS pooling + L2 normalize。"""

    def __init__(self, cache_dir: Optional[str] = None, hf_endpoint: Optional[str] = None):
        self.dim = EMBED_DIM
        self.cache_dir = Path(cache_dir or EMBED_CACHE_DIR).expanduser()
        self.hf_endpoint = (hf_endpoint or HF_ENDPOINT).rstrip("/")
        self._session = None
        self._tokenizer = None
        self._load()

    def _model_dir(self) -> Path:
        return self.cache_dir / "Xenova" / "bge-small-zh-v1.5"

    def _load(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = self._model_dir()
        onnx_path = model_dir / "onnx" / "model.onnx"
        tokenizer_path = model_dir / "tokenizer.json"

        if not onnx_path.exists() or not tokenizer_path.exists():
            self._download_model()

        logger.info("Loading BGE tokenizer from %s", tokenizer_path)
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=256)
        if self._tokenizer.padding is None:
            self._tokenizer.enable_padding()

        logger.info("Loading BGE ONNX model from %s", onnx_path)
        sess_opts = ort.SessionOptions()
        sess_opts.inter_op_num_threads = 1
        sess_opts.intra_op_num_threads = os.cpu_count() or 1
        self._session = ort.InferenceSession(str(onnx_path), sess_opts, providers=["CPUExecutionProvider"])

    def _download_model(self) -> None:
        repo = "Xenova/bge-small-zh-v1.5"
        base = f"{self.hf_endpoint}/{repo}/resolve/main"
        files = [
            ("onnx/model.onnx", "onnx/model.onnx"),
            ("tokenizer.json", "tokenizer.json"),
            ("tokenizer_config.json", "tokenizer_config.json"),
            ("special_tokens_map.json", "special_tokens_map.json"),
            ("vocab.txt", "vocab.txt"),
        ]
        model_dir = self._model_dir()
        for remote_path, local_rel in files:
            url = f"{base}/{remote_path}"
            dest = model_dir / local_rel
            if dest.exists():
                continue
            logger.info("Downloading %s", url)
            _download_file(url, str(dest))

    def _encode(self, texts: List[str]) -> np.ndarray:
        encoded = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)

        input_name = self._session.get_inputs()[0].name
        feed = {input_name: input_ids}
        for inp in self._session.get_inputs()[1:]:
            if "attention" in inp.name.lower() or "mask" in inp.name.lower():
                feed[inp.name] = attention_mask
            else:
                feed[inp.name] = np.zeros_like(input_ids)

        outputs = self._session.run(None, feed)
        # CLS pooling: 取第一个 token 的 hidden state
        token_embeddings = outputs[0]
        cls_embeddings = token_embeddings[:, 0, :]
        # L2 normalize
        norms = np.linalg.norm(cls_embeddings, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-12)
        return cls_embeddings / norms

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        vecs = self._encode(texts)
        return vecs.tolist()

    def embed_query(self, text: str) -> List[float]:
        prefixed = QUERY_PREFIX + text
        vecs = self._encode([prefixed])
        return vecs[0].tolist()


# ──────────────────────────── HashEmbedder ────────────────────────────


class HashEmbedder:
    """512 维字符 2/3-gram 哈希 + TF 加权 + L2 normalize，确定性、零依赖。"""

    def __init__(self):
        self.dim = EMBED_DIM

    @staticmethod
    def _char_ngrams(text: str) -> List[str]:
        text = text.strip()
        ngrams: List[str] = []
        for n in (2, 3):
            for i in range(len(text) - n + 1):
                ngrams.append(text[i : i + n])
        return ngrams

    def _vectorize(self, text: str) -> np.ndarray:
        vec = np.zeros(_HASH_DIM, dtype=np.float64)
        ngrams = self._char_ngrams(text)
        if not ngrams:
            return vec
        counts: Dict[int, float] = {}
        for ng in ngrams:
            h = int(hashlib.md5(ng.encode("utf-8")).hexdigest(), 16) % _HASH_DIM
            counts[h] = counts.get(h, 0.0) + 1.0
        for idx, cnt in counts.items():
            vec[idx] = math.log(1.0 + cnt)
        norm = np.linalg.norm(vec)
        if norm > 1e-12:
            vec /= norm
        return vec

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        result = []
        for t in texts:
            v = self._vectorize(t)
            result.append(v[:_HASH_DIM].tolist())
        return result

    def embed_query(self, text: str) -> List[float]:
        v = self._vectorize(text)
        return v[:_HASH_DIM].tolist()


# ──────────────────────────── ApiEmbedder ────────────────────────────


class ApiEmbedder:
    """OpenAI 兼容 /embeddings 接口。"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.dim = EMBED_DIM
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _call_api(self, texts: List[str]) -> List[List[float]]:
        payload = json.dumps({"input": texts, "model": self.model}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._call_api(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._call_api([QUERY_PREFIX + text])[0]


# ──────────────────────────── 单例管理 ────────────────────────────

_lock = threading.Lock()
_embedder_instance = None
_degraded = False
_degraded_reason = ""
_actual_mode = ""
_requested_mode = ""


def get_embedder(mode: Optional[str] = None) -> Tuple[object, bool, str]:
    """获取嵌入器单例。返回 (embedder, degraded, actual_mode)。

    mode: auto | onnx | hash | api，默认从环境变量读取。
    """
    global _embedder_instance, _degraded, _degraded_reason, _actual_mode, _requested_mode

    mode = mode or EMBED_MODE

    with _lock:
        if _embedder_instance is not None and _requested_mode == mode:
            return _embedder_instance, _degraded, _actual_mode
        _requested_mode = mode

        if mode == "hash":
            _embedder_instance = HashEmbedder()
            _degraded = False
            _actual_mode = "hash"
            return _embedder_instance, False, "hash"

        if mode == "onnx":
            try:
                _embedder_instance = BgeZhEmbedder()
                _degraded = False
                _actual_mode = "onnx"
                return _embedder_instance, False, "onnx"
            except Exception as e:
                logger.error("BGE ONNX load failed: %s", e)
                _embedder_instance = HashEmbedder()
                _degraded = True
                _degraded_reason = f"BGE ONNX 加载失败: {e}"
                _actual_mode = "hash"
                return _embedder_instance, True, "hash"

        if mode == "api":
            if not EMBED_API_BASE:
                logger.warning("EMBED_MODE=api but EMBED_API_BASE empty, fallback to hash")
                _embedder_instance = HashEmbedder()
                _degraded = True
                _degraded_reason = "EMBED_API_BASE 未配置"
                _actual_mode = "hash"
                return _embedder_instance, True, "hash"
            try:
                _embedder_instance = ApiEmbedder(EMBED_API_BASE, EMBED_API_KEY, EMBED_API_MODEL)
                _embedder_instance.embed_query("test")
                _degraded = False
                _actual_mode = "api"
                return _embedder_instance, False, "api"
            except Exception as e:
                logger.warning("API embedder failed: %s, fallback to hash", e)
                _embedder_instance = HashEmbedder()
                _degraded = True
                _degraded_reason = f"API 嵌入失败: {e}"
                _actual_mode = "hash"
                return _embedder_instance, True, "hash"

        # auto: 优先 BGE -> 降级 Hash
        try:
            _embedder_instance = BgeZhEmbedder()
            _degraded = False
            _degraded_reason = ""
            _actual_mode = "onnx"
            return _embedder_instance, False, "onnx"
        except Exception as e:
            logger.warning("Auto mode: BGE failed (%s), falling back to hash", e)
            _embedder_instance = HashEmbedder()
            _degraded = True
            _degraded_reason = f"BGE 不可用，降级为 hash: {e}"
            _actual_mode = "hash"
            return _embedder_instance, True, "hash"


def get_degraded_reason() -> str:
    return _degraded_reason
