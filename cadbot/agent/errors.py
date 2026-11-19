# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 cadbot contributors
"""Map Claude API failures to the plain spoken messages in the design ("When Claude returns
an error"). Claude can't explain its own failure, so this is fixed in code.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

import anthropic


class ErrorKind(enum.StrEnum):
    OFFLINE = "offline"
    OVERLOADED = "overloaded"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    BUDGET = "budget"
    AUTH = "auth"
    PERMISSION = "permission"
    TOO_LARGE = "too_large"
    BAD_REQUEST = "bad_request"
    UNKNOWN = "unknown"


RETRYABLE = frozenset({ErrorKind.OVERLOADED, ErrorKind.RATE_LIMIT, ErrorKind.SERVER_ERROR,
                       ErrorKind.TIMEOUT})
"""Errors that usually pass: retried after about 1 s and then 4 s."""

NEEDS_OWNER = frozenset({ErrorKind.BUDGET, ErrorKind.AUTH, ErrorKind.PERMISSION})
"""Errors the owner has to fix: alerted (log now, phone notification in a later milestone)."""

CANNED_KEY: dict[ErrorKind, str] = {
    ErrorKind.OFFLINE: "offline",
    ErrorKind.TIMEOUT: "offline",
    ErrorKind.OVERLOADED: "overloaded",
    ErrorKind.RATE_LIMIT: "rate_limit",
    ErrorKind.SERVER_ERROR: "server_error",
    ErrorKind.BUDGET: "budget",
    ErrorKind.AUTH: "auth",
    ErrorKind.PERMISSION: "permission",
    ErrorKind.TOO_LARGE: "too_large",
    ErrorKind.BAD_REQUEST: "bad_request",
    ErrorKind.UNKNOWN: "unknown",
}

_TYPE_KINDS = {
    "overloaded_error": ErrorKind.OVERLOADED,
    "rate_limit_error": ErrorKind.RATE_LIMIT,
    "api_error": ErrorKind.SERVER_ERROR,
    "authentication_error": ErrorKind.AUTH,
    "permission_error": ErrorKind.PERMISSION,
    "not_found_error": ErrorKind.PERMISSION,
    "request_too_large": ErrorKind.TOO_LARGE,
    "billing_error": ErrorKind.BUDGET,
}


@dataclass
class ClaudeFailure(Exception):
    kind: ErrorKind
    detail: str
    status: int | None = None
    request_id: str | None = None
    retry_after_s: float | None = None

    def __str__(self) -> str:
        return f"{self.kind} (status={self.status}, request_id={self.request_id}): {self.detail}"


def _retry_after(exc: anthropic.APIStatusError) -> float | None:
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value else None
    except (ValueError, AttributeError):
        return None


def _looks_like_budget(exc: anthropic.APIStatusError) -> bool:
    code = (exc.error_code or "").lower()
    if any(word in code for word in ("credit", "billing", "spend", "budget")):
        return True
    message = (exc.api_message or "").lower()  # last resort: wording can change
    return "credit balance" in message or "spend limit" in message


def _looks_too_long(exc: anthropic.APIStatusError) -> bool:
    code = (exc.error_code or "").lower()
    message = (exc.api_message or "").lower()
    return "too_long" in code or "context" in code or "prompt is too long" in message


def classify(exc: BaseException) -> ClaudeFailure:
    if isinstance(exc, ClaudeFailure):
        return exc
    if isinstance(exc, anthropic.APITimeoutError):
        return ClaudeFailure(ErrorKind.TIMEOUT, "request timed out")
    if isinstance(exc, anthropic.APIConnectionError):
        return ClaudeFailure(ErrorKind.OFFLINE, f"connection error: {exc}")
    if not isinstance(exc, anthropic.APIStatusError):
        return ClaudeFailure(ErrorKind.UNKNOWN, f"{type(exc).__name__}: {exc}")

    detail = f"{exc.type or 'error'}: {exc.api_message or exc}"

    def failure(kind: ErrorKind) -> ClaudeFailure:
        return ClaudeFailure(kind, detail, exc.status_code, exc.request_id, _retry_after(exc))

    if exc.status_code == 402 or _looks_like_budget(exc):
        return failure(ErrorKind.BUDGET)
    if exc.status_code == 413 or _looks_too_long(exc):
        return failure(ErrorKind.TOO_LARGE)
    if exc.type in _TYPE_KINDS:
        return failure(_TYPE_KINDS[exc.type])
    by_class: list[tuple[type[anthropic.APIStatusError], ErrorKind]] = [
        (anthropic.OverloadedError, ErrorKind.OVERLOADED),
        (anthropic.RateLimitError, ErrorKind.RATE_LIMIT),
        (anthropic.InternalServerError, ErrorKind.SERVER_ERROR),
        (anthropic.AuthenticationError, ErrorKind.AUTH),
        (anthropic.PermissionDeniedError, ErrorKind.PERMISSION),
        (anthropic.NotFoundError, ErrorKind.PERMISSION),
        (anthropic.BadRequestError, ErrorKind.BAD_REQUEST),
    ]
    for cls, kind in by_class:
        if isinstance(exc, cls):
            return failure(kind)
    return failure(ErrorKind.SERVER_ERROR if exc.status_code >= 500 else ErrorKind.UNKNOWN)
