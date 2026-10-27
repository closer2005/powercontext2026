FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    EMBED_CACHE_DIR=/root/.cache/citeseek/models

WORKDIR /app

# 允许用镜像源加速依赖安装（国内网络建议：--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/）
ARG PIP_INDEX_URL=https://pypi.org/simple

COPY requirements.txt .
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

# 预下载中文嵌入模型（BGE-small-zh-v1.5，约 95MB）到镜像内缓存：
# - 构建期下载成功：运行期无需联网即可得到完整语义检索能力
# - 构建期网络不可用：不阻断构建（|| true），运行期仍会按 EMBED_CACHE_DIR 重试下载，
#   仍失败则自动降级为 hash 向量（/api/health 中 embed.degraded=true）
RUN python - <<'PY' || true
import os
os.environ.setdefault("EMBED_CACHE_DIR", "/root/.cache/citeseek/models")
from app.embeddings import BgeZhEmbedder
BgeZhEmbedder()
print("embedding model pre-fetched into image cache")
PY

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=90s --retries=10 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]