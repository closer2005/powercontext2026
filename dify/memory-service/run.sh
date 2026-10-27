#!/usr/bin/env bash
# 离谱法庭 · 书记员服务启动脚本（Linux / macOS / WSL）
# 用法：
#   ./run.sh            启动服务
#   ./run.sh --init-db  先建库建表再启动
#   ./run.sh --only-init 只初始化数据库
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8

if [ ! -f config.env ]; then
  cp config.example.env config.env
  echo "[离谱法庭] 已从 config.example.env 生成 config.env，请按需修改数据库密码。"
fi

PY=python3
if [ -x .venv/bin/python ]; then PY=.venv/bin/python; fi

if [ "${1:-}" = "--only-init" ]; then
  exec "$PY" app.py --init-db --only-init
elif [ "${1:-}" = "--init-db" ]; then
  "$PY" app.py --init-db
  exec "$PY" app.py
else
  exec "$PY" app.py
fi