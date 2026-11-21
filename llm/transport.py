"""The only module that opens a socket.

Dialects build an `HttpRequest`; this sends it. Tests substitute a `Transport`
that returns recorded payloads, which is why no test needs a key or a network.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from llm.errors import LlmError, ProviderError
from llm.turn import Json


@dataclass(frozen=True, slots=True)
class HttpRequest:
    url: str
    headers: Mapping[str, str]
    body: Json
    timeout_s: float


class Transport(Protocol):
    def post(self, request: HttpRequest) -> Json: ...


class HttpxTransport:
    def post(self, request: HttpRequest) -> Json:
        if "PYTEST_CURRENT_TEST" in os.environ and os.environ.get("ALLOW_LIVE") != "1":
            raise LlmError(
                "live HTTP is disabled while a test is running; use StubTransport, or set "
                "ALLOW_LIVE=1 for a deliberate live check"
            )
        import httpx

        try:
            response = httpx.post(
                request.url,
                headers=dict(request.headers),
                json=request.body,
                timeout=request.timeout_s,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(status=None, body=str(exc), message=type(exc).__name__) from exc
        if response.status_code >= 400:
            raise ProviderError(status=response.status_code, body=response.text)
        try:
            payload = response.json()
        except ValueError as exc:
            raise LlmError(f"{request.url} answered {response.status_code} without JSON") from exc
        if not isinstance(payload, dict):
            raise LlmError(f"{request.url} answered with {type(payload).__name__}, not an object")
        return payload
