from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_JSON_BYTES = 25 * 1024 * 1024
MAX_ERROR_BYTES = 64 * 1024


@dataclass(frozen=True)
class ApiResponse:
    status: int
    data: Any
    headers: dict[str, str]


class ApiError(Exception):
    def __init__(self, message: str, *, status: int | None = None, kind: str = "api_error") -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind


class _SameHostRedirectHandler(HTTPRedirectHandler):
    """Impede que Authorization seja reenviado para outro host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        source = urlsplit(req.full_url)
        target = urlsplit(newurl)

        def origin(parts):  # noqa: ANN001
            default_port = 443 if parts.scheme == "https" else 80
            return parts.scheme, parts.hostname, parts.port or default_port

        if origin(source) != origin(target):
            raise ApiError(
                "redirecionamento entre origens bloqueado",
                status=code,
                kind="unsafe_redirect",
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _redact(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text[:1000]


def _error_message(body: bytes, secret: str, fallback: str) -> str:
    if not body:
        return fallback
    decoded = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(decoded)
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                decoded = str(error.get("message") or error.get("detail") or error)
            elif error:
                decoded = str(error)
            elif payload.get("message"):
                decoded = str(payload["message"])
            elif payload.get("detail"):
                decoded = str(payload["detail"])
    except json.JSONDecodeError:
        pass
    return _redact(decoded.strip() or fallback, secret)


class HttpClient:
    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self._opener = build_opener(_SameHostRedirectHandler())

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        secret: str = "",
    ) -> ApiResponse:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "FoundLLM-KeyScope/1.0",
        }
        if headers:
            request_headers.update(headers)

        request = Request(url, headers=request_headers, method="GET")
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_JSON_BYTES:
                    raise ApiError("resposta JSON excede o limite seguro", kind="response_too_large")
                body = response.read(MAX_JSON_BYTES + 1)
                if len(body) > MAX_JSON_BYTES:
                    raise ApiError("resposta JSON excede o limite seguro", kind="response_too_large")
                try:
                    data = json.loads(body.decode("utf-8")) if body else None
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ApiError("provedor retornou JSON inválido", kind="invalid_json") from exc
                return ApiResponse(
                    status=response.status,
                    data=data,
                    headers={key.lower(): value for key, value in response.headers.items()},
                )
        except HTTPError as exc:
            body = exc.read(MAX_ERROR_BYTES)
            message = _error_message(body, secret, str(exc.reason))
            raise ApiError(message, status=exc.code, kind="http_error") from exc
        except ApiError:
            raise
        except (URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            raise ApiError(_redact(str(reason), secret), kind="network_error") from exc


def rate_limit_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Retorna somente headers operacionais, nunca cookies ou autorização."""

    allowed: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if "ratelimit" in lowered or lowered == "retry-after":
            allowed[lowered] = value
    return allowed
