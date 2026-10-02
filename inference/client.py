"""Minimal OpenAI-compatible chat client shared by the perception and reasoning adapters.

Provider quirks stay here and in the profile: the thinking toggle spelling, structured
output mode and ``extra_body``. Logs carry model, status, latency and attempt counts only;
request payloads (images, prompts) and API keys are never logged or put in exceptions.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

from .profiles import EndpointConfig

log = logging.getLogger(__name__)

BACKOFF_BASE_S = 0.5
BACKOFF_CAP_S = 4.0
CONNECT_TIMEOUT_S = 10.0
ERROR_BODY_CHARS = 200
_RETRY_STATUS = frozenset({408, 429})
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


class ModelCallError(RuntimeError):
    """The endpoint gave no usable completion after all retries."""

    def __init__(self, message: str, *, attempts: int, latency_s: float) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.latency_s = latency_s


class _Retryable(Exception):
    pass


@dataclass
class ChatResult:
    content: str
    model: str
    latency_s: float
    attempts: int
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    reasoning_chars: int = 0


class ChatClient:
    """Synchronous ``/chat/completions`` client with bounded retries and backoff.

    Retries: transport errors, timeouts, HTTP 5xx/408/429 and empty content (a thinking
    model that spent its whole token budget reasoning). Other 4xx fail immediately.
    """

    def __init__(
        self,
        endpoint: EndpointConfig,
        *,
        transport: httpx.BaseTransport | None = None,
        env: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if endpoint.backend != "openai_compatible" or not endpoint.base_url or not endpoint.model:
            raise ValueError("ChatClient needs an openai_compatible endpoint with base_url+model")
        self.endpoint = endpoint
        self.url = endpoint.base_url.rstrip("/") + "/chat/completions"
        self._transport = transport
        self._env = env
        self._sleep = sleep

    def build_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        response_schema: dict[str, Any] | None = None,
        schema_name: str = "output",
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        ep = self.endpoint
        payload: dict[str, Any] = {
            "model": ep.model,
            "messages": messages,
            "max_tokens": max_tokens or ep.max_tokens,
            "temperature": ep.temperature if temperature is None else temperature,
            "stream": False,
        }
        if ep.structured_output == "json_schema" and response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": response_schema},
            }
        elif ep.structured_output in ("json_schema", "json_object"):
            payload["response_format"] = {"type": "json_object"}
        if ep.think is not None:
            if ep.think_param == "reasoning_effort":
                # Only "off" is spelled explicitly; "on" is the server default for
                # thinking models and an effort value would be rejected by non-thinkers.
                if not ep.think:
                    payload["reasoning_effort"] = "none"
            elif ep.think_param == "chat_template_kwargs":
                payload["chat_template_kwargs"] = {"enable_thinking": ep.think}
        payload.update(ep.extra_body)
        return payload

    def _headers(self) -> dict[str, str]:
        key = self.endpoint.api_key(self._env)
        return {"Authorization": f"Bearer {key}"} if key else {}

    def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        payload = self.build_payload(messages, **kwargs)
        ep = self.endpoint
        timeout = httpx.Timeout(
            ep.timeout_seconds, connect=min(CONNECT_TIMEOUT_S, ep.timeout_seconds)
        )
        attempts_allowed = ep.retries + 1
        start = time.perf_counter()
        last_error = "no attempt made"
        for attempt in range(1, attempts_allowed + 1):
            try:
                with httpx.Client(timeout=timeout, transport=self._transport) as http:
                    resp = http.post(self.url, json=payload, headers=self._headers())
                result = self._parse_response(resp, attempt, start)
                log.info(
                    "chat ok model=%s attempt=%d latency=%.2fs finish=%s",
                    ep.model,
                    attempt,
                    result.latency_s,
                    result.finish_reason,
                )
                return result
            except _Retryable as exc:
                last_error = str(exc)
            except httpx.TimeoutException:
                last_error = f"timeout after {ep.timeout_seconds:g}s"
            except httpx.TransportError as exc:
                last_error = f"transport error: {type(exc).__name__}"
            log.warning(
                "chat retryable failure model=%s attempt=%d/%d: %s",
                ep.model,
                attempt,
                attempts_allowed,
                last_error,
            )
            if attempt < attempts_allowed:
                self._sleep(min(BACKOFF_CAP_S, BACKOFF_BASE_S * 2 ** (attempt - 1)))
        raise ModelCallError(
            f"{ep.model}: {last_error} (after {attempts_allowed} attempt(s))",
            attempts=attempts_allowed,
            latency_s=time.perf_counter() - start,
        )

    def _parse_response(self, resp: httpx.Response, attempt: int, start: float) -> ChatResult:
        ep = self.endpoint
        if resp.status_code >= 500 or resp.status_code in _RETRY_STATUS:
            raise _Retryable(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            # Server error text only (e.g. "model not found"); never the request.
            raise ModelCallError(
                f"{ep.model}: HTTP {resp.status_code}: {resp.text[:ERROR_BODY_CHARS]}",
                attempts=attempt,
                latency_s=time.perf_counter() - start,
            )
        try:
            data = resp.json()
            choice = data["choices"][0]
            message = choice.get("message") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise _Retryable(f"malformed completion body ({type(exc).__name__})") from exc
        content = _THINK_BLOCK.sub("", _content_text(message.get("content"))).strip()
        reasoning = message.get("reasoning") or message.get("reasoning_content") or ""
        if not content:
            raise _Retryable(
                f"empty content (finish={choice.get('finish_reason')}, "
                f"reasoning_chars={len(reasoning)}); check the thinking toggle/max_tokens"
            )
        return ChatResult(
            content=content,
            model=str(data.get("model") or ep.model),
            latency_s=time.perf_counter() - start,
            attempts=attempt,
            finish_reason=choice.get("finish_reason"),
            usage=dict(data.get("usage") or {}),
            reasoning_chars=len(reasoning),
        )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # some servers return content parts
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def extract_json(text: str) -> Any:
    """Parse the JSON value in ``text``, tolerating code fences and surrounding prose.

    Embedded in prose, the longest decodable object/array wins, so a stray ``[0, 1]``
    before the real payload is not mistaken for it.
    """
    text = _THINK_BLOCK.sub("", text or "").strip()
    candidates = [m.group(1).strip() for m in _FENCE.finditer(text)] + [text]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except ValueError:
            pass
        best: tuple[int, Any] | None = None
        i = 0
        while i < len(candidate):
            if candidate[i] in "{[":
                try:
                    value, end = decoder.raw_decode(candidate, i)
                except ValueError:
                    i += 1
                    continue
                if best is None or end - i > best[0]:
                    best = (end - i, value)
                i = end
            else:
                i += 1
        if best is not None:
            return best[1]
    raise ValueError("no JSON value found in model output")
