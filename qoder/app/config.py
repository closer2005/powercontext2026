"""环境变量配置，带合理默认值。"""

from __future__ import annotations

import os
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    val = os.environ.get(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


# seekdb 连接
SEEKDB_HOST: str = _env("SEEKDB_HOST", "127.0.0.1")
SEEKDB_PORT: int = _env_int("SEEKDB_PORT", 2881)
SEEKDB_USER: str = _env("SEEKDB_USER", "root")
SEEKDB_PASSWORD: str = _env("SEEKDB_PASSWORD", "")
SEEKDB_DATABASE: str = _env("SEEKDB_DATABASE", "citeseek")

# 嵌入模型
EMBED_MODE: str = _env("EMBED_MODE", "auto")  # auto | onnx | hash | api
EMBED_MODEL: str = _env("EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
EMBED_CACHE_DIR: str = _env(
    "EMBED_CACHE_DIR",
    str(Path.home() / ".cache" / "citeseek" / "models"),
)
HF_ENDPOINT: str = _env("HF_ENDPOINT", "https://hf-mirror.com")

# API 嵌入（可选）
EMBED_API_BASE: str = _env("EMBED_API_BASE", "")
EMBED_API_KEY: str = _env("EMBED_API_KEY", "")
EMBED_API_MODEL: str = _env("EMBED_API_MODEL", "")

# 应用
APP_PORT: int = _env_int("APP_PORT", 8000)
SEED_ON_START: bool = _env("SEED_ON_START", "0") in ("1", "true", "yes")

# 常量
COLLECTION_NAME = "citeseek_chunks_v1"
EMBED_DIM = 512
