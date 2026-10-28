"""MiniMax client for the competition task.

Uses MiniMax's OpenAI-compatible endpoint (verified against a subscription key):

* ``GET  {base}/v1/models``
* ``POST {base}/v1/chat/completions``

The client only transports prompts and responses; persistence of the development
record (``dev-records/``) is handled by :mod:`sdd_context.devrun`, so a raw
record never contains the credential.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class MiniMaxError(RuntimeError):
    """Raised when the MiniMax endpoint cannot complete a request."""

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class ChatResult:
    content: str
    model: str
    usage: dict[str, object] = field(default_factory=dict)
    latency_ms: int = 0
    request_id: str | None = None
    raw: dict[str, object] = field(default_factory=dict)


class MiniMaxClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        timeout: float = 240.0,
        max_retries: int = 2,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    # -- low level ---------------------------------------------------------
    def _post(self, path: str, payload: dict[str, object]) -> tuple[int, str]:
        url = f"{self.base_url}{path}"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Authorization", f"Bearer {self.api_key}")
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")
        except Exception as error:  # network failure
            return 0, repr(error)

    # -- public ------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 32768,
        model: str | None = None,
    ) -> ChatResult:
        target_model = model or self.model
        payload: dict[str, object] = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        last_error: str = ""
        for attempt in range(self.max_retries + 1):
            started = time.time()
            status, body = self._post("/v1/chat/completions", payload)
            latency_ms = int((time.time() - started) * 1000)
            if status == 200:
                try:
                    raw = json.loads(body)
                except json.JSONDecodeError as error:  # pragma: no cover - defensive
                    raise MiniMaxError(f"MiniMax returned non-JSON body: {error}", status=status, body=body[:500]) from error
                return self._to_result(raw, latency_ms)
            last_error = f"HTTP {status}: {body[:500]}"
            retryable = status in (0, 429, 500, 502, 503, 504)
            if not retryable or attempt == self.max_retries:
                raise MiniMaxError(f"MiniMax request failed ({last_error})", status=status, body=body[:2000])
            time.sleep(1.5 * (attempt + 1) + (status == 429))
        raise MiniMaxError(last_error)

    @staticmethod
    def _to_result(raw: dict[str, object], latency_ms: int) -> ChatResult:
        choices = raw.get("choices") or []
        content = ""
        reasoning_chars = 0
        if choices:
            message = choices[0].get("message") or {}
            # Some MiniMax deployments return the visible answer in `content`
            # and chain-of-thought in a sibling field; only `content` is used.
            # The deliverable must not ship the model's private reasoning, so the
            # stored raw payload drops it and keeps only its size.
            reasoning = message.pop("reasoning_content", None) if isinstance(message, dict) else None
            if isinstance(reasoning, str):
                reasoning_chars = len(reasoning)
            content = message.get("content") or ""
            if isinstance(content, list):  # defensive: content parts
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return ChatResult(
            content=str(content),
            model=str(raw.get("model") or ""),
            usage=dict(raw.get("usage") or {}),
            latency_ms=latency_ms,
            request_id=raw.get("id"),
            raw={"response": raw, "reasoning_chars_removed": reasoning_chars},
        )