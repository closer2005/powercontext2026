"""MiniMax 调用封装（OpenAI 兼容 HTTP 接口）。

    POST {MINIMAX_BASE_URL}/chat/completions
    Authorization: Bearer <MINIMAX_API_KEY>

每次调用都会把请求 / 响应（Key 已脱敏）追加写入 evidence/minimax_session.json，
便于评测核对“MiniMax 真实参与”，以及请求上下文与最终 diff 的对应关系。

未配置 Key 时抛出 MiniMaxError，绝不静默返回假内容。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .config import Config

DEFAULT_TIMEOUT = 60


class MiniMaxError(RuntimeError):
    """MiniMax 调用相关的可预期错误；消息为中文。"""


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _mask_headers(headers: dict[str, str]) -> dict[str, str]:
    """对请求头做脱敏，避免把真实 Key 写入 evidence。"""
    out: dict[str, str] = {}
    for key, value in headers.items():
        if key.lower() == "authorization":
            token = str(value).split(" ", 1)[-1]
            masked = token if len(token) <= 8 else f"{token[:4]}{'*' * (len(token) - 8)}{token[-4:]}"
            scheme = str(value).split(" ", 1)[0] if " " in str(value) else "Bearer"
            out[key] = f"{scheme} {masked}"
        else:
            out[key] = value
    return out


def _append_session(entry: dict) -> None:
    """把一次调用记录追加写入 evidence/minimax_session.json（JSON 数组）。"""
    cfg = Config.from_env()
    path = cfg.minimax_session_json
    path.parent.mkdir(parents=True, exist_ok=True)

    data: list[Any] = []
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                data = loaded
            elif loaded is not None:
                data = [loaded]
        except (TypeError, ValueError):
            # 旧文件损坏时不阻塞主流程，另起一个干净数组
            data = []

    data.append(entry)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_text(data: dict) -> str:
    """从 OpenAI 兼容响应中提取文本，兼容多种字段布局。"""
    choices = data.get("choices") or []
    if not choices:
        raise MiniMaxError(
            "MiniMax 响应缺少 choices 字段，无法提取内容："
            + json.dumps(data, ensure_ascii=False)[:500]
        )
    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, list):  # 多模态分片
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )

    if not content:
        # 兜底：部分兼容实现把结果放在 reasoning_content / text
        content = message.get("reasoning_content") or choices[0].get("text")

    if not content:
        raise MiniMaxError(
            "MiniMax 响应中未找到文本内容，请检查模型是否支持 chat/completions。"
        )
    return str(content)


def chat(
    prompt: str,
    *,
    config: Config | None = None,
    temperature: float = 0.0,
    timeout: int = DEFAULT_TIMEOUT,
    extra_payload: dict | None = None,
) -> str:
    """调用 MiniMax，返回模型生成的文本。"""
    cfg = config or Config.from_env()

    # 未配置 Key 时明确报错（不返回任何假内容）
    try:
        api_key = cfg.require_minimax_key()
    except RuntimeError as exc:
        raise MiniMaxError(str(exc)) from exc

    url = cfg.minimax_base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": cfg.minimax_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    if extra_payload:
        payload.update(extra_payload)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    base_entry: dict[str, Any] = {
        "timestamp": _now_iso(),
        "request": {
            "url": url,
            "model": cfg.minimax_model,
            "headers": _mask_headers(headers),
            "payload": payload,
            "prompt_chars": len(prompt or ""),
        },
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        text = _extract_text(data)
    except MiniMaxError as exc:
        base_entry["error"] = str(exc)
        _append_session(base_entry)
        raise
    except Exception as exc:  # 网络 / HTTP / JSON 解析错误
        base_entry["error"] = f"{type(exc).__name__}: {exc}"
        _append_session(base_entry)
        raise MiniMaxError(
            f"调用 MiniMax 失败：{exc}（URL={url}，model={cfg.minimax_model}）"
        ) from exc

    base_entry["response"] = {
        "status_code": resp.status_code,
        "body": data,
        "text": text,
        "usage": (data or {}).get("usage"),
    }
    _append_session(base_entry)
    return text